// Cambia BASE_URL si sirves el frontend desde otro origen.
// Déjalo vacío ('') si el frontend se sirve bajo el mismo dominio que la API.
export const API_BASE = window.MOBIL_API_BASE ?? '';

export const ENDPOINTS = {
  health:        `${API_BASE}/health`,
  clones:        `${API_BASE}/api/v1/clones`,
  batchStart:    `${API_BASE}/api/v1/clones/batch-start`,
  emergencyStop: `${API_BASE}/api/v1/clones/emergency-stop`,
  targets:       `${API_BASE}/api/v1/targets`,
};
