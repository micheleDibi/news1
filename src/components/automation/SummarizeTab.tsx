import React, { useState } from 'react';

interface SummarizeTabProps {
  scrapedLinks: string[];
  summarizedNews: any[];
  summarizeLink: (link: string) => Promise<any>;
  reconstructArticle?: (newsId: number) => Promise<any>;
  isLoading: boolean;
}

export default function SummarizeTab({ 
  scrapedLinks, 
  summarizedNews, 
  summarizeLink,
  reconstructArticle,
  isLoading 
}: SummarizeTabProps) {
  const [selectedLink, setSelectedLink] = useState('');
  const [summarizeStatus, setSummarizeStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [statusMessage, setStatusMessage] = useState('');

  const handleSummarize = async () => {
    if (!selectedLink) {
      setStatusMessage('Please select a link to summarize');
      setSummarizeStatus('error');
      return;
    }

    // Check if the link is already summarized
    const alreadySummarized = summarizedNews.some(news => news.url === selectedLink);
    if (alreadySummarized) {
      setStatusMessage('This link has already been summarized');
      setSummarizeStatus('error');
      return;
    }

    setSummarizeStatus('idle');
    setStatusMessage('');
    
    try {
      const result = await summarizeLink(selectedLink);
      if (result && result.success) {
        setSummarizeStatus('success');
        setStatusMessage(`Successfully summarized article from ${selectedLink}`);
        setSelectedLink(''); // Clear selection after successful summarization
      } else {
        setSummarizeStatus('error');
        setStatusMessage(result?.message || 'Failed to summarize article');
      }
    } catch (error) {
      console.error('Error summarizing article:', error);
      setSummarizeStatus('error');
      setStatusMessage('An error occurred while summarizing');
    }
  };

  const handleReconstructArticle = async (newsId: number) => {
    if (reconstructArticle) {
      try {
        await reconstructArticle(newsId);
      } catch (error) {
        console.error('Error reconstructing article:', error);
      }
    }
  };

  // Filter out links that have already been summarized
  const availableLinks = scrapedLinks.filter(link => 
    !summarizedNews.some(news => news.url === link)
  );

  return (
    <div>
      <h2 className="text-lg font-medium text-gray-900 mb-4">Summarize Articles</h2>
      <p className="text-sm text-gray-600 mb-6">
        Summarize scraped articles to extract key information for reconstruction.
      </p>
      
      {/* Link selection and summarize button */}
      <div className="bg-gray-50 p-4 rounded-lg mb-6">
        <div className="mb-4">
          <label htmlFor="link-select" className="block text-sm font-medium text-gray-700 mb-1">
            Select Link to Summarize
          </label>
          <select
            id="link-select"
            value={selectedLink}
            onChange={(e) => setSelectedLink(e.target.value)}
            className="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-sport-500 focus:border-sport-500 sm:text-sm rounded-md"
            disabled={isLoading || availableLinks.length === 0}
          >
            <option value="">Select a link</option>
            {availableLinks.map((link, index) => (
              <option key={index} value={link}>
                {link}
              </option>
            ))}
          </select>
        </div>
        
        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleSummarize}
            disabled={isLoading || !selectedLink}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-sport-600 hover:bg-sport-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sport-500 disabled:opacity-50"
          >
            {isLoading ? 'Summarizing...' : 'Summarize Article'}
          </button>
        </div>
        
        {/* Status message */}
        {statusMessage && (
          <div className={`mt-4 p-3 rounded-md ${
            summarizeStatus === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
          }`}>
            {statusMessage}
          </div>
        )}
      </div>
      
      {/* Summarized news list */}
      <div>
        <h3 className="text-md font-medium text-gray-900 mb-3">Summarized Articles</h3>
        
        {summarizedNews.length === 0 ? (
          <p className="text-sm text-gray-500 italic">No articles summarized yet.</p>
        ) : (
          <div className="bg-white shadow overflow-hidden sm:rounded-md">
            <ul className="divide-y divide-gray-200">
              {summarizedNews.map((news, index) => (
                <li key={index} className="px-4 py-4 sm:px-6">
                  <div className="flex flex-col gap-2">
                    <div className="flex justify-between">
                      <h4 className="text-sm font-medium text-gray-900">{news.title || 'Untitled'}</h4>
                      <div className="flex-shrink-0">
                        <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800">
                          Summarized
                        </span>
                      </div>
                    </div>
                    
                    <p className="text-sm text-gray-600 truncate">
                      <a 
                        href={news.url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="text-sport-600 hover:underline"
                      >
                        {news.url}
                      </a>
                    </p>
                    
                    {news.summary && (
                      <div className="mt-2 text-sm text-gray-700">
                        <p className="font-medium mb-1">Summary:</p>
                        <p className="line-clamp-3">{news.summary}</p>
                      </div>
                    )}
                    
                    <div className="mt-2 flex justify-end">
                      <button
                        type="button"
                        onClick={() => handleReconstructArticle(news.id)}
                        disabled={!reconstructArticle || isLoading}
                        className="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-sport-700 bg-sport-100 hover:bg-sport-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sport-500 disabled:opacity-50"
                      >
                        Reconstruct
                      </button>
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