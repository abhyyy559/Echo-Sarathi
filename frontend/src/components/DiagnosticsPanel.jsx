import React, { useCallback, useEffect, useRef, useState } from 'react';
import { playgroundApi } from '../api.js';

/**
 * DiagnosticsPanel — the "is this actually working?" panel.
 *
 * The problem it solves: a stalled or wrong-sounding call used to be debuggable
 * only by scrolling docker logs after the fact. This shows, live, whether each
 * pipeline component is configured, which LLM provider served the last turn,
 * which ones were skipped and why, and the exact provider error when something
 * fails. No keys are ever rendered (the backend does not return them).
 *
 * `active` pauses the polling so an idle playground does not hammer the API.
 */

const POLL_MS = 1500;

const LEVEL_STYLE = {
  info: { color: '#64748b', label: 'info' },
  warn: { color: '#b45309', label: 'warn' },
  error: { color: '#b91c1c', label: 'error' },
};

function StatusDot({ ok }) {
  if (ok === null || ok === undefined) return <span className="dp-dot dp-dot-idle" title="not exercised yet" />;
  return (
    <span
      className={`dp-dot ${ok ? 'dp-dot-ok' : 'dp-dot-bad'}`}
      title={ok ? 'served successfully' : 'last attempt failed'}
    />
  );
}

function EventRow({ event }) {
  const style = LEVEL_STYLE[event.level] || LEVEL_STYLE.info;
  const provider = event.provider ? `${event.provider}${event.model ? ` (${event.model})` : ''}` : '';
  return (
    <div className={`dp-row dp-${event.level || 'info'}`}>
      <span className="dp-time">{event.at_iso}</span>
      <span className="dp-lvl" style={{ color: style.color }}>
        {style.label}
      </span>
      {provider && <span className="dp-prov">{provider}</span>}
      {event.status ? <span className="dp-status">{event.status}</span> : null}
      {event.latency_ms != null && <span className="dp-lat">{event.latency_ms}ms</span>}
      <span className="dp-msg">{event.message}</span>
    </div>
  );
}

export default function DiagnosticsPanel({ active = false, callId = null }) {
  const [diag, setDiag] = useState(null);
  const [events, setEvents] = useState([]);
  const [seq, setSeq] = useState(0);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(true);
  // Backs off when the API keeps failing so a broken backend is not hammered
  // every 1.5s from every open tab.
  const [backoffMs, setBackoffMs] = useState(POLL_MS);
  const seqRef = useRef(0);

  const loadDiag = useCallback(async () => {
    try {
      const data = await playgroundApi.diagnostics();
      setDiag(data);
      setError('');
      setBackoffMs(POLL_MS);
    } catch (err) {
      // A 500 from the API surfaces in the browser as a CORS/network error:
      // the server-error middleware sits ABOVE the CORS layer, so a 500
      // carries no CORS headers and fetch reports ERR_FAILED. Status 0 here
      // therefore means "the server answered, but with an error" as often as
      // "the server is down" - say which we can, and re-probe rather than
      // hammering every 1.5s.
      const status = err?.status;
      if (status === 0) {
        setError(
          'diagnostics: server error or unreachable (browser reports this as a CORS failure when the API returns 500)'
        );
        setBackoffMs((prev) => Math.min(prev ? prev * 2 : POLL_MS * 2, 15000));
      } else {
        setError(`diagnostics failed: HTTP ${status} ${err?.message || ''}`.trim());
        setBackoffMs(POLL_MS);
      }
    }
  }, []);

  const loadEvents = useCallback(async (since) => {
    try {
      const data = await playgroundApi.events(since);
      if (data.events?.length) {
        setEvents((prev) => [...prev, ...data.events].slice(-200));
      }
      seqRef.current = data.latest_seq ?? since;
      setSeq(seqRef.current);
    } catch (err) {
      setError(String(err?.message || err));
    }
  }, []);

  useEffect(() => {
    loadDiag();
    loadEvents(0);
  }, [loadDiag, loadEvents]);

  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => {
      loadDiag();
      loadEvents(seqRef.current);
    }, backoffMs);
    return () => clearInterval(id);
  }, [active, backoffMs, loadDiag, loadEvents]);

  const clear = async () => {
    try {
      await playgroundApi.clearEvents();
      setEvents([]);
      await loadEvents(0);
    } catch (err) {
      setError(String(err?.message || err));
    }
  };

  const components = diag?.components || {};
  const chain = diag?.llm_chain || [];
  const failing = chain.filter((m) => m.healthy && m.healthy.ok === false).length;

  return (
    <div className="dp-wrap">
      <button type="button" className="dp-head" onClick={() => setOpen((v) => !v)}>
        <span className="dp-title">Diagnostics</span>
        <span className="dp-sub">
          {chain.length} LLM provider{chain.length === 1 ? '' : 's'}
          {failing > 0 ? ` · ${failing} failing` : ''}
          {active ? ' · live' : ''}
        </span>
        <span className="dp-caret">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="dp-body">
          <div className="dp-grid">
            {Object.entries(components).map(([key, c]) => (
              <div key={key} className="dp-card">
                <div className="dp-card-top">
                  <span className="dp-card-name">{c.name}</span>
                  <span className={c.configured ? 'dp-ok' : 'dp-missing'}>
                    {c.configured ? 'configured' : 'MISSING'}
                  </span>
                </div>
                <div className="dp-card-req">{c.required_for}</div>
              </div>
            ))}
          </div>

          <div className="dp-chain">
            <div className="dp-section-title">LLM failover order</div>
            {chain.length === 0 && <div className="dp-missing">No provider armed</div>}
            {chain.map((m) => (
              <div key={`${m.provider}-${m.position}`} className="dp-member">
                <StatusDot ok={m.healthy ? m.healthy.ok : null} />
                <span className="dp-pos">{m.position}</span>
                <span className="dp-name">{m.provider}</span>
                <span className="dp-model">{m.model}</span>
                {m.reasoning_model && <span className="dp-tag">reasoning</span>}
                <span className="dp-cap">cap {m.output_cap}</span>
                {m.healthy && m.healthy.latency_ms != null && (
                  <span className="dp-lat">{m.healthy.latency_ms}ms</span>
                )}
              </div>
            ))}
          </div>

          <div className="dp-section-title">
            Live events
            <button type="button" className="dp-clear" onClick={clear}>
              clear
            </button>
          </div>
          {error && <div className="dp-error">{error}</div>}
          <div className="dp-log">
            {events.length === 0 && <div className="dp-empty">No events yet. Start a session and talk.</div>}
            {events.map((e) => (
              <EventRow key={e.seq} event={e} />
            ))}
          </div>
          {callId != null && <div className="dp-foot">session {callId} · seq {seq}</div>}
        </div>
      )}
    </div>
  );
}
