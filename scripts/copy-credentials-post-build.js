/**
 * Post-build script to copy Google credentials file to the server directory
 * This ensures the file is accessible in production environments after build
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.join(__dirname, '..');

// Source path
const sourcePath = path.join(rootDir, 'src', 'pages', 'api', 'tts', 'google-credentials.json');

// Find all possible server directories where the file might be needed
const findServerDirs = (dir) => {
  const results = [];
  
  if (!fs.existsSync(dir)) {
    return results;
  }
  
  const files = fs.readdirSync(dir);
  
  for (const file of files) {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);
    
    if (stat.isDirectory()) {
      if (file === 'server' || file === 'api' || file === 'tts') {
        results.push(fullPath);
      }
      results.push(...findServerDirs(fullPath));
    }
  }
  
  return results;
};

try {
  // Check if source file exists
  if (!fs.existsSync(sourcePath)) {
    console.error(`Source file not found: ${sourcePath}`);
    process.exit(1);
  }

  // Read the source file
  const credentialsData = fs.readFileSync(sourcePath, 'utf8');

  // Find all server directories in the dist folder
  const serverDirs = findServerDirs(path.join(rootDir, 'dist'));
  
  // Add specific paths that might be needed
  const specificPaths = [
    path.join(rootDir, 'dist', 'server', 'pages', 'api', 'tts'),
    path.join(rootDir, 'dist', 'server', 'chunks'),
    path.join(rootDir, 'dist', 'server')
  ];
  
  // Combine and deduplicate paths
  const allDirs = [...new Set([...serverDirs, ...specificPaths])];
  
  // Copy to each directory
  let copyCount = 0;
  for (const dir of allDirs) {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    
    const destPath = path.join(dir, 'google-credentials.json');
    fs.writeFileSync(destPath, credentialsData);
    console.log(`Copied credentials to: ${destPath}`);
    copyCount++;
  }

  console.log(`Google credentials file copied successfully to ${copyCount} locations`);
} catch (error) {
  console.error('Error in post-build copy of Google credentials file:', error);
  process.exit(1);
} 