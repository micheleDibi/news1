export const prerender = false;

import type { APIRoute } from 'astro';
import { logger } from '../../../lib/logger';

export const POST: APIRoute = async ({ request }) => {
  try {
    const logEntry = await request.json();

    if (!logEntry.process || !logEntry.timestamp) {
      return new Response(JSON.stringify({
        error: 'Missing required fields: process and timestamp are required'
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Log the entry to the unified logging system
    const level = logEntry.status === 'error' ? 'error' : 'info';
    const message = `[${logEntry.process}] ${logEntry.message || logEntry.status || 'log entry'}`;

    if (level === 'error') {
      logger.error(message, logEntry);
    } else {
      logger.info(message, logEntry);
    }

    return new Response(JSON.stringify({
      success: true,
      message: 'Log entry added successfully'
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    logger.error('Error adding log entry', error instanceof Error ? error : new Error(String(error)));

    return new Response(JSON.stringify({
      error: 'Internal Server Error',
      details: error instanceof Error ? error.message : String(error)
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};
