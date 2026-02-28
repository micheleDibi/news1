import React, { useState } from "react";

interface RefreshStatus {
  loading: boolean;
  success: boolean;
  error: string | null;
  data: any;
}

const ItaliaDomaniRefresh: React.FC = () => {
  const [status, setStatus] = useState<RefreshStatus>({
    loading: false,
    success: false,
    error: null,
    data: null,
  });

  const refreshData = async () => {
    setStatus({
      loading: true,
      success: false,
      error: null,
      data: null,
    });

    try {
      const response = await fetch("/api/eu-funding/refresh-italiadomani", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ force_refresh: true }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();

      setStatus({
        loading: false,
        success: true,
        error: null,
        data: result,
      });

      // Auto-refresh the page after 2 seconds to show updated data
      setTimeout(() => {
        window.location.reload();
      }, 2000);
    } catch (error) {
      setStatus({
        loading: false,
        success: false,
        error:
          error instanceof Error ? error.message : "Unknown error occurred",
        data: null,
      });
    }
  };

  const getStatusMessage = () => {
    if (status.loading) {
      return (
        <div className="flex items-center space-x-2 text-blue-600">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
          <span>Actualizando datos de ItaliaDomani...</span>
        </div>
      );
    }

    if (status.success) {
      return (
        <div className="text-green-600">
          ✅ Datos actualizados exitosamente!
          {status.data?.italiadomani_count && (
            <span className="ml-2">
              {status.data.italiadomani_count} bandi encontrados
            </span>
          )}
        </div>
      );
    }

    if (status.error) {
      return <div className="text-red-600">❌ Error: {status.error}</div>;
    }

    return null;
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">
            ItaliaDomani Data Refresh
          </h3>
          <p className="text-sm text-gray-600">
            Actualiza los datos de bandi desde ItaliaDomani.gov.it
          </p>
        </div>
        <button
          onClick={refreshData}
          disabled={status.loading}
          className={`px-4 py-2 rounded-md font-medium transition-colors ${
            status.loading
              ? "bg-gray-300 cursor-not-allowed"
              : "bg-blue-600 hover:bg-blue-700 text-white"
          }`}
        >
          {status.loading ? "Actualizando..." : "🔄 Refrescar Datos"}
        </button>
      </div>

      {getStatusMessage()}

      {status.data && (
        <div className="mt-4 p-4 bg-gray-50 rounded-md">
          <h4 className="font-medium text-gray-900 mb-2">
            Resumen de la actualización:
          </h4>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="font-medium">Total oportunidades:</span>{" "}
              {status.data.summary?.total_opportunities}
            </div>
            <div>
              <span className="font-medium">ItaliaDomani:</span>{" "}
              {status.data.summary?.sources?.italiadomani_gov_it}
            </div>
            <div>
              <span className="font-medium">Incentivi.gov.it:</span>{" "}
              {status.data.summary?.sources?.incentivi_gov_it}
            </div>
            <div>
              <span className="font-medium">EC Europa:</span> 0
            </div>
          </div>
          <div className="mt-2 text-xs text-gray-500">
            Última actualización:{" "}
            {new Date(status.data.summary?.last_updated).toLocaleString()}
          </div>
        </div>
      )}
    </div>
  );
};

export default ItaliaDomaniRefresh;
