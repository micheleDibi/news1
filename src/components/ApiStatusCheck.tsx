import { useState } from 'react';

interface StatusResponse {
  found: boolean;
  status?: string;
  siteName?: string;
  siteUrl?: string;
  requestedAt?: string;
  message?: string;
  error?: string;
}

export default function ApiStatusCheck() {
  const [email, setEmail] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<StatusResponse | null>(null);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setResult(null);

    try {
      const response = await fetch('/api/check-api-status', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          email, 
          verificationCode: verificationCode.toUpperCase() 
        }),
      });

      const data: StatusResponse = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Errore durante la verifica dello stato');
      }

      setResult(data);
    } catch (error) {
      console.error('Errore durante la verifica:', error);
      setResult({
        found: false,
        error: error instanceof Error ? error.message : 'Errore durante la verifica dello stato'
      });
    } finally {
      setLoading(false);
    }
  }

  const getStatusMessage = (status: string) => {
    switch (status) {
      case 'approved':
        return {
          type: 'success' as const,
          text: 'La tua richiesta di accesso API è stata APPROVATA! Puoi ora utilizzare la nostra API.'
        };
      case 'rejected':
        return {
          type: 'error' as const,
          text: 'La tua richiesta di accesso API è stata RIFIUTATA. Contatta il supporto per maggiori informazioni.'
        };
      case 'pending':
        return {
          type: 'warning' as const,
          text: 'La tua richiesta di accesso API è ancora IN ATTESA di revisione. Ti contatteremo presto.'
        };
      default:
        return {
          type: 'info' as const,
          text: `Stato della richiesta: ${status}`
        };
    }
  };

  const handleDownload = () => {
    // Create a temporary anchor element to trigger download
    const link = document.createElement('a');
    link.href = '/api-documentation.zip'; // Path to your zip file in public directory
    link.download = 'api-documentation.zip'; // Name for the downloaded file
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('it-IT', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="max-w-md mx-auto bg-white p-8 rounded-lg shadow-lg">
      <h2 className="text-2xl font-bold text-gray-900 mb-6 text-center">
        Verifica Stato Richiesta API
      </h2>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
            Indirizzo Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="tua.email@esempio.com"
          />
        </div>

        <div>
          <label htmlFor="verificationCode" className="block text-sm font-medium text-gray-700 mb-2">
            Codice di Verifica
          </label>
          <input
            id="verificationCode"
            name="verificationCode"
            type="text"
            required
            value={verificationCode}
            onChange={(e) => setVerificationCode(e.target.value.toUpperCase())}
            className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono text-center tracking-wider"
            placeholder="ABC12345"
            maxLength={8}
            pattern="[A-Z0-9]{8}"
          />
          <p className="mt-1 text-xs text-gray-500">
            Inserisci il codice di 8 caratteri che hai ricevuto al momento della registrazione
          </p>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-md shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 transition duration-150"
        >
          {loading ? 'Controllo in corso...' : 'Verifica Stato'}
        </button>
      </form>

      {result && (
        <div className="mt-6">
          {result.error ? (
            <div className="p-4 rounded-md bg-red-50 text-red-700 border border-red-200">
              {result.error}
            </div>
          ) : result.found ? (
            <div className="space-y-4">
              {result.status && (
                <div
                  className={`p-4 rounded-md border ${
                    getStatusMessage(result.status).type === 'success'
                      ? 'bg-green-50 text-green-700 border-green-200'
                      : getStatusMessage(result.status).type === 'error'
                      ? 'bg-red-50 text-red-700 border-red-200'
                      : getStatusMessage(result.status).type === 'warning'
                      ? 'bg-yellow-50 text-yellow-700 border-yellow-200'
                      : 'bg-blue-50 text-blue-700 border-blue-200'
                  }`}
                >
                  <div className="font-semibold mb-2">
                    {getStatusMessage(result.status).text}
                  </div>
                  
                  <div className="text-sm space-y-1">
                    {result.siteName && (
                      <p><strong>Sito:</strong> {result.siteName}</p>
                    )}
                    {result.siteUrl && (
                      <p><strong>URL:</strong> {result.siteUrl}</p>
                    )}
                    {result.requestedAt && (
                      <p><strong>Richiesta inviata:</strong> {formatDate(result.requestedAt)}</p>
                    )}
                  </div>

                  {/* Download button for approved requests */}
                  {result.status === 'approved' && (
                    <div className="mt-4 pt-3 border-t border-green-200">
                      <button
                        onClick={handleDownload}
                        className="inline-flex items-center px-4 py-2 bg-green-600 hover:bg-green-700 text-white font-medium rounded-md shadow-sm transition duration-150 ease-in-out focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
                      >
                        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        Scarica Documentazione API
                      </button>
                      <p className="mt-2 text-xs text-green-600">
                        Scarica il file ZIP contenente la documentazione completa dell'API
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="p-4 rounded-md bg-gray-50 text-gray-700 border border-gray-200">
              {result.message === 'Invalid verification code for this email address.' ? (
                <div>
                  <p className="font-medium text-red-600 mb-2">Codice di verifica non valido</p>
                  <p className="text-sm">
                    Il codice di verifica inserito non corrisponde a quello associato a questa email. 
                    Controlla di aver inserito il codice corretto ricevuto al momento della registrazione.
                  </p>
                </div>
              ) : (
                result.message || 'Nessuna richiesta trovata con questa combinazione di email e codice di verifica.'
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
} 