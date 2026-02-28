import type { APIRoute } from 'astro';
import { supabase } from '../../lib/supabase';
import bcrypt from 'bcryptjs';

export const POST: APIRoute = async ({ request }) => {
  try {
    const body: any = await request.json();
    
    // Validate required fields
    if (!body.email || !body.verificationCode) {
      return new Response(JSON.stringify({ 
        error: 'Email and verification code are required' 
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(body.email)) {
      return new Response(JSON.stringify({ 
        error: 'Invalid email format' 
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Validate verification code format (should be 8 characters alphanumeric)
    const codeRegex = /^[A-Z0-9]{8}$/;
    if (!codeRegex.test(body.verificationCode)) {
      return new Response(JSON.stringify({ 
        error: 'Invalid verification code format' 
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // First, find the request by email to get the hashed verification code
    const { data: apiRequest, error } = await supabase
      .from('api_access_requests')
      .select('status, requested_at, site_name, site_url, verification_code_hash')
      .eq('email', body.email)
      .single();

    if (error) {
      // If no request found
      if (error.code === 'PGRST116') {
        return new Response(JSON.stringify({ 
          found: false,
          message: 'No API access request found for this email address.'
        }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        });
      }
      
      console.error('Error checking API request status:', error);
      return new Response(JSON.stringify({ 
        error: 'Failed to check request status. Please try again.' 
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Verify the provided code against the stored hash
    const isValidCode = await bcrypt.compare(body.verificationCode, apiRequest.verification_code_hash);
    
    if (!isValidCode) {
      return new Response(JSON.stringify({ 
        found: false,
        message: 'Invalid verification code for this email address.'
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Return the request status (code is valid)
    return new Response(JSON.stringify({ 
      found: true,
      status: apiRequest.status,
      siteName: apiRequest.site_name,
      siteUrl: apiRequest.site_url,
      requestedAt: apiRequest.requested_at
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Server error checking API status:', error);
    return new Response(JSON.stringify({ 
      error: 'Internal server error. Please try again later.' 
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
};

// Handle CORS preflight requests
export const OPTIONS: APIRoute = async () => {
  return new Response(null, {
    status: 200,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '86400'
    }
  });
}; 