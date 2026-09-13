export const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

const TOKEN_KEY = 'vat_token';
const USER_KEY = 'vat_user';

// ---------------------------------------------------------------------------
// JWT session storage
// ---------------------------------------------------------------------------

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setSession(token, user) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* private mode etc. — session simply won't persist */
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

function extractErrorDetail(body) {
  if (body == null) return null;
  if (typeof body === 'string') return body;
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => (d && d.msg ? d.msg : JSON.stringify(d))).join('; ');
  }
  if (body.detail && typeof body.detail === 'object') return JSON.stringify(body.detail);
  if (typeof body.message === 'string') return body.message;
  if (typeof body.error === 'string') return body.error;
  return JSON.stringify(body);
}

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

/** Local offline-demo tokens (never sent by a real backend session). */
function isMockToken(t) {
  return typeof t === 'string' && t.startsWith('demo-');
}

/** Paths that may legitimately return 401 without killing the session. */
function isAuthPath(path) {
  return path.startsWith('/api/auth/login') || path.startsWith('/api/auth/register');
}

/**
 * Minimal fetch wrapper. JSON in / JSON out, FormData supported.
 * Injects `Authorization: Bearer <jwt>` when a token is stored.
 * On an unexpected 401 the session is cleared and the app redirects to /login.
 * Throws ApiError with a human-readable message on non-2xx responses.
 */
export async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body != null && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(`Cannot reach the server at ${API_BASE}. Is the backend running?`, 0, null);
  }

  if (!res.ok) {
    // Offline demo sessions carry a local mock token the backend will never
    // accept — kicking back to /login on every 401 would trap demo users in
    // a login loop. Real expired sessions still redirect; mock sessions let
    // each page render its own error state instead.
    if (res.status === 401 && !isAuthPath(path) && !isMockToken(token)) {
      clearSession();
      // Full navigation is intentional: resets every in-memory state cleanly.
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login');
      }
    }
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    const detail = extractErrorDetail(body);
    throw new ApiError(detail || `Request failed (${res.status} ${res.statusText})`, res.status, body);
  }

  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// ---------------------------------------------------------------------------
// Route-group helpers ("typed-ish" wrappers per API group)
// ---------------------------------------------------------------------------

export const authApi = {
  register: ({ orgName, email, password }) =>
    apiFetch('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ org_name: orgName, email, password }),
    }),
  login: ({ email, password }) =>
    apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  me: () => apiFetch('/api/auth/me'),
};

export const agentsApi = {
  list: () => apiFetch('/api/agents'),
  create: (data) => apiFetch('/api/agents', { method: 'POST', body: JSON.stringify(data) }),
  get: (id) => apiFetch(`/api/agents/${id}`),
  patchMeta: (id, data) => apiFetch(`/api/agents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  archive: (id) => apiFetch(`/api/agents/${id}`, { method: 'DELETE' }),
  createVersion: (agentId, config) =>
    apiFetch(`/api/agents/${agentId}/versions`, { method: 'POST', body: JSON.stringify(config) }),
  listVersions: (agentId) => apiFetch(`/api/agents/${agentId}/versions`),
  getVersion: (versionId) => apiFetch(`/api/agent-versions/${versionId}`),
};

export const playgroundApi = {
  startSession: (agentVersionId, contact) => {
    const card = Object.fromEntries(
      Object.entries(contact || {}).filter(([, v]) => String(v ?? '').trim())
    );
    return apiFetch('/api/playground/sessions', {
      method: 'POST',
      body: JSON.stringify(
        Object.keys(card).length
          ? { agent_version_id: agentVersionId, contact: card }
          : { agent_version_id: agentVersionId }
      ),
    });
  },
  completeSession: (callId) => apiFetch(`/api/playground/sessions/${callId}/complete`, { method: 'POST' }),
  // Text mode: one conversational turn (or {event:'start'} for the opening line).
  sendTurn: (callId, body) =>
    apiFetch(`/api/playground/sessions/${callId}/turns`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  // SIMULATION ONLY: run campaign contacts through text-mode turns. No telephony.
  runDryRun: (campaignId, body) =>
    apiFetch(`/api/playground/campaigns/${campaignId}/dry-run`, {
      method: 'POST',
      body: JSON.stringify(body || {}),
    }),
};

export const devApi = {
  /** No auth required by design — safe to poll before login. */
  health: () => apiFetch('/api/health'),
  status: () => apiFetch('/api/dev/status'),
};

export const analyticsApi = {
  summary: () => apiFetch('/api/analytics/summary'),
  costs: () => apiFetch('/api/analytics/costs'),
};

// Legacy flat surface kept for existing pages (campaigns / contacts / calls).
export const api = {
  listCampaigns: () => apiFetch('/api/campaigns'),
  createCampaign: (data) => apiFetch('/api/campaigns', { method: 'POST', body: JSON.stringify(data) }),
  getCampaign: (id) => apiFetch(`/api/campaigns/${id}`),
  launchCampaign: (id) => apiFetch(`/api/campaigns/${id}/launch`, { method: 'POST' }),
  pauseCampaign: (id) => apiFetch(`/api/campaigns/${id}/pause`, { method: 'POST' }),
  cancelCampaign: (id) => apiFetch(`/api/campaigns/${id}/cancel`, { method: 'POST' }),
  getCampaignDashboard: (id) => apiFetch(`/api/campaigns/${id}/dashboard`),

  importContacts: (campaignId, formData) =>
    apiFetch(`/api/campaigns/${campaignId}/contacts/import`, { method: 'POST', body: formData }),
  listContacts: (campaignId, { page = 1, pageSize = 50, status = '' } = {}) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (status) params.set('status', status);
    return apiFetch(`/api/campaigns/${campaignId}/contacts?${params.toString()}`);
  },
  updateContact: (contactId, data) =>
    apiFetch(`/api/contacts/${contactId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteContact: (contactId) => apiFetch(`/api/contacts/${contactId}`, { method: 'DELETE' }),

  listDomainConfigs: () => apiFetch('/api/domain-configs'),
  listCampaignCalls: (campaignId) => apiFetch(`/api/campaigns/${campaignId}/calls`),
  listCalls: ({ limit = 500, agentVersionId } = {}) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (agentVersionId != null) params.set('agent_version_id', String(agentVersionId));
    return apiFetch(`/api/calls?${params.toString()}`);
  },
  getCall: (callId) => apiFetch(`/api/calls/${callId}`),
  placeTestCall: (data) => apiFetch('/api/test-call', { method: 'POST', body: JSON.stringify(data) }),

  // Newer additions used by pages built on the platform contract.
  listAgents: agentsApi.list,
};

export function campaignExportUrl(campaignId, format) {
  return `${API_BASE}/api/campaigns/${campaignId}/export?format=${encodeURIComponent(format)}`;
}

export function callExportUrl(callId, format) {
  return `${API_BASE}/api/calls/${callId}/export?format=${encodeURIComponent(format)}`;
}
