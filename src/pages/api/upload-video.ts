export const prerender = false;

import type { APIRoute } from 'astro';
import { uploadToS3 } from '../../lib/aws';
import { slugify } from '../../lib/utils';
import { compressAndConvertVideo } from '../../lib/video-compress';
import { readFile, unlink, readdir, writeFile, rmdir } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';

// In-memory job status store
const jobs = new Map<string, { status: 'processing' | 'done' | 'error'; url?: string; error?: string }>();

// Cleanup old jobs after 30 minutes
function scheduleJobCleanup(uploadId: string) {
  setTimeout(() => jobs.delete(uploadId), 30 * 60 * 1000);
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

    console.log('Assembly request:', { uploadId, title, originalFilename });

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

    // Read and concatenate all chunks
    const chunks: Buffer[] = [];
    for (const chunkFile of chunkFiles) {
      const chunkPath = join(chunkDir, chunkFile);
      chunks.push(await readFile(chunkPath));
      await unlink(chunkPath).catch(() => {});
    }
    await rmdir(chunkDir).catch(() => {});

    const buffer = Buffer.concat(chunks);
    console.log(`Reassembled ${chunkFiles.length} chunks: ${(buffer.length / 1024 / 1024).toFixed(1)}MB`);

    // Validate file type by extension
    const ext = originalFilename.split('.').pop()?.toLowerCase();
    const allowedExts = ['mp4', 'webm', 'ogg', 'avi', 'mov'];
    if (!ext || !allowedExts.includes(ext)) {
      return new Response(JSON.stringify({ error: 'Invalid video file type. Allowed: MP4, WebM, OGG, AVI, MOV' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Mark job as processing and respond immediately
    jobs.set(uploadId, { status: 'processing' });
    scheduleJobCleanup(uploadId);

    // Run compression + upload in the background (not awaited)
    (async () => {
      try {
        console.log(`Compressing video: ${originalFilename} (${(buffer.length / 1024 / 1024).toFixed(1)}MB)`);
        const compressedBuffer = await compressAndConvertVideo(buffer, originalFilename);
        console.log(`Compressed video: ${(compressedBuffer.length / 1024 / 1024).toFixed(1)}MB`);

        const contentType = 'video/mp4';
        const videoFilename = `${slugify(title || originalFilename.replace(/\.[^.]+$/, ''))}.mp4`;
        const videoUrl = await uploadToS3(compressedBuffer, videoFilename, contentType);

        console.log(`Video uploaded successfully: ${videoUrl}`);
        jobs.set(uploadId, { status: 'done', url: videoUrl });
      } catch (err) {
        console.error('Background compression/upload error:', err);
        jobs.set(uploadId, { status: 'error', error: err instanceof Error ? err.message : 'Compression failed' });
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
    console.error('Error in upload-video:', error);
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
