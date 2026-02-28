import React, { useState } from 'react';

interface SourcesTabProps {
  sources: string[];
  addSource: (url: string) => Promise<any>;
  removeSource: (url: string) => Promise<any>;
  isLoading: boolean;
}

export default function SourcesTab({ sources, addSource, removeSource, isLoading }: SourcesTabProps) {
  const [newSourceUrl, setNewSourceUrl] = useState('');
  const [validationError, setValidationError] = useState('');

  const handleAddSource = async (e: React.FormEvent) => {
    e.preventDefault();
    
    // Basic URL validation
    if (!newSourceUrl) {
      setValidationError('Please enter a URL');
      return;
    }
    
    try {
      new URL(newSourceUrl);
    } catch (err) {
      setValidationError('Please enter a valid URL');
      return;
    }
    
    setValidationError('');
    
    try {
      await addSource(newSourceUrl);
      setNewSourceUrl(''); // Clear input on success
    } catch (error) {
      console.error('Error adding source:', error);
    }
  };

  const handleRemoveSource = async (url: string) => {
    try {
      await removeSource(url);
    } catch (error) {
      console.error('Error removing source:', error);
    }
  };

  return (
    <div>
      <h2 className="text-lg font-medium text-gray-900 mb-4">News Sources</h2>
      <p className="text-sm text-gray-600 mb-6">
        Add news sources to scrape for articles. These sources will be used for automatic content generation.
      </p>
      
      {/* Add new source form */}
      <form onSubmit={handleAddSource} className="mb-8">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-grow">
            <label htmlFor="source-url" className="block text-sm font-medium text-gray-700 mb-1">
              Source URL
            </label>
            <input
              type="text"
              id="source-url"
              value={newSourceUrl}
              onChange={(e) => setNewSourceUrl(e.target.value)}
              placeholder="https://example.com"
              className="shadow-sm focus:ring-sport-500 focus:border-sport-500 block w-full sm:text-sm border-gray-300 rounded-md"
              disabled={isLoading}
            />
            {validationError && (
              <p className="mt-1 text-sm text-red-600">{validationError}</p>
            )}
          </div>
          <div className="flex items-end">
            <button
              type="submit"
              disabled={isLoading}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-sport-600 hover:bg-sport-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sport-500 disabled:opacity-50"
            >
              {isLoading ? 'Adding...' : 'Add Source'}
            </button>
          </div>
        </div>
      </form>
      
      {/* Sources list */}
      <div>
        <h3 className="text-md font-medium text-gray-900 mb-3">Current Sources</h3>
        
        {sources.length === 0 ? (
          <p className="text-sm text-gray-500 italic">No sources added yet.</p>
        ) : (
          <ul className="divide-y divide-gray-200 border-t border-b border-gray-200">
            {sources.map((source, index) => (
              <li key={index} className="py-3 flex justify-between items-center">
                <div>
                  <a 
                    href={source} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="text-sport-600 hover:text-sport-800"
                  >
                    {source}
                  </a>
                </div>
                <div className="flex space-x-2">
                  <button
                    type="button"
                    onClick={() => handleRemoveSource(source)}
                    className="inline-flex items-center px-2.5 py-1.5 border border-transparent text-xs font-medium rounded text-red-700 bg-red-100 hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
} 