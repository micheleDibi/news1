export const prerender = false;

import type { APIRoute } from 'astro';
import nodemailer from 'nodemailer';

export const POST: APIRoute = async ({ request }) => {
  try {
    const body = await request.json();
    const { nome, cognome, cellulare, email, note } = body;

    // Validate required fields
    if (!nome || !cognome || !email || !note) {
      return new Response(
        JSON.stringify({ error: 'Nome, cognome, email e messaggio sono obbligatori' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // Email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      return new Response(
        JSON.stringify({ error: 'Email non valida' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    // Configure nodemailer transporter
    const transporter = nodemailer.createTransport({
      host: import.meta.env.SMTP_HOST,
      port: parseInt(import.meta.env.SMTP_PORT || '587'),
      secure: import.meta.env.SMTP_SECURE === 'true', // true for 465, false for other ports
      auth: {
        user: import.meta.env.SMTP_USER,
        pass: import.meta.env.SMTP_PASS,
      },
    });

    // Email content
    const mailOptions = {
      from: `"${nome} ${cognome}" <${import.meta.env.SMTP_FROM || 'redazione@edunews24.it'}>`,
      to: 'redazione@edunews24.it',
      replyTo: email,
      subject: `Nuovo messaggio da ${nome} ${cognome}`,
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h2 style="color: #2563eb; border-bottom: 2px solid #2563eb; padding-bottom: 10px;">
            Nuovo Messaggio di Contatto
          </h2>
          
          <div style="margin: 20px 0;">
            <p><strong>Nome:</strong> ${nome}</p>
            <p><strong>Cognome:</strong> ${cognome}</p>
            ${cellulare ? `<p><strong>Cellulare:</strong> ${cellulare}</p>` : ''}
            <p><strong>Email:</strong> ${email}</p>
          </div>
          
          <div style="background-color: #f3f4f6; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <p style="margin: 0;"><strong>Messaggio:</strong></p>
            <p style="margin: 10px 0 0 0; white-space: pre-wrap;">${note}</p>
          </div>
          
          <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
          
          <p style="color: #6b7280; font-size: 12px;">
            Questo messaggio è stato inviato tramite il form di contatto di EduNews24.
          </p>
        </div>
      `,
      text: `
Nuovo Messaggio di Contatto

Nome: ${nome}
Cognome: ${cognome}
${cellulare ? `Cellulare: ${cellulare}` : ''}
Email: ${email}

Messaggio:
${note}

---
Questo messaggio è stato inviato tramite il form di contatto di EduNews24.
      `.trim(),
    };

    // Send email
    await transporter.sendMail(mailOptions);

    return new Response(
      JSON.stringify({ 
        success: true,
        message: 'Messaggio inviato con successo!' 
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );

  } catch (error) {
    console.error('Error sending contact email:', error);
    return new Response(
      JSON.stringify({ 
        error: 'Errore durante l\'invio del messaggio. Riprova più tardi.' 
      }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};
