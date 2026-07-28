/**
 * Catalogo API per la discovery da parte di agenti (RFC 9727).
 * Servito dal middleware su /.well-known/api-catalog e pubblicizzato
 * dalla homepage con `Link: </.well-known/api-catalog>; rel="api-catalog"`.
 * Elenca SOLO risorse pubbliche realmente esistenti.
 */
export const API_CATALOG_PATH = '/.well-known/api-catalog';

export const API_CATALOG_CONTENT_TYPE =
  'application/linkset+json; profile="https://www.rfc-editor.org/info/rfc9727"';

// Formato Linkset (RFC 9264).
export const API_CATALOG = {
  linkset: [
    {
      anchor: 'https://edunews24.it/.well-known/api-catalog',
      item: [
        {
          href: 'https://edunews24.it/api/search',
          title: 'Ricerca articoli EduNews24 (POST, body JSON {query})',
        },
        {
          href: 'https://edunews24.it/sitemap-index.xml',
          title: 'Sitemap index (articoli, categorie, bandi, video)',
          type: 'application/xml',
        },
      ],
    },
  ],
};
