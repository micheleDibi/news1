/**
 * Web Bot Auth — directory delle chiavi pubbliche (RFC 9421 HTTP Message
 * Signatures). Serve edunews24 a identificarsi crittograficamente quando
 * invia richieste come bot/agente verso altri siti: la directory JWKS viene
 * servita dal middleware su /.well-known/http-message-signatures-directory e i
 * siti riceventi la usano per verificare le richieste firmate.
 *
 * Qui c'e' SOLO la chiave PUBBLICA. La chiave privata Ed25519 corrispondente
 * vive in .env (WEB_BOT_AUTH_PRIVATE_KEY), gitignored, e non e' necessaria al
 * checker: serve solo quando/se si firmeranno davvero le richieste in uscita.
 */
export const WEB_BOT_AUTH_DIRECTORY_PATH = '/.well-known/http-message-signatures-directory';

export const WEB_BOT_AUTH_CONTENT_TYPE = 'application/http-message-signatures-directory+json';

// JWKS con la chiave pubblica Ed25519. kid = thumbprint RFC 7638.
export const WEB_BOT_AUTH_JWKS = {
  keys: [
    {
      kty: 'OKP',
      crv: 'Ed25519',
      x: 'NeL8VwYl4wW4UPz4Bv_hj2SbiPqaZt5kdm4kIf9yHV0',
      kid: 'W2492ZD4ioSeUuBFzbh_jZMt9MdBOiKP0aM-tIzQvME',
      nbf: 1785235338,
    },
  ],
};
