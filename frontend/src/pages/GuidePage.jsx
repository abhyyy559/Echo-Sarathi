import React from 'react';
import { Link } from 'react-router-dom';

const JOURNEY = [
  {
    n: 1,
    title: 'Start on the landing page',
    body: (
      <>
        <p>
          The landing page is the front door. It explains what the platform does in one line and gets you to
          Register or Log in. You are past that step — this Guide is your map for everything after it.
        </p>
      </>
    ),
    link: null,
  },
  {
    n: 2,
    title: 'Register your organization',
    body: (
      <p>
        Registering creates your <strong>organization</strong> and its first owner account in one step. Everything
        you build afterwards — agents, contacts, campaigns — lives inside that organization. Use a work email and a
        password of at least 8 characters.
      </p>
    ),
    link: null,
  },
  {
    n: 3,
    title: 'Find your way around the dashboard',
    body: (
      <p>
        Home shows one card per capability: <strong>Agents</strong> (build callers),{' '}
        <strong>Playground</strong> (test them by talking), <strong>Campaigns</strong> (dial real people) and{' '}
        <strong>Call review</strong> (read transcripts, export results). When unsure, come back here — the
        suggested order is always agents → playground → campaigns.
      </p>
    ),
    link: { to: '/', label: 'Open the dashboard' },
  },
  {
    n: 4,
    title: 'Create & train an agent',
    body: (
      <>
        <p>
          An agent is one AI caller persona. Click <strong>+ New Agent</strong> and the builder wizard walks you
          through six steps:
        </p>
        <ul className="guide-list">
          <li>
            <strong>Basics</strong> — name it, describe when it calls, and edit the opening disclosure the agent
            must speak ("this is an automated call…").
          </li>
          <li>
            <strong>Company Context</strong> — facts the agent should know (timings, fees, department numbers). It
            uses these to answer questions instead of guessing.
          </li>
          <li>
            <strong>Question Flow</strong> — the exact questions to ask, in order, and which field each answer
            fills.
          </li>
          <li>
            <strong>Extraction Schema</strong> — what to write down per call (e.g. <code>reason</code>,{' '}
            <code>will_attend</code>) with types and confidence thresholds.
          </li>
          <li>
            <strong>Voice Settings</strong> — pick the voice and speaking pace.
          </li>
          <li>
            <strong>Review &amp; Save Version</strong> — saving creates an immutable numbered version (v1, v2, …).
            Editing never silently changes what campaigns call.
          </li>
        </ul>
      </>
    ),
    link: { to: '/agents', label: 'Go to Agents' },
  },
  {
    n: 5,
    title: 'Test it live in the Playground',
    body: (
      <>
        <p>
          Pick a saved version and press start — your browser microphone becomes the caller's phone. Three things
          to expect:
        </p>
        <ul className="guide-list">
          <li>
            <strong>Mic permission</strong> — the browser asks once; allow it or nothing can be heard.
          </li>
          <li>
            <strong>Talking turns</strong> — speak, then stop. The agent waits for natural pauses before
            replying, and you can interrupt it mid-sentence (barge-in), just like a real call.
          </li>
          <li>
            <strong>Captions</strong> — both sides of the conversation appear as live captions while you talk.
          </li>
        </ul>
        <p>
          After hanging up you get the transcript, every field the agent extracted with confidence scores, and
          per-turn latency. Playground calls use no phone numbers and no minutes.
        </p>
      </>
    ),
    link: { to: '/playground', label: 'Open the Playground' },
  },
  {
    n: 6,
    title: 'Campaigns & contact imports',
    body: (
      <>
        <p>
          A campaign dials real people from a contact list using one pinned agent version. Create it, then import
          contacts:
        </p>
        <ul className="guide-list">
          <li>
            Drop in a <strong>.csv or .xlsx</strong> file — columns are read automatically, no typing column names.
          </li>
          <li>
            Confirm the suggested mapping (name, phone, plus any extra fields) against a preview of your rows.
          </li>
          <li>
            Rows with invalid phone numbers are flagged <em>before</em> anything is submitted, so bad data never
            reaches the dialer.
          </li>
        </ul>
        <p>Calls only run inside the permitted calling window (9 AM–9 PM IST) once you launch.</p>
      </>
    ),
    link: { to: '/campaigns', label: 'Go to Campaigns' },
  },
  {
    n: 7,
    title: 'Review transcripts & export',
    body: (
      <p>
        Every finished call keeps its full transcript, the structured fields collected (with confidence), cost and
        latency stats, and the recording where available. Calls the agent was unsure about are flagged for human
        review. Export everything to CSV or Excel from the campaign page in one click.
      </p>
    ),
    link: null,
  },
  {
    n: 8,
    title: 'When calls go live',
    body: (
      <p>
        Launching is deliberate: the campaign page asks for confirmation, then dials queued contacts inside
        calling hours only. Pause anytime to stop new dials without losing progress; cancel to end everything.
        Contacts without recorded consent, opted-out numbers, and out-of-window times are skipped automatically.
        Regional rollout (Telugu and beyond) comes in a later phase.
      </p>
    ),
    link: null,
  },
];

export default function GuidePage() {
  return (
    <div className="guide narrow">
      <div className="page-head">
        <div>
          <h2 className="page-title">Guide</h2>
          <p className="page-sub">
            What is this? A beginner's walkthrough of the whole platform — follow the eight steps in order and you
            will go from empty account to reviewing real call transcripts.
          </p>
        </div>
      </div>

      <ol className="guide-journey">
        {JOURNEY.map((step) => (
          <li key={step.n} className="card guide-step">
            <div className="guide-step-head">
              <span className="guide-step-num">{step.n}</span>
              <h3>{step.title}</h3>
            </div>
            {step.body}
            {step.link && (
              <Link className="btn primary guide-step-link" to={step.link.to}>
                {step.link.label} →
              </Link>
            )}
          </li>
        ))}
      </ol>

      <div className="hint">
        Stuck? Dev Tools (footer link below the nav) shows service health and the full API catalog if something
        looks broken.
      </div>
    </div>
  );
}
