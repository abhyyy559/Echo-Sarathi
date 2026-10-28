/**
 * Lead-card defaults ("who are we calling?") for a saved agent version.
 *
 * The playground used to seed one hardcoded student-absence card, so a
 * real-estate or clinic agent was tested with student_name / parent_name rows
 * its own script never reads. These defaults come from the version itself:
 * the caller-side bracket tokens its prompt asks for, plus the extra facts
 * its vertical needs (a clinic needs the appointment slot, a school needs the
 * class and absence date).
 */

const TOKEN_FIELDS = {
  '[Student Name]': 'student_name',
  '[Parent/Guardian Name]': 'parent_name',
  '[Patient Name]': 'patient_name',
  '[Lead Name]': 'contact_name',
  '[Contact Name]': 'contact_name',
  '[Customer Name]': 'contact_name',
};

const VERTICAL_FIELDS = {
  school: ['student_name', 'parent_name', 'class_section', 'absent_date'],
  clinic: ['patient_name', 'appointment_date', 'appointment_time'],
  real_estate: ['contact_name'],
  service: ['contact_name'],
  generic: ['contact_name'],
};

/** Placeholders shown in an empty value box; also a reminder of what a key means. */
export const LEAD_FIELD_HINTS = {
  student_name: 'Student’s full name',
  parent_name: 'Parent or guardian',
  patient_name: 'Patient’s full name',
  contact_name: 'Who answers the phone',
  class_section: 'e.g. 10-B',
  absent_date: 'YYYY-MM-DD',
  appointment_date: 'YYYY-MM-DD',
  appointment_time: 'e.g. 10:30 AM',
};

function isoDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function addDays(date, days) {
  const next = new Date(date.getTime());
  next.setDate(next.getDate() + days);
  return next;
}

function contextKeys(version) {
  const ctx = version && typeof version.company_context === 'object' ? version.company_context : null;
  if (!ctx) return [];
  return Object.keys(ctx).map((k) => k.toLowerCase());
}

function promptText(version) {
  if (!version) return '';
  return [
    version.system_prompt,
    version.disclosure_script,
    JSON.stringify(version.question_flow || ''),
  ]
    .filter(Boolean)
    .join('\n');
}

function detectVertical(version) {
  const keys = contextKeys(version);
  const text = promptText(version);
  const hasKey = (prefixes, names = []) =>
    keys.some((k) => prefixes.some((p) => k.startsWith(p)) || names.includes(k));

  if (hasKey(['clinic', 'doctor', 'patient', 'appointment']) || /\[(Patient Name|Doctor Name|Appointment Date|Appointment Time)\]/.test(text)) {
    return 'clinic';
  }
  if (hasKey(['property', 'locality']) || /\[(Property Name|Locality)\]/.test(text)) {
    return 'real_estate';
  }
  if (/\[(Student Name|Parent\/Guardian Name)\]/.test(text) || hasKey([], ['student_name', 'parent_name', 'class_section', 'absent_date'])) {
    return 'school';
  }
  if (hasKey(['service']) || text.includes('[Customer Name]')) {
    return 'service';
  }
  return 'generic';
}

function seedsFor(vertical, text, now) {
  return {
    student_name: 'Abhi',
    parent_name: 'Ram',
    patient_name: 'Ananya',
    class_section: '10-B',
    absent_date: isoDate(now),
    appointment_date: isoDate(addDays(now, 1)),
    appointment_time: '10:30 AM',
    contact_name: vertical === 'service' || text.includes('[Customer Name]') ? 'Meera' : 'Kiran',
  };
}

/**
 * Contact card prefill for `version` (an AgentVersion payload, or null when no
 * version is selected yet). `now` is injectable so date seeds stay testable.
 */
export function leadCardDefaults(version, now = new Date()) {
  const vertical = detectVertical(version);
  const text = promptText(version);
  const fields = [...VERTICAL_FIELDS[vertical]];

  for (const [token, key] of Object.entries(TOKEN_FIELDS)) {
    if (text.includes(token) && !fields.includes(key)) fields.push(key);
  }

  const seeds = seedsFor(vertical, text, now);
  const card = {};
  for (const key of fields) card[key] = seeds[key] ?? '';
  return card;
}
