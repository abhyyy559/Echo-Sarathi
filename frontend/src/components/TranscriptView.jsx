import React from 'react';
import { cleanTranscriptText } from '../utils/transcript.js';

const AGENT_SPEAKERS = new Set(['agent', 'ai', 'bot', 'assistant', 'system', 'voice_agent']);

function speakerIsAgent(speaker) {
  return AGENT_SPEAKERS.has(String(speaker || '').toLowerCase());
}

function titleCase(s) {
  return String(s)
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function fmtClock(value) {
  if (value == null) return null;
  if (typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value))) {
    const s = Math.max(0, Math.round(Number(value)));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }
  const d = new Date(value);
  if (!Number.isNaN(d.getTime())) {
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  return null;
}

/**
 * Speaker-colored transcript turns.
 * turns: [{ turn_index?, speaker, text, timestamp? }]
 */
export default function TranscriptView({ turns, emptyText }) {
  const list = Array.isArray(turns) ? turns : [];
  if (!list.length) {
    return <p className="hint">{emptyText || 'No turns recorded.'}</p>;
  }
  return (
    <div className="transcript" aria-live="polite">
      {list.map((t, i) => {
        const agent = speakerIsAgent(t.speaker);
        const clock = fmtClock(t.timestamp);
        return (
          <div
            key={t.turn_index != null ? `turn-${t.turn_index}` : `i-${i}`}
            className={`bubble-row ${agent ? 'agent' : 'caller'}`}
          >
            <div className={`bubble ${agent ? 'bubble-agent' : 'bubble-caller'}`}>
              <div className="bubble-meta">
                <span className="bubble-speaker">{agent ? 'Agent' : t.speaker ? titleCase(t.speaker) : 'Caller'}</span>
                {clock && <span className="bubble-time">{clock}</span>}
              </div>
              <div className="bubble-text">{cleanTranscriptText(t.text)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
