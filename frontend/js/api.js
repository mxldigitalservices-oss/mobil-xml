import { ENDPOINTS } from './config.js';

async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${text ? ` · ${text}` : ''}`);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

export const Api = {
  health: () => request(ENDPOINTS.health),

  // Clones
  listClones: async () => {
    try {
      return await request(`${ENDPOINTS.clones}`);
    } catch {
      return null;
    }
  },

  batchStart: (body) => request(ENDPOINTS.batchStart, {
    method: 'POST', body: JSON.stringify(body),
  }),

  emergencyStop: (body) => request(ENDPOINTS.emergencyStop, {
    method: 'POST', body: JSON.stringify(body),
  }),

  // Targets
  listTargets: (category) => request(`${ENDPOINTS.targets}?category=${encodeURIComponent(category)}`),
  createTarget: (body) => request(ENDPOINTS.targets, {
    method: 'POST', body: JSON.stringify(body),
  }),
};
