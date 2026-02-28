/**
 * Script to copy Google credentials file to the root directory
 * This ensures the file is accessible in production environments
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.join(__dirname, '..');

// Source path
const sourcePath = path.join(rootDir, 'src', 'pages', 'api', 'tts', 'google-credentials.json');

// Destination paths
const destPaths = [
  path.join(rootDir, 'google-credentials.json'),
  path.join(rootDir, 'dist', 'google-credentials.json'),
  path.join(rootDir, 'public', 'google-credentials.json')
];

try {
  // Check if source file exists
  if (!fs.existsSync(sourcePath)) {
    console.error(`Source file not found: ${sourcePath}`);
    process.exit(1);
  }

  // Read the source file
  const credentialsData = fs.readFileSync(sourcePath, 'utf8');

  // Copy to each destination
  destPaths.forEach(destPath => {
    // Create directory if it doesn't exist
    const destDir = path.dirname(destPath);
    if (!fs.existsSync(destDir)) {
      fs.mkdirSync(destDir, { recursive: true });
    }

    // Write the file
    fs.writeFileSync(destPath, credentialsData);
    console.log(`Copied credentials to: ${destPath}`);
  });

  console.log('Google credentials file copied successfully to all locations');
} catch (error) {
  console.error('Error copying Google credentials file:', error);
  process.exit(1);
} 