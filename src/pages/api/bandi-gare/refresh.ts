import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// Define the BandoGara interface based on what the Python scraper extracts
interface BandoGara {
  titolo: string;
  url: string;
  data_atto?: string;
  data_atto_human?: string;
  scadenza?: string;
  scadenza_human?: string;
  origine?: string;
  ufficio?: string;
  cig?: string;
  link_anac?: string;
}

// Define the path to the data file
const dataFilePath = path.resolve(process.cwd(), 'src/data/bandi-gare.json');
const dataDir = path.dirname(dataFilePath);

// Function to convert CSV to JSON
function csvToJson(csvText: string): BandoGara[] {
  const lines = csvText.trim().split('\n');
  if (lines.length < 2) return []; // No data rows
  
  const headers = lines[0].split(',').map(h => h.replace(/"/g, '').trim());
  const result: BandoGara[] = [];
  
  for (let i = 1; i < lines.length; i++) {
    const values = parseCSVLine(lines[i]);
    if (values.length !== headers.length) continue; // Skip malformed rows
    
    const bando: any = {};
    headers.forEach((header, index) => {
      const value = values[index]?.replace(/"/g, '').trim();
      if (value && value !== '') {
        bando[header] = value;
      }
    });
    
    // Only add if we have essential data
    if (bando.titolo && bando.url) {
      result.push(bando as BandoGara);
    }
  }
  
  return result;
}

// Helper function to properly parse CSV lines (handles commas inside quotes)
function parseCSVLine(line: string): string[] {
  const result = [];
  let current = '';
  let inQuotes = false;
  
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    
    if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === ',' && !inQuotes) {
      result.push(current);
      current = '';
    } else {
      current += char;
    }
  }
  
  result.push(current); // Don't forget the last field
  return result;
}

// Function to run the Python scraper
async function runBandiScraper(): Promise<BandoGara[] | null> {
  try {
    console.log('Running Python bandi scraper...');
    
    // Change to the directory containing the Python script and run it
    const projectRoot = process.cwd();
    const { stdout, stderr } = await execAsync(`cd ${projectRoot} && python3 bandi_scraper.py`);
    
    if (stderr && !stderr.includes('Warning')) {
      console.error('Python script stderr:', stderr);
    }
    
    console.log('Python script output:', stdout);
    
    // Read the generated CSV file
    const csvFilePath = path.resolve(projectRoot, 'bandi_gara.csv');
    
    try {
      const csvContent = await fs.readFile(csvFilePath, 'utf-8');
      console.log('CSV file read successfully, length:', csvContent.length);
      
      // Convert CSV to JSON
      const bandiData = csvToJson(csvContent);
      console.log(`Converted ${bandiData.length} bandi from CSV to JSON`);
      
      return bandiData;
      
    } catch (csvError) {
      console.error('Error reading CSV file:', csvError);
      return null;
    }
    
  } catch (error) {
    console.error('Error running Python scraper:', error);
    return null;
  }
}

// Astro API Route (GET request to trigger refresh)
export const GET: APIRoute = async ({ request }) => {
  console.log('Received request to refresh bandi-gare data...');

  const bandiGare = await runBandiScraper();

  if (bandiGare === null) {
    return new Response(JSON.stringify({ message: "Failed to fetch data from bandi scraper." }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  try {
    // Ensure the data directory exists
    await fs.mkdir(dataDir, { recursive: true });

    // Write the fetched data to the JSON file
    await fs.writeFile(dataFilePath, JSON.stringify(bandiGare, null, 2), 'utf-8');
    console.log(`Successfully wrote ${bandiGare.length} bandi-gare to ${dataFilePath}`);

    return new Response(JSON.stringify({ message: `Successfully updated bandi-gare. Found ${bandiGare.length} items.` }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error("Error writing bandi-gare data to file:", error);
    return new Response(JSON.stringify({ message: "Failed to write data to file." }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}; 