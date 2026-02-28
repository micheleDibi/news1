import React, { useState } from 'react';

interface ReconstructTabProps {
  summarizedNews: any[];
  reconstructedArticles: any[];
  reconstructArticle: (newsId: number) => Promise<any>;
  publishArticle?: (newsId: number) => Promise<any>;
  isLoading: boolean;
}

export default function ReconstructTab({ 
  summarizedNews, 
  reconstructedArticles, 
  reconstructArticle,
  publishArticle,
  isLoading 
}: ReconstructTabProps) {
  const [selectedNewsId, setSelectedNewsId] = useState<number | ''>('');
  const [reconstructStatus, setReconstructStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [statusMessage, setStatusMessage] = useState('');
  const [viewingArticle, setViewingArticle] = useState<any>(null);

  const handleReconstruct = async () => {
    if (!selectedNewsId) {
      setStatusMessage('Please select an article to reconstruct');
      setReconstructStatus('error');
      return;
    }

    // Check if the article is already reconstructed
    const alreadyReconstructed = reconstructedArticles.some(article => article.news_id === Number(selectedNewsId));
    if (alreadyReconstructed) {
      setStatusMessage('This article has already been reconstructed');
      setReconstructStatus('error');
      return;
    }

    setReconstructStatus('idle');
    setStatusMessage('');
    
    try {
      const result = await reconstructArticle(Number(selectedNewsId));
      if (result && result.success) {
        setReconstructStatus('success');
        setStatusMessage(`Successfully reconstructed article`);
        setSelectedNewsId(''); // Clear selection after successful reconstruction
      } else {
        setReconstructStatus('error');
        setStatusMessage(result?.message || 'Failed to reconstruct article');
      }
    } catch (error) {
      console.error('Error reconstructing article:', error);
      setReconstructStatus('error');
      setStatusMessage('An error occurred while reconstructing');
    }
  };

  const handlePublishArticle = async (newsId: number) => {
    if (publishArticle) {
      try {
        const result = await publishArticle(newsId);
        if (result && result.success) {
          alert(`Article published successfully!`);
        } else {
          alert(`Failed to publish article: ${result?.message || 'Unknown error'}`);
        }
      } catch (error) {
        console.error('Error publishing article:', error);
        alert('An error occurred while publishing the article');
      }
    }
  };

  // Filter out news that have already been reconstructed
  const availableNews = summarizedNews.filter(news => 
    !reconstructedArticles.some(article => article.news_id === news.id)
  );

  const handleViewArticle = (article: any) => {
    setViewingArticle(article);
  };

  const handleCloseViewer = () => {
    setViewingArticle(null);
  };

  return (
    <div>
      <h2 className="text-lg font-medium text-gray-900 mb-4">Reconstruct Articles</h2>
      <p className="text-sm text-gray-600 mb-6">
        Reconstruct full articles from summarized news for publishing.
      </p>
      
      {/* News selection and reconstruct button */}
      <div className="bg-gray-50 p-4 rounded-lg mb-6">
        <div className="mb-4">
          <label htmlFor="news-select" className="block text-sm font-medium text-gray-700 mb-1">
            Select Summarized News to Reconstruct
          </label>
          <select
            id="news-select"
            value={selectedNewsId}
            onChange={(e) => setSelectedNewsId(e.target.value ? Number(e.target.value) : '')}
            className="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-sport-500 focus:border-sport-500 sm:text-sm rounded-md"
            disabled={isLoading || availableNews.length === 0}
          >
            <option value="">Select a summarized news</option>
            {availableNews.map((news) => (
              <option key={news.id} value={news.id}>
                {news.title || 'Untitled'} - {news.url}
              </option>
            ))}
          </select>
        </div>
        
        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleReconstruct}
            disabled={isLoading || !selectedNewsId}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-sport-600 hover:bg-sport-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sport-500 disabled:opacity-50"
          >
            {isLoading ? 'Reconstructing...' : 'Reconstruct Article'}
          </button>
        </div>
        
        {/* Status message */}
        {statusMessage && (
          <div className={`mt-4 p-3 rounded-md ${
            reconstructStatus === 'success' ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
          }`}>
            {statusMessage}
          </div>
        )}
      </div>
      
      {/* Reconstructed articles list */}
      <div>
        <h3 className="text-md font-medium text-gray-900 mb-3">Reconstructed Articles</h3>
        
        {reconstructedArticles.length === 0 ? (
          <p className="text-sm text-gray-500 italic">No articles reconstructed yet.</p>
        ) : (
          <div className="bg-white shadow overflow-hidden sm:rounded-md">
            <ul className="divide-y divide-gray-200">
              {reconstructedArticles.map((article, index) => (
                <li key={index} className="px-4 py-4 sm:px-6">
                  <div className="flex flex-col gap-2">
                    <div className="flex justify-between">
                      <h4 className="text-sm font-medium text-gray-900">{article.title || 'Untitled'}</h4>
                      <div className="flex-shrink-0">
                        <span className="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-blue-100 text-blue-800">
                          Reconstructed
                        </span>
                      </div>
                    </div>
                    
                    {article.excerpt && (
                      <p className="text-sm text-gray-600 line-clamp-2">{article.excerpt}</p>
                    )}
                    
                    <div className="mt-2 flex justify-end space-x-2">
                      <button
                        type="button"
                        onClick={() => handleViewArticle(article)}
                        className="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-sport-700 bg-sport-100 hover:bg-sport-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sport-500"
                      >
                        View
                      </button>
                      <button
                        type="button"
                        onClick={() => handlePublishArticle(article.news_id)}
                        disabled={!publishArticle || isLoading}
                        className="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-green-700 bg-green-100 hover:bg-green-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:opacity-50"
                      >
                        Publish
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      
      {/* Article viewer modal */}
      {viewingArticle && (
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl overflow-hidden max-w-4xl w-full max-h-[90vh] flex flex-col">
            <div className="px-4 py-3 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-medium text-gray-900">
                {viewingArticle.title || 'Untitled Article'}
              </h3>
              <button
                type="button"
                onClick={handleCloseViewer}
                className="text-gray-400 hover:text-gray-500"
              >
                <span className="sr-only">Close</span>
                <svg className="h-6 w-6" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-auto p-6">
              {viewingArticle.image_url && (
                <img 
                  src={viewingArticle.image_url} 
                  alt={viewingArticle.title} 
                  className="w-full h-64 object-cover rounded-lg mb-6"
                />
              )}
              
              {viewingArticle.excerpt && (
                <div className="mb-6 text-lg text-gray-600 italic border-l-4 border-sport-500 pl-4 py-2">
                  {viewingArticle.excerpt}
                </div>
              )}
              
              <div className="prose max-w-none">
                {viewingArticle.content && (
                  <div dangerouslySetInnerHTML={{ __html: viewingArticle.content.replace(/\n\n/g, '<br><br>') }} />
                )}
              </div>
            </div>
            <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 flex justify-end">
              <button
                type="button"
                onClick={handleCloseViewer}
                className="px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sport-500"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
} 