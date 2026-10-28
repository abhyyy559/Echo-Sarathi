import assert from 'node:assert/strict';
import test from 'node:test';

import { LEAD_FIELD_HINTS, leadCardDefaults } from './leadCard.js';

const NOW = new Date(2026, 9, 28); // 28 Oct 2026, local time

test('student agent gets attendance fields, no clinic or contact rows', () => {
  const card = leadCardDefaults(
    {
      system_prompt: 'You call about [Student Name].',
      disclosure_script: 'Calling from [Institution Name].',
      question_flow: [{ step: 1, question: 'Why was [Student Name] absent?' }],
      company_context: { institution_name: 'CMR College' },
    },
    NOW
  );
  assert.deepEqual(Object.keys(card), ['student_name', 'parent_name', 'class_section', 'absent_date']);
  assert.equal(card.student_name, 'Abhi');
  assert.equal(card.parent_name, 'Ram');
  assert.equal(card.class_section, '10-B');
  assert.equal(card.absent_date, '2026-10-28');
  assert.equal(card.contact_name, undefined);
  assert.equal(card.patient_name, undefined);
});

test('clinic agent gets the patient and tomorrow’s appointment slot', () => {
  const card = leadCardDefaults(
    {
      system_prompt: 'Confirm appointments with [Doctor Name].',
      disclosure_script: 'Calling from [Clinic Name].',
      question_flow: [{ step: 1, question: 'Is [Patient Name] coming on [Appointment Date]?' }],
      company_context: {
        clinic_name: 'Sunrise Dental',
        doctor_name: 'Dr Rao',
        appointment_date: '[Appointment Date]',
        appointment_time: '[Appointment Time]',
      },
    },
    NOW
  );
  assert.deepEqual(Object.keys(card), ['patient_name', 'appointment_date', 'appointment_time']);
  assert.equal(card.patient_name, 'Ananya');
  assert.equal(card.appointment_date, '2026-10-29');
  assert.equal(card.appointment_time, '10:30 AM');
  assert.equal(card.student_name, undefined);
});

test('real-estate agent only asks who is on the call', () => {
  const card = leadCardDefaults(
    {
      system_prompt: 'You call about [Property Name] in [Locality] for [Company Name].',
      question_flow: [{ step: 1, question: 'Am I speaking with [Contact Name]?' }],
      company_context: { company_name: 'Skyline Estates', property_name: 'Green Meadows', locality: 'Kondapur' },
    },
    NOW
  );
  assert.deepEqual(Object.keys(card), ['contact_name']);
  assert.equal(card.contact_name, 'Kiran');
  assert.equal(card.student_name, undefined);
  assert.equal(card.patient_name, undefined);
});

test('service-feedback agent seeds its customer name', () => {
  const card = leadCardDefaults(
    {
      system_prompt: 'Call customers after their service visit.',
      question_flow: [{ step: 1, question: 'Am I speaking with [Customer Name]?' }],
      company_context: { company_name: 'Acme Care', service_type: 'AC repair', service_date: '2026-10-27' },
    },
    NOW
  );
  assert.deepEqual(Object.keys(card), ['contact_name']);
  assert.equal(card.contact_name, 'Meera');
});

test('custom agent with no vertical falls back to a contact row', () => {
  const card = leadCardDefaults({ system_prompt: 'Call the lead and ask two questions.', question_flow: [] }, NOW);
  assert.deepEqual(card, { contact_name: 'Kiran' });
  assert.deepEqual(leadCardDefaults(null, NOW), { contact_name: 'Kiran' });
});

test('an institution key alone does not imply a student card', () => {
  const card = leadCardDefaults(
    {
      system_prompt: 'Call the parent about the annual day.',
      question_flow: [{ step: 1, question: 'Will you attend?' }],
      company_context: { institution_name: 'CMR College' },
    },
    NOW
  );
  assert.deepEqual(Object.keys(card), ['contact_name']);
});

test('extra caller tokens add their own fields', () => {
  const card = leadCardDefaults(
    {
      system_prompt: 'You call about [Student Name] and also ask for [Lead Name].',
      question_flow: [],
      company_context: {},
    },
    NOW
  );
  assert.deepEqual(Object.keys(card), [
    'student_name',
    'parent_name',
    'class_section',
    'absent_date',
    'contact_name',
  ]);
  assert.equal(card.contact_name, 'Kiran');
});

test('every seeded field key has a placeholder hint', () => {
  const card = leadCardDefaults(
    {
      system_prompt: 'Call about [Student Name].',
      question_flow: [],
      company_context: { institution_name: 'Demo' },
    },
    NOW
  );
  for (const key of Object.keys(card)) {
    assert.ok(LEAD_FIELD_HINTS[key], `missing hint for ${key}`);
  }
});
