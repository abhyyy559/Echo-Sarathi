import React from 'react';
import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout.jsx';

const AVAILABLE = [
  { title: 'Configure a versioned agent', description: 'Set the context, questions, disclosure, and extraction fields for a structured conversation. Start with an existing preset or use the agent builder.', to: '/agents', link: 'Explore agents' },
  { title: 'Test in the Playground', description: 'Review an agent through browser voice or text testing before preparing a campaign. Phone testing is a separate mode and requires authorization for a real outbound call.', to: '/playground', link: 'Open Playground' },
  { title: 'Prepare and operate campaigns', description: 'Import and review contacts, record consent, choose who to include, and use launch or pause controls. Calling windows, credit checks, and deployment capacity still apply.', to: '/campaigns', link: 'Open campaigns' },
  { title: 'Review calls and export results', description: 'Read available transcripts and extracted fields, inspect human-review flags, and export CSV or Excel. Missing data stays distinct from a confirmed answer.', to: '/calls', link: 'Open call history' },
];

const PLANNED = [
  { title: 'Telugu conversations', description: 'A language direction beyond the English baseline. Preset or configuration availability alone does not establish production voice quality.', condition: 'Requires end-to-end language validation.' },
  { title: 'Telugu–English code-switching', description: 'Mixed-language conversations need their own recognition, pronunciation, and extraction checks. Do not assume support from single-language testing.', condition: 'Requires mixed-language conversation testing.' },
  { title: 'More Indian languages', description: 'Hindi, Tamil, Kannada, and other languages remain future scope. The order and availability are not committed on this page.', condition: 'Scope and delivery dates are not committed.' },
];

export default function RoadmapPage() {
  return (
    <PublicLayout>
      <section className="es-public-page-intro es-public-roadmap-intro" aria-labelledby="es-public-roadmap-heading">
        <div><p className="es-public-context">Product roadmap</p><h1 id="es-public-roadmap-heading">What you can use.<br />What comes next.</h1><p className="es-public-lead">The current calling workflow, separate from future language work. Plan around what is available to your workspace, not a promise on a timeline.</p><div className="es-public-actions"><Link className="es-public-button" to="/login">Open workspace</Link><a className="es-public-button es-public-button-secondary" href="#es-public-planned">View planned work</a></div></div>
        <aside className="es-public-roadmap-note" aria-label="How to read this roadmap"><span className="es-public-badge">Scope, not a release guarantee</span><p>English is the current baseline. Account access, phone capacity, and payment availability are separate from feature scope.</p><p>Planned items are not included as delivered features in a paid plan. No release dates are promised here.</p><Link className="es-public-text-link" to="/pricing">Read pricing &amp; availability</Link></aside>
      </section>

      <section className="es-public-section es-public-roadmap-section" aria-labelledby="es-public-available-title">
        <div className="es-public-section-intro"><span className="es-public-badge">Current workflow</span><h2 id="es-public-available-title">From configuration<br />to review.</h2><p>These surfaces are implemented in the workspace. Access and service readiness depend on your organization’s setup; this is not a claim of an unrestricted public launch.</p></div>
        <div className="es-public-roadmap-list">
          {AVAILABLE.map((item) => <article key={item.title}><h3>{item.title}</h3><p>{item.description}</p><Link className="es-public-text-link" to={item.to}>{item.link}</Link></article>)}
        </div>
      </section>

      <section className="es-public-section es-public-roadmap-section es-public-planned" id="es-public-planned" tabIndex={-1} aria-labelledby="es-public-planned-title">
        <div className="es-public-section-intro"><span className="es-public-badge es-public-badge-neutral">Planned, not generally available</span><h2 id="es-public-planned-title">More languages.<br />The same need for clarity.</h2><p>A new language needs more than a translated prompt. Recognition, conversation, voice, and the resulting fields all need to work together.</p></div>
        <div className="es-public-roadmap-list">
          {PLANNED.map((item) => <article key={item.title}><h3>{item.title}</h3><p>{item.description}</p><p className="es-public-roadmap-condition">{item.condition}</p></article>)}
        </div>
      </section>

      <section className="es-public-section es-public-readiness" aria-labelledby="es-public-readiness-title">
        <div className="es-public-section-heading"><div><p className="es-public-context">Before a new capability becomes routine.</p><h2 id="es-public-readiness-title">Test the whole conversation.</h2></div><p>These are review criteria for future releases, not benchmarks we claim to have passed.</p></div>
        <ol className="es-public-steps">
          <li><span className="es-public-step-number" aria-hidden="true">1</span><h3>Check what is heard</h3><p>Review recognition across representative speakers, background conditions, and language changes. Keep uncertain words visible in the evidence.</p></li>
          <li><span className="es-public-step-number" aria-hidden="true">2</span><h3>Check what is said</h3><p>Evaluate pronunciation, turn-taking, disclosure, and the agent’s handling of unclear requests. A translated script is only a starting point.</p></li>
          <li><span className="es-public-step-number" aria-hidden="true">3</span><h3>Check what is recorded</h3><p>Compare extracted answers against the conversation, including missing values and escalation needs. Confirm that the result supports human review.</p></li>
        </ol>
      </section>

      <section className="es-public-closing" aria-labelledby="es-public-roadmap-closing">
        <div><h2 id="es-public-roadmap-closing">Explore the workflow<br />that is here today.</h2><p>See a labelled example, or sign in to your existing workspace.</p></div>
        <div><Link className="es-public-button" to="/login">Open workspace</Link><Link className="es-public-text-link" to="/landing#demo">View the illustrative example</Link></div>
      </section>
    </PublicLayout>
  );
}
