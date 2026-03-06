import ffmpeg from 'fluent-ffmpeg';
import { randomUUID } from 'crypto';
import { tmpdir } from 'os';
import { join } from 'path';
import { writeFile, readFile, unlink } from 'fs/promises';

const MAX_SIZE_BYTES = 100 * 1024 * 1024; // 100MB

function getVideoDuration(filePath: string): Promise<number> {
  return new Promise((resolve, reject) => {
    ffmpeg.ffprobe(filePath, (err, metadata) => {
      if (err) return reject(err);
      resolve(metadata.format.duration || 60);
    });
  });
}

function runFfmpeg(inputPath: string, outputPath: string, options: { targetBitrate?: number }): Promise<void> {
  return new Promise((resolve, reject) => {
    let cmd = ffmpeg(inputPath)
      .output(outputPath)
      .videoCodec('libx264')
      .audioCodec('aac')
      .format('mp4')
      .outputOptions(['-movflags', '+faststart']);

    if (options.targetBitrate) {
      const br = `${options.targetBitrate}k`;
      cmd = cmd.outputOptions([
        `-maxrate`, br,
        `-bufsize`, `${options.targetBitrate * 2}k`,
      ]);
    } else {
      cmd = cmd.outputOptions(['-crf', '23']);
    }

    cmd
      .on('end', () => resolve())
      .on('error', (err: Error) => reject(err))
      .run();
  });
}

export async function compressAndConvertVideo(inputBuffer: Buffer, originalFilename: string): Promise<Buffer> {
  const id = randomUUID();
  const ext = originalFilename.includes('.') ? '.' + originalFilename.split('.').pop()!.toLowerCase() : '.mp4';
  const inputPath = join(tmpdir(), `${id}-input${ext}`);
  const outputPath = join(tmpdir(), `${id}-output.mp4`);

  try {
    await writeFile(inputPath, inputBuffer);

    const duration = await getVideoDuration(inputPath);
    const inputSize = inputBuffer.length;

    let targetBitrate: number | undefined;
    if (inputSize > MAX_SIZE_BYTES) {
      // Calculate bitrate to fit in 100MB: (100MB in kbits) / duration
      targetBitrate = Math.floor((MAX_SIZE_BYTES * 8) / (duration * 1024));
    }

    await runFfmpeg(inputPath, outputPath, { targetBitrate });

    const outputBuffer = await readFile(outputPath);
    return outputBuffer;
  } finally {
    await unlink(inputPath).catch(() => {});
    await unlink(outputPath).catch(() => {});
  }
}
