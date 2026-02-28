// src/lib/s3-multipart.ts
import {
    AbortMultipartUploadCommand,
    CompleteMultipartUploadCommand,
    CreateMultipartUploadCommand,
    S3Client,
    UploadPartCommand,
  } from '@aws-sdk/client-s3';
  
  const s3Client = new S3Client({
    region: import.meta.env.AWS_REGION,
    credentials: {
      accessKeyId: import.meta.env.AWS_ACCESS_KEY_ID,
      secretAccessKey: import.meta.env.AWS_SECRET_ACCESS_KEY,
    },
  });
  
  const BUCKET = import.meta.env.AWS_BUCKET_NAME;
  
  /**
   * Avvia un multipart upload e restituisce UploadId + chiave.
   */
  export async function createMultipartUpload(key: string) {
    return s3Client.send(
      new CreateMultipartUploadCommand({
        Bucket: BUCKET,
        Key: key,
        CacheControl: 'public, max-age=31536000',
      })
    );
  }
  
  /**
   * Carica la singola parte n-esima (0-based nell’iterazione, 1-based per S3).
   */
  export async function uploadPartToS3(
    key: string,
    uploadId: string,
    chunk: Buffer,
    partIndex: number
  ) {
    return s3Client.send(
      new UploadPartCommand({
        Bucket: BUCKET,
        Key: key,
        UploadId: uploadId,
        Body: chunk,
        PartNumber: partIndex + 1,
      })
    );
  }
  
  /**
   * Completa l’upload passando l’array di ETag restituiti da uploadPartToS3.
   */
  export async function completeMultipartUpload(
    key: string,
    uploadId: string,
    parts: Array<{ ETag: string }>
  ) {
    return s3Client.send(
      new CompleteMultipartUploadCommand({
        Bucket: BUCKET,
        Key: key,
        UploadId: uploadId,
        MultipartUpload: {
          Parts: parts.map(({ ETag }, index) => ({
            ETag,
            PartNumber: index + 1,
          })),
        },
      })
    );
  }
  
  /**
   * Annulla l’upload (da chiamare se qualcosa va storto).
   */
  export async function abortMultipartUpload(key: string, uploadId: string) {
    await s3Client.send(
      new AbortMultipartUploadCommand({
        Bucket: BUCKET,
        Key: key,
        UploadId: uploadId,
      })
    );
  }
  