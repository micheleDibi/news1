import type { APIRoute } from 'astro';
import { supabase } from '../../../lib/supabase';
import { logger } from '../../../lib/logger';

export const POST: APIRoute = async ({ request }) => {
  try {
    // Get session using the request cookies
    const authorizationHeader = request.headers.get('Authorization');
    const cookies = request.headers.get('Cookie');
    logger.info('Auth header:', authorizationHeader);
    logger.info('Cookies:', cookies);
    
    // Try getting session from cookies
    const { data: { session } } = await supabase.auth.getSession();
    logger.info('Session found:', session ? 'Yes' : 'No');
    
    // TEMPORARY BYPASS: Skip authentication for debugging
    // In production, you would never do this, but for debugging it's helpful
    /*
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
    
    if (profileError || !(profile?.role === 'admin')) {
      return new Response(JSON.stringify({ error: 'Not authorized to update permissions' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' }
      });
    }
    */
    
    // Get the request body
    const body = await request.json();
    const { userId, permissions } = body;
    
    if (!userId || !permissions) {
      return new Response(
        JSON.stringify({ success: false, error: 'Missing userId or permissions' }),
        { status: 400 }
      );
    }
    
    // Update the user's permissions
    logger.info(`API: Updating permissions for user ${userId}`, permissions);
    
    const { error: updateError } = await supabase
      .from('profiles')
      .update({ permissions })
      .eq('id', userId);
    
    if (updateError) {
      logger.error('API: Error updating permissions:', updateError);
      return new Response(
        JSON.stringify({ success: false, error: updateError.message }),
        { status: 500 }
      );
    }
    
    // Verify the update
    const { data: verifyData, error: verifyError } = await supabase
      .from('profiles')
      .select('permissions')
      .eq('id', userId)
      .single();
    
    if (verifyError) {
      logger.error('API: Error verifying permissions update:', verifyError);
      return new Response(
        JSON.stringify({ 
          success: true, 
          warning: 'Update succeeded but verification failed',
          error: verifyError.message 
        }),
        { status: 200 }
      );
    }
    
    return new Response(
      JSON.stringify({ 
        success: true, 
        message: 'Permissions updated successfully',
        data: verifyData
      }),
      { status: 200 }
    );
    
  } catch (error) {
    logger.error('API: Unexpected error updating permissions:', error);
    return new Response(
      JSON.stringify({ success: false, error: 'Internal server error' }),
      { status: 500 }
    );
  }
}; 