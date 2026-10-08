import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import '../od-roadmap-v2.css';
import ThemeToggle from '../components/ThemeToggle.jsx';

/* Roadmap â€” redesigned Oct 2026.
 * Three status lanes (Live / Building / Planned), a vertical journey
 * timeline, and the per-turn loop. All content visible without interaction;
 * reveal-on-scroll is progressive enhancement only.
 * Public page: no auth, no backend calls.
 */
const LIVE = [
  { t: 'English voice calls', d: 'Full-quality conversations with sub-second replies, barge-in, and structured field extraction on every call.' },
  { t: 'Playground testing', d: 'Try any agent in the browser first â€” live console, per-turn latency, and provider attribution before spending a rupee.' },
  { t: 'Campaign calling', d: 'Upload contacts, launch inside the 9 AM â€“ 9 PM IST window, pause anytime. Busy numbers retry politely later.' },
  { t: 'Transcripts & Excel export', d: 'Every word with speakers and timestamps, fields with confidence scores, one row per person out to Excel.' },
];

const BUILDING = [
  { t: 'Telugu', d: 'In training â€” ships only after it passes our accent benchmarks, not before.', meta: 'Accent benchmarks in progress' },
  { t: 'Telugu + English code-switching', d: 'Mixed sentences handled naturally (â€œfee pay cheyyandi pleaseâ€).', meta: 'Follows Telugu' },
];

const PLANNED = [
  { t: 'Hindi, Tamil, Kannada & beyond', d: 'More Indian languages in community-driven order. Tell us which your callers speak.', meta: 'Vote: hello@echosarathi.ai' },
];

const STEPS = [
  { t: 'Create a campaign', you: 'Name your campaign â€” â€œAug absence sweepâ€ is enough.', sarathi: 'Sets up a safe workspace where every call is tracked and reversible.', tip: 'Campaigns can be paused anytime; queued people are never disturbed twice.' },
  { t: 'Upload contacts', you: 'Drop in a CSV or Excel with names and phone numbers.', sarathi: 'Parses it locally, checks every numberâ€™s format, flags bad rows red before import.', tip: 'Extra columns like student_name become words the agent can say naturally.' },
  { t: 'Configure the agent', you: 'Pick questions to ask and the fields you want captured.', sarathi: 'Turns that list into a natural conversation plan â€” not a rigid script.', tip: 'Every save creates a new version; old calls keep the version that made them.' },
  { t: 'Launch', you: 'Press launch inside the calling window (9 AM â€“ 9 PM IST).', sarathi: 'Dials contacts one by one, respects busy numbers, retries politely later.', tip: 'Launch is disabled outside the window â€” nobody gets a midnight call.' },
  { t: 'AI holds the conversation', you: 'Watch live tiles as calls connect, answer or miss.', sarathi: 'Listens, takes turns, handles interruptions â€” like a trained human caller.', tip: 'Median response time target is under 900 ms so pauses feel natural.' },
  { t: 'Transcribe', you: 'Nothing â€” this happens automatically.', sarathi: 'Writes down every word with speakers and timestamps, second by second.', tip: 'Transcripts power the extraction step and stay attached to each contact.' },
  { t: 'Extract structured results', you: 'Define what counts as an answer: reason, callback, yes/no.', sarathi: 'Fills those fields with confidence scores â€” low-confidence items get flagged.', tip: 'Flagged calls surface for human review; you only check what needs checking.' },
  { t: 'Review & export', you: 'Open results, filter what matters, export to Excel.', sarathi: 'Produces one row per person: transcript link, fields, outcome, duration.', tip: 'Exports include everything â€” ready for your existing systems.' },
];

const LOOP = [
  ['Phone line', 'The call connects'],
  ['Speech recognition', 'Every word, live'],
  ['Conversation engine', 'Decides the reply'],
  ['Voice generation', 'Speaks naturally'],
];

function StatusDot({ kind, label }) {
  return (
    <span className={`rm2-status rm2-${kind}`}>
      <span className="rm2-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

function Lane({ id, title, sub, kind, label, items }) {
  return (
    <section className="rm2-lane reveal" aria-labelledby={id}>
      <div className="rm2-lane-head">
        <h2 id={id}>{title}</h2>
        <StatusDot kind={kind} label={label} />
      </div>
      <p className="rm2-lane-sub">{sub}</p>
      <div className="rm2-cards">
        {items.map((it) => (
          <article className="rm2-card" key={it.t}>
            <h3>{it.t}</h3>
            <p>{it.d}</p>
            {it.meta && <p className="rm2-meta">{it.meta}</p>}
          </article>
        ))}
      </div>
    </section>
  );
}

export default function RoadmapPage() {
  const [navScrolled, setNavScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    const onScroll = () => setNavScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !('IntersectionObserver' in window)) {
      root?.querySelectorAll('.reveal').forEach((el) => el.classList.add('in'));
      return undefined;
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      }),
      { threshold: 0.12 },
    );
    root.querySelectorAll('.reveal').forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  return (
    <div className="rm2" ref={rootRef}>
      <nav id="mainNav" className={navScrolled ? 'scrolled' : ''}>
        <div className="nav-inner">
          <div className="nav-left">
            <Link to="/" className="logo" style={{ display: 'flex', alignItems: 'center', gap: 12, textDecoration: 'none' }}>
              <svg className="logo-mark" width="38" height="22" viewBox="0 0 46 26" fill="none" aria-hidden="true"><circle className="lm-src" cx="6" cy="13" r="2.2" /><path className="lm-a l1" d="M10.02 7.27 A7 7 0 0 1 10.02 18.73" /><path className="lm-a l2" d="M12.88 3.17 A12 12 0 0 1 12.88 22.83" /><circle className="lm-echo" cx="40" cy="13" r="2.2" /><path className="lm-b r1" d="M35.98 7.27 A7 7 0 0 0 35.98 18.73" /><path className="lm-b r2" d="M33.12 3.17 A12 12 0 0 0 33.12 22.83" /></svg>
              <span className="logo-text">Echo Sarathi</span>
            </Link>
            <Link to="/#product" className="nav-link">Product</Link>
            <Link to="/#usecases" className="nav-link">Use Cases</Link>
            <Link to="/#demo" className="nav-link">Demo</Link>
          </div>
          <div className="nav-right">
            <Link to="/playground" className="nav-link">Playground</Link>
            <Link to="/roadmap" className="nav-link" aria-current="page">Roadmap</Link>
            <ThemeToggle />            <Link to="/login" className="nav-cta">Start free</Link>
            <div className={`hamburger${mobileOpen ? ' open' : ''}`} role="button" tabIndex={0} aria-label="Menu"
              onClick={() => setMobileOpen((v) => !v)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setMobileOpen((v) => !v); }}>
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </nav>
      <div className={`mobile-drawer${mobileOpen ? ' open' : ''}`} onClick={() => setMobileOpen(false)}>
        <Link to="/#product">Product</Link>
        <Link to="/#usecases">Use Cases</Link>
        <Link to="/#demo">Demo</Link>
        <Link to="/playground">Playground</Link>
        <Link to="/roadmap">Roadmap</Link>
        <Link to="/login" className="drawer-cta">Start free</Link>
      </div>

      <main className="rm2-page">
        <header className="rm2-hero reveal">
          <span className="rm2-kick">Roadmap Â· updated October 2026</span>
          <h1>Built in the open.</h1>
          <p className="rm2-sub">
            What works today, what&apos;s in training, and what&apos;s next â€” no vapor.
            We ship each language only when it passes our quality bar, not before.
          </p>
          <div className="rm2-counts" role="list" aria-label="Roadmap status summary">
            <span role="listitem"><b>4</b> live now</span>
            <span role="listitem"><b>2</b> in training</span>
            <span role="listitem"><b>1</b> planned</span>
          </div>
          <div className="rm2-hero-cta">
            <Link to="/playground" className="rm2-btn-primary">Try the playground</Link>
            <Link to="/pricing" className="rm2-btn-ghost">See pricing</Link>
          </div>
        </header>

        <Lane
          id="lane-live"
          title="Live now"
          sub="Working today, on real calls, billed by the second."
          kind="live"
          label="Live"
          items={LIVE}
        />
        <Lane
          id="lane-building"
          title="In training"
          sub="Being built and benchmarked right now."
          kind="building"
          label="Building"
          items={BUILDING}
        />
        <Lane
          id="lane-planned"
          title="Planned"
          sub="Committed direction, community decides the order."
          kind="planned"
          label="Planned"
          items={PLANNED}
        />

        <section className="rm2-journey reveal" aria-labelledby="journey-h">
          <h2 id="journey-h">From a spreadsheet to structured answers â€” in eight steps.</h2>
          <p className="rm2-lane-sub">What you do, what Sarathi does, and one practical tip per step.</p>
          <ol className="rm2-timeline">
            {STEPS.map((st, i) => (
              <li className="rm2-step" key={st.t}>
                <span className="rm2-node" aria-hidden="true">{i + 1}</span>
                <div className="rm2-step-body">
                  <h3>{st.t}</h3>
                  <dl className="rm2-cols">
                    <div className="rm2-col rm2-you">
                      <dt>You do</dt>
                      <dd>{st.you}</dd>
                    </div>
                    <div className="rm2-col rm2-sarathi">
                      <dt>Sarathi does</dt>
                      <dd>{st.sarathi}</dd>
                    </div>
                    <div className="rm2-col rm2-tip">
                      <dt>Good to know</dt>
                      <dd>{st.tip}</dd>
                    </div>
                  </dl>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="rm2-loop reveal" aria-labelledby="loop-h">
          <h2 id="loop-h">Every turn, in under a second.</h2>
          <p className="rm2-lane-sub">
            This loop runs many times per call. Speed here is why Sarathi doesn&apos;t sound like a robot â€”
            and callers can interrupt mid-sentence and be heard.
          </p>
          <div className="rm2-pipe">
            {LOOP.map(([t, d], i) => (
              <React.Fragment key={t}>
                {i > 0 && <div className="rm2-flow" aria-hidden="true" />}
                <div className="rm2-pnode">
                  <span className="rm2-pnum" aria-hidden="true">{i + 1}</span>
                  <b>{t}</b>
                  <small>{d}</small>
                </div>
              </React.Fragment>
            ))}
          </div>
          <div className="rm2-targets">
            <span><b>â‰¤ 900 ms</b> median reply</span>
            <span><b>â‰¤ 1.5 s</b> slowest 5%</span>
            <span><b>â‚¹8.50</b> per minute</span>
          </div>
        </section>

        <section className="rm2-cta reveal" aria-labelledby="cta-h">
          <h2 id="cta-h">Start free. Scale when it works.</h2>
          <p>Create an agent, run your first calls on us, and only pay when you take it live.</p>
          <div className="rm2-hero-cta">
            <Link to="/login" className="rm2-btn-primary">Start free</Link>
            <Link to="/#demo" className="rm2-btn-ghost">See the demo</Link>
          </div>
        </section>
      </main>

      <footer>
        <div className="f-in">
          <span>&copy; {new Date().getFullYear()} Echo Sarathi Labs</span>
          <div className="f-links">
            <Link to="/">Home</Link>
            <Link to="/pricing">Pricing</Link>
            <Link to="/playground">Playground</Link>
            <Link to="/login">Sign in</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}


