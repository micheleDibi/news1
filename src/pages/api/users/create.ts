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
    // Get user data from request body
    const body = await request.json();
    const { 
      email,
      password,
      full_name,
      role,
      permissions
    } = body;

    if (!email || !password || !full_name) {
      return new Response(JSON.stringify({ error: 'Email, password and full name are required' }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Validate role
    const validRoles = ['admin', 'insegnante', 'docente', 'studente', 'direttore', 'redattore', 'giornalista'];
    const userRole = role || 'studente';
    
    if (!validRoles.includes(userRole)) {
      return new Response(JSON.stringify({ 
        error: `Invalid role. Must be one of: ${validRoles.join(', ')}` 
      }), {
        status: 400,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Check if the current user is admin by verifying token directly
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

    // Check admin role from profiles
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

    // Create user in auth
    const { data: authData, error: signUpError } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          full_name
        }
      }
    });

    if (signUpError) {
      console.error('Error creating user:', signUpError);
      return new Response(JSON.stringify({ error: signUpError.message }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    if (!authData.user) {
      return new Response(JSON.stringify({ error: 'Failed to create user' }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    // Create profile in database
    const { error: profileError } = await supabase
      .from('profiles')
      .insert([
        {
          id: authData.user.id,
          full_name,
          email,
          role: userRole,
          permissions: permissions || {}
        }
      ]);

    if (profileError) {
      console.error('Error creating profile:', profileError);
      
      // Try to clean up auth user if profile creation fails
      await supabase.auth.admin.deleteUser(authData.user.id);
      
      return new Response(JSON.stringify({ error: profileError.message }), {
        status: 500,
        headers: {
          'Content-Type': 'application/json'
        }
      });
    }

    return new Response(JSON.stringify({ 
      success: true,
      message: 'User created successfully',
      user: {
        id: authData.user.id,
        email: authData.user.email,
        full_name
      }
    }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  } catch (error) {
    console.error('Error in create user endpoint:', error);
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