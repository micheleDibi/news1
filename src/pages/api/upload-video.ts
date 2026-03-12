export const prerender = false;

import type { APIRoute } from 'astro';
import { streamUploadToS3 } from '../../lib/aws';
import { slugify } from '../../lib/utils';
import { compressAndConvertVideo } from '../../lib/video-compress';
import { logger } from '../../lib/logger';
import { readFile, unlink, readdir, writeFile, rmdir } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import { randomUUID } from 'crypto';

// In-memory job status store
type JobStatus = {
  status: 'queued' | 'processing' | 'uploading' | 'done' | 'error';
  message: string;
  url?: string;
  error?: string;
};
const jobs = new Map<string, JobStatus>();

// Cleanup old jobs after 30 minutes
function scheduleJobCleanup(uploadId: string) {
  setTimeout(() => jobs.delete(uploadId), 30 * 60 * 1000);
}

// Semaphore: max 1 ffmpeg process at a time
let ffmpegQueue: Promise<void> = Promise.resolve();
function withFfmpegLock<T>(fn: () => Promise<T>): Promise<T> {
  const prev = ffmpegQueue;
  let releaseFn: () => void;
  ffmpegQueue = new Promise<void>(resolve => { releaseFn = resolve; });
  return prev.then(fn).finally(() => releaseFn!());
}

export const POST: APIRoute = async ({ request }) => {
  try {
    const authHeader = request.headers.get('Authorization');
    const apiKey = authHeader?.split('Bearer ')[1];

    if (apiKey !== import.meta.env.API_SECRET_KEY) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const formData = await request.formData();
    const uploadId = formData.get('uploadId') as string;
    const title = (formData.get('title') as string) || '';
    const originalFilename = formData.get('filename') as string;

    logger.info('Assembly request:', { uploadId, title, originalFilename });

    if (!uploadId || !originalFilename) {
      return new Response(JSON.stringify({ error: 'Missing uploadId or filename' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Reassemble chunks from temp directory
    const chunkDir = join(tmpdir(), `upload-${uploadId}`);
    let chunkFiles: string[];
    try {
      chunkFiles = await readdir(chunkDir);
    } catch {
      return new Response(JSON.stringify({ error: 'No chunks found. Upload chunks first.' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Sort chunks by index
    chunkFiles.sort((a, b) => {
      const idxA = parseInt(a.split('-')[1]);
      const idxB = parseInt(b.split('-')[1]);
      return idxA - idxB;
    });

    // Read chunks, concatenate, and write to a single temp file (then release buffer)
    const ext = originalFilename.split('.').pop()?.toLowerCase();
    const allowedExts = ['mp4', 'webm', 'ogg', 'avi', 'mov'];
    if (!ext || !allowedExts.includes(ext)) {
      return new Response(JSON.stringify({ error: 'Invalid video file type. Allowed: MP4, WebM, OGG, AVI, MOV' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const inputPath = join(tmpdir(), `${randomUUID()}-input.${ext}`);

    // Reassemble chunks into a temp file, then free the buffer
    const chunks: Buffer[] = [];
    for (const chunkFile of chunkFiles) {
      const chunkPath = join(chunkDir, chunkFile);
      chunks.push(await readFile(chunkPath));
      await unlink(chunkPath).catch(() => {});
    }
    await rmdir(chunkDir).catch(() => {});

    let buffer: Buffer | null = Buffer.concat(chunks);
    // Free individual chunk references
    chunks.length = 0;

    logger.info(`Reassembled ${chunkFiles.length} chunks: ${(buffer.length / 1024 / 1024).toFixed(1)}MB`);

    // Write reassembled buffer to disk and release it from memory
    await writeFile(inputPath, buffer);
    buffer = null; // Allow GC to free ~500MB

    // Mark job as queued and respond immediately
    jobs.set(uploadId, { status: 'queued', message: 'In coda — un altro video è in fase di elaborazione...' });
    scheduleJobCleanup(uploadId);

    // Run compression + upload in the background (not awaited)
    const videoFilename = `${slugify(title || originalFilename.replace(/\.[^.]+$/, ''))}.mp4`;

    (async () => {
      let outputPath: string | undefined;
      try {
        await withFfmpegLock(async () => {
          jobs.set(uploadId, { status: 'processing', message: 'Compressione del video in corso...' });
          logger.info(`Compressing video: ${originalFilename}`);
          outputPath = await compressAndConvertVideo(inputPath);
          logger.info(`Compression complete: ${outputPath}`);
        });

        // Stream upload to S3 (no buffer needed)
        jobs.set(uploadId, { status: 'uploading', message: 'Salvataggio del video...' });
        const videoUrl = await streamUploadToS3(outputPath!, videoFilename, 'video/mp4');

        logger.info(`Video uploaded successfully: ${videoUrl}`);
        jobs.set(uploadId, { status: 'done', message: 'Video pronto!', url: videoUrl });
      } catch (err) {
        logger.error('Background compression/upload error:', err);
        jobs.set(uploadId, {
          status: 'error',
          message: 'Si è verificato un errore durante l\'elaborazione del video.',
          error: err instanceof Error ? err.message : 'Compression failed',
        });
      } finally {
        // Cleanup temp files
        await unlink(inputPath).catch(() => {});
        if (outputPath) await unlink(outputPath).catch(() => {});
      }
    })();

    // Respond immediately — client will poll /api/upload-video-status
    return new Response(JSON.stringify({
      success: true,
      uploadId,
      message: 'Compression started. Poll /api/upload-video-status for progress.'
    }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    logger.error('Error in upload-video:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};

// Export jobs map so the status endpoint can access it
export { jobs };
