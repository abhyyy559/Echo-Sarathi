import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { playgroundApi } from '../api.js';

/**
 * LiveConsole — terminal-style log of everything happening in the call.
 *
 * The problem it solves: "is it listening or not" was only answerable by
 * tailing docker logs on the server. This renders the same event stream the
 * backend records (LLM attempts, STT finals/partials, TTS audio, agent and
 * caller state changes, failovers) plus frontend-side rows (microphone,
 * room connection), exactly as they happen, in one scrolling view.
 *
 * `active` gates polling. `localRows` are frontend-side status rows
 * ({at_iso, tag, level, message}) for mic/room/websocket state, which the
 * backend can never see.
 */

const POLL_MS = 1200;

function levelColor(level) {
  if (level === 'error') return '#f87171';
  if (level === 'warn') return '#fbbf24';
  return '#9ca3af';
}

function kindTag(kind) {
  const map = {
    stt_final: 'STT',
    stt_partial: 'stt~',
    tts_first_audio: 'TTS',
    agent_state: 'AGENT',
    user_state: 'YOU',
    audio_track_subscribed: 'AUDIO',
    audio_track_unsubscribed: 'AUDIO',
    llm_attempt: 'LLM',
    llm_handoff: 'XFR',
    llm_skip: 'XFR',
    llm_quota_shared: 'XFR',
    llm_quota_wait: 'XFR',
    llm_quota_exhausted: 'XFR',
    llm_chain_exhausted: 'LLM',
    llm_tool_conflict: 'LLM',
    llm_chain_start: 'LLM',
    llm_quota_exhausted2: 'LLM',
    extraction_backfill: 'EXT',
    stall_filler: 'STALL',
    stall_recovery: 'STALL',
    voice_session_start: 'VOICE',
    voice_provider_problem: 'VOICE',
  };
  return map[kind] || 'GEN';
}

/** Derive "what is the agent doing right now" from the event stream. */
export function agentStatusFromEvents(events) {
  let agent = null;
  let user = null;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i];
    if (e.kind === 'agent_state' && agent === null) {
      const m = /->\s*(\w+)/.exec(e.message || '');
      agent = m ? m[1] : null;
    }
    if (e.kind === 'user_state' && user === null) {
      const m = /->\s*(\w+)/.exec(e.message || '');
      user = m ? m[1] : null;
    }
    if (agent !== null && user !== null) break;
  }
  if (user === 'speaking') return { label: 'you are speaking', tone: 'you' };
  if (agent === 'speaking') return { label: 'agent speaking', tone: 'speaking' };
  if (agent === 'thinking') return { label: 'agent thinking', tone: 'thinking' };
  if (agent === 'listening' || agent === 'idle') return { label: 'listening', tone: 'idle' };
  return { label: 'idle', tone: 'idle' };
}

export default function LiveConsole({ active = false, localRows = [] }) {
  const [events, setEvents] = useState([]);
  const [error, setError] = useState('');
  const seqRef = useRef(0);
  const boxRef = useRef(null);
  const stickRef = useRef(true);

  const load = useCallback(async () => {
    try {
      const data = await playgroundApi.events(seqRef.current);
      if (data.events?.length) {
        setEvents((prev) => [...prev, ...data.events].slice(-300));
      }
      seqRef.current = data.latest_seq ?? seqRef.current;
      setError('');
    } catch (err) {
      setError(String(err?.message || err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [active, load]);

  // Auto-scroll only while the user hasn't scrolled up.
  useEffect(() => {
    const box = boxRef.current;
    if (box && stickRef.current) box.scrollTop = box.scrollHeight;
  }, [events, localRows]);

  const status = useMemo(() => agentStatusFromEvents(events), [events]);

  const rows = useMemo(() => {
    const server = events.map((e) => ({
      at: e.at_iso,
      seq: e.seq,
      tag: kindTag(e.kind),
      level: e.level || 'info',
      text: [
        e.provider ? `[${e.provider}${e.model ? `:${e.model}` : ''}]` : '',
        e.status ? `${e.status}` : '',
        e.latency_ms != null ? `${e.latency_ms}ms` : '',
        e.message || '',
      ]
        .filter(Boolean)
        .join(' '),
    }));
    const local = (localRows || []).map((r, i) => ({
      at: r.at_iso,
      seq: `local-${i}-${r.at_iso}`,
      tag: r.tag || 'UI',
      level: r.level || 'info',
      text: r.message || '',
    }));
    return [...server, ...local].sort((a, b) => String(a.at).localeCompare(String(b.at))).slice(-300);
  }, [events, localRows]);

  return (
    <div className="lc-wrap">
      <div className="lc-head">
        <span className={`lc-status lc-${status.tone}`}>{status.label}</span>
        <span className="lc-sub">live console</span>
      </div>
      <div
        className="lc-box"
        ref={boxRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {rows.length === 0 && <div className="lc-empty">No events yet. Start a session and talk.</div>}
        {rows.map((r) => (
          <div key={r.seq} className="lc-row">
            <span className="lc-time">{r.at}</span>
            <span className="lc-tag">{r.tag}</span>
            <span className="lc-msg" style={{ color: levelColor(r.level) }}>
              {r.text}
            </span>
          </div>
        ))}
        {error && <div className="lc-row lc-err">feed error: {error}</div>}
      </div>
    </div>
  );
}
