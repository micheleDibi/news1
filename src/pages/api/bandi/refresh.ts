import type { APIRoute } from 'astro';
import type { Bando } from '../../../types/bandi'; // Adjust path as needed
import fs from 'fs/promises';
import path from 'path';

// Define the path to the data file, ensuring it's writable
const dataFilePath = path.resolve(process.cwd(), 'src/data/bandi.json');
const dataDir = path.dirname(dataFilePath);

// Interface for the expected API response structure (based on Python script usage)
interface InpaApiResponse {
  content: Bando[];
  totalElements: number;
  totalPages: number;
  // Add other fields if needed
}

// Function to fetch bandi from INPA API
async function fetchBandiFromINPA(page = 0, size = 2000): Promise<Bando[] | null> {
  const url = `https://portale.inpa.gov.it/concorsi-smart/api/concorso-public-area/search-better?page=${page}&size=${size}`;

  const payload = {
    text: "",
    categoriaId: null,
    regioneId: null,
    status: ["OPEN"], // Fetch only open bandi
    settoreId: null,
    provinciaCodice: null,
    dateFrom: null,
    dateTo: null,
    livelliAnzianitaIds: null,
    tipoImpiegoId: null,
    salaryMin: null,
    salaryMax: null,
    enteRiferimentoName: ""
  };

  const headers = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", // Using a common bot user agent
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.inpa.gov.it/"
  };

  try {
    console.log(`Fetching bandi from INPA: ${url} with size ${size}`);
    const response = await fetch(url, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status} ${response.statusText}`);
    }

    const data: InpaApiResponse = await response.json();
    console.log(`Successfully fetched ${data.content?.length ?? 0} bandi out of ${data.totalElements}.`);

    // Validate response structure
    if (data && Array.isArray(data.content)) {
       return data.content;
    } else {
      console.error('Invalid API response structure:', data);
      return null;
    }

  } catch (error) {
    console.error("Error fetching bandi from INPA:", error);
    return null;
  }
}

// Astro API Route (GET request to trigger refresh)
export const GET: APIRoute = async ({ request }) => {
  console.log('Received request to refresh bandi data...');

  const bandi = await fetchBandiFromINPA();

  if (bandi === null) {
    return new Response(JSON.stringify({ message: "Failed to fetch data from INPA API." }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  try {
    // Ensure the data directory exists
    await fs.mkdir(dataDir, { recursive: true });

    // Write the fetched data to the JSON file
    await fs.writeFile(dataFilePath, JSON.stringify(bandi, null, 2), 'utf-8');
    console.log(`Successfully wrote ${bandi.length} bandi to ${dataFilePath}`);

    return new Response(JSON.stringify({ message: `Successfully updated bandi. Found ${bandi.length} items.` }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error("Error writing bandi data to file:", error);
    return new Response(JSON.stringify({ message: "Failed to write data to file." }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}; 