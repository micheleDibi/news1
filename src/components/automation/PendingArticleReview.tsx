import { useState, useEffect } from 'react';

const BACKEND_URL = '';

interface NewsItem {
  id: number;
  title: string;
  facts: string[];
  context: string;
  category: string;
  location: string | null;
  published_date: string | null;
  date_scraped: string | null;
  url: string;
}

interface Props {
  newsId: string;
}

const PROGRESS_STEPS = [
  { pct: 10, msg: 'Avvio generazione...' },
  { pct: 30, msg: 'Generazione keywords SEO...' },
  { pct: 50, msg: 'Ricerca articoli correlati...' },
  { pct: 70, msg: 'Ricostruzione articolo...' },
  { pct: 85, msg: 'Finalizzazione...' },
  { pct: 95, msg: 'Quasi fatto...' },
];

export default function PendingArticleReview({ newsId }: Props) {
  const [article, setArticle] = useState<NewsItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState('');

  useEffect(() => {
    fetch(`${BACKEND_URL}/api/news/${newsId}`)
      .then(res => {
        if (!res.ok) throw new Error('Articolo non trovato');
        return res.json();
      })
      .then(data => {
        setArticle(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [newsId]);

  const handleGenerate = async () => {
    if (!article) return;
    setGenerating(true);
    setProgress(0);
    setProgressMsg('Avvio generazione...');

    // Simulate progress steps while waiting for the API
    let stepIndex = 0;
    const interval = setInterval(() => {
      if (stepIndex < PROGRESS_STEPS.length) {
        setProgress(PROGRESS_STEPS[stepIndex].pct);
        setProgressMsg(PROGRESS_STEPS[stepIndex].msg);
        stepIndex++;
      }
    }, 5000);

    try {
      // Step 1: Reconstruct with Claude
      const reconstructRes = await fetch(`${BACKEND_URL}/api/news/reconstruct/${article.id}`, {
        method: 'POST',
      });
      if (!reconstructRes.ok) throw new Error('Errore nella generazione dell\'articolo');

      setProgress(90);
      setProgressMsg('Pubblicazione bozza...');

      // Step 2: Publish as draft to Supabase via CMS API
      const publishRes = await fetch(`${BACKEND_URL}/api/news/publish/${article.id}`, {
        method: 'POST',
      });
      if (!publishRes.ok) throw new Error('Errore nella creazione della bozza');

      const publishData = await publishRes.json();
      const supabaseId = publishData?.data?.article?.id;

      clearInterval(interval);
      setProgress(100);
      setProgressMsg('Completato!');

      // Redirect to the article editor
      setTimeout(() => {
        if (supabaseId) {
          window.location.href = `/admin/articles/${supabaseId}/edit`;
        } else {
          window.location.href = '/admin/articles';
        }
      }, 500);
    } catch (err: any) {
      clearInterval(interval);
      setGenerating(false);
      setError(err.message);
    }
  };

  const handleDiscard = async () => {
    if (!article || !confirm('Sei sicuro di voler scartare questo articolo?')) return;

    try {
      const res = await fetch(`${BACKEND_URL}/api/news/${article.id}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Errore nello scarto dell\'articolo');
      window.location.href = '/admin/articles';
    } catch (err: any) {
      setError(err.message);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  if (error && !generating) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
        {error}
      </div>
    );
  }

  if (!article) return null;

  if (generating) {
    return (
      <div className="max-w-2xl mx-auto py-12">
        <div className="text-center mb-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-2">{progressMsg}</h2>
          <p className="text-sm text-gray-500">Non chiudere questa pagina</p>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-4 mb-2">
          <div
            className="bg-green-500 h-4 rounded-full transition-all duration-700 ease-in-out"
            style={{ width: `${progress}%` }}
          ></div>
        </div>
        <p className="text-center text-sm text-gray-600">{progress}%</p>
        {error && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
            {error}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <a href="/admin/articles/pending" className="text-indigo-600 hover:text-indigo-800 text-sm">
          &larr; Torna alla lista articoli
        </a>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-5 border-b border-gray-200">
          <h1 className="text-2xl font-bold text-gray-900">{article.title}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            {article.category && (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800">
                {article.category}
              </span>
            )}
            {article.location && (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                {article.location}
              </span>
            )}
            {article.date_scraped && (
              <span className="text-xs text-gray-500">
                Raccolto il {new Date(article.date_scraped).toLocaleDateString('it-IT')}
              </span>
            )}
          </div>
        </div>

        {article.context && (
          <div className="px-6 py-4 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-2">Riassunto</h3>
            <p className="text-gray-700 leading-relaxed">{article.context}</p>
          </div>
        )}

        {article.facts && article.facts.length > 0 && (
          <div className="px-6 py-4 border-b border-gray-200">
            <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-2">Punti salienti</h3>
            <ul className="space-y-2">
              {article.facts.map((fact, i) => (
                <li key={i} className="flex items-start">
                  <span className="flex-shrink-0 h-5 w-5 text-green-500 mr-2">•</span>
                  <span className="text-gray-700">{fact}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {article.url && (
          <div className="px-6 py-3 border-b border-gray-200 flex items-center gap-2">
            <span className="text-sm text-gray-500">Fonte:</span>
            <a href={article.url} target="_blank" rel="noopener noreferrer" className="text-sm text-indigo-600 hover:text-indigo-800 flex items-center gap-1">
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              {(() => { try { return new URL(article.url).hostname.replace(/^www\./, ''); } catch { return article.url; } })()}
            </a>
          </div>
        )}

        <div className="px-6 py-6 bg-gray-50 flex flex-col sm:flex-row gap-3 justify-center">
          <button
            onClick={handleGenerate}
            className="inline-flex items-center justify-center px-8 py-3 border border-transparent text-base font-bold rounded-md text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 shadow-lg"
          >
            <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Genera articolo
          </button>
          <button
            onClick={handleDiscard}
            className="inline-flex items-center justify-center px-6 py-3 border border-red-300 text-base font-medium rounded-md text-red-700 bg-white hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
          >
            Scarta articolo
          </button>
        </div>
      </div>
    </div>
  );
}
