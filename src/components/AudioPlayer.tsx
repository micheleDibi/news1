import React, { useState, useRef, useEffect } from 'react';

interface AudioPlayerProps {
  audioUrl: string;
  title: string;
}

export default function AudioPlayer({ audioUrl, title }: AudioPlayerProps) {
  const isSoundCloud = audioUrl.includes('soundcloud.com');

  if (isSoundCloud) {
    const embedUrl = `https://w.soundcloud.com/player/?url=${encodeURIComponent(audioUrl)}&color=%23ff5500&auto_play=false&hide_related=true&show_comments=false&show_user=true&show_reposts=false&show_teaser=false`;

    return (
      <div className="w-full rounded-lg overflow-hidden bg-gray-100">
        <iframe
          width="100%"
          height="166"
          scrolling="no"
          frameBorder="no"
          allow="autoplay"
          src={embedUrl}
          className="w-full"
        ></iframe>
      </div>
    );
  }

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    // Force metadata loading on mobile
    audio.preload = "metadata";
    
    // Try to load duration immediately if available
    if (audio.duration && !isNaN(audio.duration)) {
      setDuration(audio.duration);
    }

    // Handle cases where duration isn't immediately available
    const handleDurationChange = () => {
      if (audio.duration && !isNaN(audio.duration)) {
        setDuration(audio.duration);
      }
    };

    audio.addEventListener('durationchange', handleDurationChange);
    
    return () => {
      audio.removeEventListener('durationchange', handleDurationChange);
    };
  }, [audioUrl]); // Add audioUrl as dependency to reload when URL changes

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handleLoadedMetadata = () => {
      if (audio.duration && !isNaN(audio.duration)) {
        setDuration(audio.duration);
      }
    };

    const handleTimeUpdate = () => {
      if (audio.currentTime && !isNaN(audio.currentTime)) {
        setCurrentTime(audio.currentTime);
      }
    };

    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
    };

    audio.addEventListener('loadedmetadata', handleLoadedMetadata);
    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('ended', handleEnded);

    // Load duration immediately if already loaded
    if (audio.readyState >= 2 && audio.duration && !isNaN(audio.duration)) {
      setDuration(audio.duration);
    }

    return () => {
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('ended', handleEnded);
    };
  }, []);

  const togglePlay = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
      } else {
        audioRef.current.play().catch(error => {
          console.error('Error playing audio:', error);
        });
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = Number(e.target.value);
    if (audioRef.current && !isNaN(time)) {
      audioRef.current.currentTime = time;
      setCurrentTime(time);
    }
  };

  const formatTime = (timeInSeconds: number) => {
    if (!timeInSeconds || isNaN(timeInSeconds)) return '0:00';
    
    const minutes = Math.floor(timeInSeconds / 60);
    const seconds = Math.floor(timeInSeconds % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  const remainingTime = duration && currentTime ? duration - currentTime : 0;

  return (
    <div className="bg-white rounded-lg shadow-sm p-4 mb-6">
      <audio 
        ref={audioRef} 
        src={audioUrl} 
        preload="metadata"
        // Add playsInline for better mobile handling
        playsInline 
      />
      
      <div className="flex items-center gap-4">
        <button
          onClick={togglePlay}
          className="w-12 h-12 flex items-center justify-center rounded-full bg-sport-500 text-white hover:bg-sport-600 transition-colors"
          aria-label={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? (
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
            </svg>
          ) : (
            <svg className="w-5 h-5 ml-1" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>

        <div className="flex-1">
          <div className="text-sm font-medium text-gray-900 mb-1">
            {title}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 min-w-[40px]">
              {formatTime(currentTime)}
            </span>
            <input
              type="range"
              min="0"
              max={duration || 0}
              value={currentTime}
              onChange={handleSeek}
              className="flex-1 h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-sport-500"
            />
            <span className="text-xs text-gray-500 min-w-[40px] text-right">
              {formatTime(remainingTime)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
} 