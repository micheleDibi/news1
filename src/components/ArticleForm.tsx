import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useForm, FieldError, Merge, FieldErrorsImpl } from 'react-hook-form';
import { supabase } from '../lib/supabase';
import { categories } from '../lib/categories';
import { v4 as uuidv4 } from 'uuid';
import { slugify, getArticleUrl } from '../lib/utils';
import { useEditor, EditorContent, Editor, BubbleMenu } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import Link from '@tiptap/extension-link';
import Placeholder from '@tiptap/extension-placeholder';
// Import list extensions
import BulletList from '@tiptap/extension-bullet-list';
import OrderedList from '@tiptap/extension-ordered-list';
import ListItem from '@tiptap/extension-list-item';

// Import SecondaryCategory type
import type { SecondaryCategory } from '../lib/supabase';
import { promise } from 'astro:schema';
//import { url } from 'inspector/promises';

interface ArticleFormProps {
  article?: any;
}

// Facebook posting function
async function sendFacebookPost(articleUrl: string, title: string, tags: string[] = []) {
  const PAGE_ID = import.meta.env.PUBLIC_FACEBOOK_PAGE_ID;
  const ACCESS_TOKEN = import.meta.env.PUBLIC_FACEBOOK_ACCESS_TOKEN;
  const url = `https://graph.facebook.com/v22.0/${PAGE_ID}/feed`;
  const PAGE_NAME = "EduNews24.it";

  // Format tags into hashtags
  const hashtags = tags.map(tag => `#${tag.replace(/\s+/g, '')}`).join(' '); // Remove spaces within tags

  // Simple message without the URL, adding hashtags if available
  let message = `${title}`;
  if (hashtags) {
    message += `\n\n${hashtags}`;
  }

  const payload = {
    message: message,
    // Use the link parameter for Facebook's link preview functionality
    link: articleUrl,
    message_tags: JSON.stringify([
      {id: PAGE_ID, name: PAGE_NAME}
    ]),
    access_token: ACCESS_TOKEN
  };

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams(payload),
    });
    
    const data = await response.json();
    console.log('Facebook post response:', data);
    console.log('Sent message:', message);
    console.log('Sent link URL:', articleUrl);
    return data;
  } catch (error) {
    console.error('Error posting to Facebook:', error);
    throw error;
  }
}

// Helper function to convert markdown to HTML
function markdownToHtml(markdown: string): string {
  if (!markdown) return '';
  
  console.log('Converting markdown to HTML:', markdown.substring(0, 100) + '...');
  
  let html = '';
  const lines = markdown.split('\n');
  let inUl = false;
  let inOl = false;

  lines.forEach((line, index) => {
    const trimmedLine = line.trim();
    
    // Handle List Items
    const ulMatch = trimmedLine.match(/^[-*]\s+(.*)/);
    const olMatch = trimmedLine.match(/^(\d+)\.\s+(.*)/);

    if (ulMatch) {
      const itemContent = ulMatch[1];
      if (inOl) { // Close previous OL if starting UL
        html += '</ol>\n';
        inOl = false;
      }
      if (!inUl) { // Start new UL
        html += '<ul>\n';
        inUl = true;
      }
      // Process inline markdown within the list item
      html += `  <li>${processInlineMarkdown(itemContent)}</li>\n`;
    } else if (olMatch) {
      const itemContent = olMatch[2];
      if (inUl) { // Close previous UL if starting OL
        html += '</ul>\n';
        inUl = false;
      }
      if (!inOl) { // Start new OL
        html += '<ol>\n';
        inOl = true;
      }
      // Process inline markdown within the list item
      html += `  <li>${processInlineMarkdown(itemContent)}</li>\n`;
    } else {
      // Close any open lists if the current line is not a list item
      if (inUl) {
        html += '</ul>\n';
        inUl = false;
      }
      if (inOl) {
        html += '</ol>\n';
        inOl = false;
      }

      // Process other block elements (Headers, Images, Paragraphs)
      if (trimmedLine) {
        // Headers
        if (trimmedLine.startsWith('# ')) {
          html += `<h2>${trimmedLine.substring(2)}</h2>\n`;
        } else if (trimmedLine.startsWith('## ')) {
          html += `<h3>${trimmedLine.substring(3)}</h3>\n`;
        } else if (trimmedLine.startsWith('### ')) {
          html += `<h4>${trimmedLine.substring(4)}</h4>\n`;
        } 
        // Images with Captions
        else {
          const imageRegex = /^!\[(.*?)\]\((.*?)\)(?:\s*\|\s*(.*?))?$/;
          const imageMatch = trimmedLine.match(imageRegex);
          if (imageMatch) {
            const [, alt, src, caption] = imageMatch;
            let imageHtml;
            if (caption) {
              imageHtml = `<figure><img src="${src}" alt="${alt || 'Article image'}"><figcaption>${caption.trim()}</figcaption></figure>`;
            } else {
              imageHtml = `<figure><img src="${src}" alt="${alt || 'Article image'}"></figure>`;
            }
            console.log(`Converted image markdown to HTML: `, { original: trimmedLine, html: imageHtml });
            html += imageHtml + '\n'; // Ensure newline after figure
          } 
          // Paragraphs (process inline markdown)
          else {
             // Only wrap non-empty lines that aren't already handled as blocks
             if (!trimmedLine.startsWith('<h') && !trimmedLine.startsWith('<figure')) {
               html += `<p>${processInlineMarkdown(trimmedLine)}</p>\n`;
             }
          }
        }
      } else if (index > 0 && lines[index - 1] && lines[index - 1].trim()) {
         // Add separation between block elements if the previous line was not empty
         // html += '\n'; // Maybe add this back if spacing is off
      }
    }
  });

  // Close any lists that might be open at the end of the document
  if (inUl) {
    html += '</ul>\n';
  }
  if (inOl) {
    html += '</ol>\n';
  }

  // Cleanup potential multiple empty lines or leading/trailing whitespace
  html = html.trim().replace(/\n{3,}/g, '\n\n');

  console.log('Converted HTML result:', html.substring(0, 100) + '...');
  return html;
}

// Helper function to process inline markdown (bold, italic, links)
function processInlineMarkdown(text: string): string {
  let processedText = text;

  // Links first to avoid conflicts
  processedText = processedText.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, linkText, url) => {
    // Basic check: if the match is inside existing HTML tags, skip.
    if (match.includes('<') || match.includes('>')) return match;
    const linkHtml = `<a href="${url}" target="_blank" rel="noopener noreferrer">${linkText}</a>`;
    console.log(`Converted link markdown to HTML: `, { original: match, html: linkHtml });
    return linkHtml;
  });

  // Bold
  processedText = processedText.replace(/\*\*(.*?)\*\*/g, (match, content) => {
    // Avoid converting if inside an HTML tag attribute
     // A more robust check might be needed depending on edge cases
     // Check if the match seems to be inside an attribute like href="...**...**..."
     const precedingText = processedText.substring(0, processedText.indexOf(match));
     const followingText = processedText.substring(processedText.indexOf(match) + match.length);
     if (precedingText.includes('="') && followingText.includes('"')) { // Basic check
        // More complex check could involve ensuring the ** is between quotes
        const lastOpenQuote = precedingText.lastIndexOf('"');
        const lastCloseQuote = precedingText.lastIndexOf('"'); 
        // This check is still basic and might fail in edge cases
        if (lastOpenQuote > lastCloseQuote) { 
             return match; // Likely inside an attribute
        }
     }
     return `<strong>${content}</strong>`;
  });

  // Italic (using word boundaries to avoid underscores in words/URLs)
  processedText = processedText.replace(/(?<![\w])_([^_]+)_(?![\w])/g, '<em>$1</em>'); // Use \w for word boundary

  return processedText;
}

// Helper function to convert html to markdown format compatible with the site rendering
function htmlToMarkdown(html: string): string {
  if (!html) return '';
  
  console.log('Converting HTML to markdown:', html.substring(0, 100) + '...');
  
  // Create a temporary div to parse the HTML
  const tempDiv = document.createElement('div');
  tempDiv.innerHTML = html;

  // Process all links first by directly converting them to markdown text nodes
  const links = Array.from(tempDiv.querySelectorAll('a'));
  console.log('Found links to convert upfront:', links.length);
  links.forEach(link => {
    const href = link.getAttribute('href') || '';
    const text = link.textContent || href; // Use textContent for the link text
    
    // Create the markdown text as a simple text node
    const markdownLinkTextNode = document.createTextNode(`[${text}](${href})`);
    link.parentNode?.replaceChild(markdownLinkTextNode, link);
    
    console.log(`Converted link to markdown text node: [${text}](${href})`);
  });
  
  // Process UL lists
  const ulElements = Array.from(tempDiv.querySelectorAll('ul'));
  ulElements.forEach(ul => {
    let markdownList = '';
    Array.from(ul.querySelectorAll('li')).forEach(li => {
       // Process inline elements within the list item before getting text
       processInlineHtmlToMarkdown(li);
       markdownList += `* ${li.textContent?.trim() || ''}\n`; // Add Markdown bullet
    });
    // Replace the UL element with a text node containing the Markdown list
    const textNode = document.createTextNode(markdownList.trim() + '\n\n'); // Add extra newline after list
    ul.parentNode?.replaceChild(textNode, ul);
  });

  // Process OL lists
  const olElements = Array.from(tempDiv.querySelectorAll('ol'));
  olElements.forEach(ol => {
    let markdownList = '';
    Array.from(ol.querySelectorAll('li')).forEach((li, index) => {
      // Process inline elements within the list item before getting text
      processInlineHtmlToMarkdown(li);
      markdownList += `${index + 1}. ${li.textContent?.trim() || ''}\n`; // Add Markdown number
    });
    // Replace the OL element with a text node containing the Markdown list
    const textNode = document.createTextNode(markdownList.trim() + '\n\n'); // Add extra newline after list
    ol.parentNode?.replaceChild(textNode, ol);
  });
  
  // Process figures with images - direct conversion to markdown
  const figures = Array.from(tempDiv.querySelectorAll('figure'));
  console.log('Found figures:', figures.length);
  
  figures.forEach((figure, index) => {
    const img = figure.querySelector('img');
    const figcaption = figure.querySelector('figcaption');
    
    if (img) {
      const src = img.getAttribute('src') || '';
      const alt = img.getAttribute('alt') || 'image';
      const caption = figcaption?.textContent || '';
      
      console.log(`Figure ${index + 1}:`, { src, alt, caption });
      
      // Direct markdown image - no processing
      const markdownImage = caption.trim() 
        ? `![${alt}](${src})|${caption.trim()}`
        : `![${alt}](${src})`;
      
      // Replace with plain text node
      const textNode = document.createTextNode(markdownImage);
      figure.parentNode?.replaceChild(textNode, figure);
    }
  });
  
  // Process standalone images directly to markdown
  const standaloneImages = Array.from(tempDiv.querySelectorAll('img:not(figure img)'));
  console.log('Found standalone images:', standaloneImages.length);
  
  standaloneImages.forEach((img, index) => {
    const src = img.getAttribute('src') || '';
    const alt = img.getAttribute('alt') || 'image';
    
    console.log(`Standalone image ${index + 1}:`, { src, alt });
    
    // Direct markdown image
    const markdownImage = `![${alt}](${src})`;
    
    // Replace with plain text
    const textNode = document.createTextNode(markdownImage);
    img.parentNode?.replaceChild(textNode, img);
  });
  
  // Convert headings
  const h2Elements = Array.from(tempDiv.querySelectorAll('h2'));
  const h3Elements = Array.from(tempDiv.querySelectorAll('h3'));
  const h4Elements = Array.from(tempDiv.querySelectorAll('h4'));
  
  h2Elements.forEach(h2 => {
    processInlineHtmlToMarkdown(h2); // Process inline within headers
    const p = document.createElement('p');
    p.textContent = `# ${h2.textContent}`; // Keep as P temporarily for easier text extraction later
    h2.parentNode?.replaceChild(p, h2);
  });
  
  h3Elements.forEach(h3 => {
    processInlineHtmlToMarkdown(h3); // Process inline within headers
    const p = document.createElement('p');
    p.textContent = `## ${h3.textContent}`; // Keep as P temporarily
    h3.parentNode?.replaceChild(p, h3);
  });
  
  h4Elements.forEach(h4 => {
    processInlineHtmlToMarkdown(h4); // Process inline within headers
    const p = document.createElement('p');
    p.textContent = `### ${h4.textContent}`; // Keep as P temporarily
    h4.parentNode?.replaceChild(p, h4);
  });
  
  // Convert formatting within paragraphs
  const paragraphs = Array.from(tempDiv.querySelectorAll('p'));
  paragraphs.forEach(p => {
    // Skip any paragraphs that already contain markdown links or images
    // Also skip paragraphs that were previously lists or headers
    if (
      p.textContent?.includes('](') || 
      p.textContent?.includes('![') ||
      p.textContent?.startsWith('* ') || // Check for converted list markers
      p.textContent?.match(/^\d+\.\s/) || // Check for converted list markers
      p.textContent?.startsWith('# ') || // Check for converted header markers
      p.textContent?.startsWith('## ') ||
      p.textContent?.startsWith('### ')
    ) {
      return;
    }
    
    // Process inline bold/italic for remaining paragraphs
    processInlineHtmlToMarkdown(p);
  });
  
  // Get the final text content, joining elements correctly
  let markdownResult = '';
  tempDiv.childNodes.forEach(node => {
    if (node.nodeType === Node.TEXT_NODE) {
      markdownResult += node.textContent?.trim();
    } else if (node.nodeType === Node.ELEMENT_NODE && node.nodeName === 'P') {
      // Process paragraph content for bold/italic
      const p = node as HTMLParagraphElement;
      markdownResult += p.textContent?.trim();
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      // Handle other potential elements if necessary, or just get their text
      markdownResult += node.textContent?.trim();
    }
    markdownResult += '\n\n'; // Add double newline separation
  });

  // Clean up extra newlines
  const result = markdownResult.trim().replace(/(\n\n)+/g, '\n\n');

  console.log('Final markdown result:', result.substring(0, 100) + '...');
  
  return result;
}

// Helper function to convert inline HTML (strong, em) within an element to Markdown
function processInlineHtmlToMarkdown(element: HTMLElement) {
  // Convert strong tags to **bold**
  const strongs = Array.from(element.querySelectorAll('strong'));
  strongs.forEach(strong => {
    // Ensure not inside a link already converted to text
    if (!strong.closest('a')) {
      const text = strong.textContent || '';
      const markdown = document.createTextNode(`**${text}**`);
      strong.parentNode?.replaceChild(markdown, strong);
    }
  });

  // Convert em tags to _italic_
  const ems = Array.from(element.querySelectorAll('em'));
  ems.forEach(em => {
    if (!em.closest('a')) {
      const text = em.textContent || '';
      // Use word boundary check similar to markdownToHtml
      const markdown = document.createTextNode(`_${text}_`); 
      em.parentNode?.replaceChild(markdown, em);
    }
  });
}

// RichTextEditor component
const RichTextEditor = ({ 
  content, 
  onChange,
  placeholder = 'Inizia a scrivere il tuo articolo...',
  articleTitle,
}: { 
  content: string; 
  onChange: (html: string) => void;
  placeholder?: string;
  articleTitle: string;
}) => {
  const [imageUploading, setImageUploading] = useState(false);
  const [editorInitialized, setEditorInitialized] = useState(false);

  // Function to handle image uploads
  const addImage = useCallback(async (file: File, editor: Editor) => {
    try {
      // Show loading indicator
      setImageUploading(true);
      
      console.log('Preparing upload for file:', file.name);
      
      // Upload to S3
      const formData = new FormData();
      formData.append('file', file);
      const titleForUpload = articleTitle || file.name || 'immagine';
      const articleSlug = slugify(titleForUpload);
      const ext = file.name.split('.').pop() || 'jpg';
      const filename = `${articleSlug}-contenuto.${ext}`;
      formData.append('filename', filename);
      formData.append('title', titleForUpload);
      
      console.log('Uploading to S3 with filename:', filename);

      const uploadResponse = await fetch('/api/upload', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: formData
      });

      console.log('Upload response status:', uploadResponse.status);
      
      if (!uploadResponse.ok) {
        const errorText = await uploadResponse.text();
        console.error('Upload error response:', errorText);
        throw new Error(`Failed to upload image file: ${errorText}`);
      }

      const responseData = await uploadResponse.json();
      console.log('Upload response data:', responseData);
      
      const { url } = responseData;
      
      if (!url) {
        throw new Error('No URL returned from image upload');
      }
      
      console.log('Image uploaded successfully to:', url);
      
      // Prompt for caption
      const caption = window.prompt('Add a caption for this image (optional):') || '';
      const trimmedCaption = caption.trim();
      
      // Create a standalone paragraph for the image to ensure proper isolation
      editor.chain().focus().insertContent({
        type: 'paragraph',
        content: []
      }).run();
      
      // Insert the image with caption in a simpler format
      if (trimmedCaption) {
        editor.chain().focus().insertContent(`
          <figure>
            <img src="${url}" alt="Article image">
            <figcaption>${trimmedCaption}</figcaption>
          </figure>
        `).run();
        
        // Log the inserted image HTML for debugging
        console.log('Inserted image with caption HTML:', `<figure><img src="${url}" alt="Article image"><figcaption>${trimmedCaption}</figcaption></figure>`);
      } else {
        editor.chain().focus().insertContent(`
          <figure>
            <img src="${url}" alt="Article image">
          </figure>
        `).run();
        
        // Log the inserted image HTML for debugging
        console.log('Inserted image HTML:', `<figure><img src="${url}" alt="Article image"></figure>`);
      }
      
      // Add another paragraph after the image
      editor.chain().focus().insertContent({
        type: 'paragraph',
        content: []
      }).run();
      
      return url;
    } catch (error) {
      console.error('Error in addImage function:', error);
      alert('Error uploading image: ' + (error as Error).message);
      return null;
    } finally {
      setImageUploading(false);
    }
  }, []);

  const editor = useEditor({
    extensions: [
      StarterKit,
      Image.configure({
        inline: false,
        allowBase64: true,
      }),
      Link.configure({
        openOnClick: false,
      }),
      Placeholder.configure({
        placeholder,
      }),
      // Add list extensions
      BulletList,
      OrderedList,
      ListItem,
    ],
    content: content,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML());
    },
    onCreate: ({ editor }) => {
      setEditorInitialized(true);
      console.log('Editor initialized with content');
    },
    editorProps: {
      attributes: {
        class: 'prose prose-sm sm:prose lg:prose-lg xl:prose-xl focus:outline-none',
      },
    },
    autofocus: false,
    immediatelyRender: false,
  });

  // Make sure HTML content is set correctly when the editor is ready
  useEffect(() => {
    if (!editor || !editorInitialized) return;
    
    // Only update if editor content is not the same as the provided content
    const currentContent = editor.getHTML();
    if (currentContent !== content && content) {
      console.log('Setting editor content with HTML:', content.substring(0, 100) + '...');
      
      // Check if content includes any image tags
      if (content.includes('<figure>') || content.includes('<img')) {
        console.log('Content contains images, ensuring proper rendering');
      }
      
      // Set content with specific options to ensure proper rendering
      editor.commands.setContent(content, false, { 
        preserveWhitespace: 'full'
      });
      
      // Force a re-render after a brief delay to ensure images are displayed
      setTimeout(() => {
        editor.commands.focus('end');
        console.log('Editor focused to ensure rendering is complete');
      }, 100);
    }
  }, [editor, content, editorInitialized]);

  // Function to handle file selection for image upload
  const handleImageUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (!editor) return;
    
    const file = event.target.files?.[0];
    if (!file) return;

    // Log for debugging
    console.log('Starting image upload for file:', file.name, 'size:', file.size, 'type:', file.type);
    
    addImage(file, editor)
      .then(url => {
        if (url) {
          console.log('Image upload completed successfully:', url);
        } else {
          console.error('Image upload failed - no URL returned');
        }
      })
      .catch(error => {
        console.error('Error in image upload process:', error);
      });
    
    // Reset the input
    event.target.value = '';
  };

  if (!editor) {
    return <div className="loading-editor p-4">Loading editor...</div>;
  }

  return (
    <div className="rich-text-editor">
      {editor && (
        <BubbleMenu editor={editor} tippyOptions={{ duration: 100 }}>
          <div className="flex bg-white shadow-lg rounded-md border border-gray-200 p-1">
            <button
              onClick={() => editor.chain().focus().toggleBold().run()}
              className={`p-1 sm:p-2 rounded hover:bg-gray-100 ${editor.isActive('bold') ? 'bg-gray-200' : ''}`}
              title="Bold"
            >
              <svg className="h-4 w-4 sm:h-5 sm:w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 12h8a4 4 0 100-8H6v8zm0 0h8a4 4 0 110 8H6v-8z" />
              </svg>
            </button>
            <button
              onClick={() => editor.chain().focus().toggleItalic().run()}
              className={`p-1 sm:p-2 rounded hover:bg-gray-100 ${editor.isActive('italic') ? 'bg-gray-200' : ''}`}
              title="Italic"
            >
              <svg className="h-4 w-4 sm:h-5 sm:w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {/* Updated Italic Icon */}
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 4v3h2.21l-3.42 8H6v3h8v-3h-2.21l3.42-8H18V4z" />
              </svg>
            </button>
            <button
              onClick={() => editor.chain().focus().toggleBulletList().run()}
              className={`p-1 sm:p-2 rounded hover:bg-gray-100 ${editor.isActive('bulletList') ? 'bg-gray-200' : ''}`}
              title="Bulleted List"
            >
              <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {/* Old Icon: <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16"/> */}
                {/* New Bullet List Icon */}
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
              </svg>
            </button>
            <button
              onClick={() => editor.chain().focus().toggleOrderedList().run()}
              className={`p-1 sm:p-2 rounded hover:bg-gray-100 ${editor.isActive('orderedList') ? 'bg-gray-200' : ''}`}
              title="Numbered List"
            >
              <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {/* Updated Numbered List Icon */}
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 6h13M7 12h13M7 18h13M4.5 6H3M4.5 12H3m1.5 6H3M3 6V5m.75 7.5L3 12m.75 6.5L3 18M4.5 6h0m-1.5 6h0m1.5 6h0" transform="matrix(1,0,0,1,0,0) translate(0,0) scale(1.1)"/>
                <line x1="3" y1="7" x2="3" y2="5"/>
                <line x1="3" y1="13" x2="3" y2="11"/>
                <line x1="3" y1="19" x2="3" y2="17"/>
                <path d="M 3 5.5 L 4.5 5.5" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
                <path d="M 3 11.5 L 4.5 11.5" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
                <path d="M 3 17.5 L 4.5 17.5" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
                <text x="3" y="7" font-family="sans-serif" font-size="3" fill="currentColor" text-anchor="middle" dominant-baseline="middle">1</text>
                <text x="3" y="13" font-family="sans-serif" font-size="3" fill="currentColor" text-anchor="middle" dominant-baseline="middle">2</text>
                <text x="3" y="19" font-family="sans-serif" font-size="3" fill="currentColor" text-anchor="middle" dominant-baseline="middle">3</text>
              </svg>
            </button>
            <button
              onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
              className={`p-1 sm:p-2 rounded hover:bg-gray-100 ${editor.isActive('heading', { level: 2 }) ? 'bg-gray-200' : ''}`}
              title="Heading"
            >
              {/* Simplified H1 Icon for H2 toggle */}
              <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-size="12" font-weight="bold">H1</text>
              </svg>
            </button>
            <button
              onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
              className={`p-1 sm:p-2 rounded hover:bg-gray-100 ${editor.isActive('heading', { level: 3 }) ? 'bg-gray-200' : ''}`}
              title="Subheading"
            >
              {/* Simplified H2 Icon for H3 toggle */}
              <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-size="12" font-weight="bold">H2</text>
              </svg>
            </button>
            <label
              className={`p-1 sm:p-2 rounded hover:bg-gray-100 focus:outline-none cursor-pointer ${imageUploading ? 'bg-blue-100 text-blue-800' : ''}`}
              title={imageUploading ? "Uploading image..." : "Insert Image"}
            >
              {imageUploading ? (
                <svg className="h-4 w-4 sm:h-5 sm:w-5 text-blue-600 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              ) : (
                <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
              )}
              <input
                type="file"
                className="sr-only"
                accept="image/*"
                onChange={handleImageUpload}
                disabled={imageUploading}
              />
            </label>
            <button
              onClick={() => {
                const url = window.prompt('Enter URL');
                if (url) {
                  // Validate URL format
                  let validatedUrl = url;
                  if (!/^https?:\/\//i.test(url)) {
                    validatedUrl = 'https://' + url;
                  }
                  
                  // Get the link text
                  const text = editor.state.selection.empty 
                    ? window.prompt('Enter link text', 'Link') 
                    : null;
                  
                  if (text) {
                    // If user provided text, replace selection with the link
                    editor.chain().focus()
                      .insertContent(`<a href="${validatedUrl}" target="_blank">${text}</a>`)
                      .run();
                  } else {
                    // Otherwise just apply to current selection
                    editor.chain().focus().setLink({ href: validatedUrl, target: '_blank' }).run();
                  }
                }
              }}
              className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none ${editor.isActive('link') ? 'bg-gray-200' : ''}`}
              title="Insert Link"
            >
              <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </button>
          </div>
        </BubbleMenu>
      )}
      
      <div className="sticky top-0 z-10 bg-white border-b border-gray-200 p-2 overflow-x-auto">
        <div className="flex items-center space-x-1 sm:space-x-2 min-w-max">
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleBold().run()}
            className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none ${editor.isActive('bold') ? 'bg-gray-200' : ''}`}
            title="Bold"
          >
            <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 12h8a4 4 0 100-8H6v8zm0 0h8a4 4 0 110 8H6v-8z" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleItalic().run()}
            className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none ${editor.isActive('italic') ? 'bg-gray-200' : ''}`}
            title="Italic"
          >
            <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {/* Updated Italic Icon */}
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 4v3h2.21l-3.42 8H6v3h8v-3h-2.21l3.42-8H18V4z" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleBulletList().run()}
            className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none ${editor.isActive('bulletList') ? 'bg-gray-200' : ''}`}
            title="Bulleted List"
          >
            <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {/* Old Icon: <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16"/> */}
              {/* New Bullet List Icon */}
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
            className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none ${editor.isActive('orderedList') ? 'bg-gray-200' : ''}`}
            title="Numbered List"
          >
            <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {/* Updated Numbered List Icon */}
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 6h13M7 12h13M7 18h13M4.5 6H3M4.5 12H3m1.5 6H3M3 6V5m.75 7.5L3 12m.75 6.5L3 18M4.5 6h0m-1.5 6h0m1.5 6h0" transform="matrix(1,0,0,1,0,0) translate(0,0) scale(1.1)"/>
              <line x1="3" y1="7" x2="3" y2="5"/>
              <line x1="3" y1="13" x2="3" y2="11"/>
              <line x1="3" y1="19" x2="3" y2="17"/>
              <path d="M 3 5.5 L 4.5 5.5" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
              <path d="M 3 11.5 L 4.5 11.5" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
              <path d="M 3 17.5 L 4.5 17.5" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>
              <text x="3" y="7" font-family="sans-serif" font-size="3" fill="currentColor" text-anchor="middle" dominant-baseline="middle">1</text>
              <text x="3" y="13" font-family="sans-serif" font-size="3" fill="currentColor" text-anchor="middle" dominant-baseline="middle">2</text>
              <text x="3" y="19" font-family="sans-serif" font-size="3" fill="currentColor" text-anchor="middle" dominant-baseline="middle">3</text>
            </svg>
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none ${editor.isActive('heading', { level: 2 }) ? 'bg-gray-200' : ''}`}
            title="Heading"
          >
            {/* Simplified H1 Icon for H2 toggle */}
            <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-size="12" font-weight="bold">H1</text>
            </svg>
          </button>
          <button
            type="button"
            onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
            className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none ${editor.isActive('heading', { level: 3 }) ? 'bg-gray-200' : ''}`}
            title="Subheading"
          >
            {/* Simplified H2 Icon for H3 toggle */}
            <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-size="12" font-weight="bold">H2</text>
            </svg>
          </button>
          <label
            className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none cursor-pointer ${imageUploading ? 'bg-blue-100 text-blue-800' : ''}`}
            title={imageUploading ? "Uploading image..." : "Insert Image"}
          >
            {imageUploading ? (
              <svg className="h-4 w-4 sm:h-5 sm:w-5 text-blue-600 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            ) : (
              <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
            )}
            <input
              type="file"
              className="sr-only"
              accept="image/*"
              onChange={handleImageUpload}
              disabled={imageUploading}
            />
          </label>
          <button
            type="button"
            onClick={() => {
              const url = window.prompt('Enter URL');
              if (url) {
                // Validate URL format
                let validatedUrl = url;
                if (!/^https?:\/\//i.test(url)) {
                  validatedUrl = 'https://' + url;
                }
                
                // Get the link text
                const text = editor.state.selection.empty 
                  ? window.prompt('Enter link text', 'Link') 
                  : null;
                
                if (text) {
                  // If user provided text, replace selection with the link
                  editor.chain().focus()
                    .insertContent(`<a href="${validatedUrl}" target="_blank">${text}</a>`)
                    .run();
                } else {
                  // Otherwise just apply to current selection
                  editor.chain().focus().setLink({ href: validatedUrl, target: '_blank' }).run();
                }
              }
            }}
            className={`p-1 sm:p-2 rounded-md hover:bg-gray-100 focus:outline-none ${editor.isActive('link') ? 'bg-gray-200' : ''}`}
            title="Insert Link"
          >
            <svg className="h-4 w-4 sm:h-5 sm:w-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
          </button>
        </div>
      </div>
      
      <EditorContent editor={editor} className="prose max-w-none p-3 sm:p-4 min-h-[300px] sm:min-h-[400px] border-gray-100 focus:outline-none" />
    </div>
  );
};

export default function ArticleForm({ article }: ArticleFormProps) {
  const [loading, setLoading] = useState(false);
  const [previewMode, setPreviewMode] = useState(false);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [uploadMethod, setUploadMethod] = useState<'file' | 'url'>('url');
  const [thumbnailUploadMethod, setThumbnailUploadMethod] = useState<'file' | 'url'>('url');
  const [thumbnailUploading, setThumbnailUploading] = useState(false);
  const [currentUser, setCurrentUser] = useState<string>('');
  const [fbPostStatus, setFbPostStatus] = useState<{message: string; isError: boolean} | null>(null);
  const [savedArticle, setSavedArticle] = useState<any>(article || null);
  const [fbPosting, setFbPosting] = useState(false);
  const [urlUploading, setUrlUploading] = useState(false);
  const [showUrlPreview, setShowUrlPreview] = useState(false);
  const [shareUrl, setShareUrl] = useState('');
  const [userPermissions, setUserPermissions] = useState<Record<string, any>>({});
  const [userProfile, setUserProfile] = useState<any>(null);
  const [creatorOptions, setCreatorOptions] = useState<{ value: string; label: string }[]>([]);
  const [selectedCreator, setSelectedCreator] = useState<string>('');
  const [editorContent, setEditorContent] = useState('');
  const [allowedCategories, setAllowedCategories] = useState<any[]>([]);
  const [showAiModal, setShowAiModal] = useState(false);
  const [aiParams, setAiParams] = useState({
    prompt: '',
    paragraphs: 3,
    wordsPerParagraph: 100,
    tone: 'Neutrale',
    persona: 'Copywriter',
    sourceUrl: '' // Optional source URL or web search term
  });
  const [aiLoading, setAiLoading] = useState(false);
  const [aiTagsLoading, setAiTagsLoading] = useState(false);
  const [aiSummaryLoading, setAiSummaryLoading] = useState(false);

  const [sidebarVideoUrl, setSidebarVideoUrl] = useState<string>(article?.video_url || '');
  const [isUploadingVideo, setIsUploadingVideo] = useState(false);
  const [videoDuration, setVideoDuration]= useState <number|null>(article?.video_duration??null);

  const [showContactConfirm, setShowContactConfirm] = useState(false);


  // State for secondary categories - RE-ADDING THESE
  const [availableSecondaryCategories, setAvailableSecondaryCategories] = useState<SecondaryCategory[]>([]);
  const [selectedSecondaryCategories, setSelectedSecondaryCategories] = useState<string[]>([]);
  

  // Ref for the title textarea
  const titleTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    getValues,
    formState: { errors },
  } = useForm({
    defaultValues: article 
    ? {
      ...article, 
      video_duration: article.video_duration ?? null,
      thumbnail_url: article.thumbnail_url ?? '',
      show_contact_form: article?.show_contact_form ?? false,
    }
    :{
      title: '',
      excerpt: '',
      summary: '',
      title_summary: '',
      content: '',
      category: '',
      image_url: `https://picsum.photos/seed/${Math.random()}/800/600`,
      video_url: '',
      video_duration: null,
      thumbnail_url: '',
      published_at: '',
      isdraft: true,
      tags: [],
      secondary_category_slugs: [], // Default for new articles
      show_contact_form: false,

    }
  });

  const showContactForm = watch('show_contact_form');

  useEffect(() => {
    if (article) {
      const initialVideoUrl = article.video_url || '';
      setSidebarVideoUrl(initialVideoUrl);
      setValue('video_url', initialVideoUrl);
    }
  }, [article, setValue]);

  // Sync video URL state with form field
  useEffect(() => {
    console.log('🔄 Syncing video URL state with form field...');
    console.log('🔄 sidebarVideoUrl state:', sidebarVideoUrl);
    setValue('video_url', sidebarVideoUrl);
    
    // Verify the sync worked
    const currentFormValue = getValues('video_url');
    console.log('🔄 Form video_url after sync:', currentFormValue);
  }, [sidebarVideoUrl, setValue, getValues]);

  
  // Initialize the editor content from the article
  useEffect(() => {
    if (article?.content) {
      try {
        console.log('Article content:', article.content.substring(0, 100));
        const html = markdownToHtml(article.content);
        console.log('Converted HTML for editor:', html.substring(0, 100));
        
        // Set state for editor
        setEditorContent(html);
        
        // Set form value (will be converted back to markdown on submit)
        setValue('content', html);
      } catch (error) {
        console.error('Error converting markdown to HTML:', error);
      }
    }


    
    // Load permissions and profile from sessionStorage
    try {
      const storedPermissions = sessionStorage.getItem('userPermissions');
      const storedProfile = sessionStorage.getItem('userProfile');
      
      console.log('Stored permissions from sessionStorage:', storedPermissions);
      
      if (storedPermissions) {
        let parsedPermissions;
        try {
          parsedPermissions = JSON.parse(storedPermissions);
        } catch (e) {
          console.error('Error parsing permissions JSON:', e);
          parsedPermissions = {};
        }
        
        // Store the parsed permissions (including category_permissions array)
        const normalizedPermissions: Record<string, any> = {};
        Object.entries(parsedPermissions).forEach(([key, value]) => { 
          normalizedPermissions[key] = value; // Keep original types
        });
        
        setUserPermissions(normalizedPermissions);
        console.log('Parsed and normalized permissions:', normalizedPermissions);
        
        // Determine allowed categories based on permissions
        const allowedSlugs: string[] = normalizedPermissions.category_permissions || [];
        let filteredCategories = categories.filter(cat => 
          allowedSlugs.includes(cat.slug)
        );

        // Ensure the article category is available in the select even if not in allowedSlugs
        if (article) {
          const articleCat = {
            id: article.category_slug ?? article.category ?? 'article-category',
            name: article.category,
            slug: article.category_slug ?? slugify(article.category || '')
          };
          if (articleCat.slug && !filteredCategories.some(cat => cat.slug === articleCat.slug)) {
            filteredCategories = [articleCat, ...filteredCategories];
          }
        }

        setAllowedCategories(filteredCategories);
        console.log('Allowed categories:', filteredCategories);
        
        const matchedCategory = filteredCategories.find(
          (cat) =>
            (article?.category_slug && cat.slug === article.category_slug) ||
            (article?.category && (cat.slug === slugify(article.category) || cat.name === article.category))
        );

        if (article && matchedCategory) {
          setValue('category', matchedCategory.name);
        } else if (filteredCategories.length === 1) {
          setValue('category', filteredCategories[0].name);
        } else if (filteredCategories.length > 0 && !getValues('category')) {
          // lascia vuoto per forzare la selezione
        }

        // Vecchia logica di default category (tenuta come riferimento)
        // if (article?.category) {
        //   setValue('category', article.category);
        // } else if (filteredCategories.length === 1) {
        //   setValue('category', filteredCategories[0].name);
        // } else if (filteredCategories.length > 0 && !getValues('category')) {
        //   // setValue('category', filteredCategories[0].name);
        // }
      } else {
        console.warn('No permissions found in sessionStorage');
        setAllowedCategories([]); // No permissions means no categories allowed
      }
      
      if (storedProfile) {
        const profile = JSON.parse(storedProfile);
        setUserProfile(profile);

        if (!selectedCreator) {
          //const existingCreator = article?.creator || profile?.full_name || profile?.id;
          const initialCreator= profile?.full_name;
          if (initialCreator) setSelectedCreator(initialCreator); //setta come creatore di default il proprietario del profilo
        }
        if (profile.full_name) {
          setCurrentUser(profile.full_name);
        }
        console.log('User profile loaded:', profile);
      } else {
        console.warn('No user profile found in sessionStorage');
      }
    } catch (e) {
      console.error('Error loading permissions from sessionStorage:', e);
    }

    // Get current user on component mount if not already set
    if (!currentUser) {
      const fetchCurrentUser = async () => {
        console.log('Fetching current user from DB as not found in session storage');
        const { data: { session } } = await supabase.auth.getSession();
        if (session?.user) {
          const { data: profile } = await supabase
            .from('profiles')
            .select('full_name, permissions')
            .eq('id', session.user.id)
            .single();
          
          if (profile) {
            if (profile.full_name) {
              setCurrentUser(profile.full_name);
            } else {
              setCurrentUser(session.user.email?.split('@')[0] || 'Unknown User');
            }
            
            // If permissions are still empty, set them from DB
            if (Object.keys(userPermissions).length === 0 && profile.permissions) {
              console.log('Setting permissions directly from DB (fallback):', profile.permissions);
              setUserPermissions(profile.permissions);
              
              // Determine allowed categories based on DB permissions
              const allowedSlugs: string[] = profile.permissions.category_permissions || [];
              let filteredCategories = categories.filter(cat => 
                allowedSlugs.includes(cat.slug)
              );

              // Ensure the article category is available in the select even if not in allowedSlugs
              if (article) {
                const articleCat = {
                  id: article.category_slug ?? article.category ?? 'article-category',
                  name: article.category,
                  slug: article.category_slug ?? slugify(article.category || '')
                };
                if (articleCat.slug && !filteredCategories.some(cat => cat.slug === articleCat.slug)) {
                  filteredCategories = [articleCat, ...filteredCategories];
                }
              }

              setAllowedCategories(filteredCategories);
              console.log('Allowed categories (DB fallback):', filteredCategories);
              
              // Set default category if editing or only one allowed (DB fallback)
              const matchedCategory = filteredCategories.find(
                (cat)=>
                (article?.category_slug && cat.slug === article.category_slug) ||
                (article?.category && (cat.slug === slugify(article.category) || cat.name === article.category))
              );
              if (article && matchedCategory){
                setValue('category', matchedCategory.name);
              }else if (filteredCategories.length === 1){
                setValue('category',filteredCategories[0].name);
              }

              // Vecchia logica di default category (tenuta come riferimento)
              // if (article?.category) {
              //   setValue('category', article.category);
              // } else if (filteredCategories.length === 1) {
              //   setValue('category', filteredCategories[0].name);
              // }

            }
          }
        }
      };

      fetchCurrentUser();
    }
    
    // Ensure selected creator is set for existing articles
    //if (!selectedCreator && article?.creator) {
      //setSelectedCreator(article.creator);
    //}
    
    // Initialize tags from article if editing
    if (article && article.tags) {
      setValue('tags', article.tags);
    }
    
    // Initialize selected secondary categories if editing an article
    if (article && article.secondary_category_slugs) {
      setSelectedSecondaryCategories(article.secondary_category_slugs);
      setValue('secondary_category_slugs', article.secondary_category_slugs);
    }
    
    // Add modal styles
    const style = document.createElement('style');
    style.textContent = `
      .modal-backdrop {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 50;
      }
      
      .modal-content {
        background-color: white;
        border-radius: 0.5rem;
        padding: 1.5rem;
        width: 100%;
        max-width: 28rem;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
      }
    `;
    document.head.appendChild(style);
    
    return () => {
      document.head.removeChild(style);
    };
  }, []);

  // Gestione toggle form contatti con conferma
const handleContactToggle = (checked: boolean) => {
  if (checked) {
    setShowContactConfirm(true);
  } else {
    setValue('show_contact_form', false, { shouldDirty: true });
  }
};

const confirmContactForm = () => {
  setValue('show_contact_form', true, { shouldDirty: true });
  setShowContactConfirm(false);
};

const cancelContactForm = () => {
  setValue('show_contact_form', false, { shouldDirty: true });
  setShowContactConfirm(false);
};


  const handleImageFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    try {
      const file = e.target.files?.[0];
      if (!file) return;

      setLoading(true); // Show loading state

      // Create temporary preview
      const tempUrl = URL.createObjectURL(file);
      setValue('image_url', tempUrl);

    // Upload to S3
    const formData = new FormData();
    formData.append('file', file);
    const articleTitle = getValues('title') || 'articolo';
    const articleSlug = slugify(articleTitle);
    const ext = file.name.split('.').pop() || 'jpg';
    formData.append('filename', `${articleSlug}.${ext}`);
    formData.append('title', articleTitle);

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
      setValue('image_url', url);
    } catch (error) {
      console.error('Error uploading image:', error);
      alert('Error uploading image: ' + (error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleThumbnailFileChange = async (e:React.ChangeEvent<HTMLInputElement>) =>{
    const file =e.target.files?.[0];
    if (!file) return;
    try{
      setThumbnailUploading(true);
      const tempUrl = URL.createObjectURL(file);
      setValue('thumbnail_url',tempUrl);

      const formData = new FormData();
      //per caricare su S3
      formData.append('file',file);
      const articleSlug = slugify(getValues('title') || 'articolo');
      const ext = file.name.split('.').pop() || 'jpg';
      formData.append('filename', `${articleSlug}-cover.${ext}`);
      formData.append('title', getValues('title') || '');

      const res= await fetch ('/api/upload',{
        method: 'POST',
        headers: { Authorization: `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}` },
        body: formData,
      });

      if(!res.ok) throw new Error('Errore upload cover');
      const {url}= await res.json();
      URL.revokeObjectURL(tempUrl);
      setValue('thumbnail_url',url);

    } catch(err){
      console.error(err);
      alert('Errore upload immagine cover: ' + (err as Error).message);

    } finally{
      setThumbnailUploading(false);

    }
  };

  const handleThumbnailUrlUpload = async () => {
    const urlFromInput = getValues('thumbnail_url');
    if (!urlFromInput || typeof urlFromInput !== 'string' || !urlFromInput.startsWith('http')){
      alert ('inserisci un url valido');
      return;
    }
    try {
      setThumbnailUploading(true);
      const res= await fetch('/api/upload-from-url',{
        method:'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`,
        },
        // Pass the article title so the backend can slugify the filename
        body: JSON.stringify({imageUrl: urlFromInput, title: getValues('title') || ''})
      });
      if (!res.ok) throw new Error ((await res.json()).error || 'Upload cover da URL fallito');
      const {url}= await res.json();
      setValue('thumbnail_url', url);
    } catch (error) {
      console.error(error);
      alert((error as Error).message)
    }finally{
      setThumbnailUploading(false);

    }
  };

  const handleSidebarVideoUpload = useCallback(async (file: File) => {
    console.time('videoUpload'); // Timing upload e lettura durata video

    const getVideoFileDuration =(file:File)=>
      new Promise<number>((resolve,reject)=>{
        const video= document.createElement('video');
        video.preload='metadata';
        video.onloadedmetadata=()=>{
          URL.revokeObjectURL(video.src);
          resolve(video.duration);
        };
        video.onerror= ()=> reject(new Error ("Unable to read video duration"));
        video.src=URL.createObjectURL(file);
      });


    if (!file) return;
    console.log('🎥 Starting video upload process...');
    console.log('🎥 File details:', { name: file.name, size: file.size, type: file.type });
    
    try {
      setIsUploadingVideo(true);

      const formData = new FormData();
      const articleSlug = slugify(getValues('title') || 'articolo');
      const ext = file.name.split('.').pop() || 'mp4';
      const filename = `${articleSlug}.${ext}`;
      formData.append('file', file);
      formData.append('filename', filename);
      formData.append('title', getValues('title') || '');
      
      console.log('🎥 Uploading with filename:', filename);

      const response = await fetch('/api/upload-video', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: formData
      });
      
      console.log('🎥 Upload response status:', response.status);
      
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        console.error('🎥 Upload failed with error:', errorPayload);
        throw new Error(errorPayload?.error || 'Video upload failed');
      }
  
      const payload = await response.json();
      console.log('🎥 Upload successful! Payload:', payload);
      console.log('🎥 Video URL received:', payload.url);
      
      // Update state
      setSidebarVideoUrl(payload.url);
      console.log('🎥 Updated sidebarVideoUrl state to:', payload.url);

      try {
        const durationSeconds = await getVideoFileDuration (file);
        const roundedDuration= Math.round(durationSeconds);
        setValue('video_duration', roundedDuration);
        setVideoDuration(roundedDuration);
        console.log('Video duration (seconds): ',roundedDuration);

      } catch (error) {
        console.warn('Unable to get video duration',error);
        setVideoDuration(null);
        setValue('video_duration',null);
      }
      
      // Update form value
      setValue('video_url', payload.url);
      console.log('🎥 Set form video_url value to:', payload.url);
      
      // Verify the form value was set
      const currentFormValue = getValues('video_url');
      console.log('🎥 Current form video_url value after setValue:', currentFormValue);
      
    } catch (err) {
      console.error('🎥 Error uploading video:', err);
      alert((err as Error).message);
    } finally {
      console.timeEnd('videoUpload'); // Fine timing upload video
      setIsUploadingVideo(false);
      console.log('🎥 Video upload process completed');
    }

     /*await new Promise(resolve => setTimeout(resolve, 500));
      const fakeUrl = '/videoSimona.mov';
      setSidebarVideoUrl(fakeUrl);
      setValue('video_url', fakeUrl);
    } catch (err) {
      console.error('Mock upload error:', err);
    } finally {
      setIsUploadingVideo(false);
    }*/

  }, [article?.id, setValue]);


  
  

  const handleUrlUpload = async () => {
    const imageUrl = getValues('image_url');
    if (!imageUrl || typeof imageUrl !== 'string' || !imageUrl.startsWith('http')) {
      alert('Inserisci un URL valido.');
      return;
    }

    setUrlUploading(true);
    try {
      const response = await fetch('/api/upload-from-url', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        // Include title so the API can rename the file using slugified title
        body: JSON.stringify({ imageUrl, title: getValues('title') || '' })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to upload image from URL');
      }

      const { url: s3Url } = await response.json();
      setValue('image_url', s3Url);
      alert('Immagine caricata con successo da URL!');

    } catch (error) {
      console.error('Error uploading image from URL:', error);
      alert('Errore nel caricamento dell\'immagine da URL: ' + (error as Error).message);
    } finally {
      setUrlUploading(false);
    }
  };

  const onSubmit = async (data: any, event?: React.BaseSyntheticEvent) => {
    console.time('submit');
    try {
      setLoading(true);
      
      // Determine which button triggered the submit
      // Use type assertion to access submitter
      const submitter = (event?.nativeEvent as SubmitEvent | undefined)?.submitter as HTMLButtonElement | null;
      const submitterName = submitter?.name;
      const shouldSendToFacebook = submitterName === 'saveWithFacebook';
      
      console.log('Submit triggered by:', submitterName, ' | Should send to Facebook:', shouldSendToFacebook);

      // --- Category Permission Check --- 
      const selectedCategoryName = data.category;
      const selectedCategorySlug = slugify(selectedCategoryName);
      const allowedCategorySlugs: string[] = userPermissions.category_permissions || [];

      console.log('Checking category permission for save:', {
        selectedCategorySlug,
        allowedCategorySlugs,
        isAllowed: allowedCategorySlugs.includes(selectedCategorySlug)
      });

      if (!selectedCategorySlug || !allowedCategorySlugs.includes(selectedCategorySlug)) {
        alert(`Errore: Non hai il permesso di scrivere nella categoria '${selectedCategoryName}'. Seleziona una categoria consentita.`);
        setLoading(false);
        return; // Stop submission
      }
      // --- End Category Permission Check ---

      // --- Auto-generate missing tags and summary ---
      if (data.title && data.content) {
        const missingTags = !data.tags || data.tags.length === 0;
        const missingSummary = !data.summary || data.summary.trim() === '';
        
        if (missingTags || missingSummary) {
          console.log('Article detected with missing content:', { missingTags, missingSummary });
          
          // Convert HTML content to plain text for better AI processing
          const tempDiv = document.createElement('div');
          tempDiv.innerHTML = data.content;
          const plainTextContent = tempDiv.textContent || tempDiv.innerText || '';

          // Generate missing tags
                      if (missingTags) {
              try {
                console.log('Auto-generating tags...');
              const tagsResponse = await fetch('/api/generate-tags', {
                method: 'POST',
                headers: { 
                  'Content-Type': 'application/json',
                  'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
                },
                body: JSON.stringify({
                  title: data.title,
                  content: plainTextContent,
                  excerpt: data.excerpt
                }),
              });

              if (tagsResponse.ok) {
                const tagsResult = await tagsResponse.json();
                if (tagsResult && tagsResult.tags && Array.isArray(tagsResult.tags)) {
                  data.tags = tagsResult.tags;
                  setValue('tags', tagsResult.tags);
                  console.log('Auto-generated tags:', tagsResult.tags);
                }
              } else {
                console.warn('Failed to auto-generate tags, proceeding without them');
              }
            } catch (error) {
              console.warn('Error auto-generating tags:', error);
            }
          }

          // Generate missing summary
                      if (missingSummary) {
              try {
                console.log('Auto-generating summary...');
              const summaryResponse = await fetch('/api/generate-summary', {
                method: 'POST',
                headers: { 
                  'Content-Type': 'application/json',
                  'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
                },
                body: JSON.stringify({
                  title: data.title,
                  content: plainTextContent,
                  excerpt: data.excerpt
                }),
              });

              if (summaryResponse.ok) {
                const summaryResult = await summaryResponse.json();
                if (summaryResult && summaryResult.summary && summaryResult.title_summary) {
                  data.summary = summaryResult.summary;
                  data.title_summary = summaryResult.title_summary;
                  setValue('summary', summaryResult.summary);
                  setValue('title_summary', summaryResult.title_summary);
                  console.log('Auto-generated summary:', summaryResult.summary);
                  console.log('Auto-generated title_summary:', summaryResult.title_summary);
                }
              } else {
                console.warn('Failed to auto-generate summary, proceeding without it');
              }
            } catch (error) {
              console.warn('Error auto-generating summary:', error);
            }
          }
        }
      }
      // --- End Auto-generation ---

      console.log('📝 === FORM SUBMISSION STARTED ===');
      console.log('📝 Original HTML content:', data.content.substring(0, 200));
      console.log('📝 Complete form data before processing:', data);
      console.log('📝 Video URL from form data:', data.video_url);
      console.log('📝 Video URL from sidebarVideoUrl state:', sidebarVideoUrl);
      console.log('📝 Current form video_url value:', getValues('video_url'));
      
      // Convert the HTML content to markdown for storage
      const markdownContent = htmlToMarkdown(data.content);
      
      console.log('Converted markdown content:', markdownContent);
      
      // Test if the markdown format matches what the article renderer expects
      testMarkdownImageParsing(markdownContent);
      
      data.show_contact_form = canEditContactForm ? data.show_contact_form : false;


      // The image is already uploaded, just use the URL
      //const baseCreator = article?.creator || currentUser;
      const baseCreator = userProfile?.full_name || currentUser || article?.creator;
      const finalCreator = canModifyCreator ? (selectedCreator || baseCreator) : baseCreator;

      const articleData = {
        ...data,
        content: markdownContent, // Use the converted markdown content
        slug: slugify(data.title),
        category_slug: selectedCategorySlug, // Use the verified slug
        creator: finalCreator,
        tags: data.tags || [], // Ensure tags are included
        secondary_category_slugs: selectedSecondaryCategories, // Add selected secondary categories
        summary: data.summary || '', // Include summary
        title_summary: data.title_summary || '', // Include title_summary
        video_url: sidebarVideoUrl || data.video_url || '', // Ensure video_url is included
        video_duration: data.video_duration ?? videoDuration ?? null
      };

      // Let the API handle publication timestamps
      delete (articleData as any).published_at;

      
      
      console.log('📝 === ARTICLE DATA PREPARATION ===');
      console.log('📝 Complete article data being sent:', articleData);
      console.log('📝 Video URL in article data:', articleData.video_url);
      console.log('📝 Article data video_url type:', typeof articleData.video_url);
      console.log('📝 Article data video_url length:', articleData.video_url?.length || 0);
      
      // Determine if we're creating or updating
      const isEditing = !!article;
      
      console.log('Current permissions:', userPermissions);
      
      // Ensure permissions are properly checked
      const canPublishArticles = !!userPermissions['publish_articles']; // Use bracket notation and ensure boolean
      console.log('Publishing check:', {
        isDraft: data.isdraft,
        canPublish: canPublishArticles,
        willForceDraft: !data.isdraft && !canPublishArticles
      });
      
      // Check if user can publish articles when trying to publish
      if (!data.isdraft && !canPublishArticles) {
        console.log('Forcing draft mode due to missing publish permission');
        // Force to draft mode if no publish permission
        articleData.isdraft = true;
        alert('You do not have permission to publish articles. The article will be saved as a draft.');
      }
      
      // Check if user can feature articles when trying to feature
      if (data.is_featured && !userPermissions['feature_articles']) { // Use bracket notation
        console.log('Removing featured flag due to missing feature_articles permission');
        // Remove featured flag if no permission
        articleData.is_featured = false;
        alert('You do not have permission to feature articles. The article will be saved without featuring.');
      }
      
      const endpoint = isEditing 
        ? `/api/articles/${article.id}`
        : '/api/articles/create';
      
      console.log('📝 === API CALL ===');
      console.log('📝 Endpoint:', endpoint);
      console.log('📝 Method:', isEditing ? 'PUT' : 'POST');
      console.log('📝 Sending article data with video_url:', articleData.video_url);
      
      const response = await fetch(endpoint, {
        method: isEditing ? 'PUT' : 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: JSON.stringify(articleData)
      });
      
      console.log('📝 API Response status:', response.status);
      console.log('📝 API Response ok:', response.ok);

      if (!response.ok) {
        const error = await response.json();
        console.error('📝 API Error:', error);
        throw new Error(error.message || 'Impossibile salvare l\'articolo');
      }

      const result = await response.json();
      console.log('📝 === API SUCCESS ===');
      console.log('📝 API Response result:', result);
      console.log('📝 Saved article video_url:', result.video_url);
      console.log(`${isEditing ? 'Updated' : 'Created'} article:`, result);
      
      // Store the saved article data
      setSavedArticle(result);
      
      // If article is published (not a draft) and user has permission to publish, post to Facebook ONLY if the correct button was pressed
      if (!data.isdraft && canPublishArticles && shouldSendToFacebook) { // Use the derived boolean AND check the flag
        setFbPosting(true); // Indicate FB posting is starting
        try {
          // Create the article URL using the utility function with the production domain
          const fullArticleUrl = "https://edunews24.it" + getArticleUrl({
            category: selectedCategoryName, // Use the selected name
            title: data.title,
            slug: articleData.slug
          });
          
          // Pass tags to the Facebook post function
          const fbResponse = await sendFacebookPost(fullArticleUrl, data.title, articleData.tags);
          
          if (fbResponse && fbResponse.id) {
            setFbPostStatus({
              message: `Articolo pubblicato con successo su Facebook! Post ID: ${fbResponse.id}`,
              isError: false
            });
            console.log('Posted to Facebook successfully:', fbResponse);
            alert(`Articolo pubblicato con successo su Facebook!\n\nPost ID: ${fbResponse.id}\nURL: ${fullArticleUrl}`);
          } else {
            setFbPostStatus({
              message: `Errore nella pubblicazione su Facebook: ${JSON.stringify(fbResponse)}`,
              isError: true
            });
            console.error('Facebook post response error:', fbResponse);
            alert(`Errore nella pubblicazione su Facebook: ${JSON.stringify(fbResponse)}\n\nURL tentato: ${fullArticleUrl}`);
          }
        } catch (fbError) {
          setFbPostStatus({
            message: `Errore nella pubblicazione su Facebook: ${(fbError as Error).message}`,
            isError: true
          });
          console.error('Failed to post to Facebook:', fbError);
          alert(`Errore nella pubblicazione su Facebook: ${(fbError as Error).message}`);
        } finally {
          setFbPosting(false); // Indicate FB posting finished
        }
      } else if (!data.isdraft && canPublishArticles && !shouldSendToFacebook) {
        console.log('Skipping Facebook post because "Salva (senza FB)" was clicked.');
        // Optional: Show a specific alert for this case
        alert('Articolo salvato con successo senza pubblicazione su Facebook.');
      } else if (data.isdraft) {
        console.log('Article is a draft, skipping Facebook post.');
        alert('Bozza salvata con successo.'); // Alert for saving draft
      } else if (!canPublishArticles) {
        console.log('User cannot publish, skipping Facebook post.');
        // Alert for this case is handled within the permission check logic earlier
      }
      
      // Redirect to articles list only after potential alerts have been shown
      // Add a slight delay to allow user to read alerts
      setTimeout(() => {
        window.location.href = '/admin';
      }, fbPosting ? 3000 : 1500); // Longer delay if FB posting happened
    } catch (error) {
      console.error('Errore nel salvare l\'articolo:', error);
      alert('Errore nel salvare l\'articolo: ' + (error as Error).message);
    } finally {
      console.timeEnd('submit');
      setLoading(false);
    }
  };

  const handleAudioUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    try {
      const file = e.target.files?.[0];
      if (!file) return;

      // Show loading state
      setLoading(true);

      // Upload to Supabase Storage
      const fileExt = file.name.split('.').pop();
      const fileName = `${uuidv4()}.${fileExt}`;
      const { data, error } = await supabase.storage
        .from('article-audio')
        .upload(fileName, file);

      if (error) throw error;

      // Get public URL
      const { data: { publicUrl } } = supabase.storage
        .from('article-audio')
        .getPublicUrl(fileName);

      // Update form
      setValue('audio_url', publicUrl);
    } catch (error) {
      console.error('Errore nel caricamento dell\'audio:', error);
      alert('Errore nel caricamento dell\'audio file');
    } finally {
      setLoading(false);
    }
  };

  // Helper function to split long sentences
  const splitLongSentences = (text: string, maxLength: number = 200): string => {
    // Split by sentence endings
    const sentences = text.split(/([.!?]+)/);
    const result: string[] = [];
    
    for (let i = 0; i < sentences.length; i += 2) {
      const sentence = sentences[i];
      const punctuation = sentences[i + 1] || '';
      
      if (sentence && sentence.trim().length > maxLength) {
        // For very long sentences, split by commas and other natural breaks
        const parts = sentence.split(/([,;:]\s+)/);
        let currentPart = '';
        
        for (let j = 0; j < parts.length; j += 2) {
          const part = parts[j];
          const separator = parts[j + 1] || '';
          
          if ((currentPart + part + separator).length > maxLength && currentPart.trim()) {
            result.push(currentPart.trim() + '.');
            currentPart = part + separator;
          } else {
            currentPart += part + separator;
          }
        }
        
        if (currentPart.trim()) {
          result.push(currentPart.trim() + punctuation);
        }
      } else if (sentence && sentence.trim()) {
        result.push(sentence.trim() + punctuation);
      }
    }
    
    return result.join(' ').replace(/\s+/g, ' ').trim();
  };

  const generateAudioUrl = async (articleId: string, title: string, content: string) => {
    console.time('audioGen'); // Timing generazione audio
    try {
      setLoading(true);
      
      // Process content to handle long sentences
      const processedContent = splitLongSentences(content, 200);
      
      console.log('Original content length:', content.length);
      console.log('Processed content length:', processedContent.length);
      
      const response = await fetch('/api/tts/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: JSON.stringify({
          articleId,
          title,
          content: processedContent, // Send processed content with split sentences
          excerpt: getValues('excerpt') // Add excerpt here
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Failed to generate audio');
      }

      const { jobId } = await response.json();
      return jobId;
      
    } catch (error) {
      console.error('Errore nella generazione dell\'audio:', error);
      alert('Errore nella generazione dell\'audio file: ' + (error as Error).message);
      return null;
    } finally {
      console.timeEnd('audioGen'); // Fine timing audio
      setLoading(false);
    }
  };

  const content = watch('content');
  const title = watch('title');
  const isDraft = watch('isdraft');
  const currentTags = watch('tags'); // Watch the tags field

  // Destructure register for the title field to combine refs
  const { ref: rfhTitleRefCallback, ...titlePropsFromRegister } = register('title', { 
    required: "Il titolo è obbligatorio" 
  });

  // Callback to combine React Hook Form's ref with our local ref
  const combinedTitleRefCallback = useCallback(
    (element: HTMLTextAreaElement) => {
      rfhTitleRefCallback(element); // Call RHF's ref function
      titleTextareaRef.current = element; // Set our local ref
    },
    [rfhTitleRefCallback]
  );

  // Function to handle textarea resizing
  const autoResizeTextarea = (textarea: HTMLTextAreaElement | null) => {
    if (textarea) {
      const originalOverflow = textarea.style.overflowY;
      textarea.style.overflowY = 'hidden'; // Prevent scrollbar flash during resize
      textarea.style.height = 'auto'; // Reset height to accurately calculate scrollHeight
      textarea.style.height = `${textarea.scrollHeight}px`; // Set height to scrollHeight
      textarea.style.overflowY = originalOverflow; // Restore original overflow style
    }
  };

  // Permission flags
  const canPublish = !!userPermissions['publish_articles'];
  const canFeatureArticles = !!userPermissions['feature_articles'];
  const canEditContactForm = !!userPermissions['contact_form_in_article'];
  const canModifyCreator = !!userPermissions['modify_creator'];

  // Effect to resize on initial load or programmatic changes to title
  useEffect(() => {
    // Initial resize might be needed if there's a default value
    if (titleTextareaRef.current) {
        autoResizeTextarea(titleTextareaRef.current);
    }
  }, [title]); // Runs when title (from watch) changes

  // Load creators list if allowed
  useEffect(() => {
    if (!canModifyCreator) return;

    const loadCreators = async () => {
      try {
        const { data, error } = await supabase
          .from('profiles')
          .select('id, full_name')
          .in('role', ['giornalista', 'redattore', 'direttore', 'admin'])
          .order('full_name', { ascending: true });

        if (error) throw error;
        const opts = (data || []).map((p) => ({
          value: p.full_name,
          label: p.full_name
        }));

        const current = selectedCreator || article?.creator;
        if (current && !opts.some((o) => o.value === current)) {
          opts.push({ value: current, label: current });
        }

        setCreatorOptions(opts);
      } catch (e) {
        console.error('Errore caricamento giornalisti', e);
      }
    };

    loadCreators();
  }, [article?.creator, selectedCreator, canModifyCreator]);

  // Content handling
  const handleEditorChange = (html: string) => {
    // This function is called whenever the editor content changes
    setEditorContent(html);
    setValue('content', html);
    // We don't set secondary_category_slugs here as it's handled by its own state and input
  };

  const handleGenerateAi = async () => {
    setAiLoading(true);
    try {
      const response = await fetch('/api/generate-article', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: JSON.stringify(aiParams), // includes sourceUrl
      });
      const result = await response.json();
      
      // Check if the API call was successful and returned the expected article structure
      if (result && result.article) {
        const articleAi = result.article;
        setValue('category', articleAi.category || ''); // Use default if category is missing
        setValue('title', articleAi.title);
        setValue('excerpt', articleAi.excerpt);
        setValue('tags', articleAi.keywords);
        // Convert markdown content to HTML for the editor
        const html = markdownToHtml(articleAi.content);
        setEditorContent(html);
        setValue('content', html); // Update form value with HTML
        // Remove the TagsInput key increment since we no longer use TagsInput
        // setTagsInputKey(prevKey => prevKey + 1); // Increment key to force TagsInput re-render
        
        setPreviewMode(true); // Optionally switch to preview
        console.log('Article generated by AI:', articleAi);
        console.log('final object:', result);
      } else {
        // Handle the error case where the API returned an error or unexpected format
        console.error('AI Generation Error:', result?.error || 'Unexpected response format');
        // Corrected alert message string escaping
        alert("Errore nella generazione dell'articolo AI: " + (result?.error || 'Risposta inattesa dal server.')); 
      }
    } catch (error) {
      console.error('Errore generazione AI:', error);
      alert('Errore nella generazione dell\'articolo AI: ' + (error as Error).message);
    } finally {
      setAiLoading(false);
      setShowAiModal(false);
    }
  };

  const handleGenerateAiTags = async () => {
    const currentTitle = getValues('title');
    const currentContent = getValues('content');
    const currentExcerpt = getValues('excerpt');

    if (!currentTitle || !currentContent) {
      alert('Inserisci prima un titolo e del contenuto per generare i tags.');
      return;
    }

    setAiTagsLoading(true);
    try {
      // Convert HTML content to plain text for better AI processing
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = currentContent;
      const plainTextContent = tempDiv.textContent || tempDiv.innerText || '';

      const response = await fetch('/api/generate-tags', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: JSON.stringify({
          title: currentTitle,
          content: plainTextContent,
          excerpt: currentExcerpt
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`API error: ${errorText}`);
      }

      const result = await response.json();
      
      // Check if the API call was successful and returned tags
      if (result && result.tags && Array.isArray(result.tags)) {
        setValue('tags', result.tags);
        console.log('AI generated tags:', result.tags);
      } else {
        console.error('AI Tags Generation Error:', result?.error || 'Unexpected response format');
        alert("Errore nella generazione dei tags AI: " + (result?.error || 'Risposta inattesa dal server.')); 
      }
    } catch (error) {
      console.error('Errore generazione tags AI:', error);
      alert('Errore nella generazione dei tags AI: ' + (error as Error).message);
    } finally {
      setAiTagsLoading(false);
    }
  };

  const handleGenerateAiSummary = async () => {
    const currentTitle = getValues('title');
    const currentContent = getValues('content');
    const currentExcerpt = getValues('excerpt');

    if (!currentTitle || !currentContent) {
      alert('Inserisci prima un titolo e del contenuto per generare la sezione riassunto.');
      return;
    }

    setAiSummaryLoading(true);
    try {
      // Convert HTML content to plain text for better AI processing
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = currentContent;
      const plainTextContent = tempDiv.textContent || tempDiv.innerText || '';

      const response = await fetch('/api/generate-summary', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${import.meta.env.PUBLIC_API_SECRET_KEY}`
        },
        body: JSON.stringify({
          title: currentTitle,
          content: plainTextContent,
          excerpt: currentExcerpt
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`API error: ${errorText}`);
      }

      const result = await response.json();
      
      // Check if the API call was successful and returned summary data
      if (result && result.summary && result.title_summary) {
        setValue('summary', result.summary);
        setValue('title_summary', result.title_summary);
        console.log('AI generated summary:', result.summary);
        console.log('AI generated title_summary:', result.title_summary);
      } else {
        console.error('AI Summary Generation Error:', result?.error || 'Unexpected response format');
        alert("Errore nella generazione dei riassunti AI: " + (result?.error || 'Risposta inattesa dal server.')); 
      }
    } catch (error) {
      console.error('Errore generazione riassunti AI:', error);
      alert('Errore nella generazione dei riassunti AI: ' + (error as Error).message);
    } finally {
      setAiSummaryLoading(false);
    }
  };

  const primaryCategory = watch('category'); // Watch the primary category field

  // Fetch secondary categories when primary category changes
  useEffect(() => {
    const fetchSecondaryCategories = async () => {
      if (!primaryCategory) {
        setAvailableSecondaryCategories([]);
        setSelectedSecondaryCategories([]); // Clear selected when primary changes
        setValue('secondary_category_slugs', []);
        return;
      }
      const primaryCategorySlug = slugify(primaryCategory);
      setLoading(true);
      try {
        const { data, error } = await supabase
          .from('secondary_categories') // Make sure this table exists
          .select('*')
          .eq('parent_category_slug', primaryCategorySlug);

        if (error) {
          console.error('Error fetching secondary categories:', error);
          setAvailableSecondaryCategories([]);
        } else {
          setAvailableSecondaryCategories(data || []);
        }
      } catch (err) {
        console.error('Error fetching secondary categories:', err);
        setAvailableSecondaryCategories([]);
      } finally {
        setLoading(false);
      }
    };

    fetchSecondaryCategories();
  }, [primaryCategory, setValue]);

  return (
    <div className="min-h-screen bg-gray-50 py-4 sm:py-8">
      <form onSubmit={handleSubmit(onSubmit)} className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="bg-white shadow-sm rounded-lg">
          {/* Header */}
          <div className="px-4 sm:px-8 py-4 sm:py-6 border-b border-gray-200">
            <div className="flex flex-col space-y-4 xl:flex-row xl:justify-between xl:items-start xl:space-y-0">
              <div className="flex-1">
                <h1 className="text-xl sm:text-2xl font-semibold text-gray-900 mb-2">
                  {article ? 'Modifica Articolo' : 'Crea Nuovo Articolo'}
                </h1>
                
                {/* Status and quick actions row */}
                <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
                  {/* Draft/Published Status */}
                  <div className="flex items-center">
                    <button
                      type="button"
                      onClick={() => setValue('isdraft', !isDraft)}
                      className={`inline-flex items-center px-3 py-1.5 border rounded-full shadow-sm text-sm font-medium transition-colors
                        ${isDraft 
                          ? 'border-yellow-300 text-yellow-800 bg-yellow-50 hover:bg-yellow-100' 
                          : 'border-green-300 text-green-800 bg-green-50 hover:bg-green-100'}`}
                      disabled={!canPublish && !isDraft}
                      title={!canPublish && !isDraft ? "You don't have permission to publish articles" : ""}
                    >
                      <div className={`w-2 h-2 rounded-full mr-2 ${isDraft ? 'bg-yellow-400' : 'bg-green-400'}`}></div>
                      {isDraft ? 'Bozza' : 'Pubblicato'}
                      {!canPublish && isDraft && (
                        <span className="ml-1 text-xs opacity-75">(Solo bozze)</span>
                      )}
                    </button>
                  </div>

                  {/* Mode Toggle */}
                  <div className="flex items-center bg-gray-100 rounded-lg p-1">
                    <button
                      type="button"
                      onClick={() => setPreviewMode(false)}
                      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                        !previewMode 
                          ? 'bg-white text-gray-900 shadow-sm' 
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      <div className="flex items-center">
                        <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                        </svg>
                        Modifica
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setPreviewMode(true)}
                      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                        previewMode 
                          ? 'bg-white text-gray-900 shadow-sm' 
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      <div className="flex items-center">
                        <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                        Anteprima
                      </div>
                    </button>
                  </div>
                </div>
              </div>
              
              {/* Action buttons */}
              <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 xl:flex-shrink-0">
                <button
                  type="button"
                  onClick={() => setShowAiModal(true)}
                  className="inline-flex items-center justify-center px-4 py-2 border border-gray-300 rounded-lg shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary transition-colors"
                >
                  <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  <span className="hidden sm:inline">Genera con AI</span>
                  <span className="sm:hidden">AI</span>
                </button>
                
                <button
                  type="submit"
                  name="saveWithoutFacebook"
                  disabled={loading || fbPosting}
                  className="inline-flex items-center justify-center px-4 py-2 border border-gray-300 rounded-lg shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                  {loading ? 'Salvataggio...' : 'Salva'}
                </button>
                
                <button
                  type="submit"
                  name="saveWithFacebook"
                  disabled={loading || fbPosting}
                  className="inline-flex items-center justify-center px-4 py-2 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {fbPosting ? (
                    <>
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Pubblicando...
                    </>
                  ) : loading ? (
                    <>
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Salvataggio...
                    </>
                  ) : (
                    <>
                      <svg className="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/>
                      </svg>
                      <span className="hidden sm:inline">Salva e Pubblica</span>
                      <span className="sm:hidden">Pubblica</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Permission warnings */}
            {!canPublish && (
              <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                <div className="flex">
                  <svg className="h-5 w-5 text-yellow-400 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <div className="text-sm text-yellow-700">
                    <span className="font-semibold">Nota:</span> Non hai il permesso di pubblicare articoli. L'articolo verrà salvato come bozza.
                  </div>
                </div>
              </div>
            )}
            {allowedCategories.length === 0 && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
                <div className="flex">
                  <svg className="h-5 w-5 text-red-400 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                  <div className="text-sm text-red-700">
                    <span className="font-semibold">Attenzione:</span> Non hai permessi assegnati per nessuna categoria. Non potrai salvare l'articolo.
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="px-4 sm:px-8 py-4 sm:py-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:gap-6">
              {/* Main Content - Left 2 columns */}
              <div className="col-span-1 lg:col-span-2 space-y-4 lg:space-y-6">
                {/* Title */}
                <div>
                  <textarea
                    {...titlePropsFromRegister} // Spread other props from register (like onChange, onBlur, name)
                    ref={combinedTitleRefCallback}   // Use the combined ref
                    rows={1}
                    onInput={() => autoResizeTextarea(titleTextareaRef.current)} // Resize immediately on user input
                    className={`block w-full border-0 border-b-2 ${errors.title ? 'border-red-500' : 'border-gray-200'} focus:ring-0 focus:border-primary text-xl sm:text-2xl lg:text-3xl font-bold placeholder-gray-400 px-0 resize-none overflow-y-hidden min-h-12`}
                    placeholder="Titolo Articolo"
                  />
                  {errors.title && <p className="mt-1 text-xs sm:text-sm text-red-600">{errors.title.message as string}</p>}
                </div>

                {/* Content Editor */}
                <div className="relative border border-gray-200 rounded-md">
                  {previewMode ? (
                    <div className="article-preview-container bg-gray-100 p-3 sm:p-6 rounded-md min-h-[300px] sm:min-h-[400px]">
                      {/* This div will contain the rendered HTML and have styles applied */}
                      <div
                        className="prose max-w-none article-content bg-white p-3 sm:p-6 rounded shadow-inner" // Add 'article-content' class and some basic styling
                        dangerouslySetInnerHTML={{ __html: editorContent }} // Use editorContent (HTML) directly
                      />
                    </div>
                  ) : (
                    <RichTextEditor 
                      content={editorContent} 
                      onChange={handleEditorChange}
                      articleTitle={title || ''}
                    />
                  )}
                </div>
              </div>

              {/* Sidebar - Right column */}
              <div className="col-span-1 space-y-4 lg:space-y-6">
                {/* Publish Settings Card */}
                <div className="bg-gray-50 rounded-lg p-4 lg:p-6">
                  <h3 className="text-base lg:text-lg font-medium text-gray-900 mb-3 lg:mb-4">Impostazioni di Pubblicazione</h3>
                  
                  <div className="space-y-3 lg:space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700">Categoria</label>
                      <select
                        {...register('category', { required: "La categoria è obbligatoria" })}
                        className={`mt-1 block w-full rounded-md ${errors.category ? 'border-red-500' : 'border-gray-300'} shadow-sm focus:border-primary focus:ring-primary text-sm`}
                        disabled={allowedCategories.length === 0}
                      >
                        { !article && <option value="">-- Seleziona Categoria --</option>}
                        {allowedCategories.map(category => (
                          <option key={category.id} value={category.name}>
                            {category.name}
                          </option>
                        ))}
                      </select>
                      {errors.category && <p className="mt-1 text-xs sm:text-sm text-red-600">{errors.category.message as string}</p>}
                      {allowedCategories.length === 0 && <p className="mt-1 text-xs sm:text-sm text-red-600">Non hai permessi per nessuna categoria.</p>}
                    </div>

                    {/* Secondary Categories Section */}
                    {availableSecondaryCategories.length > 0 && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700">Categorie Secondarie</label>
                        <div className="mt-2 space-y-2">
                          {availableSecondaryCategories.map(secCat => (
                            <div key={secCat.slug} className="flex items-center">
                              <input
                                id={`sec-cat-${secCat.slug}`}
                                type="checkbox"
                                value={secCat.slug}
                                checked={selectedSecondaryCategories.includes(secCat.slug)}
                                onChange={(e) => {
                                  const { value, checked } = e.target;
                                  let updatedSelection: string[];
                                  if (checked) {
                                    updatedSelection = [...selectedSecondaryCategories, value];
                                  } else {
                                    updatedSelection = selectedSecondaryCategories.filter(slug => slug !== value);
                                  }
                                  setSelectedSecondaryCategories(updatedSelection);
                                  setValue('secondary_category_slugs', updatedSelection);
                                }}
                                className="h-4 w-4 text-primary border-gray-300 rounded focus:ring-primary"
                              />
                              <label htmlFor={`sec-cat-${secCat.slug}`} className="ml-2 block text-sm text-gray-700">
                                {secCat.name}
                              </label>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Show contact form checkbox */}
                    <div className="flex items-center">
                      <input
                        type="checkbox"
                        id="show_contact_form"
                        {...register('show_contact_form')}
                        className="h-4 w-4 text-primary border-gray-300 rounded focus:ring-primary"
                      />
                      <label htmlFor="show_contact_form" className="ml-2 block text-sm text-gray-700">
                        Mostra Form Contatti in Articolo
                      </label>
                    </div>
                    
                    {/* Only show featured checkbox if user has permission */}
                    {canFeatureArticles && (
                      <div className="flex items-center">
                        <input
                          type="checkbox"
                          id="is_featured"
                          {...register('is_featured')}
                          className="h-4 w-4 text-primary border-gray-300 rounded focus:ring-primary"
                        />
                        <label htmlFor="is_featured" className="ml-2 block text-sm text-gray-700">
                          Articolo in Evidenza
                        </label>
                      </div>
                    )}

                    {canModifyCreator && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700">Modifica Creatore</label>
                        <select
                          value={selectedCreator}
                          onChange={(e) => setSelectedCreator(e.target.value)}
                          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                        >
                          <option value="">-- Seleziona Creatore --</option>
                          {creatorOptions.map((opt) => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                      </div>
                    )}

                
                {/* Media Card */}
                <div className="bg-gray-50 rounded-lg p-4 lg:p-6">
                  <h3 className="text-base lg:text-lg font-medium text-gray-900 mb-3 lg:mb-4">Media</h3>
                  
                  <div className="space-y-3 lg:space-y-4">
                    {/* Featured Image */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700">Immagine in Evidenza</label>
                      <div className="mt-1 space-y-3 lg:space-y-4">
                        {/* Image Preview */}
                        <img
                          src={watch('image_url')}
                          alt="Preview"
                          className="h-24 sm:h-32 w-full object-cover rounded-lg"
                        />
                        
                        {/* Upload Method Selector */}
                        <div className="inline-flex p-1 bg-gray-100 rounded-lg w-full">
                          <button
                            type="button"
                            onClick={() => setUploadMethod('file')}
                            className={`flex-1 px-2 sm:px-4 py-2 rounded-md transition-all duration-200 ${
                              uploadMethod === 'file'
                                ? 'bg-white text-primary shadow-sm'
                                : 'text-gray-600 hover:text-gray-900'
                            }`}
                          >
                            <div className="flex items-center justify-center space-x-1 sm:space-x-2">
                              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 sm:h-5 sm:w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                              </svg>
                              <span className="text-xs sm:text-sm">Carica File</span>
                            </div>
                          </button>
                          <button
                            type="button"
                            onClick={() => setUploadMethod('url')}
                            className={`flex-1 px-2 sm:px-4 py-2 rounded-md transition-all duration-200 ${
                              uploadMethod === 'url'
                                ? 'bg-white text-primary shadow-sm'
                                : 'text-gray-600 hover:text-gray-900'
                            }`}
                          >
                            <div className="flex items-center justify-center space-x-1 sm:space-x-2">
                              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 sm:h-5 sm:w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                              </svg>
                              <span className="text-xs sm:text-sm">Inserisci URL</span>
                            </div>
                          </button>
                        </div>
                        
                        {/* Add conditional rendering based on uploadMethod */}
                        {uploadMethod === 'file' ? (
                          <div className="flex justify-center px-3 sm:px-6 pt-3 sm:pt-5 pb-3 sm:pb-6 border-2 border-gray-300 border-dashed rounded-lg">
                            <div className="space-y-1 text-center">
                              <svg
                                className="mx-auto h-8 w-8 sm:h-12 sm:w-12 text-gray-400"
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
                              <div className="flex text-xs sm:text-sm text-gray-600 justify-center">
                                <label
                                  htmlFor="imageFile"
                                  className="relative cursor-pointer rounded-md font-medium text-primary hover:text-primary-dark focus-within:outline-none"
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
                                <p className="pl-1 hidden sm:inline">o trascina qui</p>
                              </div>
                              <p className="text-xs text-gray-500">PNG, JPG, GIF fino a 10MB</p>
                            </div>
                          </div>
                        ) : (
                          // Corrected structure for URL input and button
                          <div>
                            <input
                              type="text"
                              {...register('image_url', { required: uploadMethod === 'url' })}
                              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                              placeholder="Inserisci URL dell'immagine"
                            />
                            <button
                              type="button"
                              onClick={handleUrlUpload}
                              disabled={urlUploading}
                              className="mt-2 w-full inline-flex items-center justify-center px-3 py-2 border border-transparent shadow-sm text-xs sm:text-sm font-medium rounded-md text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50"
                            >
                              {urlUploading ? (
                                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 sm:h-5 sm:w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                </svg>
                              ) : null}
                              <span>{urlUploading ? 'Caricando...' : 'Carica Immagine'}</span>
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Sidebar Video */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700">Video barra laterale</label>
                      <div className="mt-1 space-y-3 lg:space-y-4">
                        {/* Video Preview */}
                        {sidebarVideoUrl && (
                          <video
                            controls
                            playsInline
                            className="h-24 sm:h-32 w-full object-cover rounded-lg border border-gray-200"
                            src={sidebarVideoUrl}
                          />
                        )}
                        
                        {/* Video Upload Area */}
                        <div className="flex justify-center px-3 sm:px-6 pt-3 sm:pt-5 pb-3 sm:pb-6 border-2 border-gray-300 border-dashed rounded-lg">
                          <div className="space-y-1 text-center">
                            <svg
                              className="mx-auto h-8 w-8 sm:h-12 sm:w-12 text-gray-400"
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
                            <div className="flex text-xs sm:text-sm text-gray-600 justify-center">
                              <label
                                htmlFor="videoFile"
                                className={`relative cursor-pointer rounded-md font-medium focus-within:outline-none ${
                                  isUploadingVideo 
                                    ? 'text-gray-400 cursor-not-allowed' 
                                    : 'text-primary hover:text-primary-dark'
                                }`}
                              >
                                <span>
                                  {isUploadingVideo ? 'Caricamento in corso...' : 'Carica un video'}
                                </span>
                                <input
                                  id="videoFile"
                                  type="file"
                                  accept="video/mp4,video/webm,video/quicktime"
                                  onChange={(event) => {
                                    const videoFile = event.target.files?.[0];
                                    if (videoFile) handleSidebarVideoUpload(videoFile);
                                  }}
                                  disabled={isUploadingVideo}
                                  className="sr-only"
                                />
                              </label>
                              <p className="pl-1 hidden sm:inline">o trascina qui</p>
                            </div>
                            <p className="text-xs text-gray-500">MP4, WebM, MOV fino a 100MB</p>
                            {isUploadingVideo && (
                              <div className="flex items-center justify-center mt-2">
                                <svg className="animate-spin h-4 w-4 text-primary" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                </svg>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Remove Video Button */}
                        {sidebarVideoUrl && (
                          <div className="text-center">
                            <button
                              type="button"
                            onClick={() => {
                              console.log('🗑️ Removing video URL...');
                              console.log('🗑️ Current sidebarVideoUrl:', sidebarVideoUrl);
                              setSidebarVideoUrl('');
                              setValue('video_url', '');
                              console.log('🗑️ Video URL cleared from state and form');
                            }}
                              className="inline-flex items-center px-3 py-2 border border-transparent text-xs sm:text-sm font-medium rounded-md text-red-600 bg-red-50 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
                            >
                              <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                              Rimuovi video
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Hidden input for video_url to ensure it's registered with the form */}
                    <input
                      type="hidden"
                      {...register('video_url')}
                      value={sidebarVideoUrl}
                    />
                    <input 
                        type="hidden"
                        {...register('video_duration')}
                        value={videoDuration ?? ''}
                    />


                  {/* Cover video (mobile) */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700"> Thumbnail </label>
                    <div className="mt-1 space-y-3 lg:space-y-4">
                      {/*{watch('thumbnail_url') && (
                        <img
                          src={watch('thumbnail_url')}
                          alt="Cover del video"
                          className="h-24 sm:h-32 w-full object-cover rounded-lg border border-gray-200"
                        />

                      )}*/}

                        {watch('thumbnail_url') && (
                          <>
                            <img
                              src={watch('thumbnail_url')}
                              alt="Cover del video"
                              className="w-full h-outo object-contain rounded-lg border border-gray-200"
                            />
                            <div className="text-center mt-2">
                              <button
                                type="button"
                                onClick={() => {
                                  const current = watch('thumbnail_url');
                                  if (current?.startsWith('blob:')) URL.revokeObjectURL(current);
                                  setValue('thumbnail_url', '');
                                }}
                                className="inline-flex items-center px-3 py-2 border border-transparent text-xs sm:text-sm font-medium rounded-md text-red-600 bg-red-50 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
                              >
                                <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                </svg>
                                Rimuovi cover
                              </button>
                            </div>
                          </>
                        )}




                      <div className="inline-flex p-1 bg-gray-100 rounded-lg w-full">
                        <button
                          type="button"
                          onClick={() => setThumbnailUploadMethod('file')}
                          className={`flex-1 px-2 sm:px-4 py-2 rounded-md transition-all duration-200 ${thumbnailUploadMethod === 'file' ? 'bg-white text-primary shadow-sm' : 'text-gray-600 hover:text-gray-900'}`}
                        >
                          <span className="text-xs sm:text-sm">Carica File</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => setThumbnailUploadMethod('url')}
                          className={`flex-1 px-2 sm:px-4 py-2 rounded-md transition-all duration-200 ${thumbnailUploadMethod === 'url' ? 'bg-white text-primary shadow-sm' : 'text-gray-600 hover:text-gray-900'}`}
                        >
                          <span className="text-xs sm:text-sm">Inserisci URL</span>
                        </button>
                      </div>

                      {thumbnailUploadMethod === 'file' ? (
                        <div className="flex justify-center px-3 sm:px-6 pt-3 sm:pt-5 pb-3 sm:pb-6 border-2 border-gray-300 border-dashed rounded-lg">
                          <div className="space-y-1 text-center">
                            <label
                              htmlFor="thumbnailFile"
                              className={`relative cursor-pointer rounded-md font-medium ${thumbnailUploading ? 'text-gray-400 cursor-not-allowed' : 'text-primary hover:text-primary-dark'}`}
                            >
                              <span>{thumbnailUploading ? 'Caricamento...' : 'Carica cover'}</span>
                              <input
                                id="thumbnailFile"
                                type="file"
                                accept="image/*"
                                onChange={handleThumbnailFileChange}
                                disabled={thumbnailUploading}
                                className="sr-only"
                              />
                            </label>
                            <p className="text-xs text-gray-500">PNG/JPG/WebP fino a 10MB</p>
                          </div>
                        </div>
                      ) : (
                        <div>
                          <input
                            type="text"
                            {...register('thumbnail_url')}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                            placeholder="URL cover video"
                          />
                          <button
                            type="button"
                            onClick={handleThumbnailUrlUpload}
                            disabled={thumbnailUploading}
                            className="mt-2 w-full inline-flex items-center justify-center px-3 py-2 border border-transparent shadow-sm text-xs sm:text-sm font-medium rounded-md text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50"
                          >
                            {thumbnailUploading ? 'Caricando...' : 'Carica da URL'}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>



                    {/* Add back the Audio section */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700">Audio</label>
                      <div className="mt-1">
                    <input
                      type="text"
                      {...register('audio_url')} // Register the audio URL field
                      className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                  placeholder="L'URL dell'audio verrà generato"
                  readOnly
                />
                <button
                  type="button"
                  onClick={async () => {
                            const currentTitle = getValues('title'); // Use getValues to ensure latest title
                            const htmlContent = getValues('content'); // Get HTML content
                            const articleId = article?.id || savedArticle?.id;

                            if (!articleId) {
                              alert('Salva prima l\'articolo per generare l\'audio.');
                              return;
                            }

                            // Convert HTML to plain text for TTS
                            const tempDiv = document.createElement('div');
                            tempDiv.innerHTML = htmlContent;
                            const plainTextContent = tempDiv.textContent || tempDiv.innerText || '';

                            // Call generateAudioUrl with plain text
                            const jobId = await generateAudioUrl(articleId, currentTitle, plainTextContent);
                            if (jobId) {
                              alert('Generazione audio avviata. L\'audio verra\' salvato automaticamente.');
                            }
                          }}
                          className="mt-2 w-full inline-flex items-center justify-center px-3 sm:px-4 py-2 border border-transparent rounded-md shadow-sm text-xs sm:text-sm font-medium text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50"
                          disabled={loading}
                        >
                          {loading ? 'Generazione...' : 'Genera Audio'}
                        </button>
                        {/* Optional: Add manual upload button if needed */}
                        {/* 
                        <label htmlFor="audioFile" className="mt-2 w-full inline-flex items-center justify-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 cursor-pointer">
                          Carica File Audio
                        </label>
                        <input
                          id="audioFile"
                          type="file"
                          accept="audio/*"
                          onChange={handleAudioUpload} 
                          className="sr-only"
                        />
                        */}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Excerpt Card */}
                <div className="bg-gray-50 rounded-lg p-4 lg:p-6">
                  <h3 className="text-base lg:text-lg font-medium text-gray-900 mb-3 lg:mb-4">Estratto</h3>
                  <textarea
                    {...register('excerpt', { required: "L'estratto è obbligatorio" })}
                    rows={4}
                    className={`block w-full rounded-md ${errors.excerpt ? 'border-red-500' : 'border-gray-300'} shadow-sm focus:border-primary focus:ring-primary text-sm`}
                    placeholder="Scrivi un breve estratto..."
                  />
                  {errors.excerpt && <p className="mt-1 text-xs sm:text-sm text-red-600">{errors.excerpt.message as string}</p>}
                </div>

                {/* Summary Section Card */}
                <div className="bg-gray-50 rounded-lg p-4 lg:p-6">
                  <div className="flex items-center justify-between mb-3 lg:mb-4">
                    <h3 className="text-base lg:text-lg font-medium text-gray-900">Sezione Riassunto</h3>
                    <button
                      type="button"
                      onClick={handleGenerateAiSummary}
                      disabled={aiSummaryLoading}
                      className="inline-flex items-center px-3 py-1.5 border border-gray-300 rounded-md shadow-sm text-xs font-medium text-gray-700 bg-white hover:bg-gray-50 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      title="Genera sezione riassunto con AI"
                    >
                      {aiSummaryLoading ? (
                        <>
                          <svg className="animate-spin -ml-1 mr-1.5 h-3 w-3 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                          </svg>
                          <span className="hidden sm:inline">Generando...</span>
                          <span className="sm:hidden">...</span>
                        </>
                      ) : (
                        <>
                          <svg className="w-3 h-3 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                          <span className="hidden sm:inline">Genera Riassunto</span>
                          <span className="sm:hidden">AI</span>
                        </>
                      )}
                    </button>
                  </div>
                  
                  <div className="space-y-4">
                    {/* Title Summary */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Titolo del Riassunto</label>
                      <input
                        type="text"
                        {...register('title_summary')}
                        className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                        placeholder=""
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        Intestazione per la sezione riassunto dell'articolo
                      </p>
                    </div>

                    {/* Summary */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Contenuto del Riassunto</label>
                      <textarea
                        {...register('summary')}
                        rows={6}
                        className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                        placeholder=""
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        Riassunto che verrà pubblicato come sezione separata nell'articolo
                      </p>
                    </div>
                  </div>
                </div>

                {/* Tags Card */}
                <div className="bg-gray-50 rounded-lg p-4 lg:p-6">
                  <div className="flex items-center justify-between mb-3 lg:mb-4">
                    <h3 className="text-base lg:text-lg font-medium text-gray-900">Keywords</h3>
                    <button
                      type="button"
                      onClick={handleGenerateAiTags}
                      disabled={aiTagsLoading}
                      className="inline-flex items-center px-3 py-1.5 border border-gray-300 rounded-md shadow-sm text-xs font-medium text-gray-700 bg-white hover:bg-gray-50 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      title="Genera tags ottimizzati con AI"
                    >
                      {aiTagsLoading ? (
                        <>
                          <svg className="animate-spin -ml-1 mr-1.5 h-3 w-3 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                          </svg>
                          <span className="hidden sm:inline">Generando...</span>
                          <span className="sm:hidden">...</span>
                        </>
                      ) : (
                        <>
                          <svg className="w-3 h-3 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                          <span className="hidden sm:inline">AI Tags</span>
                          <span className="sm:hidden">AI</span>
                        </>
                      )}
                    </button>
                  </div>
                  <div className="space-y-3 lg:space-y-4">
                    {/* Current Tags Display */}
                    {currentTags && currentTags.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {currentTags.map((tag: string, index: number) => (
                          <span
                            key={index}
                            className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-primary text-white"
                          >
                            {tag}
                            <button
                              type="button"
                              onClick={() => {
                                const updatedTags = currentTags.filter((_: string, i: number) => i !== index);
                                setValue('tags', updatedTags);
                              }}
                              className="ml-1.5 inline-flex items-center justify-center w-4 h-4 rounded-full text-white hover:bg-white hover:text-primary transition-colors"
                            >
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          </span>
                        ))}
                      </div>
                    )}
                    
                    {/* Tag Input */}
                    <div className="flex gap-2">
                      <input
                        type="text"
                        placeholder="Inserisci un tag e premi Invio"
                        className="flex-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            const input = e.target as HTMLInputElement;
                            const newTag = input.value.trim();
                            if (newTag && !currentTags?.includes(newTag)) {
                              const updatedTags = [...(currentTags || []), newTag];
                              setValue('tags', updatedTags);
                              input.value = '';
                            }
                          }
                        }}
                      />
                      <button
                        type="button"
                        onClick={(e) => {
                          const input = e.currentTarget.previousElementSibling as HTMLInputElement;
                          const newTag = input.value.trim();
                          if (newTag && !currentTags?.includes(newTag)) {
                            const updatedTags = [...(currentTags || []), newTag];
                            setValue('tags', updatedTags);
                            input.value = '';
                          }
                        }}
                        className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                        </svg>
                      </button>
                    </div>
                    
                    {/* Helper text */}
                    <p className="text-xs text-gray-500">
                      Premi Invio o clicca + per aggiungere un tag. Clicca sulla X per rimuovere.
                    </p>
                  </div>

                </div>
                    {/* Show contact form checkbox */}
                    {canEditContactForm &&(
                      <div className="flex items-center">
                        <input
                          type="checkbox"
                          id="show_contact_form"
                          {...register('show_contact_form')}
                          checked={!!showContactForm}
                          onChange={(e) => handleContactToggle(e.target.checked)}
                          disabled={!canEditContactForm}
                          className="h-4 w-4 text-primary border-gray-300 rounded focus:ring-primary"
                        />
                        <label htmlFor="show_contact_form" className="ml-2 block text-sm text-gray-700">
                          Mostra Form Contatti in Articolo
                        </label>
                      </div>
                    )}
                  </div>
                </div>

              </div>
            </div>
          </div>
        </div>
      </form>
      
      {/* Add styles for TipTap editor AND Preview */}
      <style>{`
        .ProseMirror {
          min-height: 300px;
          padding: 0.75rem;
          outline: none !important;
        }
        @media (min-width: 640px) {
          .ProseMirror {
            min-height: 400px;
            padding: 1rem;
          }
        }
        .ProseMirror p {
          margin-bottom: 1rem;
        }
        .ProseMirror h2, .article-preview h2 {
          font-size: 1.25rem;
          font-weight: 700;
          margin-top: 1.5rem;
          margin-bottom: 0.75rem;
        }
        @media (min-width: 640px) {
          .ProseMirror h2, .article-preview h2 {
            font-size: 1.5rem;
          }
        }
        .ProseMirror h3, .article-preview h3 {
          font-size: 1.125rem;
          font-weight: 600;
          margin-top: 1.25rem;
          margin-bottom: 0.5rem;
        }
        @media (min-width: 640px) {
          .ProseMirror h3, .article-preview h3 {
            font-size: 1.25rem;
          }
        }
        .ProseMirror h4, .article-preview h4 {
          font-size: 1rem;
          font-weight: 600;
          margin-top: 1rem;
          margin-bottom: 0.5rem;
        }
        .ProseMirror img, .article-preview img {
          max-width: 100%;
          height: auto;
          border-radius: 0.375rem;
        }
        .ProseMirror a, .article-preview a {
          color: #3182ce;
          text-decoration: underline;
        }
        .ProseMirror ul, .article-preview ul {
          list-style-type: disc;
          padding-left: 1.5rem;
          margin-bottom: 1rem;
        }
        .ProseMirror ol, .article-preview ol {
          list-style-type: decimal;
          padding-left: 1.5rem;
          margin-bottom: 1rem;
        }
        .article-preview figure {
          margin: 1.5rem 0;
        }
        .article-preview figure img {
          display: block;
          margin: 0 auto;
        }
        .article-preview figcaption {
          text-align: center;
          font-style: italic;
          color: #718096;
          margin-top: 0.5rem;
          font-size: 0.875rem;
        }
        
        /* Styles copied from [slug].astro for the preview */
        .article-content p {
          margin-bottom: 1rem;
          line-height: 1.75;
        }
        
        .article-content strong {
          color: #1a1a1a;
          font-weight: 600;
        }
        
        .article-content em {
          font-style: italic;
          color: #4a5568;
        }

        .article-content h2 {
          font-size: 1.5rem; /* 24px on mobile */
          font-weight: 700;
          margin-top: 2.5rem;
          margin-bottom: 1.25rem;
          color: #1a1a1a;
          line-height: 2rem;
          border-bottom: 1px solid #e2e8f0;
          padding-bottom: 0.5rem;
        }
        @media (min-width: 640px) {
          .article-content h2 {
            font-size: 1.875rem; /* 30px on desktop */
            line-height: 2.25rem;
          }
        }

        .article-content h3 {
          font-size: 1.25rem; /* 20px on mobile */
          font-weight: 600;
          margin-top: 2rem;
          margin-bottom: 1rem;
          color: #2d3748;
          line-height: 1.75rem;
        }
        @media (min-width: 640px) {
          .article-content h3 {
            font-size: 1.5rem; /* 24px on desktop */
            line-height: 2rem;
          }
        }
        
        .article-content h4 {
          font-size: 1rem; /* 16px */
          font-weight: 600;
          margin-top: 1rem;
          margin-bottom: 0.5rem;
          color: #4a5568;
          line-height: 1.5rem;
        }
        
        .article-content figure {
          margin: 1.5rem 0;
        }
        @media (min-width: 640px) {
          .article-content figure {
            margin: 2rem 0;
          }
        }
        
        .article-content figure img {
          width: 100%;
          border-radius: 0.5rem;
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
          display: block;
          margin-left: auto;
          margin-right: auto;
        }
        
        .article-content figcaption {
          margin-top: 0.75rem;
          text-align: center;
          font-size: 0.875rem;
          color: #718096;
          font-style: italic;
        }

        .article-content a {
            color: #4299e1;
            text-decoration: underline;
        }
        .article-content a:hover {
            color: #2b6cb0;
        }
      `}</style>

      {showContactConfirm && (
        <div className="modal-backdrop">
          <div className="modal-content mx-4 sm:mx-0 max-w-sm">
            <h2 className="text-lg font-semibold mb-2">Inserire il form contatti?</h2>
            <p className="text-sm text-gray-600 mb-4">
              Sei sicura di voler mostrare il form di contatto dentro l'articolo?
            </p>
            <div className="flex justify-end space-x-3">
              <button
                type="button"
                onClick={cancelContactForm}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm bg-white hover:bg-gray-50"
              >
                No
              </button>
              <button
                type="button"
                onClick={confirmContactForm}
                className="px-3 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary-dark"
              >
                Sì, inserisci
              </button>
            </div>
          </div>
        </div>
      )}


      {showAiModal && (
        <div className="modal-backdrop">
          <div className="modal-content mx-4 sm:mx-0 max-w-xs sm:max-w-md lg:max-w-lg">
            <h2 className="text-lg sm:text-xl font-semibold mb-3 sm:mb-4">Genera Articolo con AI</h2>
            <div className="space-y-3 sm:space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">Prompt / Argomento</label>
                <textarea
                  value={aiParams.prompt}
                  onChange={(e) => setAiParams({ ...aiParams, prompt: e.target.value })}
                  rows={3}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                  placeholder="Descrivi l'argomento dell'articolo"
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700">Numero Paragrafi</label>
                  <input
                    type="number"
                    min={1}
                    value={aiParams.paragraphs}
                    onChange={(e) => setAiParams({ ...aiParams, paragraphs: parseInt(e.target.value) })}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Parole per Paragrafo</label>
                  <input
                    type="number"
                    min={10}
                    value={aiParams.wordsPerParagraph}
                    onChange={(e) => setAiParams({ ...aiParams, wordsPerParagraph: parseInt(e.target.value) })}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700">Tono</label>
                  <select
                    value={aiParams.tone}
                    onChange={(e) => setAiParams({ ...aiParams, tone: e.target.value })}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                  >
                    <option>Neutrale</option>
                    <option>Formale</option>
                    <option>Informale</option>
                    <option>Persuasivo</option>
                    <option>Umoristico</option>
                    <option>Serio</option>
                    <option>Ottimistico</option>
                    <option>Motivazionale</option>
                    <option>Rispettoso</option>
                    <option>Assertivo</option>
                    <option>Conversazione</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Persona</label>
                  <select
                    value={aiParams.persona}
                    onChange={(e) => setAiParams({ ...aiParams, persona: e.target.value })}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                  >
                    <option>Copywriter</option>
                    <option>Giornalista</option>
                    <option>Blogger</option>
                    <option>Esperto di settore</option>
                    <option>Freelance</option>
                    <option>Accademico</option>
                    <option>Saggista</option>
                    <option>Attivista</option>
                    <option>Divulgatore Scientifico</option>
                    <option>Insegnante</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Fonte (URL) opzionale</label>
                <input
                  type="text"
                  value={aiParams.sourceUrl}
                  onChange={(e) => setAiParams({ ...aiParams, sourceUrl: e.target.value })}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary focus:ring-primary text-sm"
                  placeholder="https://esempio.com/articolo"
                />
              </div>
            </div>
            <div className="mt-4 sm:mt-6 flex flex-col sm:flex-row justify-end space-y-2 sm:space-y-0 sm:space-x-4">
              <button
                type="button"
                onClick={() => setShowAiModal(false)}
                className="w-full sm:w-auto px-3 sm:px-4 py-2 border border-gray-300 rounded-md text-sm font-medium bg-white hover:bg-gray-50"
              >
                Annulla
              </button>
              <button
                type="button"
                onClick={handleGenerateAi}
                disabled={aiLoading}
                className={`w-full sm:w-auto px-3 sm:px-4 py-2 bg-primary text-white rounded-md text-sm font-medium hover:bg-primary-dark ${aiLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                {aiLoading ? (
                  <>
                    <svg className="animate-spin -ml-1 mr-2 h-4 w-4 sm:h-5 sm:w-5 text-white inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Generando...
                  </>
                ) : 'Genera'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Test function to verify the markdown image syntax is correctly formed and parseable
function testMarkdownImageParsing(markdown: string) {
  // Split the markdown into paragraphs
  const paragraphs = markdown.split('\n\n');
  
  console.log(`Testing ${paragraphs.length} paragraphs for image syntax`);
  
  // Test each paragraph for image syntax
  paragraphs.forEach((paragraph, index) => {
    // Check if paragraph is an image (using the same regex as in [slug].astro)
    const imageMatch = paragraph.match(/!\[.*?\]\((.*?)\)(\|(.*?))?/);
    if (imageMatch) {
      const imageUrl = imageMatch[1];
      const fullMatch = imageMatch[0];
      const captionPart = imageMatch[2] || '';
      const caption = imageMatch[3] ? imageMatch[3].trim() : '';
      
      console.log(`Image test #${index + 1} - Valid image markdown found:`, {
        originalText: paragraph,
        fullMatch: fullMatch,
        captionPart: captionPart,
        extractedUrl: imageUrl,
        extractedCaption: caption,
        // This is what [slug].astro would generate:
        htmlOutput: `<figure class="my-8">
          <img src="${imageUrl}" alt="Article image" class="w-full rounded-lg shadow-md" />
          ${caption ? `<figcaption class="text-center text-sm text-gray-500 mt-2">${caption}</figcaption>` : ''}
        </figure>`
      });
    }
    
    // Check if paragraph contains links
    const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
    let linkMatch;
    while ((linkMatch = linkRegex.exec(paragraph)) !== null) {
      const linkText = linkMatch[1];
      const linkUrl = linkMatch[2];
      
      console.log(`Link test in paragraph #${index + 1} - Valid link markdown found:`, {
        originalText: linkMatch[0],
        extractedText: linkText,
        extractedUrl: linkUrl,
        // This is what should be generated:
        htmlOutput: `<a href="${linkUrl}" target="_blank">${linkText}</a>`
      });
    }
  });
}
