import type { APIContext } from 'astro';
import { refreshCategories } from '../../lib/categories';
import { supabase } from '../../lib/supabase'; // Import for auth check

export async function POST({ request }: APIContext) {
  // --- Authentication Check --- 
  const token = request.headers.get('Authorization')?.replace('Bearer ', '');
  let isAuthorized = false;

  if (token) {
    const { data: { user }, error: userError } = await supabase.auth.getUser(token);
    if (user && !userError) {
      const { data: profile, error: profileError } = await supabase
        .from('profiles')
        .select('role')
        .eq('id', user.id)
        .single();
      
      // Check if user has admin or director role
      if (profile && !profileError && (profile.role === 'admin' || profile.role === 'direttore')) {
        isAuthorized = true;
      }
    }
  }

  if (!isAuthorized) {
    return new Response(JSON.stringify({ success: false, error: 'Unauthorized' }), {
      status: 401, 
      headers: { 'Content-Type': 'application/json' }
    });
  }
  // --- End Authentication Check ---

  try {
    console.log('API endpoint /api/refresh-categories called.');
    await refreshCategories();
    console.log('Categories refresh triggered successfully via API.');
    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error('Error calling refreshCategories from API:', error);
    return new Response(JSON.stringify({ success: false, error: 'Failed to refresh categories' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// Optional: Handle other methods like GET
export function ALL({ request }: APIContext) {
    if (request.method !== 'POST') {
        return new Response(null, { status: 405, statusText: 'Method Not Allowed' });
    }
    // If it's POST, it will be handled by the POST function above
    // This primarily serves to return 405 for non-POST methods
}
