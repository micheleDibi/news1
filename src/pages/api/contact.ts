export const prerender = false;

import type { APIRoute } from 'astro';
import nodemailer from 'nodemailer';
import { logger } from '../../lib/logger';

/**
 * Escape HTML per evitare injection nel corpo email che arriva in redazione.
 * I 5 caratteri standard: & < > " '
 */
function escapeHtml(s: unknown): string {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => {
    if (c === '&') return '&amp;';
    if (c === '<') return '&lt;';
    if (c === '>') return '&gt;';
    if (c === '"') return '&quot;';
    return '&#39;';
  });
}

interface ContactContext {
  source?: string;
  bando_titolo?: string;
  bando_slug?: string;
  bando_url?: string;
}

/** Normalizza context: solo stringhe, ognuna max 500 char, dict piatto. */
function sanitizeContext(raw: unknown): ContactContext | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Record<string, unknown>;
  const out: ContactContext = {};
  const keys: (keyof ContactContext)[] = ['source', 'bando_titolo', 'bando_slug', 'bando_url'];
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === 'string' && v.length > 0) {
      out[k] = v.slice(0, 500);
    }
  }
  return Object.keys(out).length > 0 ? out : null;
}

function buildSubject(nome: string, cognome: string, ctx: ContactContext | null): string {
  if (!ctx) return `Nuovo messaggio da ${nome} ${cognome}`;
  if (ctx.source === 'bando-detail') {
    const titolo = ctx.bando_titolo ? `: ${ctx.bando_titolo}` : '';
    return `Richiesta esperto bandi${titolo}`;
  }
  if (ctx.source === 'listing-bandi') {
    return 'Richiesta esperto bandi (listing)';
  }
  return `Nuovo messaggio da ${nome} ${cognome}`;
}

/** Blocco HTML che riassume il riferimento al bando (se context presente). */
function buildContextHtml(ctx: ContactContext | null): string {
  if (!ctx) return '';
  if (ctx.source === 'bando-detail' && ctx.bando_titolo) {
    const titolo = escapeHtml(ctx.bando_titolo);
    const url = ctx.bando_url ? escapeHtml(ctx.bando_url) : '';
    const link = url
      ? `<a href="${url}" style="color:#2563eb;text-decoration:underline;">${titolo}</a>`
      : titolo;
    return `
      <div style="background-color:#eff6ff;border-left:4px solid #2563eb;padding:12px 16px;margin:20px 0;border-radius:4px;">
        <p style="margin:0 0 4px 0;color:#1e40af;font-weight:600;font-size:13px;text-transform:uppercase;letter-spacing:0.05em;">Riferimento bando</p>
        <p style="margin:0;color:#1e3a8a;font-size:15px;">${link}</p>
      </div>
    `;
  }
  if (ctx.source === 'listing-bandi') {
    return `
      <div style="background-color:#eff6ff;border-left:4px solid #2563eb;padding:12px 16px;margin:20px 0;border-radius:4px;">
        <p style="margin:0;color:#1e40af;font-weight:600;font-size:13px;">Richiesta partita dalla pagina /bandi (listing)</p>
      </div>
    `;
  }
  return '';
}

function buildContextText(ctx: ContactContext | null): string {
  if (!ctx) return '';
  if (ctx.source === 'bando-detail' && ctx.bando_titolo) {
    const url = ctx.bando_url ? ` (${ctx.bando_url})` : '';
    return `Riferimento bando: ${ctx.bando_titolo}${url}\n\n`;
  }
  if (ctx.source === 'listing-bandi') {
    return 'Richiesta partita dalla pagina /bandi (listing)\n\n';
  }
  return '';
}

export const POST: APIRoute = async ({ request }) => {
  try {
    const body = await request.json();
    const { nome, cognome, cellulare, email, note, context: rawContext } = body;

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

    const ctx = sanitizeContext(rawContext);
    const subject = buildSubject(nome, cognome, ctx);
    const contextHtml = buildContextHtml(ctx);
    const contextText = buildContextText(ctx);

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

    // Escape user input prima di inserirlo nell'HTML della mail (anti-injection).
    const safeNome = escapeHtml(nome);
    const safeCognome = escapeHtml(cognome);
    const safeCellulare = escapeHtml(cellulare);
    const safeEmail = escapeHtml(email);
    const safeNote = escapeHtml(note);

    // Email content
    const mailOptions = {
      from: `"${nome} ${cognome}" <${import.meta.env.SMTP_FROM || 'redazione@edunews24.it'}>`,
      to: 'redazione@edunews24.it',
      replyTo: email,
      subject,
      html: `
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
          <h2 style="color: #2563eb; border-bottom: 2px solid #2563eb; padding-bottom: 10px;">
            ${ctx?.source?.startsWith('bando') || ctx?.source === 'listing-bandi' ? 'Richiesta supporto bandi' : 'Nuovo Messaggio di Contatto'}
          </h2>

          ${contextHtml}

          <div style="margin: 20px 0;">
            <p><strong>Nome:</strong> ${safeNome}</p>
            <p><strong>Cognome:</strong> ${safeCognome}</p>
            ${cellulare ? `<p><strong>Cellulare:</strong> ${safeCellulare}</p>` : ''}
            <p><strong>Email:</strong> ${safeEmail}</p>
          </div>

          <div style="background-color: #f3f4f6; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <p style="margin: 0;"><strong>Messaggio:</strong></p>
            <p style="margin: 10px 0 0 0; white-space: pre-wrap;">${safeNote}</p>
          </div>

          <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">

          <p style="color: #6b7280; font-size: 12px;">
            Questo messaggio è stato inviato tramite il form di contatto di EduNews24.
          </p>
        </div>
      `,
      text: `
Nuovo Messaggio di Contatto

${contextText}Nome: ${nome}
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
    logger.error('Error sending contact email:', error);
    return new Response(
      JSON.stringify({
        error: 'Errore durante l\'invio del messaggio. Riprova più tardi.'
      }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
};
