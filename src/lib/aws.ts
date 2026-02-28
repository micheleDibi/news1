import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

// Initialize S3 Client
const s3Client = new S3Client({
  region: import.meta.env.AWS_REGION,
  credentials: {
    accessKeyId: import.meta.env.AWS_ACCESS_KEY_ID,
    secretAccessKey: import.meta.env.AWS_SECRET_ACCESS_KEY,
  },
});

export const uploadToS3 = async (
  buffer: Buffer,
  filename: string,
  contentType: string
): Promise<string> => {
  // Normalize MIME: fall back to a sensible video type if missing
  const normalizedContentType =
    contentType ||
    (filename.toLowerCase().endsWith('.mov') ? 'video/quicktime' : 'video/mp4');

  const command = new PutObjectCommand({
    Bucket: import.meta.env.AWS_BUCKET_NAME,
    Key: `audios/${filename}`,
    Body: buffer,
    ContentType: normalizedContentType,
    ContentDisposition: 'inline',
    CacheControl: 'public, max-age=31536000',
  });

  await s3Client.send(command);

  // Return the public URL
  return `https://${import.meta.env.AWS_BUCKET_NAME}.s3.${import.meta.env.AWS_REGION}.amazonaws.com/audios/${filename}`;
};
