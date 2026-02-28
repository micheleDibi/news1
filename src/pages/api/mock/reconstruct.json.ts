import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request, params }) => {
  try {
    const newsId = params.id || '123';
    
    console.log(`Mock reconstruct request for news ID: ${newsId}`);
    
    // Simulate a delay
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    // Return mock data
    return new Response(JSON.stringify({
      success: true,
      article: {
        news_id: Number(newsId),
        title: 'Sample Reconstructed Article',
        excerpt: 'This is a sample excerpt of the reconstructed article. It provides a brief overview of the content.',
        content: `
          <p>This is the first paragraph of the reconstructed article. It introduces the topic and sets the context for the reader.</p>
          
          <p>The second paragraph provides more details about the subject matter. It expands on the introduction and presents key information.</p>
          
          <p>In the third paragraph, we delve deeper into the topic. This section might include quotes, statistics, or other relevant data to support the main points.</p>
          
          <p>The fourth paragraph continues the discussion, possibly presenting different perspectives or additional information that helps the reader understand the topic more fully.</p>
          
          <p>Finally, the conclusion summarizes the main points and may offer some closing thoughts or implications of the information presented.</p>
        `,
        image_url: 'https://via.placeholder.com/800x400',
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
    console.error('Error in mock reconstruct endpoint:', error);
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