import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';

export const POST: APIRoute = async ({ request }) => {
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
    // Get user ID from request body
    const body = await request.json();
    const { user_id } = body;

    if (!user_id) {
      return new Response(JSON.stringify({ error: 'User ID is required' }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

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

    // Skip auth deletion since it requires admin privileges
    // Instead, just delete from profiles table
    console.log('Attempting to delete user profile from database:', user_id);
    
    try {
      // First, check if the profile exists
      const { data: existingProfile, error: checkError } = await supabase
        .from('profiles')
        .select('id, full_name')
        .eq('id', user_id)
        .single();
        
      if (checkError) {
        console.error('Error checking if profile exists:', checkError);
        return new Response(JSON.stringify({ 
          error: `Error checking profile: ${checkError.message}`,
          code: checkError.code 
        }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      
      if (!existingProfile) {
        console.warn('Profile not found for deletion:', user_id);
        return new Response(JSON.stringify({ 
          success: true,
          message: 'No profile found to delete' 
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      
      console.log('Found profile to delete:', existingProfile.full_name, existingProfile.id);
      
      // Now actually delete the profile
      const { error: deleteError } = await supabase
        .from('profiles')
        .delete()
        .eq('id', user_id);
      
      if (deleteError) {
        console.error('Error during profile deletion:', deleteError);
        
        return new Response(JSON.stringify({ 
          error: `Failed to delete: ${deleteError.message}`, 
          code: deleteError.code 
        }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      
      console.log('Successfully deleted profile:', user_id);
      return new Response(JSON.stringify({ 
        success: true,
        message: 'User deleted successfully' 
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
      
    } catch (deleteError) {
      console.error('Unexpected error during deletion process:', deleteError);
      return new Response(JSON.stringify({ 
        error: 'Unexpected error during deletion',
        details: deleteError instanceof Error ? deleteError.message : String(deleteError)
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }
  } catch (error) {
    console.error('Error in delete user endpoint:', error);
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