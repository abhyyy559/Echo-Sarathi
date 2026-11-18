import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { analyticsApi, billingApi } from '../api.js';
import StatusBadge from '../components/StatusBadge.jsx';
import '../workspace-pages.css';

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
  const [billing, setBilling] = useState(null);
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
    billingApi
      .summary()
      .then(setBilling)
      .catch(() => setBilling(null));
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

  return (
    <div className="es-workspace es-workspace-overview">
      <div className="page-head">
        <div>
          <h2 className="page-title">Overview</h2>
          <p className="page-sub">Review recent conversations, captured fields and workspace usage.</p>
        </div>
        <div className="head-actions">
          <Link to="/playground" className="btn primary">Test an agent</Link>
        </div>
      </div>

      {error && (
        <div className="banner banner-error" role="alert">
          {error}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={load}>Retry</button>
        </div>
      )}
      {loading && !summary && (
        <div className="loading-page" role="status">
          <span className="spinner" aria-hidden="true" /> Loading analytics…
        </div>
      )}

      {summary && (
        <div className="es-workspace-overview-grid">
          <div className="es-workspace-stack">
            <section className="card" aria-labelledby="overview-recent-title">
              <div className="card-h">
                <div>
                  <h3 id="overview-recent-title">Recent calls</h3>
                  <p className="hint">Open a call to review its fields and transcript.</p>
                </div>
                <Link to="/calls">View call history</Link>
              </div>
              <div className="es-workspace-table-scroll" role="region" aria-label="Recent calls" tabIndex={0}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th scope="col">Call</th>
                      <th scope="col">Status</th>
                      <th scope="col">Agent</th>
                      <th scope="col">Started / duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentCalls.length === 0 && (
                      <tr>
                        <td colSpan={4} className="table-state">
                          <strong>No calls recorded yet.</strong>
                          <p>Configure an <Link to="/agents">agent</Link>, then test it in the <Link to="/playground">Playground</Link>.</p>
                        </td>
                      </tr>
                    )}
                    {recentCalls.map((call) => (
                      <tr key={call.id} onClick={() => navigate(`/calls/${call.id}`)}>
                        <td className="mono"><Link to={`/calls/${call.id}`} aria-label={`Review call ${call.id}`}>#{call.id}</Link></td>
                        <td><StatusBadge status={call.status} /></td>
                        <td>{call.agent_name || '—'}</td>
                        <td className="mono">
                          {fmtDateTime(call.started_at)}
                          {call.duration_seconds != null && (
                            <span className="es-workspace-cell-note">{fmtDuration(call.duration_seconds)}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="card" aria-labelledby="overview-volume-title">
              <div className="card-h">
                <h3 id="overview-volume-title">Call volume</h3>
                <span>Last 7 days, all agents</span>
              </div>
              <div className="es-workspace-chart-body">
                {calls7d.length === 0 && <p className="hint">Daily call counts are not available yet.</p>}
                <div className="chart" role="list" aria-label="Daily call counts">
                  {calls7d.map((day) => {
                    const h = day.count === 0 ? 0 : Math.max(4, Math.round((day.count / maxDayCount) * 100));
                    const date = new Date(`${day.date}T00:00:00`);
                    const label = Number.isNaN(date.getTime())
                      ? day.date.slice(5)
                      : date.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' });
                    return (
                      <div key={day.date} className="bar" role="listitem" aria-label={`${day.count} calls · ${label}`} data-v={day.count} title={`${day.count} calls · ${label}`}>
                        <span className="es-workspace-bar-count" aria-hidden="true">{day.count}</span>
                        <i style={{ height: `${h}%` }} aria-hidden="true" />
                        <em aria-hidden="true">{label}</em>
                      </div>
                    );
                  })}
                </div>
              </div>
              <p className="es-workspace-section-note">Bars show recorded calls per day, not successful outcomes.</p>
            </section>
          </div>

          <aside className="es-workspace-stack" aria-label="Usage and performance">
            <section className="card pad">
              <h3 className="card-title">Usage &amp; performance</h3>
              <dl className="es-workspace-facts">
                <div><dt>Total calls</dt><dd>{summary.total_calls != null ? summary.total_calls.toLocaleString() : '—'}<small>{summary.completed_calls != null ? `${summary.completed_calls.toLocaleString()} completed` : 'Completed count unavailable'}</small></dd></div>
                <div><dt>Success rate<small>Answered &amp; completed</small></dt><dd>{summary.success_rate_pct != null ? `${summary.success_rate_pct}%` : '—'}</dd></div>
                <div>
                  <dt>{summary.median_e2e_ms != null ? 'Median latency' : 'Average latency'}</dt>
                  <dd>{medianLatency != null ? `${medianLatency.toLocaleString()} ms` : '—'}
                    <small className={medianLatency == null ? '' : latencyOnTarget ? 'es-workspace-on-target' : 'es-workspace-warning'}>
                      {medianLatency == null ? 'Measurement unavailable' : latencyOnTarget ? 'Within 900 ms target' : 'Over 900 ms target'}
                    </small>
                  </dd>
                </div>
                <div><dt>Fields captured<small>Structured data points</small></dt><dd>{summary.total_extracted_fields != null ? summary.total_extracted_fields.toLocaleString() : '—'}</dd></div>
              </dl>
              <p className="hint">Latency targets: median ≤900 ms, p95 ≤1500 ms.</p>
            </section>
            <section className="card pad">
              <h3 className="card-title">Credits this month</h3>
              <dl className="es-workspace-facts">
                <div><dt>Spent</dt><dd>{billing?.spent_this_month_rupees != null ? `₹${Number(billing.spent_this_month_rupees).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}</dd></div>
                <div><dt>Minutes used</dt><dd>{billing?.minutes_used_this_month ?? '—'}</dd></div>
                <div><dt>Wallet balance</dt><dd>{billing?.balance_rupees != null ? `₹${Number(billing.balance_rupees).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}</dd></div>
              </dl>
              <Link to="/credits">View billing &amp; credits</Link>
            </section>
            <div className="es-workspace-next-action">
              <h3>Prepare your next campaign</h3>
              <p className="hint">Choose a saved agent version and review contacts before launching.</p>
              <Link to="/campaigns">View campaigns</Link>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
