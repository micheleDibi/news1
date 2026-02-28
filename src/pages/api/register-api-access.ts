import type { APIRoute } from 'astro';
import { supabase } from '../../lib/supabase';
import bcrypt from 'bcryptjs';

// Function to generate a random verification code
function generateVerificationCode(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  let result = '';
  for (let i = 0; i < 8; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

export const POST: APIRoute = async ({ request }) => {
  try {
    const body = await request.json();
    
    // Validate required fields
    const requiredFields = ['name', 'email', 'phone', 'siteName', 'siteUrl'];
    const missingFields = requiredFields.filter(field => !body[field]);
    
    if (missingFields.length > 0) {
      return new Response(JSON.stringify({ 
        error: `Missing required fields: ${missingFields.join(', ')}` 
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Validate URL format
    try {
      const url = new URL(body.siteUrl);
      if (!['http:', 'https:'].includes(url.protocol)) {
        throw new Error('Invalid protocol');
      }
    } catch {
      return new Response(JSON.stringify({ 
        error: 'Invalid URL format. Must be a valid HTTP or HTTPS URL.' 
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Check if email or URL already exists
    const { data: existingRequest } = await supabase
      .from('api_access_requests')
      .select('email, site_url')
      .or(`email.eq.${body.email},site_url.eq.${body.siteUrl}`)
      .single();

    if (existingRequest) {
      return new Response(JSON.stringify({ 
        error: 'A request with this email or URL already exists. Please contact support if you need to update your request.' 
      }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Generate verification code and hash it
    const verificationCode = generateVerificationCode();
    const hashedVerificationCode = await bcrypt.hash(verificationCode, 12);

    // Insert the registration request
    const { data, error } = await supabase
      .from('api_access_requests')
      .insert({
        name: body.name,
        email: body.email,
        phone: body.phone,
        site_name: body.siteName,
        site_url: body.siteUrl,
        verification_code_hash: hashedVerificationCode,
        status: 'pending',
        requested_at: new Date().toISOString()
      })
      .select()
      .single();

    if (error) {
      console.error('Error inserting API access request:', error);
      return new Response(JSON.stringify({ 
        error: 'Failed to submit registration request. Please try again.' 
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // TODO: Send notification email to admin
    // TODO: Send confirmation email to user

    return new Response(JSON.stringify({ 
      message: 'API access request submitted successfully',
      requestId: data.id,
      verificationCode: verificationCode // Send plain text code to user (only this once)
    }), {
      status: 201,
      headers: { 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Server error processing API registration:', error);
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