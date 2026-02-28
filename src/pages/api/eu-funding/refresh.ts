import type { APIRoute } from "astro";
import fs from "fs/promises";
import path from "path";

// Define the path to the EU funding data file
const dataFilePath = path.resolve(
  process.cwd(),
  "src/data/eu-funding-opportunities.json"
);
const dataDir = path.dirname(dataFilePath);

// Interface for EU funding opportunities
interface EUFundingOpportunity {
  source: string;
  title: string;
  description: string;
  published_date: string;
  deadline: string;
  budget: string;
  category: string;
  url: string;
  status: string;
  scraped_at: string;
}

interface EUFundingData {
  incentivi_gov_it: EUFundingOpportunity[];
  obiettivoeuropa_com: EUFundingOpportunity[];
  italiadomani_gov_it: EUFundingOpportunity[];
  summary: {
    total_opportunities: number;
    last_updated: string;
    sources: Record<string, number>;
  };
}

// Function to trigger the Python scraper
async function triggerEUScraping(): Promise<EUFundingData | null> {
  try {
    console.log("Triggering EU funding opportunities scraping...");

    // Import and run the Python scraper
    const { spawn } = require("child_process");
    const path = require("path");

    return new Promise((resolve, reject) => {
      const pythonScript = path.join(
        process.cwd(),
        "backend",
        "app",
        "eu_funding_scraper.py"
      );
      const pythonProcess = spawn("python", [pythonScript], {
        cwd: path.join(process.cwd(), "backend", "app"),
      });

      let output = "";
      let errorOutput = "";

      pythonProcess.stdout.on("data", (data: Buffer) => {
        output += data.toString();
      });

      pythonProcess.stderr.on("data", (data: Buffer) => {
        errorOutput += data.toString();
      });

      pythonProcess.on("close", (code: number) => {
        if (code === 0) {
          console.log("Python scraper completed successfully");
          console.log("Output:", output);

          // Try to read the generated JSON file
          try {
            const fs = require("fs");
            const dataPath = path.join(
              process.cwd(),
              "backend",
              "app",
              "eu_funding_opportunities.json"
            );

            if (fs.existsSync(dataPath)) {
              const rawData = fs.readFileSync(dataPath, "utf8");
              const scrapedData = JSON.parse(rawData);

              // Transform the data to match our interface
              const transformedData: EUFundingData = {
                incentivi_gov_it: scrapedData.incentivi_gov_it || [],

                obiettivoeuropa_com: scrapedData.obiettivoeuropa_com || [],
                italiadomani_gov_it: scrapedData.italiadomani_gov_it || [],
                summary: {
                  total_opportunities:
                    scrapedData.summary?.total_opportunities || 0,
                  last_updated: new Date().toISOString(),
                  sources: scrapedData.summary?.sources || {},
                },
              };

              resolve(transformedData);
            } else {
              console.log("No data file found, using empty structure");
              resolve({
                incentivi_gov_it: [],

                obiettivoeuropa_com: [],
                italiadomani_gov_it: [],
                summary: {
                  total_opportunities: 0,
                  last_updated: new Date().toISOString(),
                  sources: {},
                },
              });
            }
          } catch (error) {
            console.error("Error reading scraped data:", error);
            reject(error);
          }
        } else {
          console.error("Python scraper failed with code:", code);
          console.error("Error output:", errorOutput);
          reject(new Error(`Python scraper failed with code ${code}`));
        }
      });
    });
  } catch (error) {
    console.error("Error triggering EU scraping:", error);
    return null;
  }
}

// Astro API Route (GET request to trigger refresh)
export const GET: APIRoute = async ({ request }) => {
  console.log("Received request to refresh EU funding opportunities...");

  const euData = await triggerEUScraping();

  if (euData === null) {
    return new Response(
      JSON.stringify({ message: "Failed to fetch EU funding data." }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }

  try {
    // Ensure the data directory exists
    await fs.mkdir(dataDir, { recursive: true });

    // Write the fetched data to the JSON file
    await fs.writeFile(dataFilePath, JSON.stringify(euData, null, 2), "utf-8");
    console.log(`Successfully wrote EU funding data to ${dataFilePath}`);

    return new Response(
      JSON.stringify({
        message: `Successfully updated EU funding opportunities. Found ${euData.summary.total_opportunities} total opportunities.`,
        summary: euData.summary,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }
    );
  } catch (error) {
    console.error("Error writing EU funding data to file:", error);
    return new Response(
      JSON.stringify({ message: "Failed to write data to file." }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
};

// POST endpoint to manually trigger scraping with parameters
export const POST: APIRoute = async ({ request }) => {
  try {
    const body = await request.json();
    const { sources, max_pages } = body;

    console.log(
      `Manual EU scraping triggered with sources: ${sources}, max_pages: ${max_pages}`
    );

    // Here you would call the Python scraper with specific parameters
    const euData = await triggerEUScraping();

    if (euData === null) {
      return new Response(
        JSON.stringify({ message: "Failed to fetch EU funding data." }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    // Save the data
    await fs.mkdir(dataDir, { recursive: true });
    await fs.writeFile(dataFilePath, JSON.stringify(euData, null, 2), "utf-8");

    return new Response(
      JSON.stringify({
        message: "Manual EU funding scraping completed successfully.",
        summary: euData.summary,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }
    );
  } catch (error) {
    console.error("Error in manual EU scraping:", error);
    return new Response(
      JSON.stringify({ message: "Failed to process manual scraping request." }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
};
