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

export const GET: APIRoute = async ({ request }) => {
  try {
    // Read logs file
    let logs = [];
    try {
      const logsData = fs.readFileSync(LOGS_FILE, 'utf8');
      logs = JSON.parse(logsData);
    } catch (err) {
      console.error('Error reading logs file:', err);
      return new Response(JSON.stringify({ 
        error: 'Error reading logs file',
        details: err instanceof Error ? err.message : String(err)
      }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Process query parameters
    const url = new URL(request.url);
    const limit = url.searchParams.get('limit') ? parseInt(url.searchParams.get('limit') as string, 10) : 50;
    const process = url.searchParams.get('process');
    const status = url.searchParams.get('status');
    const startDate = url.searchParams.get('startDate');
    const endDate = url.searchParams.get('endDate');

    // Filter logs based on query parameters
    let filteredLogs = [...logs];

    if (process) {
      filteredLogs = filteredLogs.filter(log => log.process === process);
    }

    if (status) {
      filteredLogs = filteredLogs.filter(log => log.status === status);
    }

    if (startDate) {
      const startTimestamp = new Date(startDate).getTime();
      filteredLogs = filteredLogs.filter(log => new Date(log.timestamp).getTime() >= startTimestamp);
    }

    if (endDate) {
      const endTimestamp = new Date(endDate).getTime();
      filteredLogs = filteredLogs.filter(log => new Date(log.timestamp).getTime() <= endTimestamp);
    }

    // Sort logs by timestamp (newest first)
    filteredLogs.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

    // Apply limit
    const limitedLogs = filteredLogs.slice(0, limit);

    // Return logs
    return new Response(JSON.stringify({
      logs: limitedLogs,
      total: filteredLogs.length,
      limit
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate'
      }
    });

  } catch (error) {
    console.error('Error fetching logs:', {
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