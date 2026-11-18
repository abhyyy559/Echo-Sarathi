import React from 'react';

const CARDS = [
  { key: 'queued', label: 'Queued', tone: 'blue' },
  { key: 'calling', label: 'Calling', tone: 'amber' },
  { key: 'completed', label: 'Completed', tone: 'green' },
  { key: 'no_answer', label: 'No answer', tone: 'orange' },
  { key: 'busy', label: 'Busy', tone: 'orange' },
  { key: 'failed', label: 'Failed', tone: 'red' },
];

export default function CountsCards({ counts = {}, inFlight }) {
  return (
    <div className="counts-grid">
      {typeof inFlight === 'number' && (
        <div className={`count-card cc-live${inFlight > 0 ? ' live' : ''}`}>
          <div className="count-value">
            {inFlight}
            {inFlight > 0 && <span className="live-dot" aria-hidden="true" />}
          </div>
          <div className="count-label">In flight</div>
        </div>
      )}
      {CARDS.map((c) => (
        <div key={c.key} className={`count-card cc-${c.tone}`}>
          <div className="count-value">{counts[c.key] ?? 0}</div>
          <div className="count-label">{c.label}</div>
        </div>
      ))}
      {counts.pending_review != null && (
        <div className="count-card cc-gray">
          <div className="count-value">{counts.pending_review}</div>
          <div className="count-label">Pending review</div>
        </div>
      )}
      {counts.total != null && (
        <div className="count-card cc-total">
          <div className="count-value">{counts.total}</div>
          <div className="count-label">Total contacts</div>
        </div>
      )}
    </div>
  );
}
