import React, { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';

interface PluginAccessRequest {
  id: string;
  name: string;
  email: string;
  phone: string;
  site_name: string;
  site_url: string;
  status: 'pending' | 'approved' | 'rejected';
  requested_at: string;
  reviewed_at?: string;
  reviewed_by?: string;
  admin_notes?: string;
  created_at: string;
  updated_at: string;
}

interface ApprovedOrigin {
  origin: string;
  siteName: string;
  ownerName: string;
  ownerEmail: string;
  approvedAt: string;
}

export default function PluginRequestsManager() {
  const [requests, setRequests] = useState<PluginAccessRequest[]>([]);
  const [approvedOrigins, setApprovedOrigins] = useState<ApprovedOrigin[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'pending' | 'approved' | 'rejected'>('all');
  const [selectedRequest, setSelectedRequest] = useState<PluginAccessRequest | null>(null);
  const [editingRequest, setEditingRequest] = useState<PluginAccessRequest | null>(null);
  const [editForm, setEditForm] = useState<Partial<PluginAccessRequest>>({});
  const [adminNotes, setAdminNotes] = useState('');
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [showApprovedOrigins, setShowApprovedOrigins] = useState(false);

  useEffect(() => {
    fetchRequests();
    fetchApprovedOrigins();
  }, []);

  async function fetchRequests() {
    try {
      setLoading(true);
      const { data, error } = await supabase
        .from('api_access_requests')
        .select('*')
        .order('requested_at', { ascending: false });

      if (error) throw error;
      setRequests(data || []);
    } catch (error) {
      console.error('Error fetching plugin requests:', error);
    } finally {
      setLoading(false);
    }
  }

  async function fetchApprovedOrigins() {
    try {
      const { data, error } = await supabase
        .from('api_access_requests')
        .select('site_url, site_name, name, email, reviewed_at')
        .eq('status', 'approved')
        .order('reviewed_at', { ascending: false });

      if (error) throw error;
      
      const origins = data?.map(req => ({
        origin: req.site_url,
        siteName: req.site_name,
        ownerName: req.name,
        ownerEmail: req.email,
        approvedAt: req.reviewed_at
      })) || [];
      
      setApprovedOrigins(origins);
    } catch (error) {
      console.error('Error fetching approved origins:', error);
    }
  }

  async function updateRequestStatus(requestId: string, status: 'approved' | 'rejected', notes?: string) {
    try {
      setActionLoading(requestId);
      
      const { data: userData } = await supabase.auth.getUser();
      
      const { error } = await supabase
        .from('api_access_requests')
        .update({
          status,
          reviewed_at: new Date().toISOString(),
          reviewed_by: userData.user?.id,
          admin_notes: notes || null
        })
        .eq('id', requestId);

      if (error) throw error;

      // Update local state
      setRequests(prev => prev.map(req => 
        req.id === requestId 
          ? { ...req, status, reviewed_at: new Date().toISOString(), admin_notes: notes }
          : req
      ));

      setSelectedRequest(null);
      setAdminNotes('');
      
      // Refresh approved origins if status is approved
      if (status === 'approved') {
        fetchApprovedOrigins();
      }
      
      // Show success message
      alert(`Richiesta ${status === 'approved' ? 'approvata' : 'rifiutata'} con successo!`);
      
    } catch (error) {
      console.error(`Error ${status === 'approved' ? 'approving' : 'rejecting'} request:`, error);
      alert(`Errore nel ${status === 'approved' ? 'approvare' : 'rifiutare'} la richiesta. Riprova.`);
    } finally {
      setActionLoading(null);
    }
  }

  async function updateRequestDetails(requestId: string, updates: Partial<PluginAccessRequest>) {
    try {
      setActionLoading(requestId);
      
      const originalRequest = requests.find(r => r.id === requestId);
      const statusChanged = originalRequest && updates.status && originalRequest.status !== updates.status;
      
      const updateData: any = {
        name: updates.name,
        email: updates.email,
        phone: updates.phone,
        site_name: updates.site_name,
        site_url: updates.site_url,
        admin_notes: updates.admin_notes,
        updated_at: new Date().toISOString()
      };

      // If status is being changed, add review fields
      if (statusChanged) {
        const { data: userData } = await supabase.auth.getUser();
        updateData.status = updates.status;
        updateData.reviewed_at = new Date().toISOString();
        updateData.reviewed_by = userData.user?.id;
      }
      
      const { error } = await supabase
        .from('api_access_requests')
        .update(updateData)
        .eq('id', requestId);

      if (error) throw error;

      // Update local state
      setRequests(prev => prev.map(req => 
        req.id === requestId 
          ? { ...req, ...updates, ...updateData }
          : req
      ));

      // Refresh approved origins if status changed to/from approved
      if (statusChanged && (updates.status === 'approved' || originalRequest?.status === 'approved')) {
        fetchApprovedOrigins();
      }

      setEditingRequest(null);
      setEditForm({});
      
      const message = statusChanged 
        ? `Richiesta aggiornata e ${updates.status === 'approved' ? 'approvata' : updates.status === 'rejected' ? 'rifiutata' : 'messa in attesa'} con successo!`
        : 'Richiesta aggiornata con successo!';
      alert(message);
      
    } catch (error) {
      console.error('Error updating request:', error);
      alert('Errore nell\'aggiornamento della richiesta. Riprova.');
    } finally {
      setActionLoading(null);
    }
  }

  async function deleteRequest(requestId: string) {
    if (!confirm('Sei sicuro di voler eliminare questa richiesta? Questa azione non può essere annullata.')) return;

    try {
      setActionLoading(requestId);
      
      const { error } = await supabase
        .from('api_access_requests')
        .delete()
        .eq('id', requestId);

      if (error) throw error;

      // Update local state
      setRequests(prev => prev.filter(req => req.id !== requestId));
      
      // Refresh approved origins in case we deleted an approved request
      fetchApprovedOrigins();
      
      alert('Richiesta eliminata con successo!');
      
    } catch (error) {
      console.error('Error deleting request:', error);
      alert('Errore nell\'eliminazione della richiesta. Riprova.');
    } finally {
      setActionLoading(null);
    }
  }

  const startEditing = (request: PluginAccessRequest) => {
    setEditingRequest(request);
    setEditForm({
      name: request.name,
      email: request.email,
      phone: request.phone,
      site_name: request.site_name,
      site_url: request.site_url,
      admin_notes: request.admin_notes || '',
      status: request.status
    });
  };

  const handleEditFormChange = (field: string, value: string) => {
    setEditForm(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const validateUrl = (url: string): boolean => {
    try {
      const urlObj = new URL(url);
      return urlObj.protocol === 'http:' || urlObj.protocol === 'https:';
    } catch {
      return false;
    }
  };

  const filteredRequests = requests.filter(req => {
    if (filter === 'all') return true;
    return req.status === filter;
  });

  const getStatusBadge = (status: string) => {
    const baseClasses = "px-2 inline-flex text-xs leading-5 font-semibold rounded-full";
    switch (status) {
      case 'pending':
        return `${baseClasses} bg-yellow-100 text-yellow-800`;
      case 'approved':
        return `${baseClasses} bg-green-100 text-green-800`;
      case 'rejected':
        return `${baseClasses} bg-red-100 text-red-800`;
      default:
        return `${baseClasses} bg-gray-100 text-gray-800`;
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-GB', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (loading) {
    return (
      <div className="p-6">
        <div className="flex justify-center items-center h-64">
          <div className="text-lg">Caricamento richieste plugin...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Gestione Accessi Plugin</h1>
        <div className="flex items-center space-x-4">
          <button
            onClick={() => setShowApprovedOrigins(!showApprovedOrigins)}
            className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 text-sm"
          >
            {showApprovedOrigins ? 'Nascondi' : 'Mostra'} Origini Approvate ({approvedOrigins.length})
          </button>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as any)}
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="all">Tutte le Richieste</option>
            <option value="pending">In Attesa</option>
            <option value="approved">Approvate</option>
            <option value="rejected">Rifiutate</option>
          </select>
          <button
            onClick={() => {
              fetchRequests();
              fetchApprovedOrigins();
            }}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 text-sm"
          >
            Aggiorna
          </button>
        </div>
      </div>

      {/* Approved Origins Section */}
      {showApprovedOrigins && (
        <div className="mb-8 bg-green-50 border border-green-200 rounded-lg p-6">
          <h2 className="text-lg font-semibold text-green-800 mb-4">
            🟢 Origini Attualmente Approvate ({approvedOrigins.length})
          </h2>
          <p className="text-sm text-green-700 mb-4">
            Questi domini sono attualmente autorizzati ad accedere al plugin. Il plugin controlla dinamicamente questo elenco per ogni richiesta.
          </p>
          
          {approvedOrigins.length > 0 ? (
            <div className="bg-white rounded-md shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      URL Origine
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Nome Sito
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Proprietario
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Approvato
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {approvedOrigins.map((origin, index) => (
                    <tr key={index} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm">
                        <a 
                          href={origin.origin} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:text-blue-800 font-mono"
                        >
                          {origin.origin}
                        </a>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900">
                        {origin.siteName}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <div className="text-gray-900">{origin.ownerName}</div>
                        <div className="text-gray-500 text-xs">{origin.ownerEmail}</div>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {formatDate(origin.approvedAt)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-4 text-green-600">
              Nessuna origine approvata ancora.
            </div>
          )}
        </div>
      )}

      {/* Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="text-2xl font-bold text-gray-900">{requests.length}</div>
          <div className="text-sm text-gray-500">Richieste Totali</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="text-2xl font-bold text-yellow-600">
            {requests.filter(r => r.status === 'pending').length}
          </div>
          <div className="text-sm text-gray-500">In Attesa</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="text-2xl font-bold text-green-600">
            {requests.filter(r => r.status === 'approved').length}
          </div>
          <div className="text-sm text-gray-500">Approvate</div>
        </div>
        <div className="bg-white p-4 rounded-lg shadow">
          <div className="text-2xl font-bold text-red-600">
            {requests.filter(r => r.status === 'rejected').length}
          </div>
          <div className="text-sm text-gray-500">Rifiutate</div>
        </div>
      </div>

      {/* Requests Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Richiedente
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Dettagli Sito
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Stato
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Richiesto
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Azioni
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {filteredRequests.map((request) => (
              <tr key={request.id} className="hover:bg-gray-50">
                <td className="px-6 py-4 whitespace-nowrap">
                  <div className="text-sm font-medium text-gray-900">{request.name}</div>
                  <div className="text-sm text-gray-500">{request.email}</div>
                  {request.phone && <div className="text-sm text-gray-500">{request.phone}</div>}
                </td>
                <td className="px-6 py-4">
                  <div className="text-sm font-medium text-gray-900">{request.site_name}</div>
                  <div className="text-sm text-blue-600 hover:text-blue-800">
                    <a href={request.site_url} target="_blank" rel="noopener noreferrer">
                      {request.site_url}
                    </a>
                  </div>
                </td>
                <td className="px-6 py-4 whitespace-nowrap">
                  <span className={getStatusBadge(request.status)}>
                    {request.status === 'pending' ? 'In Attesa' : 
                     request.status === 'approved' ? 'Approvata' : 'Rifiutata'}
                  </span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                  {formatDate(request.requested_at)}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                  <button
                    onClick={() => setSelectedRequest(request)}
                    className="text-indigo-600 hover:text-indigo-900 mr-4"
                  >
                    Visualizza
                  </button>
                  <button
                    onClick={() => startEditing(request)}
                    className="text-blue-600 hover:text-blue-900 mr-4"
                  >
                    Modifica
                  </button>
                  <button
                    onClick={() => deleteRequest(request.id)}
                    disabled={actionLoading === request.id}
                    className="text-red-600 hover:text-red-900 mr-4 disabled:opacity-50"
                  >
                    {actionLoading === request.id ? 'Eliminazione...' : 'Elimina'}
                  </button>
                  {request.status === 'pending' && (
                    <>
                      <button
                        onClick={() => updateRequestStatus(request.id, 'approved')}
                        disabled={actionLoading === request.id}
                        className="text-green-600 hover:text-green-900 mr-4 disabled:opacity-50"
                      >
                        {actionLoading === request.id ? 'Elaborazione...' : 'Approva'}
                      </button>
                      <button
                        onClick={() => updateRequestStatus(request.id, 'rejected')}
                        disabled={actionLoading === request.id}
                        className="text-red-600 hover:text-red-900 disabled:opacity-50"
                      >
                        {actionLoading === request.id ? 'Elaborazione...' : 'Rifiuta'}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        
        {filteredRequests.length === 0 && (
          <div className="text-center py-8 text-gray-500">
            Nessuna richiesta {filter !== 'all' ? (filter === 'pending' ? 'in attesa' : filter === 'approved' ? 'approvata' : 'rifiutata') : ''} trovata.
          </div>
        )}
      </div>

      {/* Edit Request Modal */}
      {editingRequest && (
        <div className="fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50">
          <div className="relative top-20 mx-auto p-5 border w-11/12 md:w-3/4 lg:w-2/3 shadow-lg rounded-md bg-white">
            <div className="mt-3">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-medium text-gray-900">Modifica Richiesta</h3>
                <button
                  onClick={() => {
                    setEditingRequest(null);
                    setEditForm({});
                  }}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <span className="sr-only">Chiudi</span>
                  <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Nome *</label>
                    <input
                      type="text"
                      value={editForm.name || ''}
                      onChange={(e) => handleEditFormChange('name', e.target.value)}
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      placeholder="Nome completo"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Email *</label>
                    <input
                      type="email"
                      value={editForm.email || ''}
                      onChange={(e) => handleEditFormChange('email', e.target.value)}
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      placeholder="email@esempio.com"
                    />
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Telefono</label>
                    <input
                      type="text"
                      value={editForm.phone || ''}
                      onChange={(e) => handleEditFormChange('phone', e.target.value)}
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      placeholder="Telefono"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Nome Sito *</label>
                    <input
                      type="text"
                      value={editForm.site_name || ''}
                      onChange={(e) => handleEditFormChange('site_name', e.target.value)}
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      placeholder="Il Mio Sito Web"
                    />
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">URL Sito *</label>
                    <input
                      type="url"
                      value={editForm.site_url || ''}
                      onChange={(e) => handleEditFormChange('site_url', e.target.value)}
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      placeholder="https://esempio.com"
                    />
                  </div>
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700">Note Admin</label>
                  <textarea
                    value={editForm.admin_notes || ''}
                    onChange={(e) => handleEditFormChange('admin_notes', e.target.value)}
                    rows={2}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    placeholder="Note interne..."
                  />
                </div>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700">Stato</label>
                  <select
                    value={editForm.status || 'pending'}
                    onChange={(e) => handleEditFormChange('status', e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  >
                    <option value="pending">In Attesa</option>
                    <option value="approved">Approvata</option>
                    <option value="rejected">Rifiutata</option>
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    Cambiare lo stato aggiornerà automaticamente il timestamp di revisione e il revisore.
                  </p>
                </div>
                
                <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
                  <p className="text-sm text-blue-700">
                    <strong>Stato Originale:</strong> <span className={getStatusBadge(editingRequest.status)}>
                      {editingRequest.status === 'pending' ? 'In Attesa' : 
                       editingRequest.status === 'approved' ? 'Approvata' : 'Rifiutata'}
                    </span>
                  </p>
                  <p className="text-xs text-blue-600 mt-1">
                    Ora puoi cambiare lo stato direttamente in questo modulo.
                  </p>
                </div>
              </div>
              
              <div className="mt-6 flex justify-end space-x-3">
                <button
                  onClick={() => {
                    setEditingRequest(null);
                    setEditForm({});
                  }}
                  className="bg-gray-300 text-gray-700 px-4 py-2 rounded hover:bg-gray-400"
                >
                  Annulla
                </button>
                <button
                  onClick={() => {
                    // Validate required fields
                    if (!editForm.name || !editForm.email || !editForm.site_name || !editForm.site_url) {
                      alert('Compila tutti i campi obbligatori');
                      return;
                    }
                    
                    // Validate URL
                    if (!validateUrl(editForm.site_url || '')) {
                      alert('Inserisci un URL valido');
                      return;
                    }
                    
                    // Validate status
                    if (!editForm.status || !['pending', 'approved', 'rejected'].includes(editForm.status)) {
                      alert('Seleziona uno stato valido');
                      return;
                    }
                    
                    updateRequestDetails(editingRequest.id, editForm);
                  }}
                  disabled={actionLoading === editingRequest.id}
                  className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  {actionLoading === editingRequest.id ? 'Salvataggio...' : 'Salva Modifiche'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Request Details Modal */}
      {selectedRequest && (
        <div className="fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50">
          <div className="relative top-20 mx-auto p-5 border w-11/12 md:w-3/4 lg:w-1/2 shadow-lg rounded-md bg-white">
            <div className="mt-3">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-medium text-gray-900">Dettagli Richiesta</h3>
                <button
                  onClick={() => setSelectedRequest(null)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <span className="sr-only">Chiudi</span>
                  <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Nome</label>
                    <p className="mt-1 text-sm text-gray-900">{selectedRequest.name}</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Email</label>
                    <p className="mt-1 text-sm text-gray-900">{selectedRequest.email}</p>
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Telefono</label>
                    <p className="mt-1 text-sm text-gray-900">{selectedRequest.phone}</p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Nome Sito</label>
                    <p className="mt-1 text-sm text-gray-900">{selectedRequest.site_name}</p>
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">URL Sito</label>
                    <p className="mt-1 text-sm text-blue-600">
                      <a href={selectedRequest.site_url} target="_blank" rel="noopener noreferrer">
                        {selectedRequest.site_url}
                      </a>
                    </p>
                  </div>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Stato</label>
                    <span className={`mt-1 ${getStatusBadge(selectedRequest.status)}`}>
                      {selectedRequest.status === 'pending' ? 'In Attesa' : 
                       selectedRequest.status === 'approved' ? 'Approvata' : 'Rifiutata'}
                    </span>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Richiesto il</label>
                    <p className="mt-1 text-sm text-gray-900">{formatDate(selectedRequest.requested_at)}</p>
                  </div>
                </div>
                
                {selectedRequest.admin_notes && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Note Admin</label>
                    <p className="mt-1 text-sm text-gray-900 whitespace-pre-wrap">{selectedRequest.admin_notes}</p>
                  </div>
                )}
                
                {selectedRequest.status === 'pending' && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Note Admin (Opzionale)</label>
                    <textarea
                      value={adminNotes}
                      onChange={(e) => setAdminNotes(e.target.value)}
                      rows={3}
                      className="mt-1 block w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                      placeholder="Aggiungi note sulla tua decisione..."
                    />
                  </div>
                )}
              </div>
              
              {selectedRequest.status === 'pending' && (
                <div className="mt-6 flex justify-end space-x-3">
                  <button
                    onClick={() => updateRequestStatus(selectedRequest.id, 'rejected', adminNotes)}
                    disabled={actionLoading === selectedRequest.id}
                    className="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-700 disabled:opacity-50"
                  >
                    {actionLoading === selectedRequest.id ? 'Elaborazione...' : 'Rifiuta'}
                  </button>
                  <button
                    onClick={() => updateRequestStatus(selectedRequest.id, 'approved', adminNotes)}
                    disabled={actionLoading === selectedRequest.id}
                    className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:opacity-50"
                  >
                    {actionLoading === selectedRequest.id ? 'Elaborazione...' : 'Approva'}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}