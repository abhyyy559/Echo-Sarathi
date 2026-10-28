// Production builds talk to the same origin (`/api/...`) so Vercel can proxy
// to the backend without baking a host into the bundle. Local Vite dev keeps
// the historical localhost:8000 default. An explicit VITE_API_URL always wins
// (useful for Docker and for direct-to-Render deployments).
const CONFIGURED_API_BASE = String(import.meta.env.VITE_API_URL || '').trim();
const RUNTIME_ORIGIN =
  typeof window !== 'undefined' && window.location ? window.location.origin : '';
const IS_LOCAL_RUNTIME =
  typeof window !== 'undefined' &&
  window.location &&
  ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);

export const API_BASE = (
  CONFIGURED_API_BASE || (IS_LOCAL_RUNTIME ? 'http://localhost:8000' : '')
).replace(/\/+$/, '');

/** Human-readable backend target for error messages. */
export function apiTargetLabel() {
  return API_BASE || RUNTIME_ORIGIN || 'the configured backend';
}

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
    throw new ApiError(
      `Cannot reach the backend at ${apiTargetLabel()}. Check that the API service is running and that the frontend is pointed at it.`,
      0,
      null
    );
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
  googleLogin: (credential) =>
    apiFetch('/api/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    }),
  me: () => apiFetch('/api/auth/me'),
  forgotPassword: (email) =>
    apiFetch('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  resetPassword: ({ token, password }) =>
    apiFetch('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, password }),
    }),
  acceptInvite: ({ token, password }) =>
    apiFetch('/api/auth/accept-invite', {
      method: 'POST',
      body: JSON.stringify({ token, password }),
    }),
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
  // Verification aid: what is configured, which provider served, what fell back.
  diagnostics: () => apiFetch('/api/playground/diagnostics'),
  // Live feed, polled with the last seq so nothing is re-fetched.
  events: (since) => apiFetch(`/api/playground/events?since=${Number(since) || 0}`),
  clearEvents: () => apiFetch('/api/playground/events', { method: 'DELETE' }),
};

export const devApi = {
  /** No auth required by design — safe to poll before login. */
  health: () => apiFetch('/api/health'),
  status: () => apiFetch('/api/dev/status'),
  /** Poll the Deepgram/Cartesia balances now instead of waiting for the daily poll. */
  refreshUsage: () => apiFetch('/api/dev/usage/refresh', { method: 'POST' }),
};

export const analyticsApi = {
  summary: () => apiFetch('/api/analytics/summary'),
  costs: () => apiFetch('/api/analytics/costs'),
  /** Per-key provider quota state ("which limit gets exhausted first"). */
  usage: () => apiFetch('/api/analytics/usage'),
};

export const billingApi = {
  /** Plan, minutes, wallet balance, this month's spend, packs and ledger. */
  summary: () => apiFetch('/api/billing'),
  /** Public plan catalog plus the organization's current plan. */
  plans: () => apiFetch('/api/billing/plans'),
  /** Start a plan period (gateway checkout or operator-settled). */
  subscribe: (planId) =>
    apiFetch('/api/billing/subscribe', {
      method: 'POST',
      body: JSON.stringify({ plan_id: planId }),
    }),
  /** Stop renewal at the end of the paid period. */
  cancel: () => apiFetch('/api/billing/cancel', { method: 'POST' }),
  profile: () => apiFetch('/api/billing/profile'),
  updateProfile: (data) =>
    apiFetch('/api/billing/profile', { method: 'PATCH', body: JSON.stringify(data) }),
  invoices: () => apiFetch('/api/billing/invoices'),
  invoice: (id) => apiFetch(`/api/billing/invoices/${id}`),
  /** Creates a gateway order. Credits are granted only after /verify. */
  checkout: (packId) =>
    apiFetch('/api/billing/checkout', {
      method: 'POST',
      body: JSON.stringify({ pack_id: packId }),
    }),
  /** Verifies the gateway signature and credits the pack once. */
  verify: (payload) =>
    apiFetch('/api/billing/verify', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  /** Offline top-up; only enabled when the operator turned payments on. */
  topup: (packId) =>
    apiFetch('/api/billing/topup', {
      method: 'POST',
      body: JSON.stringify({ pack_id: packId }),
    }),
};

export const platformApi = {
  summary: () => apiFetch('/api/platform/summary'),
  orgs: (query) =>
    apiFetch(`/api/platform/orgs${query ? `?query=${encodeURIComponent(query)}` : ''}`),
  org: (id) => apiFetch(`/api/platform/orgs/${id}`),
  adjustCredits: (orgId, { amountPaise, description }) =>
    apiFetch(`/api/platform/orgs/${orgId}/credits`, {
      method: 'POST',
      body: JSON.stringify({ amount_paise: amountPaise, description }),
    }),
  assignPlan: (orgId, body) =>
    apiFetch(`/api/platform/orgs/${orgId}/plan`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  runLifecycle: () => apiFetch('/api/platform/lifecycle/run', { method: 'POST' }),
};

// Legacy flat surface kept for existing pages (campaigns / contacts / calls).
export const api = {
  listCampaigns: () => apiFetch('/api/campaigns'),
  createCampaign: (data) => apiFetch('/api/campaigns', { method: 'POST', body: JSON.stringify(data) }),
  getCampaign: (id) => apiFetch(`/api/campaigns/${id}`),
  patchCampaign: (id, data) =>
    apiFetch(`/api/campaigns/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  launchCampaign: (id) => apiFetch(`/api/campaigns/${id}/launch`, { method: 'POST' }),
  pauseCampaign: (id) => apiFetch(`/api/campaigns/${id}/pause`, { method: 'POST' }),
  cancelCampaign: (id) => apiFetch(`/api/campaigns/${id}/cancel`, { method: 'POST' }),
  deleteCampaign: (id) => apiFetch(`/api/campaigns/${id}`, { method: 'DELETE' }),
  getCampaignDashboard: (id) => apiFetch(`/api/campaigns/${id}/dashboard`),

  importContacts: (campaignId, formData) =>
    apiFetch(`/api/campaigns/${campaignId}/contacts/import`, { method: 'POST', body: formData }),
  copyContacts: (campaignId, sourceCampaignId) =>
    apiFetch(`/api/campaigns/${campaignId}/contacts/copy`, {
      method: 'POST',
      body: JSON.stringify({ source_campaign_id: sourceCampaignId }),
    }),
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

/**
 * Download an authenticated file (CSV/XLSX export).
 *
 * ``window.open`` cannot carry the Authorization header, so an export URL
 * opened in a new tab always 401s. Fetch the bytes with the session token,
 * then save them through a temporary object URL.
 */
export async function downloadExport(path, fallbackName) {
  const token = getToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { headers });
  } catch {
    throw new ApiError(
      `Cannot reach the backend at ${apiTargetLabel()}. Check that the API service is running.`,
      0,
      null
    );
  }

  if (!res.ok) {
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (res.status === 401 && !isMockToken(token)) {
      clearSession();
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login');
      }
    }
    throw new ApiError(
      extractErrorDetail(body) || `Export failed (${res.status} ${res.statusText})`,
      res.status,
      body
    );
  }

  const disposition = res.headers.get('Content-Disposition') || '';
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match ? match[1].trim() : fallbackName;

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return filename;
}

export function downloadCampaignExport(campaignId, format = 'csv') {
  const ext = format === 'xlsx' ? 'xlsx' : 'csv';
  return downloadExport(
    `/api/campaigns/${campaignId}/export?format=${ext}`,
    `campaign-${campaignId}.${ext}`
  );
}

export function downloadCallExport(callId, format = 'csv') {
  const ext = format === 'xlsx' ? 'xlsx' : 'csv';
  return downloadExport(`/api/calls/${callId}/export?format=${ext}`, `call-${callId}.${ext}`);
}
