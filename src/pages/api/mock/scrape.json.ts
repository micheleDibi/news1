import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request }) => {
  try {
    const body = await request.json();
    const { url } = body;
    
    console.log(`Mock scrape request for URL: ${url}`);
    
    // Simulate a delay
    await new Promise(resolve => setTimeout(resolve, 1000));
    
    // Return mock data
    return new Response(JSON.stringify({
      success: true,
      links: [
        'https://example.com/article1',
        'https://example.com/article2',
        'https://example.com/article3',
        'https://example.com/article4',
        'https://example.com/article5',
      ]
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  } catch (error) {
    console.error('Error in mock scrape endpoint:', error);
    return new Response(JSON.stringify({ 
      success: false,
      message: error instanceof Error ? error.message : 'Unknown error'
    }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
}; 