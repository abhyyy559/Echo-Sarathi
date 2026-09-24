import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveCallActivity } from './callActivity.js';

const cases = [
  {
    name: 'queued calls are being placed',
    call: { status: 'queued' },
    expected: { label: 'Placing call', detail: 'Waiting for the call to start.' },
  },
  {
    name: 'ringing calls show ringing',
    call: { status: 'ringing' },
    expected: { label: 'Ringing', detail: 'The call is ringing.' },
  },
  {
    name: 'in-progress calls without activity are connecting the agent',
    call: { status: 'in_progress' },
    expected: { label: 'Connecting AI agent', detail: 'Waiting for a live activity update.' },
  },
  {
    name: 'agent_connecting activity is connecting the agent',
    call: { status: 'in_progress', activity: { state: 'agent_connecting' } },
    expected: { label: 'Connecting AI agent', detail: 'The AI agent is connecting.' },
  },
  {
    name: 'listening activity is listening',
    call: { status: 'in_progress', activity: { state: 'listening' } },
    expected: { label: 'Listening', detail: 'The AI agent is listening.' },
  },
  {
    name: 'understanding activity is understanding',
    call: { status: 'in_progress', activity: { state: 'understanding' } },
    expected: { label: 'Understanding', detail: 'The AI agent is understanding the response.' },
  },
  {
    name: 'agent_speaking activity is speaking',
    call: { status: 'in_progress', activity: { state: 'agent_speaking' } },
    expected: { label: 'Speaking', detail: 'The AI agent is speaking.' },
  },
  {
    name: 'completed calls are completed',
    call: { status: 'completed' },
    expected: { label: 'Call completed', detail: 'The call has completed.' },
  },
  {
    name: 'failed calls have a failed label',
    call: { status: 'failed' },
    expected: { label: 'Call failed', detail: 'The call ended without completing.' },
  },
  {
    name: 'no-answer calls have a no-answer label',
    call: { status: 'no_answer' },
    expected: { label: 'No answer', detail: 'The call was not answered.' },
  },
  {
    name: 'busy calls have a busy label',
    call: { status: 'busy' },
    expected: { label: 'Busy', detail: 'The line was busy.' },
  },
  {
    name: 'canceled calls have a canceled label',
    call: { status: 'canceled' },
    expected: { label: 'Call canceled', detail: 'The call was canceled.' },
  },
  {
    name: 'cancelled calls have a canceled label',
    call: { status: 'cancelled' },
    expected: { label: 'Call canceled', detail: 'The call was canceled.' },
  },
  {
    name: 'invalid calls have an invalid label',
    call: { status: 'invalid' },
    expected: { label: 'Invalid number', detail: 'The call number was invalid.' },
  },
];

for (const { name, call, expected } of cases) {
  test(name, () => {
    assert.deepEqual(resolveCallActivity(call), expected);
  });
}

test('terminal status takes precedence over stale activity', () => {
  assert.deepEqual(
    resolveCallActivity({ status: 'completed', activity: { state: 'agent_speaking' } }),
    { label: 'Call completed', detail: 'The call has completed.' },
  );
});

test('transcript age does not invent a live activity', () => {
  assert.deepEqual(
    resolveCallActivity({
      status: 'in_progress',
      transcript: [{ timestamp: 0, text: 'An old transcript turn' }],
    }),
    { label: 'Connecting AI agent', detail: 'Waiting for a live activity update.' },
  );
});

test('missing call data returns an honest fallback', () => {
  assert.deepEqual(resolveCallActivity(null), {
    label: 'Call status unavailable',
    detail: 'No call activity is available.',
  });
});
