import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import '../od-roadmap.css';

/* Roadmap & Guide — ported from frontend by opendesign/roadmap.html.
 * Public page: journey stepper + language phases + turn pipeline diagram.
 * All state local; no backend calls.
 */
const STEPS = [
  { t: 'Create a campaign', you: 'Name your campaign — “Aug absence sweep” is enough.', sarati: 'Sets up a safe workspace where every call is tracked and reversible.', tip: 'Campaigns can be paused anytime; queued people are never disturbed twice.' },
  { t: 'Upload contacts', you: 'Drop in a CSV or Excel with names and phone numbers.', sarati: 'Parses it locally, checks every number’s format, flags bad rows red before import.', tip: 'Extra columns like student_name become words the agent can say naturally.' },
  { t: 'Configure the agent', you: 'Pick questions to ask and the fields you want captured.', sarati: 'Turns that list into a natural conversation plan — not a rigid script.', tip: 'Every save creates a new version; old calls keep the version that made them.' },
  { t: 'Launch', you: 'Press launch inside the calling window (9 AM – 9 PM IST).', sarati: 'Dials contacts one by one, respects busy numbers, retries politely later.', tip: 'Launch is disabled outside the window — nobody gets a midnight call.' },
  { t: 'AI holds the conversation', you: 'Watch live tiles as calls connect, answer or miss.', sarati: 'Listens, takes turns, handles interruptions — like a trained human caller.', tip: 'Median response time target is under 900 ms so pauses feel natural.' },
  { t: 'Transcribe', you: 'Nothing — this happens automatically.', sarati: 'Writes down every word with speakers and timestamps, second by second.', tip: 'Transcripts power the extraction step and stay attached to each contact.' },
  { t: 'Extract structured results', you: 'Define what counts as an answer: reason, callback, yes/no.', sarati: 'Fills those fields with confidence scores — low-confidence items get flagged.', tip: 'Flagged calls surface with ⚑ so a human reviews only what needs review.' },
  { t: 'Review & export', you: 'Open results, filter what matters, export to Excel.', sarati: 'Produces one row per person: transcript link, fields, outcome, duration.', tip: 'Exports include everything — perfect for feeding your existing systems.' },
];

const PHASES = [
  ['Phase 1 · English', 'Live today — full quality', 'live', 'ok'],
  ['Phase 2 · Telugu', 'In training — rolling out after accent benchmarks pass', 'next', 'warn'],
  ['Phase 3 · Telugu + English code-switching', 'Mixed sentences handled naturally (“fee pay cheyyandi please”)', 'next', 'warn'],
  ['Phase 4 · More Indian languages', 'Hindi, Tamil, Kannada and beyond — community-driven order', 'planned', 'queued'],
];

const PIPE = [['☎', 'Phone line'], ['〰', 'Real-time audio'], ['A|', 'Speech recognition'], ['◆', 'Conversation engine'], ['♪', 'Voice generation'], ['☎', 'Back to caller']];

export default function RoadmapPage() {
  const [navScrolled, setNavScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [cur, setCur] = useState(0);

  React.useEffect(() => {
    const onScroll = () => setNavScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const go = (i) => setCur(Math.max(0, Math.min(STEPS.length - 1, i)));
  const s = STEPS[cur];

  return (
    <div className="od-roadmap">
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
            <Link to="/roadmap" className="nav-link">Roadmap</Link>
            <Link to="/login" className="nav-cta">Start free</Link>
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

      <main className="page" style={{ maxWidth: 1120, margin: '0 auto', padding: '170px 24px 80px' }}>
        <div className="card pad" style={{ marginBottom: 20 }}>
          <span style={{ fontSize: 11, letterSpacing: '.24em', textTransform: 'uppercase', color: 'var(--gold)' }}>Start here</span>
          <h2 style={{ fontFamily: 'var(--font-d)', fontSize: 'clamp(22px,3vw,30px)', fontWeight: 600, marginTop: 10 }}>From a spreadsheet to structured answers — in eight steps.</h2>
          <p style={{ color: 'var(--muted)', marginTop: 10, maxWidth: 640, lineHeight: 1.7 }}>Click any step below (or use the arrows) to see exactly what <b style={{ color: 'var(--brand)' }}>you do</b>, what <b style={{ color: 'var(--cyan)' }}>Sarathi does</b>, and one practical tip.</p>
        </div>

        <div className="journey-steps">
          {STEPS.map((st, i) => (
            <div key={st.t} className={`js ${i === cur ? 'on' : ''} ${i < cur ? 'seen' : ''}`} onClick={() => go(i)} role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') go(i); }}>
              <span className="node">{i < cur ? '✓' : i + 1}</span><p>{st.t}</p>
            </div>
          ))}
        </div>
        <div className="detail-card card pad">
          <div className="dc-grid">
            <div className="dc-box you"><h5>You do</h5><p>{s.you}</p></div>
            <div className="dc-box sarati"><h5>Sarathi does</h5><p>{s.sarati}</p></div>
            <div className="dc-box tip"><h5>Good to know</h5><p>{s.tip}</p></div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 26 }}>
            <button className="btn ghost sm" disabled={cur === 0} onClick={() => go(cur - 1)}>← Previous</button>
            <button className="btn primary sm" onClick={() => { if (cur === STEPS.length - 1) { window.location.href = '/playground'; } else { go(cur + 1); } }}>
              {cur === STEPS.length - 1 ? '+ Try the playground' : 'Next →'}
            </button>
            <div className="progress" style={{ maxWidth: 220, marginLeft: 'auto' }}><b style={{ width: `${((cur + 1) / STEPS.length) * 100}%` }}></b></div>
          </div>
        </div>

        <h2 style={{ fontFamily: 'var(--font-d)', fontSize: 24, fontWeight: 600, margin: '46px 0 6px' }} id="languages">Language roadmap</h2>
        <p style={{ color: 'var(--muted)', maxWidth: 640, lineHeight: 1.7 }}>Honest phases — we ship each language only when it passes our quality bar, not before.</p>
        <div className="rowflex" style={{ marginTop: 22, alignItems: 'stretch', gap: 22 }}>
          <div className="card pad" style={{ flex: 1.1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center', gap: 10 }}>
            <div className="dia">తెలుగు</div>
            <p style={{ fontSize: 13, color: 'var(--dim)' }}>Designed with Indian multilingual voice interaction in mind from day one.</p>
          </div>
          <div className="card pad" style={{ flex: 2 }}>
            {PHASES.map(([t, d, k, c]) => (
              <div key={t} className={`phase ${k}`}>
                <span className="pn">{k === 'live' ? '✓' : k === 'next' ? '…' : '→'}</span>
                <div style={{ flex: 1 }}><b style={{ fontSize: 15 }}>{t}</b><p style={{ fontSize: 13, color: 'var(--muted)' }}>{d}</p></div>
                <span className={`chip ${c}`}>{c}</span>
              </div>
            ))}
          </div>
        </div>

        <h2 style={{ fontFamily: 'var(--font-d)', fontSize: 24, fontWeight: 600, margin: '46px 0 6px' }}>Under the hood — every single turn</h2>
        <p style={{ color: 'var(--muted)', maxWidth: 640, lineHeight: 1.7 }}>This loop runs many times per call. Speed here is why Sarathi doesn’t sound like a robot.</p>
        <div className="card pad" style={{ marginTop: 18 }}>
          <div className="pipe">
            {PIPE.map((p, i) => (
              <React.Fragment key={p[1]}>
                {i > 0 && <div className="pflow"></div>}
                <div className="pnode hot" style={{ animationDelay: `${i * 0.2}s` }}>
                  <div className="ic" style={{ fontSize: 19, fontFamily: 'var(--font-m)' }}>{p[0]}</div>
                  <small>{p[1]}</small>
                </div>
              </React.Fragment>
            ))}
          </div>
          <p className="hint" style={{ marginTop: 6 }}>Streaming audio both ways means barge-in works — callers can interrupt mid-sentence and be heard.</p>
        </div>
      </main>

      <footer>
        <div className="f-in" style={{ maxWidth: 1120, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, flexWrap: 'wrap', fontSize: 13, color: 'var(--dim)' }}>
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
