import React, { useState, useEffect, useRef } from 'react';

interface TagsInputProps {
  initialTags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

const TagsInput: React.FC<TagsInputProps> = ({ initialTags, onChange, placeholder = "Add tags..." }) => {
  const [tags, setTags] = useState<string[]>(initialTags || []);
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // Update local state when initialTags changes
  useEffect(() => {
    if (initialTags && Array.isArray(initialTags)) {
      // Prevent infinite loop if onChange updates initialTags directly
      // Only update if initialTags is truly different from the current tags.
      if (JSON.stringify(tags) !== JSON.stringify(initialTags)) {
        setTags(initialTags);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps 
  }, [initialTags]); // Depend ONLY on initialTags to break update cycles

  useEffect(() => {
    // Update parent component when tags change
    // Ensure onChange is stable or properly memoized by parent to avoid unnecessary runs
    onChange(tags);
  }, [tags, onChange]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(e.target.value);
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag();
    } else if (e.key === 'Backspace' && inputValue === '' && tags.length > 0) {
      removeTag(tags.length - 1);
      // Optionally, if you want to edit the last tag:
      // setInputValue(tags[tags.length - 1] + ' '); // Add space for easier editing
      // removeTag(tags.length - 1);
    }
  };

  const addTag = () => {
    const trimmedInput = inputValue.trim();
    if (trimmedInput === '') return;

    if (!tags.includes(trimmedInput)) {
      const newTags = [...tags, trimmedInput];
      setTags(newTags);
    }
    setInputValue('');
  };

  const removeTag = (indexToRemove: number) => {
    setTags(tags.filter((_, index) => index !== indexToRemove));
  };

  const handleContainerClick = () => {
    inputRef.current?.focus();
  };

  return (
    <div 
      className="w-full p-2 border border-gray-300 rounded-md shadow-sm flex flex-wrap gap-2 items-center cursor-text focus-within:border-primary focus-within:ring-1 focus-within:ring-primary"
      // onClick={handleContainerClick} // Remove outer click for focusing if button causes issues, or manage focus carefully
    >
      {tags.map((tag, index) => (
        <div 
          key={index} 
          className="inline-flex items-center px-2.5 py-1 rounded-full text-sm bg-primary-50 text-primary-700 border border-primary-200"
        >
          <span className="mr-1.5">{tag}</span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation(); // Prevent container click event
              removeTag(index);
            }}
            className="h-4 w-4 rounded-full flex items-center justify-center hover:bg-primary-200 focus:outline-none"
            aria-label={`Remove ${tag}`}
          >
            <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      ))}
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={handleInputChange}
        onKeyDown={handleInputKeyDown}
        placeholder={tags.length === 0 ? placeholder : ""} // Show placeholder only if no tags
        className="flex-grow p-1 outline-none text-sm min-w-[100px]" // Ensure input has some min width
        style={{ background: 'transparent', border: 'none' }} // Make input "invisible"
        onBlur={(e) => {
          // Add tag on blur only if the focus is not moving to the "Add" button
          // This check helps prevent double-adding if the button also calls addTag
          if (!e.relatedTarget || (e.relatedTarget as HTMLElement)?.tagName !== 'BUTTON') {
            addTag();
          }
        }}
      />
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation(); // Prevent any container click handlers
          addTag();
          inputRef.current?.focus(); // Keep focus on input after adding
        }}
        className="ml-2 px-3 py-1.5 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
      >
        Add
      </button>
    </div>
  );
};

export default TagsInput; 