import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import StatusBadge from '../components/StatusBadge.jsx';

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
    <div>
      <div className="page-head">
        <div>
          <h2 className="page-title">Call history</h2>
          <p className="page-sub">Every conversation — phone and playground — with latency per call.</p>
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

      <div className="filters">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="completed">completed</option>
          <option value="no-answer">no-answer</option>
          <option value="busy">busy</option>
          <option value="failed">failed</option>
          <option value="in-progress">in-progress</option>
        </select>
        <input
          type="text"
          placeholder="Search agent or contact…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {calls && (
          <span style={{ alignSelf: 'center', color: 'var(--dim)', fontSize: '12.5px' }}>
            {filtered.length} results
          </span>
        )}
      </div>

      <div className="card" style={{ overflowX: 'auto' }}>
        <table className="tbl">
          <thead>
            <tr>
              <th></th>
              <th>#</th>
              <th>Status</th>
              <th>Agent</th>
              <th>Contact</th>
              <th>Started</th>
              <th>Duration</th>
              <th>E2E avg</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
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
                  <td><KindIcon kind={call.kind} /></td>
                  <td className="mono">#{call.id}</td>
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
