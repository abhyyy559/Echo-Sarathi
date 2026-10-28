import test from 'node:test';
import assert from 'node:assert/strict';

import { agentOptionLabel, agentPurpose } from './agentPurpose.js';

// The five agents the demo org seeds / creates from presets.
const PRESETS = {
  Priya: 'Attendance follow-up specialist — calls guardians of absent students.',
  Sahithi: 'Attendance follow-up specialist (Telugu) — calls guardians of absent students.',
  Kavya: 'Customer care — collects post-service feedback and arranges callbacks.',
  Meera: 'Clinic front desk — confirms and reschedules patient appointments.',
  Arjun: 'Property advisor — calls buyers who enquired about a site visit.',
};

test('presets get a readable purpose label', () => {
  assert.equal(agentPurpose({ name: 'Priya', description: PRESETS.Priya }), 'Attendance follow-up');
  assert.equal(agentPurpose({ name: 'Sahithi', description: PRESETS.Sahithi }), 'Attendance follow-up');
  assert.equal(agentPurpose({ name: 'Kavya', description: PRESETS.Kavya }), 'Customer feedback');
  assert.equal(agentPurpose({ name: 'Meera', description: PRESETS.Meera }), 'Clinic appointments');
  assert.equal(agentPurpose({ name: 'Arjun', description: PRESETS.Arjun }), 'Real estate enquiries');
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
