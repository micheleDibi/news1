import { useState } from 'react';

interface FormData {
  name: string;
  email: string;
  phone: string;
  siteName: string;
  siteUrl: string;
}

interface SubmissionResponse {
  message: string;
  requestId: string;
  verificationCode: string;
}

export default function ApiRegistrationForm() {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);
  const [submissionResult, setSubmissionResult] = useState<SubmissionResponse | null>(null);

  const [formData, setFormData] = useState<FormData>({
    name: '',
    email: '',
    phone: '',
    siteName: '',
    siteUrl: ''
  });

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setMessage(null);
    setSubmissionResult(null);

    try {
      // Submit the API registration request
      const response = await fetch('/api/register-api-access', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...formData,
          requestedAt: new Date().toISOString(),
          status: 'pending'
        }),
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || 'Invio della richiesta di registrazione fallito');
      }

      setSubmissionResult(result);
      setMessage({
        type: 'success',
        text: 'La tua richiesta di accesso API è stata inviata con successo! Salva il codice di verifica mostrato sotto per controllare lo stato della tua richiesta.'
      });

      // Reset form
      setFormData({
        name: '',
        email: '',
        phone: '',
        siteName: '',
        siteUrl: ''
      });

    } catch (error) {
      console.error('Errore di registrazione:', error);
      setMessage({
        type: 'error',
        text: error instanceof Error ? error.message : 'Errore durante l\'invio della richiesta di registrazione'
      });
    } finally {
      setLoading(false);
    }
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  return (
    <div className="space-y-6">
      {message && (
        <div
          className={`p-4 rounded-md ${
            message.type === 'error' 
              ? 'bg-red-50 text-red-700 border border-red-200' 
              : 'bg-green-50 text-green-700 border border-green-200'
          }`}
        >
          {message.text}
        </div>
      )}

      {submissionResult && (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-6">
          <h3 className="text-lg font-semibold text-blue-900 mb-4">
            Richiesta Inviata con Successo!
          </h3>
          <div className="space-y-3 text-blue-800">
            <p>
              <strong>ID Richiesta:</strong> {submissionResult.requestId}
            </p>
            <div className="bg-white border-2 border-blue-300 rounded-lg p-4">
              <p className="text-sm font-medium text-blue-900 mb-2">
                Codice di Verifica (salvalo in un luogo sicuro!):
              </p>
              <p className="text-2xl font-mono font-bold text-blue-600 tracking-wider">
                {submissionResult.verificationCode}
              </p>
            </div>
            <p className="text-sm">
              Utilizza questo codice insieme alla tua email per verificare lo stato della tua richiesta.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6 bg-white p-8 rounded-lg shadow-lg">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-2">
              Nome Completo *
            </label>
            <input
              id="name"
              name="name"
              type="text"
              required
              value={formData.name}
              onChange={handleInputChange}
              className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="Il tuo nome completo"
            />
          </div>

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
              Indirizzo Email *
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              value={formData.email}
              onChange={handleInputChange}
              className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="tua.email@esempio.com"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label htmlFor="phone" className="block text-sm font-medium text-gray-700 mb-2">
              Numero di Telefono *
            </label>
            <input
              id="phone"
              name="phone"
              type="tel"
              required
              value={formData.phone}
              onChange={handleInputChange}
              className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="Il tuo numero di telefono"
            />
          </div>

          <div>
            <label htmlFor="siteName" className="block text-sm font-medium text-gray-700 mb-2">
              Nome Sito/Progetto *
            </label>
            <input
              id="siteName"
              name="siteName"
              type="text"
              required
              value={formData.siteName}
              onChange={handleInputChange}
              className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="Il Mio Sito di Notizie"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label htmlFor="siteUrl" className="block text-sm font-medium text-gray-700 mb-2">
              URL Sito *
            </label>
            <input
              id="siteUrl"
              name="siteUrl"
              type="url"
              required
              value={formData.siteUrl}
              onChange={handleInputChange}
              className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="https://esempio.com"
            />
            <p className="mt-1 text-xs text-gray-500">
              Questo è il dominio che sarà autorizzato ad accedere alla nostra API
            </p>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 px-4 rounded-md shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 transition duration-150"
        >
          {loading ? 'Invio in corso...' : 'Invia Richiesta'}
        </button>
      </form>
    </div>
  );
} 