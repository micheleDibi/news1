export const prerender = false;

import type { APIRoute } from 'astro';
import { uploadToS3 } from '../../lib/aws';
import { slugify } from '../../lib/utils';
import { compressAndConvertVideo } from '../../lib/video-compress';
import { readFile, unlink, readdir } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';

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
    const title = formData.get('title') as string;
    const originalFilename = formData.get('filename') as string;

    if (!uploadId || !title || !originalFilename) {
      return new Response(JSON.stringify({ error: 'Missing uploadId, title, or filename' }), {
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

    // Remove chunk directory
    const { rmdir } = await import('fs/promises');
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

    // Compress and convert to MP4 via FFmpeg
    console.log(`Compressing video: ${originalFilename} (${(buffer.length / 1024 / 1024).toFixed(1)}MB)`);
    const compressedBuffer = await compressAndConvertVideo(buffer, originalFilename);
    console.log(`Compressed video: ${(compressedBuffer.length / 1024 / 1024).toFixed(1)}MB`);

    const contentType = 'video/mp4';
    const videoFilename = `${slugify(title)}.mp4`;

    const videoUrl = await uploadToS3(compressedBuffer, videoFilename, contentType);

    console.log(`Video uploaded successfully: ${videoUrl}`);

    return new Response(JSON.stringify({
      success: true,
      url: videoUrl
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error('Error uploading video file:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};
