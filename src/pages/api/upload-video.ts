export const prerender = false;

import type { APIRoute } from 'astro';
import { uploadToS3 } from '../../lib/aws';
import { slugify } from '../../lib/utils';

export const POST: APIRoute = async ({ request }) => {
  try {
    // Check for API key
    const authHeader = request.headers.get('Authorization');
    const apiKey = authHeader?.split('Bearer ')[1];

    if (apiKey !== import.meta.env.API_SECRET_KEY) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    const formData = await request.formData();
    const file = formData.get('file') as File;
    const originalClientFilename = formData.get('filename') as string; // e.g., article_video_uuid.mp4
    const title = formData.get('title') as string;

    if (!file || !originalClientFilename || !title) {
      return new Response(JSON.stringify({ error: 'No file or filename or title provided' }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Validate file type
    const allowedVideoTypes = ['video/mp4', 'video/webm', 'video/ogg', 'video/avi', 'video/mov', 'video/quicktime'];
    if (!allowedVideoTypes.includes(file.type)) {
      return new Response(JSON.stringify({ error: 'Invalid video file type. Allowed: MP4, WebM, OGG, AVI, MOV' }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Normalize content type for S3 (ensure inline playback)
    let contentType = file.type;
    if (!contentType) {
      const lowerName = originalClientFilename?.toLowerCase() || '';
      contentType = lowerName.endsWith('.mov') ? 'video/quicktime' : 'video/mp4';
    }

    const buffer = Buffer.from(await file.arrayBuffer());

    //usamil titolo per il nome del file
    const ext = (originalClientFilename.split('.').pop() || 'mp4').toLowerCase();
    const videoFilename = `${slugify(title)}.${ext}`;

    // Upload the video file directly (no processing needed like with images)
    //const videoUrl = await uploadToS3(buffer, originalClientFilename, contentType);
    const videoUrl = await uploadToS3(buffer, videoFilename, contentType);

    console.log(`Video uploaded successfully: ${videoUrl}`);

    // Return the URL of the uploaded video
    return new Response(JSON.stringify({ 
      success: true,
      url: videoUrl
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  } catch (error) {
    console.error('Error uploading video file:', error);
    return new Response(JSON.stringify({ 
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
};
