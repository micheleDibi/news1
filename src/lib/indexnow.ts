/**
 * IndexNow integration for EduNews24
 * Notifies search engines about URL changes via the IndexNow protocol.
 */

const INDEXNOW_ENDPOINT = 'https://api.indexnow.org/indexnow';
const SITE_HOST = 'edunews24.it';

/**
 * Submits one or more URLs to IndexNow for indexing.
 * Fire-and-forget: never throws, never blocks the caller.
 */
export async function submitToIndexNow(urls: string | string[]): Promise<void> {
  const apiKey = import.meta.env.INDEXNOW_API_KEY;
  if (!apiKey) {
    console.warn('[IndexNow] INDEXNOW_API_KEY non configurata, skip notifica');
    return;
  }

  const urlList = Array.isArray(urls) ? urls : [urls];
  if (urlList.length === 0) return;

  try {
    if (urlList.length === 1) {
      // Single URL → GET request
      const params = new URLSearchParams({
        url: urlList[0],
        key: apiKey,
      });
      const res = await fetch(`${INDEXNOW_ENDPOINT}?${params}`);
      console.log(`[IndexNow] GET ${urlList[0]} → ${res.status}`);
    } else {
      // Multiple URLs → POST batch
      const body = {
        host: SITE_HOST,
        key: apiKey,
        keyLocation: `https://${SITE_HOST}/${apiKey}.txt`,
        urlList,
      };
      const res = await fetch(INDEXNOW_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      console.log(`[IndexNow] POST batch (${urlList.length} URL) → ${res.status}`);
    }
  } catch (error) {
    console.error('[IndexNow] Errore invio:', error);
  }
}
