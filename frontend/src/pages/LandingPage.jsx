import React, { useEffect, useRef, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { getToken } from '../api.js';
import '../od-landing.css';
import ThemeToggle from '../components/ThemeToggle.jsx';
import { initOdLanding } from '../od-landing.js';

/* OpenDesign landing, ported from frontend by opendesign/echo-sarati-landing.html.
 * Canvases + labs + 3D run through od-landing.js (mount/cleanup);
 * nav scroll, hamburger, and reveal live in React below.
 */
export default function LandingPage() {
  const signedIn = getToken();
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
    if (root) {
      const targets = root.querySelectorAll('.reveal,.reveal-left,.reveal-right,.reveal-scale');
      if (!targets.length || !('IntersectionObserver' in window)) {
        targets.forEach((el) => el.classList.add('in'));
      } else {
        const io = new IntersectionObserver(
          (entries) => entries.forEach((e) => {
            if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
          }),
          { threshold: 0.12 },
        );
        targets.forEach((el) => io.observe(el));
        return () => io.disconnect();
      }
    }
    return undefined;
  }, []);

  useEffect(() => {
    let destroy = null;
    try {
      destroy = initOdLanding();
    } catch {
      destroy = null;
    }
    return () => {
      try { if (destroy) destroy(); } catch { /* already torn down */ }
    };
  }, []);

  if (signedIn) return <Navigate to="/" replace />;

  return (
    <div className="od-landing" ref={rootRef}>
      <nav id="mainNav" className={navScrolled ? 'scrolled' : ''}>
        <div className="nav-inner">
          <div className="nav-left">
            <a href="#" className="logo" aria-label="Echo Sarathi — home" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>
              <span className="logo-text">Echo Sarathi</span>
            </a>
            <a href="#product" className="nav-link">Product</a>
            <a href="#usecases" className="nav-link">Use Cases</a>
            <Link to="/pricing" className="nav-link">Pricing</Link>
            <Link to="/playground" className="nav-link">Playground</Link>
          </div>
          <div className="nav-right">
            <Link to="/roadmap" className="nav-link">Roadmap</Link>
            <Link to="/login" className="nav-link">Sign in</Link>
            <ThemeToggle />            <Link to="/login" className="nav-cta">Start free</Link>
            <div className={`hamburger${mobileOpen ? ' open' : ''}`} id="hamburgerBtn" aria-label="Menu" role="button" tabIndex={0}
              onClick={() => setMobileOpen((v) => !v)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setMobileOpen((v) => !v); }}>
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </nav>

      <div className={`mobile-drawer${mobileOpen ? ' open' : ''}`} id="mobileDrawer" onClick={() => setMobileOpen(false)}>
        <a href="#product">Product</a>
        <a href="#usecases">Use Cases</a>
        <Link to="/pricing">Pricing</Link>
        <Link to="/playground">Playground</Link>
        <Link to="/roadmap">Roadmap</Link>
        <Link to="/login" className="drawer-cta">Start free</Link>
      </div>

{/* ─── HERO ─── */}
<section className="hero">
  <div className="hero-kicker">AI Voice Infrastructure</div>
  <h1>Calls that <span className="accent">listen</span>, understand, and remember.</h1>
  <p className="hero-sub">The bridge between how people actually talk and what your software records — outbound voice agents that take turns, yield when interrupted, and return every answer as structured data you can act on.</p>
  <div className="hero-btns">
    <Link to="/login" className="btn-primary">Start making calls</Link>
    <a className="btn-ghost" href="#demo">Try the demo</a>
  </div>
  <div className="hero-visual">
    <canvas id="waveCanvas"></canvas>
    <div className="hero-visual-overlay">
      <div className="hero-visual-pill">
        <span className="pill-dot"></span>
        <span className="pill-text"><strong>Live call</strong> — 01:42 elapsed</span>
      </div>
      <span className="wave-tag left">Your voice</span>
      <span className="wave-tag right">Echo Sarathi</span>
    </div>
  </div>
</section>


{/* --- POSITIONING: one platform, any structured outbound conversation --- */}
<section className="flow-band" style={{textAlign: 'center'}} aria-label="Built for any outbound conversation">
  <div className="wrap">
    <span className="kick" style={{justifyContent: "center"}}>One platform, any conversation</span>
    <h2 className="section-title display">Built to bridge the gap between people and your software.</h2>
    <p className="sec-sub">Sarathi is voice infrastructure, not a single-purpose bot. Any workflow that runs on a structured phone call — reminders, confirmations, qualification, feedback, collections, follow-ups — becomes an agent your team launches from the console.</p>
    <div className="usecase-chips">
      <span>Appointment reminders</span>
      <span>Lead qualification</span>
      <span>Attendance follow-up</span>
      <span>Feedback &amp; NPS</span>
      <span>Payment reminders</span>
      <span>Event RSVPs</span>
      <span>Delivery rescheduling</span>
      <span>Surveys</span>
    </div>
    <div className="sim-actions" style={{justifyContent: "center"}}>
      <a href="#demo" className="btn-primary sm">Hear a live agent</a>
      <Link to="/login" className="btn-ghost sm">Start free with 10 minutes</Link>
    </div>
  </div>
</section>

{/* ─── PROBLEM ─── */}
<section className="problem" id="product">
  <div className="wrap">
    <span className="kick">The problem</span>
    <h2 className="section-title display">Phone calls shouldn't need a human on the line.</h2>
    <p className="section-sub">Teams spend hours on repetitive outbound calls — reminders, confirmations, qualification, follow-ups. The work is structured, but the conversations need to feel human.</p>
    <div className="problem-grid">
      <div className="problem-list">
        <div className="problem-item reveal-left"><div className="problem-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg></div><div><h4>Hours wasted on repetitive calls</h4><p>Same questions, same scripts, every day. Your team's time goes to conversations that could be automated.</p></div></div>
        <div className="problem-item reveal-left"><div className="problem-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div><div><h4>IVR systems frustrate callers</h4><p>Press 1 for this, press 2 for that. People hang up. Information stays uncollected.</p></div></div>
        <div className="problem-item reveal-left"><div className="problem-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg></div><div><h4>Data stays locked in recordings</h4><p>Call logs pile up but the insights — who said what, what was decided — stay buried in audio.</p></div></div>
      </div>
      <div className="problem-stat">
        <div className="stat-card reveal-right"><div className="num">73%</div><div className="label">of outbound calls are routine, repeatable conversations</div><div className="stat-bar"></div></div>
        <div className="stat-card reveal-right" style={{transitionDelay: ".1s"}}><div className="num" style={{color: "var(--gold)"}}>0.9s</div><div className="label">median end-to-end response time with Sarathi</div><div className="stat-bar" style={{background: "linear-gradient(90deg,var(--gold),var(--violet))"}}></div></div>
        <div className="stat-card reveal-right" style={{transitionDelay: ".2s"}}><div className="num" style={{color: "var(--fg)"}}>5/5</div><div className="label">fields extracted per call on average, with confidence scores</div><div className="stat-bar" style={{background: "linear-gradient(90deg,var(--cyan),var(--violet))"}}></div></div>
      </div>
    </div>
  </div>
</section>

{/* ─── PRODUCT SHOWCASE ─── */}
<section className="showcase reveal-scale">
  <div className="wrap">
    <span className="kick">The product</span>
    <h2 className="section-title display">See it run a real call.</h2>
    <p className="section-sub">Upload contacts, pick an agent, launch. The AI handles the conversation — and every answer lands in a structured table you can export.</p>
    <div className="showcase-visual">
      <div className="showcase-header">
        <h4>Campaign: Site Visit Follow-up — Prestige Realty</h4>
        <div className="showcase-dots"><span></span><span></span><span></span></div>
      </div>
      <div className="showcase-body">
        <div className="showcase-main">
          <div className="s-bar">
            <span className="s-pill"><b></b>Active</span>
            <span className="s-timer">42 / 80 calls</span>
          </div>
          <div className="s-bubbles">
            <div className="s-bubble agent"><span className="who">Sarathi Agent</span>Good morning! Am I speaking with Mr. Rao?</div>
            <div className="s-bubble caller"><span className="who">Caller</span>Yes, speaking.</div>
            <div className="s-bubble agent"><span className="who">Sarathi Agent</span>I'm calling from Prestige Realty about your site visit yesterday. Did you get a chance to see the 3BHK at Whitefield?</div>
            <div className="s-bubble caller"><span className="who">Caller</span>Yes, I saw it. I liked it, but the price feels high.</div>
            <div className="s-bubble agent"><span className="who">Sarathi Agent</span>Understood. I've noted that. Would you like our sales team to call you with pricing options?</div>
          </div>
        </div>
        <div className="showcase-side">
          <span className="pane-h">Extracted data</span>
          <div className="s-fields">
            <div className="s-frow"><span className="k">contact_name</span><span className="v">Mr. Rao <span className="conf hi">96%</span></span></div>
            <div className="s-frow"><span className="k">visited</span><span className="v">Yes <span className="conf hi">92%</span></span></div>
            <div className="s-frow"><span className="k">interest</span><span className="v">Liked the 3BHK <span className="conf hi">89%</span></span></div>
            <div className="s-frow"><span className="k">concern</span><span className="v">Price <span className="conf md">86%</span></span></div>
            <div className="s-frow"><span className="k">callback</span><span className="v">Pricing call <span className="conf wait">pending</span></span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

{/* ─── HOW IT WORKS ─── */}
<section className="how">
  <div className="wrap">
    <span className="kick">How it works</span>
    <h2 className="section-title display">Four steps. Zero infrastructure.</h2>
    <p className="section-sub">No phone hardware. No scripts to record. No call-center setup. Upload, configure, launch, review.</p>
    <div className="how-steps">
      <div className="step reveal" style={{transitionDelay: "0s"}}>
        <span className="step-ghost">1</span>
        <div className="step-icon"><svg viewBox="0 0 24 24"><path d="M12 16V4m0 0l-4 4m4-4l4 4"/><path d="M4 20h16"/></svg></div>
        <h4>Upload contacts</h4>
        <p>Drop a CSV or Excel file. Columns map to conversation variables — names, IDs, anything the agent should know.</p>
        <span className="step-bar"></span>
      </div>
      <div className="step reveal" style={{transitionDelay: ".12s"}}>
        <span className="step-ghost">2</span>
        <div className="step-icon"><svg viewBox="0 0 24 24"><path d="M4 6h8M18 6h2M4 12h2M10 12h10M4 18h12"/><circle cx="15" cy="6" r="2"/><circle cx="7" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg></div>
        <h4>Configure your agent</h4>
        <p>Set questions, context, voice, and what data to extract. Save as an immutable version you can always roll back to.</p>
        <span className="step-bar"></span>
      </div>
      <div className="step reveal" style={{transitionDelay: ".24s"}}>
        <span className="step-ghost">3</span>
        <div className="step-icon"><svg viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg></div>
        <h4>Launch campaign</h4>
        <p>The AI calls each contact, holds a natural conversation, and handles busy signals, no-answers, and callbacks automatically.</p>
        <span className="step-bar"></span>
      </div>
      <div className="step reveal" style={{transitionDelay: ".36s"}}>
        <span className="step-ghost">4</span>
        <div className="step-icon"><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/></svg></div>
        <h4>Review &amp; export</h4>
        <p>Every call returns a transcript, extracted fields with confidence scores, and a structured outcome — all exportable as CSV.</p>
        <span className="step-bar"></span>
      </div>
    </div>
  </div>
</section>

{/* ─── TRANSFORMATION ─── */}
<section className="transform" id="usecases">
  <div className="wrap">
    <span className="kick">The difference</span>
    <h2 className="section-title display">What changes when your calls answer themselves.</h2>
    <p className="section-sub">Every workflow that used to eat your team's hours now runs autonomously — with structured results, not voicemail.</p>
  </div>
  <div className="wrap">
    <div className="transform-grid">

      <div className="transform-card reveal-left">
        <div className="tc-before">
          <span className="tc-label">Before</span>
          <h3 className="tc-title">A sales team dials 300 inbound leads by hand</h3>
          <p className="tc-desc">Most go to voicemail. The ones who answer get a different pitch from every rep, and nobody knows which leads are actually ready to buy.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><path d="M13 17l5-5-5-5M6 17l5-5-5-5"/></svg>2 days of calling</span>
        </div>
        <div className="tc-divider"><div className="tc-arrow"><svg viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg></div></div>
        <div className="tc-after">
          <span className="tc-label">After</span>
          <h3 className="tc-title">Sarathi qualifies every lead on your list, start to finish</h3>
          <p className="tc-desc">Each call asks budget, timeline and intent, answers questions from your context, and flags the hot leads with a transcript. Your reps only call the ones who are ready.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>300 leads, zero staff hours</span>
        </div>
      </div>

      <div className="transform-card reveal-left">
        <div className="tc-before">
          <span className="tc-label">Before</span>
          <h3 className="tc-title">A hospital's follow-up team calls 150 post-surgery patients</h3>
          <p className="tc-desc">Each call takes 3–5 minutes. The team gets through 30 per day. Patients who needed urgent attention get called back on day three — too late for some.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><path d="M13 17l5-5-5-5M6 17l5-5-5-5"/></svg>5 days to reach everyone</span>
        </div>
        <div className="tc-divider"><div className="tc-arrow"><svg viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg></div></div>
        <div className="tc-after">
          <span className="tc-label">After</span>
          <h3 className="tc-title">Sarathi calls every patient within hours of discharge</h3>
          <p className="tc-desc">It asks about pain levels, medication compliance, and symptoms. Urgent responses are flagged instantly with a transcript and structured summary. No patient falls through the cracks.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>All 150 in 4 hours</span>
        </div>
      </div>


    </div>
  </div>
</section>

{/* ─── INTERACTIVE DEMO ─── */}
<section className="demo" id="demo">
  <div className="wrap">
    <span className="kick">Try it yourself</span>
    <h2 className="section-title display">Don't read about it — hear it.</h2>
    <p className="section-sub">This is a real-estate follow-up call exactly as Sarathi runs it. Interrupt the agent mid-sentence; it stops instantly, absorbs what you say, and picks up where it left off.</p>
    <div className="demo-box reveal-scale">
      <div className="demo-inner">
        <div className="demo-left">
          <div className="demo-bar">
            <span className="s-pill" id="dChip"><b></b><span id="dChipTxt">Idle</span></span>
            <span className="s-timer" id="dTimer">00:00</span>
          </div>
          <div className="demo-transcript" id="dTranscript">
            <p style={{color: 'var(--muted)', fontSize: '13px', lineHeight: 1.7, margin: 0}}>Tap the microphone to start the call — or interrupt it mid-sentence to see how it yields.</p>
          </div>
          <div className="demo-choices" id="dChoices"></div>
          <div className="demo-btns">
            <button className="demo-orb" id="dOrb" data-m="idle">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><rect x="9" y="3" width="6" height="11" rx="3" fill="#e9e4da"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="#e9e4da" strokeWidth="1.8" strokeLinecap="round"/></svg>
            </button>
            <button className="btn-interrupt" id="dIntBtn">Interrupt</button>
            <button className="btn-end" id="dEndBtn">End call</button>
          </div>
        </div>
        <div className="demo-right">
          <span className="pane-h">Extracted fields</span>
          <div className="demo-fields" id="dFields">
            <div className="d-frow" data-k="contact_name"><span className="k">contact_name</span><span className="v">— <span className="conf wait">waiting</span></span></div>
            <div className="d-frow" data-k="purpose"><span className="k">purpose</span><span className="v">— <span className="conf wait">waiting</span></span></div>
            <div className="d-frow" data-k="outcome"><span className="k">outcome</span><span className="v">— <span className="conf wait">waiting</span></span></div>
            <div className="d-frow" data-k="callback_requested"><span className="k">callback_requested</span><span className="v">— <span className="conf wait">waiting</span></span></div>
          </div>
          <div className="demo-latency" id="dLatency"></div>
          <div className="demo-summary" id="dSummary">
            <h5>Call complete</h5>
            <p id="dSumTxt"></p>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

{/* ─── LANGUAGE FIELD ─── */}
<section className="lang-band" id="languages">
  <div className="wrap">
    <span className="kick" style={{justifyContent: "center"}}>Built multilingual from day one</span>
    <h2 className="section-title display">English today. Every Indian voice next.</h2>
    <p className="sec-sub">Phase 1 runs on English. Telugu, Telugu–English code-switching and more Indian languages are already on the road — designed in from the start, not bolted on later.</p>
    <div className="sim-actions"><Link to="/roadmap" className="btn-ghost sm">See the language roadmap →</Link></div>
  </div>
</section>

{/* ─── CTA ─── */}
<section className="cta reveal">
  <canvas className="cta-orb" id="ctaOrb" aria-hidden="true"></canvas>
  <div className="wrap">
    <span className="kick" style={{justifyContent: "center"}}>Start in minutes</span>
    <h2 className="section-title display">A thousand conversations are waiting.</h2>
    <p>Create an agent, upload your list, and hear the difference on your very first call. No hardware, no scripts to record.</p>
    <div className="cta-btns">
      <Link to="/login" className="btn-primary">Start free</Link>
      <Link to="/roadmap" className="btn-ghost">See the full flow</Link>
    </div>
  </div>
</section>

<footer>
  <div className="wrap">
    <div className="f-grid">
      <div className="f-brand">
        <a href="#" className="logo" aria-label="Echo Sarathi — home">
          <svg className="logo-mark" width="38" height="22" viewBox="0 0 46 26" fill="none" aria-hidden="true">
            <circle className="lm-src" cx="6" cy="13" r="2.2"/>
            <path className="lm-a l1" d="M10.02 7.27 A7 7 0 0 1 10.02 18.73"/>
            <path className="lm-a l2" d="M12.88 3.17 A12 12 0 0 1 12.88 22.83"/>
            <circle className="lm-echo" cx="40" cy="13" r="2.2"/>
            <path className="lm-b r1" d="M35.98 7.27 A7 7 0 0 0 35.98 18.73"/>
            <path className="lm-b r2" d="M33.12 3.17 A12 12 0 0 0 33.12 22.83"/>
          </svg>
          <span className="logo-text" style={{fontSize: "20px"}}>Echo Sarathi</span>
        </a>
        <p>Voice infrastructure for real conversations — calls that listen, take turns, and return answers as data.</p>
      </div>
      <div className="f-col"><h6>Platform</h6><Link to="/">Overview</Link><Link to="/agents">Agents</Link><Link to="/campaigns">Campaigns</Link><Link to="/calls">Call history</Link></div>
      <div className="f-col"><h6>Experience</h6><Link to="/playground">Playground</Link><Link to="/agents/new">Agent builder</Link><Link to="/pricing">Pricing</Link><Link to="/roadmap">Roadmap</Link><Link to="/login">Sign in</Link></div>
      <div className="f-col"><h6>Company</h6><a href="mailto:hello@echosarathi.ai">hello@echosarathi.ai</a><Link to="/roadmap">Languages</Link></div>
    </div>
    <div className="f-base">
      <span>&copy; 2026 Echo Sarathi Labs</span>
      <span className="tl">English today &middot; తెలుగు next</span>
    </div>
  </div>
</footer>

    </div>
  );
}


