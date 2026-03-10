export const prerender = false;

import type { APIRoute } from 'astro';
import { TextToSpeechClient, protos } from '@google-cloud/text-to-speech';
import { v4 as uuidv4 } from 'uuid';
import { uploadToS3 } from '../../../lib/aws';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import { slugify } from '../../../lib/utils';
import { logger } from '../../../lib/logger';

// Get the directory name of the current module
const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Define multiple possible paths for the credentials file
const possibleCredentialPaths = [
  // Path relative to this file
  path.join(__dirname, "google-credentials.json"),
  // Path from project root
  path.join(process.cwd(), "google-credentials.json")
];

// Find the first path that exists
let credentialsPath = possibleCredentialPaths.find(p => {
  try {
    return fs.existsSync(p);
  } catch (error) {
    logger.error(`Error checking path ${p}:`, error);
    return false;
  }
});

if (!credentialsPath) {
  logger.error("Google credentials file not found in any of the expected locations");
  // Fallback to the first path and let it fail with a clear error if needed
  credentialsPath = possibleCredentialPaths[0];
}

logger.info("Using credentials file at:", credentialsPath);

// Initialize the client
const client = new TextToSpeechClient({
  keyFilename: credentialsPath
});

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

    const { title, content, excerpt } = await request.json();
    if (!title){
      return new Response (JSON.stringify({error: 'Missing title'}),{
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }
    
    // Log the received content for debugging
    logger.info('--- TTS Generation --- Received Title:', title);
    logger.info('--- TTS Generation --- Received Excerpt:', excerpt);
    logger.info('--- TTS Generation --- Received Content:', content);
    
    // Prepare the text - include excerpt
    const fullText = `${title}. ${excerpt}. ${content}`;

    // Split text into chunks that stay under 5000 bytes (Google TTS limit)
    const MAX_BYTES = 4800; // margine di sicurezza
    const encoder = new TextEncoder();
    const textParts: string[] = [];
    let remaining = fullText;
    while (remaining.length > 0) {
      let end = remaining.length;
      // Shrink until the chunk fits in MAX_BYTES
      while (encoder.encode(remaining.substring(0, end)).length > MAX_BYTES) {
        const prevEnd = end;
        // Try to cut at a sentence boundary
        const cut = remaining.lastIndexOf('. ', end - 1);
        if (cut > 0 && cut > end * 0.3) {
          end = cut + 1; // include the period
        } else {
          // Fallback: cut at space
          const spaceCut = remaining.lastIndexOf(' ', end - 1);
          end = spaceCut > 0 ? spaceCut : Math.floor(end * 0.8);
        }
        // Safety: force progress to avoid infinite loop
        if (end >= prevEnd) {
          end = Math.floor(prevEnd * 0.8);
        }
        if (end <= 0) {
          end = 1;
          break;
        }
      }
      textParts.push(remaining.substring(0, end));
      remaining = remaining.substring(end).trimStart();
    }

    const audioContents: Buffer[] = [];

    for (const textPart of textParts) {
      if (textPart.trim().length === 0) continue; // Skip empty parts

      // Configure the request
      const ttsRequest: protos.google.cloud.texttospeech.v1.ISynthesizeSpeechRequest = {
        input: { text: textPart },
        voice: {
          languageCode: "it-IT",
          name: "it-IT-Journey-O",
          ssmlGender: protos.google.cloud.texttospeech.v1.SsmlVoiceGender.FEMALE
        },
        audioConfig: { audioEncoding: protos.google.cloud.texttospeech.v1.AudioEncoding.MP3 }
      };

      // Generate speech
      const [response] = await client.synthesizeSpeech(ttsRequest);
      if (response.audioContent) {
        audioContents.push(Buffer.from(response.audioContent as Uint8Array));
      }
    }

    // Concatenate audio buffers
    const combinedAudioBuffer = Buffer.concat(audioContents);

    // Generate filename
    //const titleNoSpaces = title.replace(/\s+/g, '');
    //const filename = `audio_${titleNoSpaces}_${uuidv4()}.mp3`;
    const baseName = slugify(title);
    const filename= `${baseName}.mp3`;

    // Upload to S3
    const audioUrl = await uploadToS3(
      combinedAudioBuffer,
      filename,
      'audio/mpeg'
    );

    return new Response(JSON.stringify({ 
      success: true,
      audioUrl
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });

  } catch (error) {
    logger.error('Error generating audio:', error);
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
