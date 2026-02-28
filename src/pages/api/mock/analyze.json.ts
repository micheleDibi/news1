import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request }) => {
  try {
    const body = await request.json();
    const { links } = body;
    
    console.log(`Mock analyze request for links: ${JSON.stringify(links)}`);
    
    // Simulate a delay
    await new Promise(resolve => setTimeout(resolve, 1500));
    
    // Return mock data
    return new Response(JSON.stringify({
      success: true,
      summarized: {
        id: Math.floor(Math.random() * 1000),
        title: 'Sample Summarized Article',
        url: links[0],
        summary: 'This is a sample summary of the article. It contains the key points and main ideas from the original content.',
        facts: [
          'Sample fact 1',
          'Sample fact 2',
          'Sample fact 3'
        ],
        category: 'News',
        created_at: new Date().toISOString()
      }
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  } catch (error) {
    console.error('Error in mock analyze endpoint:', error);
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