import React, { useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { getToken } from '../api.js';
import PublicLayout, { PublicFaq } from '../components/PublicLayout.jsx';

const EXAMPLES = [
  {
    id: 'attendance',
    label: 'Attendance',
    title: 'An absence, with a next step.',
    contact: 'Nila Rao',
    context: 'Guardian · Example School',
    agent: 'What was the reason for the absence, and when do you expect Maya to return?',
    speaker: 'Guardian',
    reply: 'We are travelling for a family event. I am not sure about the return date yet. Could her teacher call me?',
    fields: [
      ['reason_for_absence', 'Family travel'],
      ['expected_return_date', 'Not confirmed'],
      ['escalation_needed', 'Yes'],
    ],
    review: 'A teacher callback is requested. Leave the return date unconfirmed for review.',
  },
  {
    id: 'appointment',
    label: 'Appointment',
    title: 'A change of plan, captured.',
    contact: 'Dev Shah',
    context: 'Patient · Example Clinic',
    agent: 'Will you be able to attend your appointment on Friday morning?',
    speaker: 'Patient',
    reply: 'I cannot make Friday. Could someone from the front desk call me to find another time?',
    fields: [
      ['will_attend', 'No'],
      ['reschedule_date', 'Not confirmed'],
      ['escalation_needed', 'Yes'],
    ],
    review: 'The front desk needs to arrange a new time. No replacement appointment is booked.',
  },
  {
    id: 'feedback',
    label: 'Feedback',
    title: 'Feedback your team can act on.',
    contact: 'Asha Menon',
    context: 'Customer · Example Services',
    agent: 'What was the main reason for your rating? Would you like the service team to call you back?',
    speaker: 'Customer',
    reply: 'The repair is working, but the technician arrived late. Yes, I would like a callback.',
    fields: [
      ['feedback_reason', 'Technician arrived late'],
      ['callback_requested', 'Yes'],
      ['issue_reported', 'Yes'],
    ],
    review: 'A service callback is requested. The record does not mean the issue has been resolved.',
  },
];

const USE_CASES = [
  { title: 'Attendance follow-up', team: 'Education', description: 'Ask a parent or guardian about an absence, record the expected return, and surface requests for a human coordinator.', fields: 'reason_for_absence · expected_return_date', example: 'attendance' },
  { title: 'Appointment confirmation', team: 'Clinic front desk', description: 'Capture attendance and rescheduling preferences for your team to review. This is appointment coordination, not medical advice.', fields: 'will_attend · reschedule_date', example: 'appointment' },
  { title: 'Service feedback', team: 'Customer care', description: 'Collect the rating, the reason behind it, and whether the customer wants a callback. Keep complaints visible to your team.', fields: 'feedback_reason · callback_requested', example: 'feedback' },
  { title: 'Site-visit follow-up', team: 'Property teams', description: 'Follow up with people who asked to be contacted. Capture their interest, budget, and preferred visit time without promising availability.', fields: 'still_interested · site_visit_date' },
];

const FAQS = [
  { question: 'Can I create an account today?', answer: <p>Public self-registration is not open. Use an existing account or an invitation from your workspace administrator. <Link to="/login">Sign in</Link> to continue; the public examples do not require an account.</p> },
  { question: 'Is the example a real call?', answer: <p>No. The names, conversation excerpts, and extracted answers are synthetic examples based on existing agent configurations. Switching examples does not use a microphone, play audio, contact anyone, or consume credits.</p> },
  { question: 'Can I test an agent before a campaign?', answer: <p>Yes. The <Link to="/playground">Playground</Link> is available after sign-in for agent testing. Browser voice and text tests are separate from phone testing. A phone test is a real outbound call and must only be launched with authorization.</p> },
  { question: 'What do I need before calling contacts?', answer: <p>An approved agent version, reviewed contact details, a recorded consent basis, and sufficient allowance or wallet credit. Campaign launch is subject to the configured calling window and operational capacity. You remain responsible for the permission to contact each person.</p> },
  { question: 'What happens when an answer is unclear?', answer: <p>Review the transcript, extracted fields, and any human-review flag. A missing answer is not a confirmed answer. Your team decides the next step rather than treating every completed call as a resolved case.</p> },
  { question: 'Which languages should I plan for?', answer: <p>English is the current baseline. Additional language work is separate from the calling workflow; see the <Link to="/roadmap">roadmap</Link> for planned scope, not a promise of availability.</p> },
];

export default function LandingPage() {
  const signedIn = getToken();
  const [exampleId, setExampleId] = useState('attendance');
  const example = EXAMPLES.find((item) => item.id === exampleId);

  if (signedIn) return <Navigate to="/" replace />;

  function showExample(id) {
    setExampleId(id);
    const preview = document.getElementById('demo');
    preview?.scrollIntoView({ behavior: 'auto', block: 'start' });
    preview?.focus({ preventScroll: true });
  }

  return (
    <PublicLayout>
      <section className="es-public-hero" id="product" tabIndex={-1} aria-labelledby="es-public-hero-title">
        <div className="es-public-hero-copy">
          <p className="es-public-context">AI calling, with a record you can use.</p>
          <h1 id="es-public-hero-title">Business calls.<br />Clear outcomes.</h1>
          <p className="es-public-lead">Configure an agent. Prepare a campaign. Review what was learned. A workspace for the follow-ups your team needs to get right.</p>
          <div className="es-public-actions">
            <Link to="/login" className="es-public-button">Open workspace</Link>
            <a href="#workflow" className="es-public-button es-public-button-secondary">See the workflow</a>
          </div>
          <p className="es-public-access-note">For existing accounts and invited teams.</p>
          <div className="es-public-hero-principle">
            <span className="es-public-principle-line" aria-hidden="true" />
            <p>The conversation is only the beginning.<br /><strong>Know what to do next.</strong></p>
          </div>
        </div>

        <figure className="es-public-example" id="demo" tabIndex={-1} aria-labelledby="es-public-example-heading">
          <div className="es-public-example-heading">
            <span className="es-public-badge">Illustrative example</span>
            <span>Synthetic data. No call or audio.</span>
          </div>
          <div className="es-public-example-options" role="group" aria-label="Choose a synthetic call example">
            {EXAMPLES.map((item) => (
              <button
                type="button"
                key={item.id}
                aria-pressed={exampleId === item.id}
                aria-controls="es-public-example-record"
                onClick={() => setExampleId(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div id="es-public-example-record" className="es-public-example-record" aria-live="polite" aria-atomic="true">
            <h2 id="es-public-example-heading">{example.title}</h2>
            <div className="es-public-contact-row">
              <span className="es-public-record-label">Contact</span>
              <div><strong>{example.contact}</strong><span>{example.context}</span></div>
            </div>
            <div className="es-public-conversation">
              <h3>Conversation excerpt</h3>
              <div className="es-public-message"><span>Agent</span><p>{example.agent}</p></div>
              <div className="es-public-message es-public-message-contact"><span>{example.speaker}</span><p>{example.reply}</p></div>
            </div>
            <div className="es-public-fields">
              <h3>Extracted fields</h3>
              <dl>
                {example.fields.map(([name, value]) => (
                  <div key={name}><dt>{name}</dt><dd className={value === 'Not confirmed' ? 'es-public-unconfirmed' : undefined}>{value}</dd></div>
                ))}
              </dl>
            </div>
            <div className="es-public-review-note"><strong>For human review</strong><p>{example.review}</p></div>
          </div>
          <figcaption>A sample record, not a completed call. Fields depend on your agent configuration.</figcaption>
        </figure>
      </section>

      <section className="es-public-section es-public-workflow" id="workflow" tabIndex={-1} aria-labelledby="es-public-workflow-title">
        <div className="es-public-section-heading">
          <div><p className="es-public-context">How it works</p><h2 id="es-public-workflow-title">A clear path from<br />contact to context.</h2></div>
          <p>Set the questions before the call. Keep the evidence after it. Your team stays responsible for the decisions in between.</p>
        </div>
        <ol className="es-public-steps">
          <li><span className="es-public-step-number" aria-hidden="true">1</span><h3>Configure the conversation</h3><p>Choose a preset or build an agent. Define its context, questions, disclosure, and the fields you want to capture. Save a version and test it in the Playground.</p><Link className="es-public-text-link" to="/agents">Explore agents</Link></li>
          <li><span className="es-public-step-number" aria-hidden="true">2</span><h3>Prepare the campaign</h3><p>Import contacts, check details and consent, then choose who to include. Review the calling window and available credit before you authorize a launch.</p><Link className="es-public-text-link" to="/campaigns">Open campaigns</Link></li>
          <li><span className="es-public-step-number" aria-hidden="true">3</span><h3>Review what was learned</h3><p>Read the transcript alongside extracted fields. Check uncertain answers and human-review flags, then export CSV or Excel for your next step.</p><Link className="es-public-text-link" to="/calls">Open call history</Link></li>
        </ol>
      </section>

      <section className="es-public-section es-public-usecases" id="usecases" tabIndex={-1} aria-labelledby="es-public-usecases-title">
        <div className="es-public-section-intro">
          <p className="es-public-context">Useful conversations, different contexts.</p>
          <h2 id="es-public-usecases-title">Your questions.<br />Your next steps.</h2>
          <p>Start from an existing configuration, then adapt it to your organization. These are supported starting points, not customer results.</p>
        </div>
        <div className="es-public-usecase-list">
          {USE_CASES.map((item) => (
            <article key={item.title}>
              <p className="es-public-usecase-team">{item.team}</p>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
              <p className="es-public-field-preview">{item.fields}</p>
              {item.example
                ? <button type="button" className="es-public-text-link" onClick={() => showExample(item.example)}>View {item.team === 'Education' ? 'attendance' : item.example} example</button>
                : <Link className="es-public-text-link" to="/agents">Explore the agent preset</Link>}
            </article>
          ))}
        </div>
      </section>

      <section className="es-public-section es-public-controls" aria-labelledby="es-public-controls-title">
        <div className="es-public-controls-copy">
          <p className="es-public-context">Built around the operator.</p>
          <h2 id="es-public-controls-title">An outcome is not<br />a reason to stop checking.</h2>
          <p>See the difference between a call that ended and an issue that needs attention. Keep control of the next campaign and the next follow-up.</p>
          <Link className="es-public-text-link" to="/playground">Test in the Playground</Link>
        </div>
        <dl className="es-public-control-list">
          <div><dt>Review before launch</dt><dd>Inspect contact consent and use Include or Skip to prepare the next run. Contacts marked <code>pending_review</code> stay visible to the operator.</dd></div>
          <div><dt>Pause campaign dialing</dt><dd>Use the campaign pause control to stop scheduling further calls. Pausing is not the same as ending an already connected conversation.</dd></div>
          <div><dt>Keep uncertainty visible</dt><dd>Check <code>flagged_for_human</code>, field confidence, and transcript evidence. Missing information should stay missing until it is confirmed.</dd></div>
          <div><dt>Take the record with you</dt><dd>Export call or campaign results as CSV or Excel. Review the <code>outcome</code> alongside <code>extracted_fields</code>, not in isolation.</dd></div>
        </dl>
      </section>

      <section className="es-public-section es-public-pricing-preview" aria-labelledby="es-public-pricing-title">
        <div><p className="es-public-context">Plan for the work ahead.</p><h2 id="es-public-pricing-title">Minutes in the plan.<br />Overage in the wallet.</h2><p>Monthly allowances and prepaid credit are separate. Compare the full terms before choosing a plan.</p><Link className="es-public-button es-public-button-secondary" to="/pricing">View pricing &amp; terms</Link></div>
        <div className="es-public-price-snapshot"><span>Starter</span><p className="es-public-snapshot-amount">₹2,990 <span>/ month</span></p><dl><div><dt>Included minutes</dt><dd>1,000 / month</dd></div><div><dt>Overage rate</dt><dd>₹3.00 / minute</dd></div><div><dt>Tax treatment</dt><dd>Includes 18% GST</dd></div></dl><p>Free plan: ₹0 monthly with no monthly allowance. Eligible new accounts receive 10 trial minutes in the wallet. Access remains invitation-based.</p></div>
      </section>

      <PublicFaq id="es-public-landing-faq" items={FAQS} />

      <section className="es-public-closing" aria-labelledby="es-public-closing-title">
        <div><h2 id="es-public-closing-title">Make the next call<br />a better-informed one.</h2><p>Start with an agent. Test the conversation. Review the answers.</p></div>
        <div><Link className="es-public-button" to="/login">Open workspace</Link><p>Existing account or invitation required.</p></div>
      </section>
    </PublicLayout>
  );
}
