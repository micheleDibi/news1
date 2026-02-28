import type { APIRoute } from 'astro';
import type { Interpello } from '../../../types/interpelli';
import fs from 'fs/promises';
import path from 'path';

// Define the path to the data file
const dataFilePath = path.resolve(process.cwd(), 'src/data/interpelli.json');
const dataDir = path.dirname(dataFilePath);

// For now, we'll create a mock function to simulate fetching interpelli data
// In the future, this can be updated to fetch from actual USR APIs or websites
async function fetchInteripelliData(): Promise<Interpello[]> {
  // This is a mock implementation - replace with actual data source
  // Common sources would be USR websites, MIUR portals, or school district APIs
  
  const mockInterpelli: Interpello[] = [
    {
      id: "INT001",
      codice: "USR-LAZIO-2025-001",
      titolo: "Interpello per docente di Matematica - Scuola Secondaria di I grado",
      descrizione: "Interpello per la ricerca di un docente di Matematica per supplenza temporanea presso Istituto Comprensivo",
      descrizioneBreve: "Ricerca docente di Matematica per supplenza temporanea",
      figuraRicercata: "Docente di Matematica",
      materia: "Matematica",
      classeRicercata: "A28",
      dataPubblicazione: new Date().toISOString(),
      dataScadenza: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(), // 7 days from now
      linkReindirizzamento: "https://www.usrlazio.it/interpelli/int001",
      tipoProcedura: "Interpello",
      usrReferente: "USR Lazio",
      provincia: "Roma",
      comune: "Roma",
      scuola: "I.C. Via dei Pini",
      codiceScuola: "RMIC12345",
      numPosti: 1,
      durata: "Fino al termine delle attività didattiche",
      calculatedStatus: 'OPEN',
      statusLabel: "Aperto"
    },
    {
      id: "INT002",
      codice: "USR-LOMBARDIA-2025-002", 
      titolo: "Interpello per docente di Inglese - Scuola Primaria",
      descrizione: "Interpello per la ricerca di un docente di Inglese per supplenza temporanea presso Scuola Primaria",
      descrizioneBreve: "Ricerca docente di Inglese per scuola primaria",
      figuraRicercata: "Docente di Inglese",
      materia: "Inglese",
      classeRicercata: "Posto comune con specializzazione inglese",
      dataPubblicazione: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(), // 2 days ago
      dataScadenza: new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString(), // 5 days from now
      linkReindirizzamento: "https://www.istruzione.lombardia.gov.it/interpelli/int002",
      tipoProcedura: "Interpello",
      usrReferente: "USR Lombardia",
      provincia: "Milano",
      comune: "Milano",
      scuola: "Scuola Primaria Manzoni",
      codiceScuola: "MIEE67890",
      numPosti: 1,
      durata: "Supplenza breve",
      calculatedStatus: 'OPEN',
      statusLabel: "Aperto"
    }
  ];

  // Calculate status based on dates
  return mockInterpelli.map(interpello => {
    const now = new Date();
    const scadenza = new Date(interpello.dataScadenza);
    const daysDiff = (scadenza.getTime() - now.getTime()) / (1000 * 3600 * 24);
    
    let calculatedStatus: 'OPEN' | 'CLOSED' | 'PENDING';
    let statusLabel: string;
    
    if (scadenza < now) {
      calculatedStatus = 'CLOSED';
      statusLabel = 'Chiuso';
    } else if (daysDiff <= 3) {
      calculatedStatus = 'PENDING';
      statusLabel = 'In Scadenza';
    } else {
      calculatedStatus = 'OPEN';
      statusLabel = 'Aperto';
    }
    
    return {
      ...interpello,
      calculatedStatus,
      statusLabel
    };
  });
}

// Astro API Route (GET request to trigger refresh)
export const GET: APIRoute = async ({ request }) => {
  console.log('Received request to refresh interpelli data...');

  const interpelli = await fetchInteripelliData();

  if (!interpelli || interpelli.length === 0) {
    return new Response(JSON.stringify({ message: "No interpelli data available." }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  }

  try {
    // Ensure the data directory exists
    await fs.mkdir(dataDir, { recursive: true });

    // Write the fetched data to the JSON file
    await fs.writeFile(dataFilePath, JSON.stringify(interpelli, null, 2), 'utf-8');
    console.log(`Successfully wrote ${interpelli.length} interpelli to ${dataFilePath}`);

    return new Response(JSON.stringify({ message: `Successfully updated interpelli. Found ${interpelli.length} items.` }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error("Error writing interpelli data to file:", error);
    return new Response(JSON.stringify({ message: "Failed to write data to file." }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}; 