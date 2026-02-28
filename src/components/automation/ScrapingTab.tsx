import React, { useState } from 'react';

interface ScrapingTabProps {
  sources: string[];
  scrapedLinks: string[];
  scrapeSource: (url: string) => Promise<any>;
  summarizeLink?: (link: string) => Promise<any>;
  isLoading: boolean;
}

export default function ScrapingTab({ 
  sources, 
  scrapedLinks, 
  scrapeSource,
  summarizeLink,
  isLoading 
}: ScrapingTabProps) {
  const [selectedSource, setSelectedSource] = useState('');
  const [scrapeStatus, setScrapeStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [statusMessage, setStatusMessage] = useState('');

  const handleScrape = async () => {
    if (!selectedSource) {
      setStatusMessage('Please select a source to scrape');
      setScrapeStatus('error');
      return;
    }

    setScrapeStatus('idle');
    setStatusMessage('');
    
    try {
      const result = await scrapeSource(selectedSource);
      if (result && result.success) {
        setScrapeStatus('success');
        setStatusMessage(`Successfully scraped ${result.links?.length || 0} links from ${selectedSource}`);
      } else {
        setScrapeStatus('error');
        setStatusMessage(result?.message || 'Failed to scrape source');
      }
    } catch (error) {
      console.error('Error scraping source:', error);
      setScrapeStatus('error');
      setStatusMessage('An error occurred while scraping');
    }
  };

  const handleSummarizeLink = async (link: string) => {
    if (summarizeLink) {
      try {
        setScrapeStatus('idle');
        setStatusMessage('');
        
        const result = await summarizeLink(link);
        
        if (result && result.success) {
          setScrapeStatus('success');
          setStatusMessage(`Successfully summarized article from ${link}`);
        } else {
          setScrapeStatus('error');
          setStatusMessage(result?.message || 'Failed to summarize article');
        }
      } catch (error) {
        console.error('Error summarizing link:', error);
        setScrapeStatus('error');
        setStatusMessage('An error occurred while summarizing');
      }
    }
  };

  return (
    <div>
      <h2 className="text-lg font-medium text-gray-900 mb-4">Scrape News Sources</h2>
      <p className="text-sm text-gray-600 mb-6">
        Scrape news sources to extract article links for summarization and reconstruction.
      </p>
      
      {/* Source selection and scrape button */}
      <div className="bg-gray-50 p-4 rounded-lg mb-6">
        <div className="mb-4">
          <label htmlFor="source-select" className="block text-sm font-medium text-gray-700 mb-1">
            Select Source to Scrape
          </label>
          <select
            id="source-select"
            value={selectedSource}
            onChange={(e) => setSelectedSource(e.target.value)}
            className="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-sport-500 focus:border-sport-500 sm:text-sm rounded-md"
            disabled={isLoading || sources.length === 0}
          >
            <option value="">Select a source</option>
            {sources.map((source, index) => (
              <option key={index} value={source}>
                {source}
              </option>
            ))}
          </select>
        </div>
        
        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleScrape}
            disabled={isLoading || !selectedSource}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-sport-600 hover:bg-sport-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sport-500 disabled:opacity-50"
          >
            {isLoading ? 'Scraping...' : 'Scrape Source'}
          </button>
        </div>
        
        {/* Status message */}
        {statusMessage && (
          <div className={`mt-4 p-3 rounded-md ${
            scrapeStatus === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
          }`}>
            {statusMessage}
          </div>
        )}
      </div>
      
      {/* Scraped links list */}
      <div>
        <h3 className="text-md font-medium text-gray-900 mb-3">Scraped Links</h3>
        
        {scrapedLinks.length === 0 ? (
          <p className="text-sm text-gray-500 italic">No links scraped yet.</p>
        ) : (
          <div className="bg-white shadow overflow-hidden sm:rounded-md">
            <ul className="divide-y divide-gray-200">
              {scrapedLinks.map((link, index) => (
                <li key={index}>
                  <div className="px-4 py-4 sm:px-6">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium text-sport-600 truncate">
                        <a 
                          href={link} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="hover:underline"
                        >
                          {link}
                        </a>
                      </p>
                      <div className="ml-2 flex-shrink-0 flex">
                        <button
                          type="button"
                          onClick={() => handleSummarizeLink(link)}
                          disabled={!summarizeLink || isLoading}
                          className="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-sport-700 bg-sport-100 hover:bg-sport-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sport-500 disabled:opacity-50"
                        >
                          Summarize
                        </button>
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
} 