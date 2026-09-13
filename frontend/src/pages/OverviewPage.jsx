import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { analyticsApi } from '../api.js';
import StatusBadge from '../components/StatusBadge.jsx';

const LATENCY_TARGET_MS = 900;

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
        </>
      )}
    </div>
  );
}
