import ffmpeg from 'fluent-ffmpeg';
import { randomUUID } from 'crypto';
import { tmpdir } from 'os';
import { join } from 'path';

const MAX_SIZE_BYTES = 100 * 1024 * 1024; // 100MB
const FFMPEG_BASE_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes base
const FFMPEG_TIMEOUT_PER_100MB_MS = 5 * 60 * 1000; // +5 min per 100MB extra

function getVideoDuration(filePath: string): Promise<number> {
  return new Promise((resolve, reject) => {
    ffmpeg.ffprobe(filePath, (err, metadata) => {
      if (err) return reject(err);
      resolve(metadata.format.duration || 60);
    });
  });
}

function getFileSize(filePath: string): Promise<number> {
  return import('fs/promises').then(fs => fs.stat(filePath)).then(s => s.size);
}

function runFfmpeg(inputPath: string, outputPath: string, options: { targetBitrate?: number; inputSize: number }): Promise<void> {
  return new Promise((resolve, reject) => {
    let cmd = ffmpeg(inputPath)
      .output(outputPath)
      .videoCodec('libx264')
      .audioCodec('aac')
      .format('mp4')
      .outputOptions([
        '-movflags', '+faststart',
        '-threads', '2',
        '-preset', 'veryfast',
      ]);

    if (options.targetBitrate) {
      const br = `${options.targetBitrate}k`;
      cmd = cmd.outputOptions([
        `-maxrate`, br,
        `-bufsize`, `${options.targetBitrate * 2}k`,
      ]);
    } else {
      cmd = cmd.outputOptions(['-crf', '23']);
    }

    // Timeout: scale with file size (10min base + 5min per 100MB)
    const timeoutMs = FFMPEG_BASE_TIMEOUT_MS + Math.ceil(options.inputSize / MAX_SIZE_BYTES) * FFMPEG_TIMEOUT_PER_100MB_MS;
    const timer = setTimeout(() => {
      cmd.kill('SIGTERM');
      reject(new Error(`ffmpeg timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);

    cmd
      .on('end', () => { clearTimeout(timer); resolve(); })
      .on('error', (err: Error) => { clearTimeout(timer); reject(err); })
      .run();
  });
}

/**
 * Compresses a video file on disk and returns the path to the compressed output.
 * The caller is responsible for cleaning up both inputPath and the returned outputPath.
 */
export async function compressAndConvertVideo(inputPath: string): Promise<string> {
  const id = randomUUID();
  const outputPath = join(tmpdir(), `${id}-output.mp4`);

  const inputSize = await getFileSize(inputPath);
  const duration = await getVideoDuration(inputPath);

  let targetBitrate: number | undefined;
  if (inputSize > MAX_SIZE_BYTES) {
    targetBitrate = Math.floor((MAX_SIZE_BYTES * 8) / (duration * 1024));
  }

  await runFfmpeg(inputPath, outputPath, { targetBitrate, inputSize });

  return outputPath;
}
