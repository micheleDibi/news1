export const prerender = false;

import type { APIRoute } from 'astro';
import { TextToSpeechClient, protos } from '@google-cloud/text-to-speech';
import { v4 as uuidv4 } from 'uuid';
import { uploadToS3 } from '../../../lib/aws';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import { slugify } from '../../../lib/utils';
import { error } from 'console';

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
    console.error(`Error checking path ${p}:`, error);
    return false;
  }
});

if (!credentialsPath) {
  console.error("Google credentials file not found in any of the expected locations");
  // Fallback to the first path and let it fail with a clear error if needed
  credentialsPath = possibleCredentialPaths[0];
}

console.log("Using credentials file at:", credentialsPath);

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
    console.log('--- TTS Generation --- Received Title:', title);
    console.log('--- TTS Generation --- Received Excerpt:', excerpt);
    console.log('--- TTS Generation --- Received Content:', content);
    
    // Prepare the text - include excerpt
    const fullText = `${title}. ${excerpt}. ${content}`;

    // Split text into 3 parts
    const textParts: string[] = [];
    const partLength = Math.ceil(fullText.length / 3);
    for (let i = 0; i < 3; i++) {
      textParts.push(fullText.substring(i * partLength, (i + 1) * partLength));
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
    console.error('Error generating audio:', error);
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



/*export const prerender = false;

import type { APIRoute } from 'astro';
import { accodaJobTts } from '../../../lib/ttsQueue';

export const POST: APIRoute = async ({ request }) => {
  try {
    // Check for API key
    const authHeader = request.headers.get('Authorization');
    const apiKey = authHeader?.split('Bearer ')[1];

    if (apiKey !== import.meta.env.API_SECRET_KEY) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const { articleId, title, content, excerpt } = await request.json();

    if (!articleId || !title) {
      return new Response(JSON.stringify({ error: 'Missing articleId or title' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Enqueue job in background
    const jobId = accodaJobTts(articleId, title, content, excerpt || '');

    return new Response(JSON.stringify({ jobId }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error('Error enqueueing TTS job:', error);
    return new Response(JSON.stringify({
      error: error instanceof Error ? error.message : 'Internal Server Error'
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};*/
