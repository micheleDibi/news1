import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';

export const GET: APIRoute = async ({ request }) => {
  try {
    // Check if user is authenticated and is admin
    const authHeader = request.headers.get('authorization');
    if (!authHeader) {
      return new Response(JSON.stringify({ error: 'Authentication required' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Get current user
    const { data: { user }, error: authError } = await supabase.auth.getUser(
      authHeader.replace('Bearer ', '')
    );

    if (authError || !user) {
      return new Response(JSON.stringify({ error: 'Invalid authentication' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Check if user is admin
    const { data: profile, error: profileError } = await supabase
      .from('profiles')
      .select('role')
      .eq('id', user.id)
      .single();

    if (profileError || !profile || profile.role !== 'admin') {
      return new Response(JSON.stringify({ error: 'Admin access required' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Get all approved origins
    const { data: approvedRequests, error } = await supabase
      .from('api_access_requests')
      .select('site_url, site_name, name, email, reviewed_at')
      .eq('status', 'approved')
      .order('reviewed_at', { ascending: false });

    if (error) {
      console.error('Error fetching approved origins:', error);
      return new Response(JSON.stringify({ error: 'Failed to fetch approved origins' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const origins = approvedRequests?.map(req => ({
      origin: req.site_url,
      siteName: req.site_name,
      ownerName: req.name,
      ownerEmail: req.email,
      approvedAt: req.reviewed_at
    })) || [];

    return new Response(JSON.stringify({
      origins,
      count: origins.length
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Server error fetching approved origins:', error);
    return new Response(JSON.stringify({ error: 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}; 