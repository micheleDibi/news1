export const prerender = false;

import type { APIRoute } from 'astro';
import { uploadToS3 } from '../../lib/aws';
import sharp from 'sharp';
// import { v4 as uuidv4 } from 'uuid'; // uuid is part of originalClientFilename from client
import { slugify } from '../../lib/utils';

const TARGET_WIDTHS = [320, 480, 640, 768, 1024, 1280]; // Define target widths for variants

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
    const originalClientFilename = formData.get('filename') as string; // e.g., article_content_uuid.jpg
    const title = formData.get('title') as string | null; // titolo passato dal client

    if (!file || !originalClientFilename) {
      return new Response(JSON.stringify({ error: 'No file or filename provided' }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    const buffer = Buffer.from(await file.arrayBuffer());

    // Determine the base name (e.g., article_content_uuid) from the client-provided filename
    // Use title if provided, otherwise fall back to filename (without extension)
    const nameParts = originalClientFilename.split('.');
    nameParts.pop(); // Remove original extension
    const filenameBase = nameParts.join('.');
    //const baseName = title && title.trim() ? slugify(title) : slugify(filenameBase);
    const uniqueSuffix = Date.now().toString();
    const baseName = (title && title.trim() ? slugify(title) : slugify(filenameBase)) + '-' + uniqueSuffix;


    // 1. Create and Upload the primary WebP image (full size or largest practical size)
    const primaryWebpBuffer = await sharp(buffer)
      .webp({ quality: 80 })
      .toBuffer();
    
    const primaryWebpFilename = `${baseName}.webp`; // e.g., titolo-articolo.webp
    const primaryWebpUrl = await uploadToS3(primaryWebpBuffer, primaryWebpFilename, 'image/webp', 'images/');

    // 2. Create and Upload variants
    for (const width of TARGET_WIDTHS) {
      try {
        const variantBuffer = await sharp(primaryWebpBuffer) // Use the primaryWebpBuffer as source
          .resize({ width })
          .webp({ quality: 75 }) // Potentially slightly lower quality for smaller files
          .toBuffer();
        
        const variantFilename = `${baseName}-${width}w.webp`; // e.g., article_content_uuid-640w.webp
        await uploadToS3(variantBuffer, variantFilename, 'image/webp', 'images/');
        console.log(`Uploaded variant: ${variantFilename}`);
      } catch (variantError) {
        console.error(`Error creating or uploading variant for width ${width}:`, variantError);
        // Decide if you want to fail the whole request or just skip this variant
        // For now, it just logs and continues
      }
    }

    // Return the URL of the primary (largest) WebP image
    return new Response(JSON.stringify({ 
      success: true,
      url: primaryWebpUrl // This URL is used as src and for the largest srcset entry
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });

  } catch (error) {
    console.error('Error uploading file:', error);
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