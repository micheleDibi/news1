import { useState } from 'react';
import { supabase } from '../lib/supabase';

export default function ResetPasswordForm() {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setMessage(null);

    const formData = new FormData(e.currentTarget);
    const email = formData.get('email') as string;

    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/update-password`,
      });

      if (error) throw error;

      setMessage({
        type: 'success',
        text: 'Ti abbiamo inviato un link per reimpostare la password. Controlla la tua email.',
      });
      
    } catch (error) {
      console.error('Reset password error:', error);
      setMessage({
        type: 'error',
        text: error instanceof Error ? error.message : 'Errore durante il reset della password',
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 bg-white p-6 rounded-lg shadow">
      {message && (
        <div
          className={`p-4 rounded ${
            message.type === 'error' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'
          }`}
        >
          {message.text}
        </div>
      )}

      <div>
        <label htmlFor="email" className="block text-sm font-medium text-gray-700">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>

      <button
        type="submit"
        disabled={loading}
        className={`w-full rounded-md bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
          loading ? 'opacity-50 cursor-not-allowed' : ''
        }`}
      >
        {loading ? 'Invio in corso...' : 'Invia link di reset'}
      </button>

      <p className="text-center text-sm text-gray-600">
        Ricordi la password?{' '}
        <a href="/login" className="text-blue-600 hover:text-blue-800">
          Torna al login
        </a>
      </p>
    </form>
  );
} 