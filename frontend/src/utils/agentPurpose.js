/**
 * Short "what is this agent for" label, shown next to an agent's name wherever
 * one is picked. Agents only carry a free-text role, so the label is derived
 * from it: "Attendance follow-up", "Real estate enquiries", and so on.
 */

const PURPOSES = [
  [/\b(attendance|absence|absent|student|school|guardian)\b/i, 'Attendance follow-up'],
  [/\b(clinic|patient|appointment|hospital|doctor)\b/i, 'Clinic appointments'],
  [/\b(property|real estate|buyer|locality|site visit)\b/i, 'Real estate enquiries'],
  [/\b(prank|mischief|silly|comedy)\b/i, 'Prank call'],
  [/\b(check-in|check in|companion|wellbeing|well-being)\b/i, 'Warm check-in'],
  [/\b(feedback|survey|customer care|callback|post-service|rating)\b/i, 'Customer feedback'],
  [/\b(lead|sales|enquiry|inquiry|demo)\b/i, 'Lead follow-up'],
  [/\b(billing|payment|invoice|renewal)\b/i, 'Billing follow-up'],
];

function firstClause(description) {
  return String(description || '')
    .split(/\s+[—–-]\s+/)[0]
    .trim()
    .slice(0, 48);
}

export function agentPurpose(agent) {
  const text = `${agent?.name || ''} ${agent?.description || ''}`;
  for (const [pattern, label] of PURPOSES) {
    if (pattern.test(text)) return label;
  }
  // No keyword matched: the role's first clause still says more than nothing.
  return firstClause(agent?.description) || 'General voice agent';
}

/** Option text for an agent picker: "Kavya — Customer feedback". */
export function agentOptionLabel(agent) {
  const name = String(agent?.name || '').trim() || 'Untitled agent';
  return `${name} — ${agentPurpose(agent)}`;
}
