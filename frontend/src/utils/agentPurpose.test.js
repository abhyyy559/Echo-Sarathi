import test from 'node:test';
import assert from 'node:assert/strict';

import { agentOptionLabel, agentPurpose } from './agentPurpose.js';

// The vertical presets the demo org uses.
const PRESETS = {
  Priya: 'Attendance follow-up specialist — calls guardians of absent students.',
  Sahithi: 'Attendance follow-up specialist (Telugu) — calls guardians of absent students.',
  Kavya: 'Customer care — collects post-service feedback and arranges callbacks.',
  Meera: 'Clinic front desk — confirms and reschedules patient appointments.',
  Arjun: 'Property advisor — calls buyers who enquired about a site visit.',
};

// The persona agents the demo org seeds alongside the vertical presets.
const PERSONAS = {
  Bunty: 'Prank caller · one harmless, silly bit for a friend, with a clear yes first.',
  Anu: "Warm check-in companion · a short, sweet call to see how someone's day is going.",
};

test('presets get a readable purpose label', () => {
  assert.equal(agentPurpose({ name: 'Priya', description: PRESETS.Priya }), 'Attendance follow-up');
  assert.equal(agentPurpose({ name: 'Sahithi', description: PRESETS.Sahithi }), 'Attendance follow-up');
  assert.equal(agentPurpose({ name: 'Kavya', description: PRESETS.Kavya }), 'Customer feedback');
  assert.equal(agentPurpose({ name: 'Meera', description: PRESETS.Meera }), 'Clinic appointments');
  assert.equal(agentPurpose({ name: 'Arjun', description: PRESETS.Arjun }), 'Real estate enquiries');
});

test('persona agents get their own labels', () => {
  assert.equal(agentPurpose({ name: 'Bunty', description: PERSONAS.Bunty }), 'Prank call');
  assert.equal(agentPurpose({ name: 'Anu', description: PERSONAS.Anu }), 'Warm check-in');
});

test('a role without a known vertical keeps its first clause', () => {
  assert.equal(
    agentPurpose({ name: 'Nisha', description: "Principal's office — calls parents about fees." }),
    "Principal's office"
  );
  assert.equal(agentPurpose({ name: 'Nisha', description: 'fees reminder' }), 'fees reminder');
});

test('missing data degrades to a neutral label instead of empty text', () => {
  assert.equal(agentPurpose(null), 'General voice agent');
  assert.equal(agentPurpose({ name: 'Orphan', description: '' }), 'General voice agent');
});

test('option label pairs the name with the purpose', () => {
  assert.equal(
    agentOptionLabel({ name: 'Meera', description: PRESETS.Meera }),
    'Meera — Clinic appointments'
  );
  assert.equal(agentOptionLabel({}), 'Untitled agent — General voice agent');
});
