import React, { useState, useEffect } from 'react';
import { supabase } from '../lib/supabase';
import type { Podcast } from '../lib/supabase';
import { v4 as uuidv4 } from 'uuid';

interface PodcastFormProps {
  podcast?: Podcast;
}

export default function PodcastForm({ podcast }: PodcastFormProps) {
  const [title, setTitle] = useState(podcast?.title || '');
  const [description, setDescription] = useState(podcast?.description || '');
  const [audioUrl, setAudioUrl] = useState(podcast?.audio_url || '');
  const [imageUrl, setImageUrl] = useState(podcast?.image_url || '');
  const [category, setCategory] = useState(podcast?.category || '');
  const [duration, setDuration] = useState(podcast?.duration?.toString() || '');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [uploadMethod, setUploadMethod] = useState<'file' | 'url'>('file');
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageUploadMethod, setImageUploadMethod] = useState<'file' | 'url'>('url');

  const handleAudioFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    // Clean up previous URL if it exists
    if (audioUrl && audioUrl.startsWith('blob:')) {
      URL.revokeObjectURL(audioUrl);
    }
    
    const file = e.target.files?.[0];
    if (file) {
      setAudioFile(file);
      // Create a temporary URL for preview
      const tempUrl = URL.createObjectURL(file);
      setAudioUrl(tempUrl);
    } else {
      // Clear everything if no file is selected
      setAudioFile(null);
      setAudioUrl('');
    }
  };

  const handleAudioUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setAudioUrl(e.target.value);
    // Clear any file selection when URL is being entered
    setAudioFile(null);
  };

  const handleImageFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    try {
      const file = e.target.files?.[0];
      if (!file) return;

      setIsSubmitting(true); // Show loading state

      // Create temporary preview
      const tempUrl = URL.createObjectURL(file);
      setImageUrl(tempUrl);

      // Upload to S3
      const formData = new FormData();
      formData.append('file', file);
      formData.append('filename', `podcast_image_${uuidv4()}.${file.name.split('.').pop()}`);
      formData.append('title', title || 'podcast');

      const uploadResponse = await fetch('/api/upload', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: formData
      });

      if (!uploadResponse.ok) {
        throw new Error('Failed to upload image file');
      }

      const { url } = await uploadResponse.json();
      
      // Clean up blob URL
      URL.revokeObjectURL(tempUrl);
      
      // Set the S3 URL
      setImageUrl(url);
    } catch (error) {
      console.error('Error uploading image:', error);
      alert('Error uploading image: ' + (error as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError('');

    try {
      let finalAudioUrl = audioUrl;

      // Handle audio upload
      if (uploadMethod === 'file' && audioFile) {
        const formData = new FormData();
        formData.append('file', audioFile);
        formData.append('filename', `podcast_${uuidv4()}.${audioFile.name.split('.').pop()}`);

        const uploadResponse = await fetch('/api/upload', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
          },
          body: formData
        });

        if (!uploadResponse.ok) {
          throw new Error('Failed to upload audio file');
        }

        const { url } = await uploadResponse.json();
        finalAudioUrl = url;
      }

      const podcastData = {
        title,
        description,
        audio_url: finalAudioUrl,
        image_url: imageUrl || `https://picsum.photos/seed/${Math.random()}/800/600`,
        category,
        duration: duration ? parseInt(duration) : null,
        published_at: new Date().toISOString(),
      };

      const endpoint = podcast 
        ? `/api/podcasts/${podcast.id}`
        : '/api/podcasts/create';

      const response = await fetch(endpoint, {
        method: podcast ? 'PUT' : 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: JSON.stringify(podcastData)
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to save podcast');
      }

      // Redirect to admin podcasts page
      window.location.href = '/admin/podcasts';

    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 max-w-2xl mx-auto">
      {error && (
        <div className="bg-red-50 border-l-4 border-red-400 p-4 mb-4">
          <p className="text-red-700">{error}</p>
        </div>
      )}

      <div>
        <label htmlFor="title" className="block text-sm font-medium text-gray-700">
          Titolo
        </label>
        <input
          type="text"
          id="title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm"
        />
      </div>

      <div>
        <label htmlFor="description" className="block text-sm font-medium text-gray-700">
          Descrizione
        </label>
        <textarea
          id="description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          required
          rows={4}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm"
        />
      </div>

      <div className="bg-white p-6 rounded-lg border border-gray-200 space-y-4">
        <label className="block text-lg font-medium text-gray-900">
          Sorgente Audio
        </label>
        
        {/* Upload Method Selector */}
        <div className="inline-flex p-1 bg-gray-100 rounded-lg">
          <button
            type="button"
            onClick={() => setUploadMethod('file')}
            className={`px-4 py-2 rounded-md transition-all duration-200 ${
              uploadMethod === 'file'
                ? 'bg-white text-primary shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <div className="flex items-center space-x-2">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <span>Carica File</span>
            </div>
          </button>
          <button
            type="button"
            onClick={() => setUploadMethod('url')}
            className={`px-4 py-2 rounded-md transition-all duration-200 ${
              uploadMethod === 'url'
                ? 'bg-white text-primary shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <div className="flex items-center space-x-2">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              <span>Inserisci URL</span>
            </div>
          </button>
        </div>

        {/* File Upload Section */}
        {uploadMethod === 'file' ? (
          <div className="space-y-4">
            <div className="flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-lg">
              <div className="space-y-1 text-center">
                <svg
                  className="mx-auto h-12 w-12 text-gray-400"
                  stroke="currentColor"
                  fill="none"
                  viewBox="0 0 48 48"
                  aria-hidden="true"
                >
                  <path
                    d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8m-12 4h.02"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                <div className="flex text-sm text-gray-600">
                  <label
                    htmlFor="audioFile"
                    className="relative cursor-pointer rounded-md font-medium text-primary hover:text-primary-dark focus-within:outline-none focus-within:ring-2 focus-within:ring-offset-2 focus-within:ring-primary"
                  >
                    <span>Carica un file</span>
                    <input
                      id="audioFile"
                      type="file"
                      accept="audio/*"
                      onChange={handleAudioFileChange}
                      className="sr-only"
                    />
                  </label>
                  <p className="pl-1">o trascina qui</p>
                </div>
                <p className="text-xs text-gray-500">MP3, WAV fino a 10MB</p>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <input
              type="url"
              id="audioUrl"
              value={audioUrl}
              onChange={handleAudioUrlChange}
              placeholder="https://esempio.com/audio.mp3"
              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm"
            />
            <p className="text-sm text-gray-500">
              Inserisci l'URL diretto del tuo file audio
            </p>
          </div>
        )}

        {/* Audio Preview */}
        {audioUrl && (
          <div className="mt-4 p-4 bg-gray-50 rounded-lg">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-medium text-gray-900">Anteprima Audio</h4>
              {audioFile && (
                <span className="text-sm text-gray-500">
                  {audioFile.name}
                </span>
              )}
            </div>
            <audio controls className="w-full">
              <source src={audioUrl} type={audioFile?.type || 'audio/mpeg'} />
              Il tuo browser non supporta l'elemento audio.
            </audio>
          </div>
        )}
      </div>

      <div className="space-y-4">
        <label className="block text-sm font-medium text-gray-700">
          Immagine Copertina
        </label>

        {/* Image Preview */}
        {imageUrl && (
          <img
            src={imageUrl}
            alt="Preview"
            className="h-32 w-full object-cover rounded-lg"
          />
        )}

        {/* Upload Method Selector */}
        <div className="inline-flex p-1 bg-gray-100 rounded-lg">
          <button
            type="button"
            onClick={() => setImageUploadMethod('file')}
            className={`px-4 py-2 rounded-md transition-all duration-200 ${
              imageUploadMethod === 'file'
                ? 'bg-white text-primary shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <div className="flex items-center space-x-2">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <span>Carica File</span>
            </div>
          </button>
          <button
            type="button"
            onClick={() => setImageUploadMethod('url')}
            className={`px-4 py-2 rounded-md transition-all duration-200 ${
              imageUploadMethod === 'url'
                ? 'bg-white text-primary shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <div className="flex items-center space-x-2">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              <span>Inserisci URL</span>
            </div>
          </button>
        </div>

        {imageUploadMethod === 'file' ? (
          <div className="flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-lg">
            <div className="space-y-1 text-center">
              <svg
                className="mx-auto h-12 w-12 text-gray-400"
                stroke="currentColor"
                fill="none"
                viewBox="0 0 48 48"
                aria-hidden="true"
              >
                <path
                  d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8m-12 4h.02"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <div className="flex text-sm text-gray-600">
                <label
                  htmlFor="imageFile"
                  className="relative cursor-pointer rounded-md font-medium text-primary hover:text-primary-dark focus-within:outline-none focus-within:ring-2 focus-within:ring-offset-2 focus-within:ring-primary"
                >
                  <span>Carica un'immagine</span>
                  <input
                    id="imageFile"
                    type="file"
                    accept="image/*"
                    onChange={handleImageFileChange}
                    className="sr-only"
                  />
                </label>
                <p className="pl-1">o trascina qui</p>
              </div>
              <p className="text-xs text-gray-500">PNG, JPG, GIF fino a 10MB</p>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <input
              type="url"
              value={imageUrl}
              onChange={(e) => setImageUrl(e.target.value)}
              placeholder="https://esempio.com/immagine.jpg"
              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm"
            />
            <button
              type="button"
              onClick={() => setImageUrl(`https://picsum.photos/seed/${Math.random()}/800/600`)}
              className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50"
            >
              Immagine Casuale
            </button>
          </div>
        )}
      </div>

      <div>
        <label htmlFor="category" className="block text-sm font-medium text-gray-700">
          Categoria (opzionale)
        </label>
        <input
          type="text"
          id="category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm"
        />
      </div>

      <div>
        <label htmlFor="duration" className="block text-sm font-medium text-gray-700">
          Durata in minuti (opzionale)
        </label>
        <input
          type="number"
          id="duration"
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
          min="0"
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary sm:text-sm"
        />
      </div>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={isSubmitting}
          className="inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50"
        >
          {isSubmitting ? 'Salvataggio...' : podcast ? 'Aggiorna Podcast' : 'Crea Podcast'}
        </button>
      </div>
    </form>
  );
} 