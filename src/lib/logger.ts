import fs from 'fs';
import path from 'path';

type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

const LOGS_DIR = path.join(process.cwd(), 'logs');

// Ensure logs directory exists
try {
  if (!fs.existsSync(LOGS_DIR)) {
    fs.mkdirSync(LOGS_DIR, { recursive: true });
  }
} catch {
  // Fallback: logs dir might not be writable in some environments
}

function getLogFilePath(): string {
  const now = new Date();
  const date = now.toISOString().slice(0, 10); // YYYY-MM-DD
  return path.join(LOGS_DIR, `frontend-${date}.log`);
}

function getTimestamp(): string {
  return new Date().toISOString().replace('T', ' ').replace('Z', '');
}

function getCallerInfo(): string {
  const err = new Error();
  const stack = err.stack?.split('\n') || [];
  // Walk up the stack to find the first frame outside logger.ts
  for (let i = 3; i < stack.length; i++) {
    const frame = stack[i];
    if (!frame.includes('logger.ts') && !frame.includes('logger.js')) {
      // Extract file:line from the stack frame
      const match = frame.match(/(?:at\s+.*?\s+\(|at\s+)(.*?):(\d+):\d+\)?/);
      if (match) {
        const file = path.basename(match[1]);
        return `${file}:${match[2]}`;
      }
      break;
    }
  }
  return 'unknown';
}

function formatArgs(args: unknown[]): string {
  return args
    .map(a => {
      if (a instanceof Error) return `${a.message}\n${a.stack}`;
      if (typeof a === 'object') {
        try { return JSON.stringify(a); } catch { return String(a); }
      }
      return String(a);
    })
    .join(' ');
}

function log(level: LogLevel, message: string, ...args: unknown[]): void {
  const timestamp = getTimestamp();
  const caller = getCallerInfo();
  const extra = args.length > 0 ? ' ' + formatArgs(args) : '';
  const line = `[${timestamp}] [${level.padEnd(5)}] [${caller}] ${message}${extra}`;

  // Write to file
  try {
    fs.appendFileSync(getLogFilePath(), line + '\n', 'utf-8');
  } catch {
    // Silently fail if file write isn't possible
  }

  // Console output (preserve dev experience)
  const consoleFn =
    level === 'ERROR' ? console.error :
    level === 'WARN' ? console.warn :
    level === 'DEBUG' ? console.debug :
    console.log;

  consoleFn(line);
}

export const logger = {
  debug: (message: string, ...args: unknown[]) => log('DEBUG', message, ...args),
  info: (message: string, ...args: unknown[]) => log('INFO', message, ...args),
  warn: (message: string, ...args: unknown[]) => log('WARN', message, ...args),
  error: (message: string, ...args: unknown[]) => log('ERROR', message, ...args),
};
