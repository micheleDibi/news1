import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';

export const GET: APIRoute = async ({ request }) => {
  // Check authorization
  const authHeader = request.headers.get('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    console.error('Authorization header missing or invalid', { authHeader });
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }

  // Extract the token
  const token = authHeader.split(' ')[1];
  
  try {
    // Check if the current user is admin
    // First verify the token by getting the user
    const { data: { user: tokenUser }, error: tokenError } = await supabase.auth.getUser(token);
    
    if (tokenError || !tokenUser) {
      console.error('Token validation failed', { tokenError });
      return new Response(JSON.stringify({ error: 'Invalid token' }), {
        status: 401,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    const { data: adminProfile } = await supabase
      .from('profiles')
      .select('role')
      .eq('id', tokenUser.id)
      .single();

    if (!adminProfile || adminProfile.role !== 'admin') {
      return new Response(JSON.stringify({ error: 'Admin privileges required' }), {
        status: 403,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Get all users from the profiles table
    const { data: users, error } = await supabase
      .from('profiles')
      .select('id, email, full_name, role, permissions, created_at')
      .order('created_at', { ascending: false });

    if (error) {
      console.error('Error fetching users:', error);
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    return new Response(JSON.stringify({ 
      users: users || [] 
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  } catch (error) {
    console.error('Error in list users endpoint:', error);
    return new Response(JSON.stringify({ 
      error: error instanceof Error ? error.message : 'Unknown error' 
    }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }
}; 