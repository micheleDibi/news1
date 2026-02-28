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
      .select('*')
      .eq('id', session.user.id)
      .single();
    
    if (profileError || !(profile?.role === 'admin')) {
      return new Response(
        JSON.stringify({ success: false, error: 'Not authorized' }),
        { status: 403 }
      );
    }
    
    // Get a sample profile
    const { data: sampleData, error: sampleError } = await supabase
      .from('profiles')
      .select('*')
      .limit(3);
    
    if (sampleError) {
      return new Response(
        JSON.stringify({ success: false, error: sampleError.message }),
        { status: 500 }
      );
    }
    
    // Test update directly
    const testPermissions = {
      test_permission: true,
      debug_mode: true
    };
    
    const { data: updateData, error: updateError } = await supabase
      .from('profiles')
      .update({ permissions: testPermissions })
      .eq('id', session.user.id)
      .select();
    
    // Query again to verify
    const { data: verifyData, error: verifyError } = await supabase
      .from('profiles')
      .select('permissions')
      .eq('id', session.user.id)
      .single();
    
    return new Response(
      JSON.stringify({ 
        success: true, 
        samples: sampleData,
        currentUserProfile: profile,
        updateResult: updateData,
        updateError: updateError || null,
        verifyResult: verifyData,
        verifyError: verifyError || null
      }),
      { status: 200 }
    );
    
  } catch (error) {
    console.error('API: Unexpected error debugging profiles:', error);
    return new Response(
      JSON.stringify({ success: false, error: 'Internal server error' }),
      { status: 500 }
    );
  }
}; 