import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';

export const get: APIRoute = async ({ request }) => {
  try {
    // Get session to verify authentication
    const { data: { session } } = await supabase.auth.getSession();
    
    if (!session) {
      return new Response(
        JSON.stringify({ success: false, error: 'Not authenticated' }),
        { status: 401 }
      );
    }
    
    // Get user role to verify authorization
    const { data: profile, error: profileError } = await supabase
      .from('profiles')
      .select('role')
      .eq('id', session.user.id)
      .single();
    
    if (profileError || !(profile?.role === 'docente' || profile?.role === 'insegnante')) {
      return new Response(
        JSON.stringify({ success: false, error: 'Not authorized' }),
        { status: 403 }
      );
    }
    
    // Get profile table schema
    const { data: tableInfo, error: tableError } = await supabase
      .rpc('get_schema_info', { table_name: 'profiles' });
    
    if (tableError) {
      return new Response(
        JSON.stringify({ success: false, error: tableError.message }),
        { status: 500 }
      );
    }
    
    // Attempt a direct query to show structure
    const { data: sampleData, error: sampleError } = await supabase
      .from('profiles')
      .select('*')
      .limit(1)
      .single();
    
    return new Response(
      JSON.stringify({ 
        success: true, 
        schema: tableInfo,
        sample: sampleData,
        sampleError: sampleError || null
      }),
      { status: 200 }
    );
    
  } catch (error) {
    console.error('API: Unexpected error debugging schema:', error);
    return new Response(
      JSON.stringify({ success: false, error: 'Internal server error' }),
      { status: 500 }
    );
  }
}; 