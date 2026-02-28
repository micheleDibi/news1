export const prerender = false;

import type { APIRoute } from 'astro';
import fs from 'fs';
import path from 'path';

// Define the path to the logs file in the frontend
const LOGS_DIR = path.join(process.cwd(), 'src', 'data');
const LOGS_FILE = path.join(LOGS_DIR, 'pipeline_logs.json');

// Ensure logs directory exists
if (!fs.existsSync(LOGS_DIR)) {
  fs.mkdirSync(LOGS_DIR, { recursive: true });
}

// Initialize logs file if it doesn't exist
if (!fs.existsSync(LOGS_FILE)) {
  fs.writeFileSync(LOGS_FILE, JSON.stringify([]));
}

export const POST: APIRoute = async ({ request }) => {
  try {
    // Get log data from request
    const logEntry = await request.json();
    
    // Validate that we have required fields
    if (!logEntry.process || !logEntry.timestamp) {
      return new Response(JSON.stringify({ 
        error: 'Missing required fields: process and timestamp are required'
      }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }
    
    // Read existing logs
    let logs = [];
    try {
      const logsData = fs.readFileSync(LOGS_FILE, 'utf8');
      logs = JSON.parse(logsData);
    } catch (err) {
      // If there's an error reading the file, just use an empty array
      console.error('Error reading logs file:', err);
    }
    
    // Add new log entry
    logs.push(logEntry);
    
    // Sort logs by timestamp (newest first)
    logs.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
    
    // Write updated logs back to file
    fs.writeFileSync(LOGS_FILE, JSON.stringify(logs, null, 2));
    
    return new Response(JSON.stringify({ 
      success: true,
      message: 'Log entry added successfully'
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
  } catch (error) {
    console.error('Error adding log entry:', {
      error,
      type: error instanceof Error ? error.constructor.name : typeof error,
      message: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined
    });
    
    return new Response(JSON.stringify({ 
      error: 'Internal Server Error',
      details: error instanceof Error ? error.message : String(error)
    }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
}; 