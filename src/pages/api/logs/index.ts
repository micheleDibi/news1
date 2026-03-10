export const prerender = false;

import type { APIRoute } from 'astro';
import fs from 'fs';
import path from 'path';
import { logger } from '../../../lib/logger';

const LOGS_DIR = path.join(process.cwd(), 'logs');

interface LogEntry {
  timestamp: string;
  level: string;
  source: string;
  message: string;
}

function parseLogLine(line: string, source: string): LogEntry | null {
  // Format: [2026-03-10 14:32:05.123] [INFO ] [file.py:func:42] message
  const match = line.match(/^\[([^\]]+)\]\s+\[(\w+)\s*\]\s+\[([^\]]+)\]\s+(.*)$/);
  if (!match) return null;
  return {
    timestamp: match[1],
    level: match[2].trim(),
    source: `${source}:${match[3]}`,
    message: match[4],
  };
}

function getLogFiles(dateStr?: string): string[] {
  if (!fs.existsSync(LOGS_DIR)) return [];
  const files = fs.readdirSync(LOGS_DIR).filter(f => f.endsWith('.log'));
  if (dateStr) {
    return files.filter(f => f.includes(dateStr));
  }
  return files;
}

export const GET: APIRoute = async ({ request }) => {
  try {
    const url = new URL(request.url);
    const limit = parseInt(url.searchParams.get('limit') || '100', 10);
    const dateFilter = url.searchParams.get('date') || undefined;
    const levelFilter = url.searchParams.get('level')?.toUpperCase() || undefined;
    const sourceFilter = url.searchParams.get('source') || undefined; // "backend" or "frontend"

    const logFiles = getLogFiles(dateFilter);
    const entries: LogEntry[] = [];

    for (const file of logFiles) {
      const filePath = path.join(LOGS_DIR, file);
      const fileSource = file.startsWith('backend') ? 'backend' : 'frontend';

      if (sourceFilter && fileSource !== sourceFilter) continue;

      try {
        const content = fs.readFileSync(filePath, 'utf-8');
        for (const line of content.split('\n')) {
          if (!line.trim()) continue;
          const entry = parseLogLine(line, fileSource);
          if (!entry) continue;
          if (levelFilter && entry.level !== levelFilter) continue;
          entries.push(entry);
        }
      } catch {
        // Skip unreadable files
      }
    }

    // Sort newest first
    entries.sort((a, b) => b.timestamp.localeCompare(a.timestamp));

    const limited = entries.slice(0, limit);

    return new Response(JSON.stringify({
      logs: limited,
      total: entries.length,
      limit,
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
      },
    });

  } catch (error) {
    logger.error('Error fetching logs', error instanceof Error ? error : new Error(String(error)));

    return new Response(JSON.stringify({
      error: 'Internal Server Error',
      details: error instanceof Error ? error.message : String(error),
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
