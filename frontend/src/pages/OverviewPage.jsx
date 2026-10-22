import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { analyticsApi, devApi } from '../api.js';
import StatusBadge from '../components/StatusBadge.jsx';

const LATENCY_TARGET_MS = 900;

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

function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return '—';
  const s = Math.max(0, Math.round(Number(seconds)));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function fmtDateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function OverviewPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [costs, setCosts] = useState(null);
  const [usage, setUsage] = useState(null);
  const [usageError, setUsageError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    setError(null);
    analyticsApi
      .summary()
      .then(setSummary)
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
    analyticsApi
      .costs()
      .then(setCosts)
      .catch(() => setCosts(null));
    analyticsApi
      .usage()
      .then((data) => {
        setUsage(data);
        setUsageError(null);
      })
      .catch((e) => setUsageError(e.message || String(e)));
  }

  // The Deepgram/Cartesia balances are polled daily by the backend; this asks
  // for a fresh pull right now so the operator can act on the numbers.
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

  useEffect(load, []);

  const medianLatency =
    summary && summary.median_e2e_ms != null
      ? Math.round(summary.median_e2e_ms)
      : summary && summary.avg_e2e_ms != null
        ? Math.round(summary.avg_e2e_ms)
        : null;
  const latencyOnTarget = medianLatency != null && medianLatency <= LATENCY_TARGET_MS;
  // Fresh/empty backends may omit these arrays — never let a missing field
  // blank the whole dashboard.
  const calls7d = summary && Array.isArray(summary.calls_last_7d) ? summary.calls_last_7d : [];
  const recentCalls = summary && Array.isArray(summary.recent_calls) ? summary.recent_calls : [];
  const maxDayCount = Math.max(1, ...calls7d.map((d) => d.count));
  const monthKey = new Date().toISOString().slice(0, 7);
  const monthCosts = costs && costs.monthly ? costs.monthly[monthKey] : null;
  const usageKeys = usage && Array.isArray(usage.keys) ? usage.keys : [];
  const usageAlerts = usage && Array.isArray(usage.alerts) ? usage.alerts : [];
  const sarvam = usage && usage.sarvam ? usage.sarvam : null;

  return (
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Overview</h2>
          <p className="page-sub">
            Health of your voice operations, updated live.
          </p>
        </div>
        <div className="head-actions">
          <Link to="/playground" className="btn primary">
            Test an agent
          </Link>
        </div>
      </div>

      {error && (
        <div className="banner banner-error">
          {error}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {loading && !summary && (
        <div className="loading-page">
          <span className="spinner" /> Loading analytics…
        </div>
      )}

      {summary && (
        <>
          <div className="grid g5">
            <div className="card stat">
              <div className="lbl">Total calls</div>
              <div className="num">{summary.total_calls != null ? summary.total_calls.toLocaleString() : '—'}</div>
              <div className="foot">{summary.completed_calls != null ? `${summary.completed_calls.toLocaleString()} completed` : '— completed'}</div>
            </div>
            <div className="card stat">
              <div className="lbl">Success rate</div>
              <div className="num">{summary.success_rate_pct != null ? `${summary.success_rate_pct}%` : '—'}</div>
              <div className="foot">answered &amp; completed</div>
            </div>
            <div className="card stat">
              <div className="lbl">Median latency</div>
              <div className="num">{medianLatency != null ? `${medianLatency.toLocaleString()} ms` : '—'}</div>
              <div className="foot">
                <span className={`badge${latencyOnTarget || medianLatency == null ? ' ok' : ' warn'}`}>
                  {medianLatency == null
                    ? 'target ≤900ms'
                    : latencyOnTarget
                      ? '✓ on target ≤900ms'
                      : '▲ over target'}
                </span>
              </div>
            </div>
            <div className="card stat">
              <div className="lbl">Fields captured</div>
              <div className="num">{summary.total_extracted_fields != null ? summary.total_extracted_fields.toLocaleString() : '—'}</div>
              <div className="foot">structured data points</div>
            </div>
            <div className="card stat">
              <div className="lbl">Est. spend</div>
              <div className="num">{monthCosts ? `$${monthCosts.est_cost_usd.toFixed(2)}` : costs ? '$0.00' : '$—'}</div>
              <div className="foot">
                {monthCosts
                  ? `${monthCosts.minutes.toLocaleString()} min this month`
                  : '— min this month'}
              </div>
            </div>
          </div>

          <div className="grid g2" style={{ marginTop: 18 }}>
            <div className="card">
              <div className="card-h">
                <h3>Calls — last 7 days</h3>
                <span>all agents</span>
              </div>
              <div style={{ padding: '20px 22px' }}>
                <div className="chart">
                  {calls7d.map((day) => {
                    const h = day.count === 0 ? 0 : Math.max(4, Math.round((day.count / maxDayCount) * 100));
                    const date = new Date(`${day.date}T00:00:00`);
                    const label = Number.isNaN(date.getTime())
                      ? day.date.slice(5)
                      : date.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' });
                    return (
                      <div key={day.date} className="bar" data-v={day.count} title={`${day.count} calls · ${label}`}>
                        <i style={{ height: `${h}%` }} />
                        <em>{label}</em>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div style={{ padding: '0 22px 16px', fontSize: 12, color: 'var(--dim)' }}>
                Latency targets — median ≤900ms · p95 ≤1500ms. Bars show total calls per day.
              </div>
            </div>

            <div className="card">
              <div className="card-h">
                <h3>Recent calls</h3>
                <Link to="/calls" style={{ color: 'var(--brand)', fontSize: 13 }}>View all →</Link>
              </div>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Status</th>
                    <th>Agent</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {recentCalls.length === 0 && (
                    <tr>
                      <td colSpan={4} className="table-state">
                        No calls yet — run one from the{' '}
                        <Link to="/playground">Playground</Link>.
                      </td>
                    </tr>
                  )}
                  {recentCalls.map((call) => (
                    <tr key={call.id} onClick={() => navigate(`/calls/${call.id}`)}>
                      <td className="mono">#{call.id}</td>
                      <td>
                        <StatusBadge status={call.status} />
                      </td>
                      <td>{call.agent_name || '—'}</td>
                      <td className="mono">
                        {fmtDateTime(call.started_at)}
                        {call.duration_seconds != null && (
                          <> · {fmtDuration(call.duration_seconds)}</>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <div className="card-h">
              <h3>API keys &amp; limits</h3>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={refreshUsage}
                disabled={refreshing}
              >
                {refreshing ? 'Refreshing…' : 'Refresh balances'}
              </button>
            </div>

            {usageError && (
              <div style={{ padding: '12px 22px', fontSize: 13, color: 'var(--red)' }}>
                Could not load usage: {usageError}
              </div>
            )}

            {usageAlerts.length > 0 && (
              <div style={{ padding: '12px 22px 0' }}>
                {usageAlerts.map((alert, i) => (
                  <div
                    key={`${alert.provider}-${alert.key_id}-${i}`}
                    className={`banner ${alert.level === 'critical' ? 'banner-error' : 'banner-info'}`}
                    style={{ marginBottom: 8 }}
                  >
                    <strong>{alert.level === 'critical' ? 'Nearly exhausted' : 'Running low'}</strong>
                    {' — '}
                    {alert.message}
                  </div>
                ))}
              </div>
            )}

            <table className="tbl">
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
                      No provider usage recorded yet — place a call or hit{' '}
                      <em>Refresh balances</em>. Groq quota fills in automatically
                      from the next call.
                    </td>
                  </tr>
                )}
                {usageKeys.map((key) => {
                  const badge = USAGE_BADGE[key.status] || USAGE_BADGE.unknown;
                  return (
                    <tr key={`${key.provider}-${key.key_id}-${key.model}`}>
                      <td>{PROVIDER_LABELS[key.provider] || key.provider}</td>
                      <td className="mono">{key.key_id || '—'}</td>
                      <td className="mono">{key.model || '—'}</td>
                      <td>{key.headline}</td>
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
                    <td className="mono">
                      {sarvam.models && sarvam.models.length ? sarvam.models.join(', ') : '—'}
                    </td>
                    <td className="mono">{sarvam.requests_last_minute ?? 0} req/min</td>
                    <td>
                      {Number(sarvam.characters || 0).toLocaleString()} chars · ₹
                      {Number(sarvam.cost_inr || 0).toFixed(2)}
                    </td>
                    <td>
                      <span className="badge cyan">metered per char</span>
                    </td>
                    <td className="mono">{fmtUsageTime(usage && usage.generated_at)}</td>
                  </tr>
                )}
              </tbody>
            </table>
            <div style={{ padding: '10px 22px 16px', fontSize: 12, color: 'var(--dim)' }}>
              Groq quota is captured from live response headers (shared across all
              keys in the org); Deepgram and Cartesia balances refresh daily or on
              demand. Rows turn amber below 25% remaining and red below 10%.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
