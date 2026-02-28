export const prerender = false;

import type { APIRoute } from 'astro';
import { v4 as uuidv4 } from 'uuid';
import { uploadToS3 } from '../../lib/aws'; // Corrected path relative to src/pages/api/
import sharp from 'sharp';
import path from 'path';
import { slugify } from '../../lib/utils';


const TARGET_WIDTHS = [320, 480, 640, 768, 1024, 1280]; // Define target widths for variants

// Helper function to extract filename and extension
function getFilenameAndExtension(url: string, contentType: string | null): { filename: string; extension: string } {
  try {
    const parsedUrl = new URL(url);
    let filenameBase = path.basename(parsedUrl.pathname);
    let extension = path.extname(filenameBase).toLowerCase();

    // If filename is empty or just an extension, generate a random one
    if (!filenameBase || filenameBase === extension) {
      filenameBase = uuidv4();
    } else {
      // Remove extension from base
      filenameBase = filenameBase.substring(0, filenameBase.length - extension.length);
    }

    // Try to get a better extension from content type if URL didn't provide one
    if (!extension && contentType) {
      const mimeTypeExtension = contentType.split('/')[1];
      if (mimeTypeExtension) {
        extension = `.${mimeTypeExtension.split('+')[0]}`; // Handle things like image/svg+xml
      }
    }

    // Default extension if still unknown
    if (!extension) {
      extension = '.jpg'; // Or handle as error?
    }

    const finalFilename = `${filenameBase}_${uuidv4()}${extension}`;
    return { filename: finalFilename, extension: extension };

  } catch (e) {
    // Fallback if URL parsing fails
    console.error("Error parsing URL for filename, using UUID:", e);
    const extension = contentType?.split('/')[1] ? `.${contentType.split('/')[1]}` : '.jpg';
    return { filename: `${uuidv4()}${extension}`, extension: extension };
  }
}


export const POST: APIRoute = async ({ request }) => {
  // --- Authorization Check ---
  const authHeader = request.headers.get('Authorization');
  const apiKey = authHeader?.split('Bearer ')[1];
  if (apiKey !== import.meta.env.API_SECRET_KEY) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401 });
  }
  // --- End Authorization Check ---

  try {
    const { imageUrl, title } = await request.json();

    if (!imageUrl || typeof imageUrl !== 'string' || !title) {
      return new Response(JSON.stringify({ error: 'Missing or invalid imageUrl or title' }), { status: 400 });
    }

    console.log(`Attempting to download image from: ${imageUrl}`);

    // 1. Download the image
    const downloadResponse = await fetch(imageUrl);
    if (!downloadResponse.ok) {
      throw new Error(`Failed to download image. Status: ${downloadResponse.status} ${downloadResponse.statusText}`);
    }

    const imageBuffer = Buffer.from(await downloadResponse.arrayBuffer());
    const contentType = downloadResponse.headers.get('content-type');

    if (!contentType || !contentType.startsWith('image/')) {
       console.warn(`Content-Type is not an image (${contentType}), proceeding anyway.`);
       // You might want to return an error here depending on requirements
       // return new Response(JSON.stringify({ error: 'Downloaded content is not an image' }), { status: 400 });
    }

    console.log(`Image downloaded successfully. Content-Type: ${contentType}, Size: ${imageBuffer.length} bytes`);

    // 2. Determine base filename for WebP conversion
    const { filename } = getFilenameAndExtension(imageUrl, contentType);
    const uniqueSuffix = Date.now().toString();
    const baseName = slugify(title || filename) + '-' + uniqueSuffix;

    //const baseName= slugify(title || filename);
    //const nameParts = filename.split('.');
    //nameParts.pop(); // Remove original extension
    //const baseName = nameParts.join('.'); // This is what we'll use for variants

    // 3. Create and Upload the primary WebP image (full size or largest practical size)
    const primaryWebpBuffer = await sharp(imageBuffer)
      .webp({ quality: 80 })
      .toBuffer();
    
    const primaryWebpFilename = `${baseName}.webp`; // e.g., filename_uuid.webp
    const primaryWebpUrl = await uploadToS3(primaryWebpBuffer, primaryWebpFilename, 'image/webp');

    console.log(`Successfully uploaded primary WebP to S3: ${primaryWebpUrl}`);

    // 4. Create and Upload variants
    for (const width of TARGET_WIDTHS) {
      try {
        const variantBuffer = await sharp(primaryWebpBuffer) // Use the primaryWebpBuffer as source
          .resize({ width })
          .webp({ quality: 75 }) // Potentially slightly lower quality for smaller files
          .toBuffer();
        
        const variantFilename = `${baseName}-${width}w.webp`; // e.g., filename_uuid-640w.webp
        await uploadToS3(variantBuffer, variantFilename, 'image/webp');
        console.log(`Uploaded variant: ${variantFilename}`);
      } catch (variantError) {
        console.error(`Error creating or uploading variant for width ${width}:`, variantError);
        // Decide if you want to fail the whole request or just skip this variant
        // For now, it just logs and continues
      }
    }

    // 5. Return the URL of the primary (largest) WebP image
    return new Response(JSON.stringify({
      success: true,
      url: primaryWebpUrl, // Changed from aws_url to url for consistency with /api/upload
      filename: primaryWebpFilename, // Return the WebP filename
      content_type: 'image/webp' // Always WebP now
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Error processing image URL upload:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};