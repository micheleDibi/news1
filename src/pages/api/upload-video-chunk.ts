export const prerender = false;

import type { APIRoute } from 'astro';
import { mkdir, writeFile } from 'fs/promises';
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
    const chunk = formData.get('chunk') as File;
    const uploadId = formData.get('uploadId') as string;
    const chunkIndex = formData.get('chunkIndex') as string;
    const totalChunks = formData.get('totalChunks') as string;

    if (!chunk || !uploadId || chunkIndex === null || !totalChunks) {
      return new Response(JSON.stringify({ error: 'Missing chunk, uploadId, chunkIndex, or totalChunks' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Create chunk directory
    const chunkDir = join(tmpdir(), `upload-${uploadId}`);
    await mkdir(chunkDir, { recursive: true });

    // Write chunk to disk with zero-padded index for correct sorting
    const paddedIndex = chunkIndex.padStart(5, '0');
    const chunkPath = join(chunkDir, `chunk-${paddedIndex}`);
    const buffer = Buffer.from(await chunk.arrayBuffer());
    await writeFile(chunkPath, buffer);

    console.log(`Received chunk ${parseInt(chunkIndex) + 1}/${totalChunks} for upload ${uploadId} (${(buffer.length / 1024 / 1024).toFixed(1)}MB)`);

    return new Response(JSON.stringify({
      success: true,
      chunkIndex: parseInt(chunkIndex),
      totalChunks: parseInt(totalChunks)
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error('Error receiving chunk:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};
