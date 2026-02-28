import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';
import { categories } from '../../../lib/categories';
// We will need functions to generate AMP HTML parts
// import { generateAmpHtml } from '../../../lib/amp-generator'; 

// Define a type for category objects
interface Category {
  slug: string;
  name: string; // Assuming name property exists based on usage elsewhere
  color: string; 
  // Add other properties if available in your categories definition
}

// Define a type for article objects based on usage
interface Article {
  id: number | string; // Or appropriate type from Supabase schema
  title: string;
  slug: string;
  category_slug: string;
  category: string;
  image_url: string;
  published_at: string; // Supabase typically returns ISO string
  updated_at?: string | null; // Optional
  excerpt: string;
  content: string;
  audio_url?: string | null; // Optional
  isdraft: boolean; // Though we filter for false
  tags?: string[]; // Based on original astro file usage
  // Add other fields if needed
}

export const GET: APIRoute = async ({ params }) => {
  const { category: categorySlug, slug } = params;

  if (!categorySlug || !slug) {
    return new Response('Category or Slug missing', { status: 400 });
  }

  // 1. Fetch article data - Specify expected type Article
  const { data: article, error: articleError } = await supabase
    .from('articles')
    .select('*') // Consider selecting only necessary fields explicitly
    .eq('category_slug', categorySlug)
    .eq('slug', slug)
    .eq('isdraft', false)
    .single<Article>(); // Assume Supabase client allows specifying type

  if (articleError || !article) {
    console.error('Error fetching article or article not found:', articleError?.message);
    // Redirect to a 404 page or return a 404 response
    // For AMP, returning a 404 status might be better than redirecting
    return new Response('Article not found', { status: 404 });
  }

  // Find category data - Use the defined Category type
  const categoryData: Category | undefined = categories.find((c: Category) => c.slug === categorySlug);

  // 2. Fetch related articles (optional for first pass, but good for parity)
  const { data: relatedArticles, error: relatedError } = await supabase
    .from('articles')
    .select('title, slug, category_slug, image_url, published_at') // Select only needed fields
    .eq('category', article.category)
    .eq('isdraft', false)
    .neq('id', article.id)
    .order('published_at', { ascending: false })
    .limit(3)
    .returns<Article[]>(); // Assume Supabase client allows specifying array type

  if (relatedError) {
    console.error('Error fetching related articles:', relatedError.message);
    // Continue without related articles if there's an error
  }
  
  // 3. Format content for AMP
  const formattedAmpContent = formatContentForAmp(article.content);

  // 4. Generate Structured Data
  const structuredData = generateArticleStructuredDataForAmp(article); 
  const breadcrumbStructuredData = generateBreadcrumbStructuredDataForAmp(article); 

  // 5. Generate AMP CSS (Updated with footer and layout styles)
  const ampCss = generateAmpCss(categoryData); 

  // 6. Construct the full AMP HTML with updated header and footer
  const ampHtml = `
<!doctype html>
<html ⚡ lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,minimum-scale=1,initial-scale=1">
  <title>${escapeHtml(article.title)} - EduNews24 AMP</title>
  <link rel="canonical" href="https://edunews24.it/${article.category_slug}/${article.slug}">
  
  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Funnel+Sans:ital,wght@0,300..800;1,300..800&display=swap" rel="stylesheet">

  <!-- Base AMP JS -->
  <script async src="https://cdn.ampproject.org/v0.js"></script>

  <!-- Component Scripts (Included directly) -->

  <!-- Structured Data -->
  <script type="application/ld+json">${JSON.stringify(structuredData)}</script>
  <script type="application/ld+json">${JSON.stringify(breadcrumbStructuredData)}</script>

  <!-- AMP Boilerplate and CSS -->
  <style amp-boilerplate>body{-webkit-animation:-amp-start 8s steps(1,end) 0s 1 normal both;-moz-animation:-amp-start 8s steps(1,end) 0s 1 normal both;-ms-animation:-amp-start 8s steps(1,end) 0s 1 normal both;animation:-amp-start 8s steps(1,end) 0s 1 normal both}@-webkit-keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}@-moz-keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}@-ms-keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}@-o-keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}@keyframes -amp-start{from{visibility:hidden}to{visibility:visible}}</style><noscript><style amp-boilerplate>body{-webkit-animation:none;-moz-animation:none;-ms-animation:none;animation:none}</style></noscript>
  <style amp-custom>
    ${ampCss}
  </style>
</head>
<body class="font-funnel">
  
  <header class="main-header">
    <div class="logo-container">
      <a href="/" aria-label="EduNews24 Home">
        <svg width="209" height="41" viewBox="0 0 209 41" fill="none" xmlns="http://www.w3.org/2000/svg">
          {/* Extracted from Header.astro - Use appropriate classes/styles if animations needed */}
          <g class="logo-edu">
            <rect width="85.7172" height="38.335" transform="matrix(1 0 -0.13191 0.991262 5.05679 3)" fill="#064C99"/>
            <path d="M20.1533 23.9583L19.4479 27.7939H31.0279L30.1706 32.4558H12.9806L16.8438 11.448H33.7338L32.8928 16.0214H21.6128L20.978 19.4735H30.878L30.0533 23.9583H20.1533ZM37.088 11.448H46.088C49.408 11.448 51.7716 12.3529 53.1788 14.1625C54.586 15.9722 54.9785 18.5686 54.3564 21.9519C53.7451 25.2762 52.4394 27.8628 50.4394 29.7118C48.443 31.5411 45.8448 32.4558 42.6448 32.4558H33.2248L37.088 11.448ZM39.6866 27.8235H42.5366C45.9566 27.8235 48.0265 25.8663 48.7464 21.9519C49.1189 19.9259 48.9539 18.4309 48.2511 17.4671C47.572 16.4836 46.2924 15.9918 44.4124 15.9918H41.8624L39.6866 27.8235ZM64.3984 33.1344C61.4584 33.1344 59.3232 32.4558 57.9928 31.0985C56.6624 29.7413 56.2305 27.7939 56.6971 25.2565L59.2364 11.448H64.8464L62.3017 25.286C61.8929 27.5087 62.8786 28.6201 65.2586 28.6201C67.6186 28.6201 69.0029 27.5087 69.4117 25.286L71.9564 11.448H77.5664L75.0271 25.2565C74.5569 27.8136 73.407 29.7708 71.5774 31.128C69.7514 32.4656 67.3584 33.1344 64.3984 33.1344Z" fill="white"/>
          </g>
          <g class="logo-news24">
            <rect x="0.901028" y="0.99509" width="124.417" height="28.148" transform="matrix(1 0 -0.0989724 0.99509 82.0823 7.00489)" fill="white" stroke="#064C99" stroke-width="2"/>
            <path d="M109.202 22.9167L110.226 14.7003H113.906L112.144 28.8308H108.404L104.484 20.6542L103.464 28.8308H99.7638L101.526 14.7003H105.226L109.202 22.9167ZM119.1 23.1151L118.778 25.6951H126.498L126.107 28.8308H114.647L116.409 14.7003H127.669L127.285 17.7765H119.765L119.476 20.0985H126.076L125.7 23.1151H119.1ZM142.25 20.9122L144.605 14.7003H148.345L142.443 28.8308H138.843L138.069 19.8008L135.123 28.8308H131.443L129.065 14.7003H132.845L133.65 20.9122L133.892 24.2662L134.89 20.9122L137.005 14.7003H140.445L141.05 20.9122L141.2 24.2067L142.25 20.9122ZM153.944 29.2873C152.037 29.2873 150.591 28.8573 149.605 27.9973C148.62 27.1241 148.188 25.887 148.308 24.286H152.008C151.933 25.6356 152.729 26.3104 154.395 26.3104C155.849 26.3104 156.634 25.8407 156.751 24.9013C156.797 24.5308 156.699 24.2464 156.457 24.0479C156.231 23.8362 155.82 23.651 155.227 23.4922L152.508 22.8373C150.126 22.2683 149.067 20.9254 149.331 18.8085C149.493 17.5119 150.099 16.4468 151.15 15.6133C152.2 14.7797 153.665 14.3629 155.545 14.3629C157.345 14.3629 158.703 14.7599 159.617 15.5537C160.533 16.3343 160.941 17.4457 160.841 18.8879H157.221C157.2 17.7765 156.516 17.2208 155.169 17.2208C154.582 17.2208 154.101 17.3399 153.724 17.578C153.363 17.803 153.158 18.1073 153.111 18.491C153.036 19.0863 153.438 19.4965 154.317 19.7214L157.153 20.3962C159.715 21.018 160.859 22.4337 160.583 24.6433C160.402 26.0987 159.72 27.2365 158.537 28.0568C157.355 28.8771 155.824 29.2873 153.944 29.2873ZM178.666 28.8308H167.386C167.542 27.5739 167.947 26.5221 168.599 25.6753C169.248 24.855 170.361 23.9487 171.938 22.9564L174.332 21.4083C174.939 21.0247 175.378 20.6608 175.648 20.3168C175.931 19.9728 176.099 19.5825 176.154 19.1459C176.225 18.577 176.107 18.1337 175.8 17.8162C175.494 17.4854 175.041 17.32 174.441 17.32C173.081 17.32 172.303 18.1073 172.107 19.6817L172.07 19.9794H168.69L168.744 19.5428C168.947 17.9154 169.586 16.6453 170.66 15.7323C171.733 14.8194 173.15 14.3629 174.91 14.3629C176.59 14.3629 177.873 14.7665 178.759 15.5736C179.657 16.3939 180.018 17.5119 179.841 18.9276C179.727 19.8405 179.385 20.6608 178.814 21.3885C178.257 22.1162 177.417 22.8108 176.294 23.4724L173.641 25.0204C173.136 25.3247 172.851 25.5827 172.784 25.7944H179.044L178.666 28.8308ZM192.971 14.6805L191.929 23.0357L194.014 22.996L193.665 25.7944L191.572 25.7348L191.183 28.8507H187.703L188.092 25.7348L181.505 25.7944L181.906 22.5793L189.331 14.6805H192.971ZM184.669 23.0357H188.429L188.988 18.5505H188.928L184.669 23.0357Z" fill="#064C99"/>
          </g>
        </svg>
      </a>
    </div>
  </header>

  <main class="container">
    <nav aria-label="breadcrumb">
      <ol class="breadcrumb">
        <li><a href="/">Home</a></li>
        <li><a href="/${article.category_slug}">${escapeHtml(article.category)}</a></li>
        <li aria-current="page">${escapeHtml(article.title)}</li> 
      </ol>
    </nav>

    <article>
      <amp-img
        src="${article.image_url}"
        alt="${escapeHtml(article.title)}"
        width="16" 
        height="9" 
        layout="responsive" 
      ></amp-img>

      <div class="article-meta">
        <a href="/category/${article.category_slug}" class="category-badge" style="background-color: ${getHexColor(categoryData?.color, '#064C99')};">
          ${escapeHtml(article.category)}
        </a>
        <time datetime="${new Date(article.published_at).toISOString()}">
          ${new Date(article.published_at).toLocaleDateString('en-GB')}
        </time>
      </div>

      <h1>${escapeHtml(article.title)}</h1>

      <p class="excerpt">${escapeHtml(article.excerpt)}</p>

      <div class="article-content">
        ${formattedAmpContent} 
      </div>

      <div class="published-date">
        Pubblicato il: ${new Date(article.published_at).toLocaleString('it-IT', { day: 'numeric', month: 'long', year: 'numeric', hour: 'numeric', minute: 'numeric' })}
      </div>
    </article>

    ${relatedArticles && relatedArticles.length > 0 ? `
      <section class="related-articles">
        <h2>Articoli Correlati</h2>
        <ul>
          ${relatedArticles.map((related: Article) => { 
            const relatedCategoryData: Category | undefined = categories.find((c: Category) => c.slug === related.category_slug); 
            const relatedHexColor = getHexColor(relatedCategoryData?.color, '#ccc');
            return `
            <li>
              <a href="/amp/${related.category_slug}/${related.slug}">
                <amp-img 
                  src="${related.image_url}" 
                  alt="${escapeHtml(related.title)}" 
                  width="100" 
                  height="75" 
                  layout="fixed" 
                ></amp-img>
                <div class="related-content">
                  <time datetime="${new Date(related.published_at).toISOString()}">
                    ${new Date(related.published_at).toLocaleDateString('en-GB')}
                  </time>
                  <h3 style="border-left-color: ${relatedHexColor};">${escapeHtml(related.title)}</h3>
                </div>
              </a>
            </li>
          `}).join('')}
        </ul>
      </section>
    ` : ''}

  </main>

  <footer class="site-footer">
    <div class="footer-container">
      <!-- Motto -->
      <div class="footer-motto">
        <p>EduNews24 - Il portale online gratuito con tante notizie culturali provenienti dal mondo della scuola, dell'università, della ricerca scientifica e della tecnologia. Focus sui bandi di concorso, selezione del personale ed interpelli, con ricerca gratuita.</p>
      </div>
      
      <!-- Separator -->
      <div class="footer-separator"></div>
      
      <!-- Columns -->
      <div class="footer-columns">
        <!-- Left Column -->
        <div class="footer-column footer-column-left">
          <p class="footer-company-title">Redazione EduNews24.it</p>
          <p>Universo S.r.l. ©2022-${new Date().getFullYear()}. Tutti i diritti riservati.</p>
          <p>P.IVA. 03930330794, Via del Tritone 132, 00187 Roma</p>
          <p>Depositata al Tribunale di Lamezia Terme(CZ) - Prot.llo 189/2025 in data 3 Marzo 2025.</p>
          <p>Iscrizione ROC Pratica n° 1436921 - Direttore Responsabile: Dott. Torchia Antonello | <a href="/privacy" class="footer-link">Privacy</a> | <a href="/chi-siamo" class="footer-link">Chi Siamo</a></p>
        </div>

        <!-- Right Column -->
        <div class="footer-column footer-column-right">
          <div class="footer-contact">
            <p class="footer-company-title">Universo S.r.l.</p>
            <p>Redazione EduNews24.it</p>
            <p>Email: redazione@edunews24.it</p>
          </div>
          
          <!-- Social Icons -->
          <div class="footer-social-icons">
             
            <a href="https://www.facebook.com/EduNews24.it" aria-label="Facebook" class="social-icon">
              <svg viewBox="0 0 24 24"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>
            </a>
            <a href="#" aria-label="Twitter" class="social-icon">
              <svg viewBox="0 0 24 24"><path d="M23.953 4.57a10 10 0 01-2.825.775 4.958 4.958 0 002.163-2.723c-.951.555-2.005.959-3.127 1.184a4.92 4.92 0 00-8.384 4.482C7.69 8.095 4.067 6.13 1.64 3.162a4.822 4.822 0 00-.666 2.475c0 1.71.87 3.213 2.188 4.096a4.904 4.904 0 01-2.228-.616v.06a4.923 4.923 0 003.946 4.827 4.996 4.996 0 01-2.212.085 4.936 4.936 0 004.604 3.417 9.867 9.867 0 01-6.102 2.105c-.39 0-.779-.023-1.17-.067a13.995 13.995 0 007.557 2.209c9.053 0 13.998-7.496 13.998-13.985 0-.21 0-.42-.015-.63A9.935 9.935 0 0024 4.59z"/></svg>
            </a>
            <a href="https://www.instagram.com/edunews24.it/" aria-label="Instagram" class="social-icon">
              <svg viewBox="0 0 24 24"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg>
            </a>
            <a href="#" aria-label="YouTube" class="social-icon">
               <svg viewBox="0 0 24 24"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
            </a>
          </div>
        </div>
      </div>
    </div>
  </footer>

</body>
</html>
  `;

  return new Response(ampHtml, {
    status: 200,
    headers: {
      'Content-Type': 'text/html; charset=utf-8', 
    },
  });
};

// --- Helper Functions ---

// Basic HTML escaping function
function escapeHtml(unsafe: string): string {
    if (!unsafe) return '';
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

// --- Color Name to Hex Mapping ---
// Based on src/pages/admin/categories/index.astro (with corrections)
const tailwindColorMap: { [key: string]: string } = {
  'sport-500': '#00529F',
  'calcio': '#4CAF50',
  'motori': '#FF9800',
  'tennis': '#2196F3',
  'cultura': '#3F51B5',
  'lavoro': '#009688',
  'bandi': '#795548',
  'red-500': '#ef4444',
  'blue-500': '#3b82f6',
  'green-500': '#22c55e',
  // Add any others if necessary
  // Default blue used elsewhere as fallback:
  'primary-blue': '#064C99' // Added for consistency if needed
};

// Function to get hex color, falling back if name not found or already hex
function getHexColor(colorName: string | undefined | null, fallbackColor: string): string {
  if (colorName && tailwindColorMap[colorName]) {
    return tailwindColorMap[colorName];
  }
  // If it's already a valid hex code, return it
  if (colorName && /^#[0-9A-F]{6}$/i.test(colorName)) {
     return colorName;
  }
  // If it's potentially a valid named CSS color (basic check)
  // Note: This is less likely given the context but could be a fallback
  // if (colorName && /^[a-zA-Z]+$/.test(colorName)) {
  //    return colorName; 
  // }
  return fallbackColor; // Use provided fallback otherwise
}
// --- End Color Mapping ---

// Function to format markdown content to AMP HTML
function formatContentForAmp(content: string): string {
  if (!content) return '';

  return content
    .split('\n\n')
    .map((paragraph: string) => paragraph.trim())
    .filter((paragraph: string) => paragraph.length > 0)
    .map((paragraph: string) => {
      // Headers
      if (paragraph.startsWith('# ')) {
        return `<h2>${escapeHtml(paragraph.replace('# ', ''))}</h2>`;
      }
      if (paragraph.startsWith('## ')) {
        return `<h3>${escapeHtml(paragraph.replace('## ', ''))}</h3>`;
      }
      if (paragraph.startsWith('### ')) {
        return `<h4>${escapeHtml(paragraph.replace('### ', ''))}</h4>`;
      }
      
      // AMP Image with Figure and Figcaption
      const imageMatch = paragraph.match(/!\[(.*?)\]\((.*?)\)(\|(.*?))?/);
      if (imageMatch) {
        const altText = escapeHtml(imageMatch[1] || 'Article image');
        const imageUrl = imageMatch[2]; // Don't escape URL src
        const caption = imageMatch[4] ? escapeHtml(imageMatch[4].trim()) : '';
        // Using responsive layout. Ensure images have intrinsic aspect ratio or provide fixed dimensions.
        return `<figure>
          <amp-img src="${imageUrl}" alt="${altText}" width="16" height="9" layout="responsive"></amp-img>
          ${caption ? `<figcaption>${caption}</figcaption>` : ''}
        </figure>`;
      }
      
      // Process links first to avoid formatting inside URLs
      paragraph = paragraph.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, url) => {
          // Basic validation/sanitization might be needed for url
          return `<a href="${url}" target="_blank" rel="noopener noreferrer">${escapeHtml(text)}</a>`;
      });

      // Bold
      paragraph = paragraph.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      // Italic - improved regex to handle word boundaries more carefully
      paragraph = paragraph.replace(/(?<!\S)_(.*?)_(?!\S)/g, '<em>$1</em>');
      
      // Default Paragraph - check if it was already converted
      if (!paragraph.startsWith('<h') && !paragraph.startsWith('<figure>') && !paragraph.startsWith('<p>')) {
           // Apply inline formats again (simple approach)
           let processedParagraph = paragraph; 
           processedParagraph = processedParagraph.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
           processedParagraph = processedParagraph.replace(/(?<!\S)_(.*?)_(?!\S)/g, '<em>$1</em>');
           // Wrap in <p> only if it doesn't look like already processed HTML block
           return `<p>${processedParagraph}</p>`; 
      } else {
           // Already converted to h2/h3/h4/figure or contains complex HTML from link replacement potentially
           return paragraph;
      }
    })
    .join('\n');
}

// Adapt from lib/seo.ts or implement - Use Article type
function generateArticleStructuredDataForAmp(article: Article) { 
  const url = `https://edunews24.it/${article.category_slug}/${article.slug}`;
  return {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "headline": article.title,
    "image": [article.image_url], // Ensure this is absolute URL
    "datePublished": new Date(article.published_at).toISOString(),
    "dateModified": new Date(article.updated_at || article.published_at).toISOString(), 
    "author": { 
      "@type": "Organization", 
      "name": "EduNews24" 
    },
    "publisher": {
        "@type": "Organization",
        "name": "EduNews24",
        "logo": {
            "@type": "ImageObject",
            "url": "https://edunews24.it/path/to/logo.png" // Replace with actual absolute logo URL
        }
    },
    "description": article.excerpt,
    "mainEntityOfPage": {
        "@type": "WebPage",
        "@id": url
    }
  };
}

// Adapt from lib/seo.ts or implement - Use Article type
function generateBreadcrumbStructuredDataForAmp(article: Article) { 
  const siteUrl = "https://edunews24.it"; // Base URL
 return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [{
      "@type": "ListItem",
      "position": 1,
      "name": "Home",
      "item": `${siteUrl}/`
    },{
      "@type": "ListItem",
      "position": 2,
      "name": article.category,
      "item": `${siteUrl}/category/${article.category_slug}`
    },{
      "@type": "ListItem",
      "position": 3,
      "name": article.title
      // No item URL for the current page itself
    }]
  };
}

// Updated CSS Generation
function generateAmpCss(categoryData: Category | undefined): string {
  const primaryFallback = '#064C99'; // Define primary fallback
  // Use the helper function to get the hex code, defaulting to primary blue
  const categoryHexColor = getHexColor(categoryData?.color, primaryFallback); 
  
  const footerBg = '#11315c';
  const footerText = '#ffffff';
  const footerTextSecondary = '#cbd5e1'; // Tailwind gray-300 approx
  const footerBorder = '#4a5568';     // Tailwind gray-700 approx

  const baseCss = `
    /* Reset / Base */ body { margin: 0; padding: 0; background-color: #f1f3f5; color: #343a40; line-height: 1.6; font-family: 'Funnel Sans', sans-serif; } * { box-sizing: border-box; } 
    /* Layout */ .container { max-width: 800px; margin: 0 auto; padding: 1rem; } 
    main.container { background-color: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-top: 1rem; margin-bottom: 1rem; padding: 1.5rem; } 
    /* Typography */ h1, h2, h3, h4, h5, h6 { margin: 0 0 0.75em 0; line-height: 1.3; font-weight: 600; color: #212529; } h1 { font-size: 2.2rem; } h2 { font-size: 1.8rem; } h3 { font-size: 1.5rem; } h4 { font-size: 1.2rem; } p { margin-bottom: 1rem; } a { color: ${categoryHexColor}; text-decoration: none; } a:hover { text-decoration: underline; } strong { font-weight: bold; } em { font-style: italic; } time { color: #6c757d; font-size: 0.9em; } 
    /* Header */ header.main-header { background-color: #ffffff; padding: 1rem 0; border-bottom: 1px solid #e5e7eb; } .logo-container { display: flex; justify-content: center; align-items: center; max-width: 800px; margin: 0 auto; padding: 0 1rem; } .logo-container svg { display: block; max-width: 100%; height: auto; } 
    /* Components */ .breadcrumb { list-style: none; padding: 0; margin: 0 0 1.5em 0; display: flex; flex-wrap: wrap; font-size: 0.9em; } .breadcrumb li { margin-right: 0.5em; color: #6c757d; } .breadcrumb li a { color: ${categoryHexColor}; } .breadcrumb li:not(:last-child)::after { content: '>'; margin-left: 0.5em; } 
    .article-meta { margin: 1.5em 0; display: flex; align-items: center; flex-wrap: wrap; gap: 1em; } .category-badge { display: inline-block; padding: 0.3em 0.7em; font-size: 0.75rem; line-height: 1; color: white; border-radius: 0.25rem; font-weight: 600; text-transform: uppercase; background-color: ${categoryHexColor}; } a.category-badge:hover { color: white; text-decoration: none; opacity: 0.9; } 
    amp-img { max-width: 100%; height: auto; display: block; margin-bottom: 0.5em; } figure { margin: 2em 0; } figure amp-img { margin-bottom: 0; border-radius: 0.25rem; } figcaption { text-align: center; font-size: 0.9em; color: #6c757d; margin-top: 0.75em; font-style: italic;} 
    .excerpt { border-left: 4px solid ${categoryHexColor}; padding: 0.75em 1em; margin: 1.5em 0; background-color: #f8f9fa; font-style: italic; font-size: 1.1em; color: #495057; } 
    .article-content p { margin-bottom: 1.25rem; } .article-content h2 { border-bottom: 1px solid #eee; padding-bottom: 0.3em; } .article-content a { font-weight: 500; } 
    .published-date { text-align: right; margin-top: 2em; font-size: 0.9em; color: #6c757d; font-style: italic; } 
    /* Related Articles */ .related-articles { margin-top: 3em; } .related-articles h2 { border-top: 1px solid #dee2e6; padding-top: 1.5em; margin-bottom: 1.5em; } .related-articles ul { list-style: none; padding: 0; margin: 0; } .related-articles li { margin-bottom: 1.5em; padding-bottom: 1.5em; border-bottom: 1px solid #eee; } .related-articles li:last-child { border-bottom: none; margin-bottom: 0; } .related-articles a { text-decoration: none; color: inherit; display: flex; gap: 1em; align-items: flex-start; } .related-articles amp-img { flex-shrink: 0; border-radius: 0.25rem; width: 100px; height: 75px; } .related-articles .related-content { flex-grow: 1; } .related-articles h3 { font-size: 1.1em; margin: 0.1em 0 0.3em 0; font-weight: bold; line-height: 1.3; color: #212529; } .related-articles a:hover h3 { color: ${categoryHexColor}; } .related-articles time { font-size: 0.8em; color: #6c757d; display: block; margin-bottom: 0.25em; } 
    /* Basic AMP overrides */ amp-img[layout=responsive][width][height] { display: block; } 
  `;

  const footerCss = `
    /* Footer Styles */
    .site-footer { background-color: ${footerBg}; color: ${footerText}; padding: 2rem 0; margin-top: 2rem; font-size: 0.875rem; /* text-sm */ }
    .footer-container { max-width: 1100px; /* Adjust as needed, similar to container mx-auto */ margin: 0 auto; padding: 0 1rem; }
    .footer-motto { text-align: center; margin-bottom: 2rem; }
    .footer-motto p { font-size: 1.25rem; /* text-xl */ line-height: 1.6; font-weight: 500; /* font-medium */ max-width: 56rem; /* max-w-4xl */ margin: 0 auto; color: ${footerTextSecondary}; }
    .footer-separator { border-top: 1px solid ${footerBorder}; margin-bottom: 2rem; }
    .footer-columns { display: grid; gap: 2rem; }
    .footer-column p { margin-bottom: 0.75rem; color: ${footerTextSecondary}; line-height: 1.5;}
    .footer-column-left {}
    .footer-column-right { } /* Default alignment is left */
    .footer-company-title { color: ${footerText}; font-weight: 500; /* font-medium */ font-size: 1rem; /* text-base */ margin-bottom: 0.5rem;}
    .footer-contact { margin-bottom: 2rem; }
    .footer-link { color: ${footerText}; text-decoration: underline; }
    .footer-link:hover { opacity: 0.8; }
    .footer-social-icons { display: flex; gap: 1rem; }
    .footer-social-icons a { color: ${footerTextSecondary}; }
    .footer-social-icons a:hover { color: ${footerText}; }
    .social-icon svg { width: 1.5rem; height: 1.5rem; fill: currentColor; }

    /* Responsive adjustments for footer columns */
    @media (min-width: 768px) { /* md breakpoint */
      .footer-columns { grid-template-columns: repeat(2, 1fr); }
      .footer-column-right { text-align: right; } /* Align right on medium screens and up */
      .footer-social-icons { justify-content: flex-end; }
      .footer-motto p { font-size: 1.5rem; } /* text-2xl */
    }
    @media (min-width: 1024px) { /* lg breakpoint */
       .footer-motto p { font-size: 1.875rem; } /* text-3xl */
    }
  `;

  // Return combined and minified CSS
  return (baseCss + footerCss).replace(/\s\s+/g, ' ').replace(/\/\*.*?\*\//g, '').trim();
}

