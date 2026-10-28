import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { API_BASE, analyticsApi, devApi, getToken } from '../api.js';
import usePoll from '../hooks/usePoll.js';
import HealthDot, { boolToState } from '../components/HealthDot.jsx';

// ---------------------------------------------------------------------------
// DEV ONLY (login-protected). Hidden only when the build sets
// VITE_DISABLE_DEVTOOLS=true.
// ---------------------------------------------------------------------------

const PROVIDER_ENV_VARS = {
  deepgram: ['DEEPGRAM_API_KEY'],
  cartesia: ['CARTESIA_API_KEY'],
  groq: ['GROQ_API_KEY'],
  openai: ['OPENAI_API_KEY'],
  twilio: ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN'],
  livekit: ['LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET'],
};

const PROVIDER_LABELS = {
  groq: 'Groq',
  'groq-secondary': 'Groq (2nd model)',
  deepgram: 'Deepgram',
  cartesia: 'Cartesia',
  sarvam: 'Sarvam',
};

const USAGE_BADGE = {
  ok: { cls: 'ok', label: 'Healthy' },
  warn: { cls: 'warn', label: 'Running low' },
  critical: { cls: 'crit', label: 'Nearly exhausted' },
  unknown: { cls: 'cyan', label: 'No data yet' },
};

function fmtUsageTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtCount(n) {
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

/** Request-rate headroom, when the provider publishes it alongside tokens. */
function requestQuota(metrics) {
  const m = metrics || {};
  if (m.remaining_requests == null || m.limit_requests == null) return null;
  return `${fmtCount(m.remaining_requests)} of ${fmtCount(m.limit_requests)} req/min left`;
}

function toState(v) {
  if (v === true || v === 'ok' || v === 'up' || v === 'healthy') return 'ok';
  if (v === false || v === 'down') return 'down';
  return 'unknown';
}

/** Minimal payload that passes server-side version validation. */
const SAMPLE_VERSION_PAYLOAD = {
  system_prompt: 'You are a polite phone assistant created by the dev tools sampler.',
  company_context: {},
  question_flow: [{ step: 1, question: 'Is this a good time to talk?' }],
  extraction_schema: {
    sample_answer: {
      type: 'string',
      description: 'Whatever the callee answers.',
      validation: 'optional',
      confidence_threshold: 0.6,
    },
  },
  disclosure_script: 'This is an automated demonstration call from the developer tools panel.',
  escalation_rules: ['The caller asks for a human'],
  voice_settings: { speaking_rate: 1.0, stt_language: 'en' },
};

const CATALOG_GROUPS = [
  {
    router: 'Auth (/api/auth)',
    entries: [
      {
        key: 'auth-register',
        method: 'POST',
        path: '/api/auth/register',
        desc: 'Create an organization + its owner user, get a JWT.',
        readOnlyInstead: () => ({ path: '/api/auth/me' }),
        insteadNote: 'Registering would create a new organization - /me is shown instead.',
      },
      {
        key: 'auth-login',
        method: 'POST',
        path: '/api/auth/login',
        desc: 'Exchange email + password for a JWT.',
        readOnlyInstead: () => ({ path: '/api/auth/me' }),
        insteadNote: 'Login would mint another token - /me is shown instead.',
      },
      { key: 'auth-me', method: 'GET', path: '/api/auth/me', desc: 'Who am I signed in as.' },
    ],
  },
  {
    router: 'Agents & versions (/api/agents)',
    entries: [
      { key: 'agents-list', method: 'GET', path: '/api/agents', desc: 'List agents for your organization.' },
      {
        key: 'agents-create',
        method: 'POST',
        path: '/api/agents',
        desc: 'Create an empty agent shell (draft status).',
        createsData: true,
      },
      {
        key: 'agents-get',
        method: 'GET',
        path: '/api/agents/{agent}',
        desc: 'Fetch one agent (org-scoped; foreign ids look like 404s).',
        needsId: 'agent',
      },
      {
        key: 'agents-patch',
        method: 'PATCH',
        path: '/api/agents/{agent}',
        desc: 'Rename / re-describe an agent (meta only).',
        needsId: 'agent',
        body: () => ({ description: 'Touched by the dev tools sampler.' }),
      },
      {
        key: 'agents-delete',
        method: 'DELETE',
        path: '/api/agents/{agent}',
        desc: 'Soft-archive an agent (owner/admin only).',
        needsId: 'agent',
        readOnlyInstead: (ids) => ({ path: `/api/agents/${ids.agent}` }),
        insteadNote: 'Archiving would hide the agent - the read side is shown instead.',
      },
      {
        key: 'agents-versions-create',
        method: 'POST',
        path: '/api/agents/{agent}/versions',
        desc: 'Validate + store a new immutable config version.',
        needsId: 'agent',
        createsData: true,
        body: () => SAMPLE_VERSION_PAYLOAD,
      },
      {
        key: 'agents-versions-list',
        method: 'GET',
        path: '/api/agents/{agent}/versions',
        desc: 'Full version history of one agent.',
        needsId: 'agent',
      },
      {
        key: 'agent-version-get',
        method: 'GET',
        path: '/api/agent-versions/{version}',
        desc: 'One immutable version snapshot (what the runtime loads).',
        needsId: 'version',
      },
    ],
  },
  {
    router: 'Playground (/api/playground)',
    entries: [
      {
        key: 'pg-start',
        method: 'POST',
        path: '/api/playground/sessions',
        desc: 'Issue a LiveKit room + browser join token (kind=playground call row).',
        needsId: 'version',
        createsData: true,
      },
      {
        key: 'pg-complete',
        method: 'POST',
        path: '/api/playground/sessions/{call}/complete',
        desc: 'Finalize a session; returns transcript, fields, latency summary.',
        needsId: 'call',
        readOnlyInstead: () => ({ path: '/api/health' }),
        insteadNote: 'Completing would finalize a live test session - /health is shown instead.',
      },
    ],
  },
  {
    router: 'Campaigns & contacts (/api/campaigns)',
    entries: [
      { key: 'camp-list', method: 'GET', path: '/api/campaigns', desc: 'List campaigns with contact counts.' },
      {
        key: 'camp-create',
        method: 'POST',
        path: '/api/campaigns',
        desc: 'Create a draft campaign pinned to an agent version.',
        createsData: true,
      },
      {
        key: 'camp-get',
        method: 'GET',
        path: '/api/campaigns/{campaign}',
        desc: "One campaign's detail record.",
        needsId: 'campaign',
      },
      {
        key: 'camp-launch',
        method: 'POST',
        path: '/api/campaigns/{campaign}/launch',
        desc: 'Start dialing the queue within calling hours.',
        needsId: 'campaign',
        readOnlyInstead: (ids) => ({ path: `/api/campaigns/${ids.campaign}/dashboard` }),
        insteadNote: 'Launching would really start phone calls - dashboard shown instead.',
      },
      {
        key: 'camp-pause',
        method: 'POST',
        path: '/api/campaigns/{campaign}/pause',
        desc: 'Pause an in-flight campaign.',
        needsId: 'campaign',
        readOnlyInstead: (ids) => ({ path: `/api/campaigns/${ids.campaign}` }),
        insteadNote: 'Pausing changes real calling state - detail shown instead.',
      },
      {
        key: 'camp-cancel',
        method: 'POST',
        path: '/api/campaigns/{campaign}/cancel',
        desc: 'Cancel a campaign permanently.',
        needsId: 'campaign',
        readOnlyInstead: (ids) => ({ path: `/api/campaigns/${ids.campaign}` }),
        insteadNote: 'Canceling cannot be undone - detail shown instead.',
      },
      {
        key: 'camp-dashboard',
        method: 'GET',
        path: '/api/campaigns/{campaign}/dashboard',
        desc: 'Live counters + recent calls snapshot.',
        needsId: 'campaign',
      },
      {
        key: 'camp-contacts',
        method: 'GET',
        path: '/api/campaigns/{campaign}/contacts',
        desc: 'Paginated contacts of a campaign.',
        needsId: 'campaign',
      },
      {
        key: 'camp-import',
        method: 'POST',
        path: '/api/campaigns/{campaign}/contacts/import',
        desc: 'Bulk-import CSV/XLSX with column mapping (multipart).',
        needsId: 'campaign',
        readOnlyInstead: (ids) => ({ path: `/api/campaigns/${ids.campaign}/contacts` }),
        insteadNote: 'Import needs a file upload - the contacts list is shown instead.',
      },
      {
        key: 'camp-export-csv',
        method: 'GET',
        path: '/api/campaigns/{campaign}/export?format=csv',
        desc: 'Export results as CSV (streams a download).',
        needsId: 'campaign',
      },
      {
        key: 'camp-export-xlsx',
        method: 'GET',
        path: '/api/campaigns/{campaign}/export?format=xlsx',
        desc: 'Export results as XLSX (binary; preview truncated).',
        needsId: 'campaign',
      },
    ],
  },
  {
    router: 'Calls & domains',
    entries: [
      {
        key: 'call-get',
        method: 'GET',
        path: '/api/calls/{call}',
        desc: 'Call record: transcript, fields, latency, cost.',
        needsId: 'call',
      },
      {
        key: 'domains-list',
        method: 'GET',
        path: '/api/domain-configs',
        desc: 'Legacy domain-config list (read-only compatibility).',
      },
      {
        key: 'test-call',
        method: 'POST',
        path: '/api/test-call',
        desc: 'Place a single telephony test call (uses real minutes).',
        readOnlyInstead: () => ({ path: '/api/domain-configs' }),
        insteadNote: 'This dials a REAL phone number by design - not fired from here.',
      },
    ],
  },
  {
    router: 'Dev tools (/api/health, /api/dev/status)',
    entries: [
      {
        key: 'dev-health',
        method: 'GET',
        path: '/api/health',
        desc: 'DB ping + provider-key presence booleans.',
      },
      {
        key: 'dev-status',
        method: 'GET',
        path: '/api/dev/status',
        desc: 'Calling hours, CPS/concurrency limits, alembic head.',
      },
    ],
  },
];

const LATENCY_GLOSSARY = [
  {
    key: 'stt_final_ms',
    name: 'STT final',
    color: '#2563eb',
    text: 'From the caller stopping speech to the speech-to-text engine returning its final transcript for that utterance (Deepgram nova-3 final hypothesis).',
  },
  {
    key: 'llm_first_token_ms',
    name: 'LLM first token',
    color: '#7c3aed',
    text: 'From final transcript to the language model emitting its first token - includes prompt assembly and tool-call decision time (Groq-hosted fast model).',
  },
  {
    key: 'tts_first_audio_ms',
    name: 'TTS first audio',
    color: '#16a34a',
    text: 'From chosen reply text to the first synthesized audio chunk reaching the room (Cartesia streaming synthesis).',
  },
  {
    key: 'e2e_ms',
    name: 'End-to-end (speech-to-speech)',
    color: '#d97706',
    text: 'Caller stops speaking -> caller hears the reply begin. THE user-perceived number; it is what the NFR measures.',
  },
];

function truncate(text, max = 1200) {
  if (text == null) return '';
  const s = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
  return s.length > max ? `${s.slice(0, max)}\n... (${s.length} chars total)` : s;
}

export default function DevToolsPage() {
  // The page is login-protected (mounted under AuthShell). It is hidden only
  // when explicitly disabled via VITE_DISABLE_DEVTOOLS=true at build time, so
  // the docker dev stack (always a PROD vite build) keeps its status view.
  // Previously this gated on import.meta.env.PROD, which compiled the page
  // out of exactly the environment where it is needed.
  if (import.meta.env.VITE_DISABLE_DEVTOOLS === 'true') {
    return <div className="empty-state">Dev tools are disabled in production builds.</div>;
  }
  return <DevToolsInner />;
}

function DevToolsInner() {
  const { data: health, error: healthError, loading: healthLoading } = usePoll('/api/health', 10000);
  const { data: status, error: statusError } = usePoll('/api/dev/status', 10000);

  const [usage, setUsage] = useState(null);
  const [usageError, setUsageError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  function loadUsage() {
    analyticsApi
      .usage()
      .then((data) => {
        setUsage(data);
        setUsageError(null);
      })
      .catch((e) => setUsageError(e.message || String(e)));
  }

  useEffect(loadUsage, []);

  // Deepgram/Cartesia balances are polled daily by the backend; this asks for
  // a fresh pull right now.
  function refreshUsage() {
    setRefreshing(true);
    devApi
      .refreshUsage()
      .catch(() => {})
      .then(() => analyticsApi.usage())
      .then((data) => {
        setUsage(data);
        setUsageError(null);
      })
      .catch((e) => setUsageError(e.message || String(e)))
      .finally(() => setRefreshing(false));
  }

  const usageKeys = usage && Array.isArray(usage.keys) ? usage.keys : [];
  const usageAlerts = usage && Array.isArray(usage.alerts) ? usage.alerts : [];
  const sarvam = usage && usage.sarvam ? usage.sarvam : null;

  const [outputs, setOutputs] = useState({});
  const idsRef = useRef({});

  async function ensureIds(kinds) {
    const ids = idsRef.current;
    for (const kind of kinds) {
      if (ids[kind] != null && ids[kind] !== 'missing') continue;
      try {
        if (kind === 'agent') {
          const list = await apiGet('/api/agents');
          ids.agent = list && list[0] ? list[0].id : 'missing';
        } else if (kind === 'version') {
          const list = await apiGet('/api/agents');
          const first = list && list[0];
          if (!first) {
            ids.version = 'missing';
          } else if (first.current_version_id != null) {
            ids.version = first.current_version_id;
          } else {
            const vs = await apiGet(`/api/agents/${first.id}/versions`);
            ids.version = vs && vs.length ? vs[vs.length - 1].id : 'missing';
          }
        } else if (kind === 'campaign') {
          const list = await apiGet('/api/campaigns');
          ids.campaign = list && list[0] ? list[0].id : 'missing';
        } else if (kind === 'call') {
          const camps = await apiGet('/api/campaigns');
          let callId = null;
          if (camps && camps.length) {
            try {
              const dash = await apiGet(`/api/campaigns/${camps[0].id}/dashboard`);
              callId = dash && dash.recent_calls && dash.recent_calls[0] ? dash.recent_calls[0].id : null;
            } catch {
              callId = null;
            }
          }
          ids.call = callId != null ? callId : 'missing';
        }
      } catch {
        ids[kind] = 'missing';
      }
    }
    idsRef.current = ids;
    return ids;
  }

  async function tryEntry(entry) {
    setOutputs((o) => ({ ...o, [entry.key]: { ...(o[entry.key] || {}), running: true } }));
    const started = performance.now();
    const finish = (patch) =>
      setOutputs((o) => ({
        ...o,
        [entry.key]: { ...patch, ms: Math.round(performance.now() - started), running: false },
      }));

    try {
      const needs = entry.needsId ? [entry.needsId] : [];
      const ids = needs.length ? await ensureIds(needs) : {};
      for (const kind of needs) {
        if (ids[kind] === 'missing') {
          finish({
            ok: false,
            note: `No ${kind} exists yet to point this request at - create one in the UI first.`,
            body: '',
          });
          return;
        }
      }

      let req;
      let note = '';
      if (entry.readOnlyInstead) {
        req = entry.readOnlyInstead(ids);
        note = entry.insteadNote || 'A read-only sample was fired instead.';
      } else if (entry.key === 'agents-create') {
        req = {
          path: '/api/agents',
          method: 'POST',
          body: { name: `Dev tools sample ${new Date().toLocaleTimeString()}`, description: 'Created from Dev Tools Try.' },
        };
        note = 'This really created an agent row - archive it from the Agents page when done.';
      } else if (entry.key === 'camp-create') {
        req = { path: '/api/campaigns', method: 'POST', body: { name: 'Dev tools sample campaign' } };
        note = 'Draft campaign created - it stays a harmless draft.';
      } else if (entry.key === 'pg-start') {
        req = { path: '/api/playground/sessions', method: 'POST', body: { agent_version_id: ids.version } };
        note = 'Session + LiveKit token issued (a playground call row was created).';
      } else {
        req = {
          path: fillPath(entry.path, ids),
          method: entry.method,
          ...(entry.body ? { body: entry.body(ids) } : {}),
        };
      }

      const headers = { Authorization: `Bearer ${getToken() || ''}` };
      if (req.body != null) headers['Content-Type'] = 'application/json';

      const res = await fetch(`${API_BASE}${req.path}`, {
        method: req.method || 'GET',
        headers,
        body: req.body != null ? JSON.stringify(req.body) : undefined,
      });
      const text = await res.text();
      finish({ ok: res.ok, status: res.status, note, body: truncate(text) });
    } catch (e) {
      finish({ ok: false, status: e.status, note: '', body: truncate(e.message || String(e)) });
    }
  }

  function fillPath(path, ids) {
    return path.replace(/\{(\w+)\}/g, (token, kind) => (ids[kind] != null ? String(ids[kind]) : token));
  }

  /** Raw GET that returns parsed JSON (used for id resolution). */
  function apiGet(path) {
    return fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${getToken() || ''}` } }).then((r) => {
      if (!r.ok) throw new Error(`GET ${path} failed (${r.status})`);
      return r.json();
    });
  }

  const providers = (health && health.providers) || {};

  return (
    <div className="devtools">
      <div className="dev-banner" role="note">
        <strong>DEV ONLY</strong> — this page disappears in production builds.
      </div>

      {/* ---- Service health ---- */}
      <section className="card">
        <h3 className="card-title">Service health</h3>
        <p className="hint">Polled every 10 seconds. Green = configured/reachable, red = missing or down.</p>
        {healthError && !health && (
          <div className="banner banner-error">
            {healthError} — is the backend running at your configured API URL?
          </div>
        )}
        {!health && healthLoading && (
          <div className="loading-page">
            <span className="spinner" /> Checking services…
          </div>
        )}
        {health && (
          <>
            <div className="health-grid">
              <HealthDot label="Database" state={boolToState(health.db)} />
              <HealthDot label="Voice worker" state={toState(health.voice_agent)} note={String(health.voice_agent)} />
              {Object.entries(providers).map(([name, ok]) => (
                <HealthDot key={name} label={`Provider: ${name}`} state={boolToState(ok)} />
              ))}
              {typeof health.livekit_ws !== 'undefined' && health.livekit_ws !== null && (
                <HealthDot label="LiveKit server" state={boolToState(health.livekit_ws)} />
              )}
              {health.egress && Object.entries(health.egress).map(([name, ok]) => (
                <HealthDot key={`egress-${name}`} label={`Reachable: ${name}`} state={boolToState(ok)} />
              ))}
            </div>
            {Object.entries(providers).some(([, ok]) => !ok) && (
              <p className="hint">
                Missing providers only matter for the features that use them — see the checklist below.
              </p>
            )}
          </>
        )}
      </section>

      {/* ---- Provider quotas ---- */}
      <section className="card">
        <div className="table-toolbar">
          <h3 className="card-title">Provider quotas</h3>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={refreshUsage}
            disabled={refreshing}
          >
            {refreshing ? 'Refreshing…' : 'Refresh balances'}
          </button>
        </div>
        <p className="hint">
          Which limit gets exhausted first. Groq reports token and request headroom in its response headers on every
          call; Sarvam is metered per character; Deepgram and Cartesia balances are polled daily or on demand.
        </p>

        {status && Array.isArray(status.llm_chain) && status.llm_chain.length > 0 && (
          <div className="quota-chain">
            <span className="quota-chain-label">Active LLM chain</span>
            {status.llm_chain.map((member, i) => (
              <span key={`${member.name}-${member.model}`} className="quota-chip" title={`Fallback ${i + 1}`}>
                {i + 1}. {PROVIDER_LABELS[member.name] || member.name} · {member.model}
              </span>
            ))}
          </div>
        )}

        {usageError && !usage && (
          <div className="banner banner-error" style={{ marginTop: 10 }}>
            Could not load usage: {usageError}
          </div>
        )}

        {usageAlerts.map((alert, i) => (
          <div
            key={`${alert.provider}-${alert.key_id}-${i}`}
            className={`banner ${alert.level === 'critical' ? 'banner-error' : 'banner-info'}`}
            style={{ marginTop: 10 }}
          >
            <strong>{alert.level === 'critical' ? 'Nearly exhausted' : 'Running low'}</strong>
            {' — '}
            {alert.message}
          </div>
        ))}

        <table className="tbl" style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Key</th>
              <th>Model</th>
              <th>Remaining</th>
              <th>Status</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {usageKeys.length === 0 && !usageError && (
              <tr>
                <td colSpan={6} className="table-state">
                  No provider usage recorded yet — place a call or hit <em>Refresh balances</em>. Groq quota fills in
                  automatically from the next call.
                </td>
              </tr>
            )}
            {usageKeys.map((key) => {
              const badge = USAGE_BADGE[key.status] || USAGE_BADGE.unknown;
              const requests = requestQuota(key.metrics);
              return (
                <tr key={`${key.provider}-${key.key_id}-${key.model}`}>
                  <td>{PROVIDER_LABELS[key.provider] || key.provider}</td>
                  <td className="mono">{key.key_id || '—'}</td>
                  <td className="mono">{key.model || '—'}</td>
                  <td>
                    {key.headline}
                    {requests && (
                      <div className="quota-sub">{requests}</div>
                    )}
                  </td>
                  <td>
                    <span className={`badge ${badge.cls}`}>{badge.label}</span>
                  </td>
                  <td className="mono">{fmtUsageTime(key.updated_at)}</td>
                </tr>
              );
            })}
            {sarvam && (
              <tr>
                <td>Sarvam (TTS)</td>
                <td className="mono">—</td>
                <td className="mono">
                  {sarvam.models && sarvam.models.length ? sarvam.models.join(', ') : '—'}
                </td>
                <td>
                  {fmtCount(sarvam.characters || 0)} chars · ₹{Number(sarvam.cost_inr || 0).toFixed(2)}
                  <div className="quota-sub">{sarvam.requests_last_minute ?? 0} req/min last minute</div>
                </td>
                <td>
                  <span className="badge cyan">metered per char</span>
                </td>
                <td className="mono">{fmtUsageTime(usage && usage.generated_at)}</td>
              </tr>
            )}
          </tbody>
        </table>
        <p className="hint" style={{ marginTop: 8 }}>
          Keys are masked and never leave the backend. Rows turn amber below 25% remaining and red below 10%. Only
          providers that publish a quota API appear here.
        </p>
      </section>

      {/* ---- Provider setup checklist ---- */}
      <section className="card">
        <h3 className="card-title">Provider &amp; environment checklist</h3>
        <p className="hint">From GET /api/dev/status. Each red item names the env var to set in backend/.env.</p>
        {statusError && !status && <div className="banner banner-error">{statusError}</div>}
        {status && (
          <>
            <ul className="check-list">
              {Object.entries(status.providers || {}).map(([name, ok]) => (
                <li key={name} className={ok ? 'check-ok' : 'check-missing'}>
                  <span className={`badge ${ok ? 'badge-green' : 'badge-red'}`}>{ok ? 'Set' : 'Missing'}</span>
                  <code>{name}</code>
                  {!ok && (
                    <span className="check-env">
                      → set{' '}
                      {(PROVIDER_ENV_VARS[name] || []).map((v) => (
                        <code key={v}>{v}</code>
                      ))}
                    </span>
                  )}
                </li>
              ))}
            </ul>

            <div className="stat-row dev-limits">
              <div className="stat-chip">
                <div className="stat-value">
                  {status.calling_hours ? `${status.calling_hours.start}–${status.calling_hours.end}` : '—'}
                </div>
                <div className="stat-label">
                  Calling window ({status.calling_hours ? status.calling_hours.timezone : ''})
                  {status.calling_hours && status.calling_hours.within_hours_now ? ' · within hours now' : ''}
                </div>
              </div>
              <div className="stat-chip">
                <div className="stat-value">{(status.limits && status.limits.cps) ?? '—'}</div>
                <div className="stat-label">Calls per second cap</div>
              </div>
              <div className="stat-chip">
                <div className="stat-value">{(status.limits && status.limits.concurrency) ?? '—'}</div>
                <div className="stat-label">Max concurrent calls</div>
              </div>
              <div className="stat-chip">
                <div className="stat-value">{(status.limits && status.limits.retry_max_attempts) ?? '—'}</div>
                <div className="stat-label">Retry attempts</div>
              </div>
              <div className="stat-chip">
                <div className="stat-value">{status.environment || '—'}</div>
                <div className="stat-label">Environment</div>
              </div>
              {status.alembic && (
                <div className="stat-chip">
                  <div className="stat-value dev-revision" title={String(status.alembic.db_revision)}>
                    {status.alembic.db_revision ? String(status.alembic.db_revision).slice(0, 8) : 'none'}
                  </div>
                  <div className="stat-label">DB migration head</div>
                </div>
              )}
            </div>
          </>
        )}
      </section>

      {/* ---- Endpoint catalog ---- */}
      <section className="card flush">
        <div className="table-toolbar">
          <h3 className="card-title">API endpoint catalog</h3>
          <span className="hint">
            “Try” fires a real request with your session. Destructive ones fire their read-only counterpart instead.
          </span>
        </div>
        {CATALOG_GROUPS.map((group) => (
          <div key={group.router} className="endpoint-group">
            <h4 className="endpoint-group-title">{group.router}</h4>
            {group.entries.map((entry) => {
              const out = outputs[entry.key];
              return (
                <div key={entry.key} className="endpoint-row">
                  <div className="endpoint-main">
                    <span className={`method-chip method-${entry.method.toLowerCase()}`}>{entry.method}</span>
                    <code className="endpoint-path">{entry.path}</code>
                    {entry.createsData && <span className="badge badge-amber">creates data</span>}
                  </div>
                  <p className="endpoint-desc">{entry.desc}</p>
                  <div className="endpoint-actions">
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={out && out.running}
                      onClick={() => tryEntry(entry)}
                    >
                      {out && out.running ? 'Running…' : 'Try'}
                    </button>
                    {out && out.status != null && (
                      <span className={`badge ${out.ok ? 'badge-green' : 'badge-red'}`}>
                        {out.status} · {out.ms} ms
                      </span>
                    )}
                  </div>
                  {out && (out.note || out.body != null) && (
                    <pre className="endpoint-output">
                      {out.note ? `# ${out.note}\n` : ''}
                      {out.body}
                    </pre>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </section>

      {/* ---- Latency glossary ---- */}
      <section className="card">
        <h3 className="card-title">Latency glossary</h3>
        <p className="hint">
          Every conversation turn records these four numbers; the Playground and Call Review pages chart them against
          the targets below.
        </p>
        <div className="glossary-grid">
          {LATENCY_GLOSSARY.map((m) => (
            <div key={m.key} className="glossary-item" style={{ borderLeftColor: m.color }}>
              <code>{m.key}</code>
              <p>{m.text}</p>
            </div>
          ))}
        </div>
        <div className="banner banner-info">
          Targets (NFR-1): end-to-end speech-to-speech latency <strong>median ≤ 900 ms</strong>,{' '}
          <strong>P95 ≤ 1.5 s</strong>. The thin tick on Playground bars marks the 900 ms median target.
        </div>
        <p className="hint">
          Related requirement: extraction confidence below 0.6 (or a required field still unfilled after three asks)
          flags the call for human review rather than guessing. See <Link to="/playground">Playground</Link> for live
          measurements.
        </p>
      </section>
    </div>
  );
}


