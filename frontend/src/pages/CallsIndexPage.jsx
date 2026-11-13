import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import StatusBadge from '../components/StatusBadge.jsx';
import '../workspace-pages.css';

const PAGE_SIZE = 50;
const LATENCY_OVER_MS = 1500;

function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return '—';
  const s = Math.max(0, Math.round(Number(seconds)));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function KindIcon({ kind }) {
  if (kind === 'playground' || kind === 'web') {
    return (
      <span className="kicon" style={{ color: 'var(--brand)' }} title="Web test (Playground)" aria-label="Web call">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
          <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="1.8" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  return (
    <span className="kicon" title="Phone call" aria-label="Phone call">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
        <path d="M5 4h4l1.5 4.5L8 10a12 12 0 0 0 6 6l1.5-2.5L20 15v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2Z" stroke="currentColor" strokeWidth="1.8" />
      </svg>
    </span>
  );
}

export default function CallsIndexPage() {
  const navigate = useNavigate();
  const [calls, setCalls] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  function load() {
    setLoading(true);
    setError(null);
    api
      .listCalls({ limit: 500 })
      .then((rows) => setCalls(Array.isArray(rows) ? rows : []))
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  const filtered = useMemo(() => {
    if (!calls) return [];
    const q = searchQuery.toLowerCase();
    return calls.filter(
      (c) =>
        (!statusFilter || c.status === statusFilter) &&
        (!q ||
          (c.agent_name && c.agent_name.toLowerCase().includes(q)) ||
          (c.contact_name && c.contact_name.toLowerCase().includes(q)))
    );
  }, [calls, statusFilter, searchQuery]);

  const pageCount = filtered.length > 0 ? Math.max(1, Math.ceil(filtered.length / PAGE_SIZE)) : 1;
  const safePage = Math.min(page, pageCount);
  const pageRows = useMemo(
    () => filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    [filtered, safePage]
  );

  useEffect(() => {
    setPage(1);
  }, [calls, statusFilter, searchQuery]);

  return (
    <div className="es-workspace es-workspace-calls">
      <div className="page-head">
        <div>
          <h2 className="page-title">Call history</h2>
          <p className="page-sub">Review phone and Playground calls. Open a record for captured fields, transcript evidence and follow-up flags.</p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="banner banner-error">
          {error}{' '}
          <button type="button" className="btn btn-secondary btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      )}

      <section className="es-workspace-filter-panel" aria-label="Filter call history">
        <div className="filters">
          <div className="field">
            <label htmlFor="calls-status">Call status</label>
            <select id="calls-status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="no-answer">No answer</option>
              <option value="busy">Busy</option>
              <option value="failed">Failed</option>
              <option value="in-progress">In progress</option>
            </select>
          </div>
          <div className="field es-workspace-search">
            <label htmlFor="calls-search">Agent or contact name</label>
            <input
              id="calls-search"
              type="text"
              placeholder="Search by name…"
              aria-describedby="calls-filter-scope"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          {calls && <span className="es-workspace-result-count" role="status">{filtered.length} results</span>}
        </div>
        <p id="calls-filter-scope" className="hint">Filters apply to the loaded records, up to 500 calls. Phone and Playground calls appear together.</p>
      </section>

      <div className="card es-workspace-table-scroll" role="region" aria-label="Call records" tabIndex={0}>
        <table className="tbl" aria-busy={loading}>
          <thead>
            <tr>
              <th scope="col">Type</th>
              <th scope="col">Call</th>
              <th scope="col">Status</th>
              <th scope="col">Agent</th>
              <th scope="col">Contact</th>
              <th scope="col">Started</th>
              <th scope="col">Duration</th>
              <th scope="col">Avg. E2E latency</th>
              <th scope="col">Review</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={9} className="table-state" role="status">Loading call records…</td></tr>}
            {!loading && !error && filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="table-state">
                  {calls && calls.length === 0
                    ? `No calls yet — run one from the `
                    : 'No matching calls — try adjusting the filters.'}
                  {calls && calls.length === 0 && (
                    <>
                      <Link to="/playground">Playground</Link> or launch a{' '}
                      <Link to="/campaigns">campaign</Link>.
                    </>
                  )}
                </td>
              </tr>
            )}
            {pageRows.map((call) => {
              const startedAt = call.started_at || call.created_at;
              const startedLabel = startedAt
                ? new Date(startedAt).toLocaleString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })
                : '—';
              const latencyMs = call.avg_e2e_ms != null ? Math.round(call.avg_e2e_ms) : null;
              const latencyClass = latencyMs != null && latencyMs > LATENCY_OVER_MS ? ' over' : '';
              return (
                <tr key={call.id} className="clickable" onClick={() => navigate(`/calls/${call.id}`)}>
                  <td><span className="es-workspace-call-kind"><KindIcon kind={call.kind} /><span>{call.kind === 'playground' || call.kind === 'web' ? 'Playground' : 'Phone'}</span></span></td>
                  <td className="mono"><Link to={`/calls/${call.id}`} aria-label={`Review call ${call.id}`}>#{call.id}</Link></td>
                  <td><StatusBadge status={call.status} /></td>
                  <td>{call.agent_name || <span className="text-muted">—</span>}</td>
                  <td>
                    {call.contact_name ? (
                      <>
                        {call.contact_name}
                        {call.contact_phone && <span className="text-muted"> · {call.contact_phone}</span>}
                      </>
                    ) : (
                      <span className="text-muted">{call.kind === 'playground' ? 'Browser test' : '—'}</span>
                    )}
                  </td>
                  <td className="mono" title={startedAt ? new Date(startedAt).toLocaleString() : ''}>
                    {startedLabel}
                  </td>
                  <td className="mono">{fmtDuration(call.duration_seconds)}</td>
                  <td className={`mono${latencyClass}`}>
                    {latencyMs != null ? `${latencyMs.toLocaleString()} ms` : '—'}
                  </td>
                  <td>
                    {call.flagged_for_human ? (
                      <span className="flag" title="Escalated to human">⚑</span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {filtered.length > 0 && (
          <div className="pager">
            <span>
              Page {safePage} of {pageCount} · {filtered.length} calls
            </span>
            <button
              type="button"
              className="btn sm ghost"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              ← Prev
            </button>
            <button
              type="button"
              className="btn sm ghost"
              disabled={safePage >= pageCount}
              onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
