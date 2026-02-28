import type { APIRoute } from "astro";
import fs from "fs/promises";
import path from "path";

// Define the path to the EU funding data file
const dataFilePath = path.resolve(
  process.cwd(),
  "src/data/eu-funding-opportunities.json"
);

interface ItaliaDomaniBando {
  source: string;
  title: string;
  description: string;
  published_date: string;
  deadline: string;
  budget: string;
  category: string;
  url: string;
  status: number;
  scraped_at: string;
}

interface EUFundingData {
  incentivi_gov_it: any[];
  obiettivoeuropa_com: any[];
  italiadomani_gov_it: ItaliaDomaniBando[];
  summary: {
    total_opportunities: number;
    last_updated: string;
    sources: Record<string, number>;
  };
}

// Function to trigger ItaliaDomani scraping
async function triggerItaliaDomaniScraping(): Promise<
  ItaliaDomaniBando[] | null
> {
  try {
    console.log("Triggering ItaliaDomani scraping...");

    const { spawn } = require("child_process");
    const path = require("path");

    return new Promise((resolve, reject) => {
      const pythonScript = path.join(
        process.cwd(),
        "backend",
        "app",
        "ScrapingBandiEuropeiFinal",
        "ScrapingBandiEuropeiFinal",
        "srapingbandiitaliadomani",
        "api_scraper_bandi.py"
      );

      const pythonProcess = spawn("python", [pythonScript], {
        cwd: path.join(
          process.cwd(),
          "backend",
          "app",
          "ScrapingBandiEuropeiFinal",
          "ScrapingBandiEuropeiFinal",
          "srapingbandiitaliadomani"
        ),
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
          console.log("ItaliaDomani scraper completed successfully");

          // Try to read the generated JSON file
          try {
            const fs = require("fs");
            const outputDir = path.join(
              process.cwd(),
              "backend",
              "app",
              "ScrapingBandiEuropeiFinal",
              "ScrapingBandiEuropeiFinal",
              "srapingbandiitaliadomani",
              "output"
            );

            // Find the latest JSON file
            const files = fs
              .readdirSync(outputDir)
              .filter(
                (f: string) =>
                  f.startsWith("bandi_italiadomani_") && f.endsWith(".json")
              )
              .map((f: string) => ({
                name: f,
                path: path.join(outputDir, f),
                mtime: fs.statSync(path.join(outputDir, f)).mtime,
              }))
              .sort((a: any, b: any) => b.mtime - a.mtime);

            if (files.length > 0) {
              const latestFile = files[0].path;
              const rawData = fs.readFileSync(latestFile, "utf8");
              const scrapedData = JSON.parse(rawData);

              // Transform the data to match our interface
              const transformedData: ItaliaDomaniBando[] = scrapedData.map(
                (item: any) => ({
                  source: "italiadomani.gov.it",
                  title: item.titolo || "",
                  description: item.descrizione || "",
                  published_date: item.data_pubblicazione || "",
                  deadline: item.scadenza || "",
                  budget: item.budget || "",
                  category: item.categoria || "Bandi ItaliaDomani",
                  url: item.link || "",
                  status: 1,
                  scraped_at: new Date().toISOString(),
                })
              );

              resolve(transformedData);
            } else {
              console.log("No output files found");
              reject(new Error("No output files found"));
            }
          } catch (error) {
            console.error("Error reading scraped data:", error);
            reject(error);
          }
        } else {
          console.error("ItaliaDomani scraper failed with code:", code);
          console.error("Error output:", errorOutput);
          reject(new Error(`ItaliaDomani scraper failed with code ${code}`));
        }
      });
    });
  } catch (error) {
    console.error("Error triggering ItaliaDomani scraping:", error);
    return null;
  }
}

// Astro API Route (GET request to trigger refresh)
export const GET: APIRoute = async ({ request }) => {
  console.log("Received request to refresh ItaliaDomani data...");

  const italiadomaniData = await triggerItaliaDomaniScraping();

  if (italiadomaniData === null) {
    return new Response(
      JSON.stringify({ message: "Failed to fetch ItaliaDomani data." }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }

  try {
    // Read existing EU funding data
    const existingData = await fs.readFile(dataFilePath, "utf-8");
    const euData: EUFundingData = JSON.parse(existingData);

    // Update ItaliaDomani section
    euData.italiadomani_gov_it = italiadomaniData;

    // Update summary
    const total_opportunities = Object.values(euData).reduce(
      (total, source) => {
        if (Array.isArray(source)) {
          return total + source.length;
        }
        return total;
      },
      0
    );

    euData.summary = {
      total_opportunities,
      last_updated: new Date().toISOString(),
      sources: {
        incentivi_gov_it: euData.incentivi_gov_it?.length || 0,
        obiettivoeuropa_com: euData.obiettivoeuropa_com?.length || 0,
        italiadomani_gov_it: italiadomaniData.length,
      },
    };

    // Write the updated data back to the file
    await fs.writeFile(dataFilePath, JSON.stringify(euData, null, 2), "utf-8");
    console.log(
      `Successfully updated ItaliaDomani data. Found ${italiadomaniData.length} opportunities.`
    );

    return new Response(
      JSON.stringify({
        message: `Successfully updated ItaliaDomani data. Found ${italiadomaniData.length} opportunities.`,
        summary: euData.summary,
        italiadomani_count: italiadomaniData.length,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }
    );
  } catch (error) {
    console.error("Error updating ItaliaDomani data:", error);
    return new Response(JSON.stringify({ message: "Failed to update data." }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
};

// POST endpoint to manually trigger scraping with parameters
export const POST: APIRoute = async ({ request }) => {
  try {
    const body = await request.json();
    const { force_refresh } = body;

    console.log(
      `Manual ItaliaDomani scraping triggered with force_refresh: ${force_refresh}`
    );

    const italiadomaniData = await triggerItaliaDomaniScraping();

    if (italiadomaniData === null) {
      return new Response(
        JSON.stringify({ message: "Failed to fetch ItaliaDomani data." }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    // Update the data file
    const existingData = await fs.readFile(dataFilePath, "utf-8");
    const euData: EUFundingData = JSON.parse(existingData);

    euData.italiadomani_gov_it = italiadomaniData;

    const total_opportunities = Object.values(euData).reduce(
      (total, source) => {
        if (Array.isArray(source)) {
          return total + source.length;
        }
        return total;
      },
      0
    );

    euData.summary = {
      total_opportunities,
      last_updated: new Date().toISOString(),
      sources: {
        incentivi_gov_it: euData.incentivi_gov_it?.length || 0,
        obiettivoeuropa_com: euData.obiettivoeuropa_com?.length || 0,
        italiadomani_gov_it: italiadomaniData.length,
      },
    };

    await fs.writeFile(dataFilePath, JSON.stringify(euData, null, 2), "utf-8");

    return new Response(
      JSON.stringify({
        message: "Manual ItaliaDomani scraping completed successfully.",
        summary: euData.summary,
        italiadomani_count: italiadomaniData.length,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }
    );
  } catch (error) {
    console.error("Error in manual ItaliaDomani scraping:", error);
    return new Response(
      JSON.stringify({ message: "Failed to process manual scraping request." }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
};
