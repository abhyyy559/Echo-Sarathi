const STATUS_ACTIVITY = {
  queued: { label: 'Placing call', detail: 'Waiting for the call to start.' },
  ringing: { label: 'Ringing', detail: 'The call is ringing.' },
  in_progress: { label: 'Connecting AI agent', detail: 'Waiting for a live activity update.' },
  completed: { label: 'Call completed', detail: 'The call has completed.' },
  failed: { label: 'Call failed', detail: 'The call ended without completing.' },
  no_answer: { label: 'No answer', detail: 'The call was not answered.' },
  busy: { label: 'Busy', detail: 'The line was busy.' },
  canceled: { label: 'Call canceled', detail: 'The call was canceled.' },
  cancelled: { label: 'Call canceled', detail: 'The call was canceled.' },
  invalid: { label: 'Invalid number', detail: 'The call number was invalid.' },
};

const ACTIVITY_ACTIVITY = {
  agent_connecting: { label: 'Connecting AI agent', detail: 'The AI agent is connecting.' },
  listening: { label: 'Listening', detail: 'The AI agent is listening.' },
  understanding: { label: 'Understanding', detail: 'The AI agent is understanding the response.' },
  agent_speaking: { label: 'Speaking', detail: 'The AI agent is speaking.' },
};

const UNAVAILABLE_ACTIVITY = { label: 'Call status unavailable', detail: 'No call activity is available.' };
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'no_answer', 'busy', 'canceled', 'cancelled', 'invalid']);

function normalizeState(value) {
  return String(value ?? '').trim().toLowerCase().replace(/-/g, '_');
}

function getActivityState(call) {
  if (call.activity && typeof call.activity === 'object') {
    return normalizeState(call.activity.state);
  }
  if (typeof call.activity === 'string') {
    return normalizeState(call.activity);
  }
  return normalizeState(call.activity_state);
}

function activityResult(activity) {
  return { label: activity.label, detail: activity.detail };
}

export function resolveCallActivity(call) {
  if (!call || typeof call !== 'object') return activityResult(UNAVAILABLE_ACTIVITY);

  const status = normalizeState(call.status);
  if (TERMINAL_STATUSES.has(status)) {
    return activityResult(STATUS_ACTIVITY[status]);
  }

  if (status === 'queued') return activityResult(STATUS_ACTIVITY.queued);
  if (status === 'ringing') return activityResult(STATUS_ACTIVITY.ringing);

  const activity = ACTIVITY_ACTIVITY[getActivityState(call)];
  if (activity) return activityResult(activity);

  if (status === 'in_progress') return activityResult(STATUS_ACTIVITY.in_progress);
  return activityResult(UNAVAILABLE_ACTIVITY);
}
