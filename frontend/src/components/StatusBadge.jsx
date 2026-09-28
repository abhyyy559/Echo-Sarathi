import React from 'react';

const STATUS_META = {
  // campaigns
  draft: { cls: 'gray', label: 'Draft' },
  created: { cls: 'gray', label: 'Created' },
  running: { cls: 'green', label: 'Running' },
  paused: { cls: 'amber', label: 'Paused' },
  canceled: { cls: 'gray', label: 'Canceled' },
  cancelled: { cls: 'gray', label: 'Canceled' },
  // shared
  pending_review: { cls: 'gray', label: 'Pending review' },
  invalid: { cls: 'dark-red', label: 'Invalid' },
  queued: { cls: 'blue', label: 'Queued' },
  in_progress: { cls: 'blue', label: 'In progress' },
  answered: { cls: 'blue', label: 'Answered' },
  completed: { cls: 'green', label: 'Completed' },
  // calls / contacts
  calling: { cls: 'amber', label: 'Calling' },
  'queued-call': { cls: 'amber', label: 'Queued call' },
  ringing: { cls: 'amber', label: 'Ringing' },
  no_answer: { cls: 'orange', label: 'No answer' },
  busy: { cls: 'orange', label: 'Busy' },
  failed: { cls: 'red', label: 'Failed' },
  opted_out: { cls: 'purple', label: 'Opted out' },
  skipped: { cls: 'gray', label: 'Skipped' },
  escalated: { cls: 'red-outline', label: 'Escalated' },
  flagged: { cls: 'red-outline', label: 'Flagged' },
};

function titleize(value) {
  return String(value)
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function statusLabel(status) {
  const meta = STATUS_META[status];
  return meta ? meta.label : titleize(status);
}

export function statusClass(status) {
  const meta = STATUS_META[status];
  return meta ? meta.cls : 'gray';
}

export default function StatusBadge({ status }) {
  if (status == null || status === '') {
    return <span className="badge badge-gray">—</span>;
  }
  return <span className={`badge badge-${statusClass(status)}`}>{statusLabel(status)}</span>;
}
