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
            <a href="#" className="logo" aria-label="Echo Sarathi â€” home" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>
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

{/* â”€â”€â”€ HERO â”€â”€â”€ */}
<section className="hero">
  <div className="hero-kicker">AI Voice Infrastructure</div>
  <h1>Calls that <span className="accent">listen</span>, understand, and remember.</h1>
  <p className="hero-sub">Outbound voice AI that holds real conversations â€” takes turns, yields when interrupted, and returns every answer as structured data you can act on.</p>
  <div className="hero-btns">
    <Link to="/login" className="btn-primary">Start making calls</Link>
    <a className="btn-ghost" href="#demo">Try the demo</a>
  </div>
  <div className="hero-visual">
    <canvas id="waveCanvas"></canvas>
    <div className="hero-visual-overlay">
      <div className="hero-visual-pill">
        <span className="pill-dot"></span>
        <span className="pill-text"><strong>Live call</strong> â€” 01:42 elapsed</span>
      </div>
      <span className="wave-tag left">Your voice</span>
      <span className="wave-tag right">Echo Sarathi</span>
    </div>
  </div>
</section>


{/* --- LIVE PILOT: CMR College of Engineering & Technology --- */}
<section className="flow-band" aria-label="Live pilot at CMR College of Engineering & Technology">
  <div className="wrap">
    <span className="kick" style={{justifyContent: "center"}}>Live pilot</span>
    <h2 className="display">Running now at CMR College of Engineering & Technology.</h2>
    <p className="sec-sub">Absent Student Follow-up &middot; English &middot; India â€” the agent calls parents every morning, records the reason for absence, and exports the sheet. Try it yourself below, or open the live console.</p>
    <div className="sim-actions" style={{justifyContent: "center"}}>
      <Link to="/playground" className="btn-primary sm">Try the live demo</Link>
      <Link to="/campaigns" className="btn-ghost sm">Open the console</Link>
    </div>
  </div>
</section>

{/* â”€â”€â”€ PROBLEM â”€â”€â”€ */}
<section className="problem" id="product">
  <div className="wrap">
    <span className="kick">The problem</span>
    <h2 className="section-title display">Phone calls shouldn't need a human on the line.</h2>
    <p className="section-sub">Teams spend hours on repetitive outbound calls â€” attendance checks, confirmations, follow-ups. The work is structured, but the conversations need to feel human.</p>
    <div className="problem-grid">
      <div className="problem-list">
        <div className="problem-item reveal-left"><div className="problem-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg></div><div><h4>Hours wasted on repetitive calls</h4><p>Same questions, same scripts, every day. Your team's time goes to conversations that could be automated.</p></div></div>
        <div className="problem-item reveal-left"><div className="problem-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div><div><h4>IVR systems frustrate callers</h4><p>Press 1 for this, press 2 for that. People hang up. Information stays uncollected.</p></div></div>
        <div className="problem-item reveal-left"><div className="problem-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg></div><div><h4>Data stays locked in recordings</h4><p>Call logs pile up but the insights â€” who said what, what was decided â€” stay buried in audio.</p></div></div>
      </div>
      <div className="problem-stat">
        <div className="stat-card reveal-right"><div className="num">73%</div><div className="label">of outbound calls are routine, repeatable conversations</div><div className="stat-bar"></div></div>
        <div className="stat-card reveal-right" style={{transitionDelay: ".1s"}}><div className="num" style={{color: "var(--gold)"}}>0.9s</div><div className="label">median end-to-end response time with Sarathi</div><div className="stat-bar" style={{background: "linear-gradient(90deg,var(--gold),var(--violet))"}}></div></div>
        <div className="stat-card reveal-right" style={{transitionDelay: ".2s"}}><div className="num" style={{color: "var(--fg)"}}>5/5</div><div className="label">fields extracted per attendance call on average</div><div className="stat-bar" style={{background: "linear-gradient(90deg,var(--cyan),var(--violet))"}}></div></div>
      </div>
    </div>
  </div>
</section>

{/* â”€â”€â”€ PRODUCT SHOWCASE â”€â”€â”€ */}
<section className="showcase reveal-scale">
  <div className="wrap">
    <span className="kick">The product</span>
    <h2 className="section-title display">See it run a real call.</h2>
    <p className="section-sub">Upload contacts, pick an agent, launch. The AI handles the conversation â€” and every answer lands in a structured table you can export.</p>
    <div className="showcase-visual">
      <div className="showcase-header">
        <h4>Campaign: Attendance Check â€” CMR College of Engineering & Technology</h4>
        <div className="showcase-dots"><span></span><span></span><span></span></div>
      </div>
      <div className="showcase-body">
        <div className="showcase-main">
          <div className="s-bar">
            <span className="s-pill"><b></b>Active</span>
            <span className="s-timer">42 / 80 calls</span>
          </div>
          <div className="s-waveform" id="showWave"></div>
          <div className="s-bubbles">
            <div className="s-bubble agent"><span className="who">Sarathi Agent</span>Good morning! Am I speaking with Mrs. Devi, parent of Rohan?</div>
            <div className="s-bubble caller"><span className="who">Caller</span>Yes, this is she.</div>
            <div className="s-bubble agent"><span className="who">Sarathi Agent</span>Thank you. I'm calling from CMR College of Engineering & Technology to confirm â€” will Rohan be attending classes today?</div>
            <div className="s-bubble caller"><span className="who">Caller</span>He has a fever today, won't be coming.</div>
            <div className="s-bubble agent"><span className="who">Sarathi Agent</span>I'm sorry to hear that. I've noted the absence. Is there anything else you'd like us to know?</div>
          </div>
        </div>
        <div className="showcase-side">
          <span className="pane-h">Extracted data</span>
          <div className="s-fields">
            <div className="s-frow"><span className="k">student_name</span><span className="v">Rohan <span className="conf hi">96%</span></span></div>
            <div className="s-frow"><span className="k">parent_name</span><span className="v">Mrs. Devi <span className="conf hi">94%</span></span></div>
            <div className="s-frow"><span className="k">present_today</span><span className="v">No <span className="conf hi">91%</span></span></div>
            <div className="s-frow"><span className="k">reason</span><span className="v">Sick leave <span className="conf md">88%</span></span></div>
            <div className="s-frow"><span className="k">callback</span><span className="v">â€” <span className="conf wait">pending</span></span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

{/* â”€â”€â”€ HOW IT WORKS â”€â”€â”€ */}
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
        <p>Drop a CSV or Excel file. Columns map to conversation variables â€” names, IDs, anything the agent should know.</p>
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
        <p>Every call returns a transcript, extracted fields with confidence scores, and a structured outcome â€” all exportable as CSV.</p>
        <span className="step-bar"></span>
      </div>
    </div>
  </div>
</section>

{/* â”€â”€â”€ TRANSFORMATION â”€â”€â”€ */}
<section className="transform" id="usecases">
  <div className="wrap">
    <span className="kick">The difference</span>
    <h2 className="section-title display">What changes when your calls answer themselves.</h2>
    <p className="section-sub">Every workflow that used to eat your team's hours now runs autonomously â€” with structured results, not voicemail.</p>
  </div>
  <div className="wrap">
    <div className="transform-grid">

      <div className="transform-card reveal-left">
        <div className="tc-before">
          <span className="tc-label">Before</span>
          <h3 className="tc-title">A staff member dials 200 numbers to take attendance</h3>
          <p className="tc-desc">Half don't pick up. The ones who do give one-word answers written on sticky notes. Nobody knows who was reached by end of day.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><path d="M13 17l5-5-5-5M6 17l5-5-5-5"/></svg>3 hours manual work</span>
        </div>
        <div className="tc-divider"><div className="tc-arrow"><svg viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg></div></div>
        <div className="tc-after">
          <span className="tc-label">After</span>
          <h3 className="tc-title">Sarathi calls every number simultaneously, in parallel</h3>
          <p className="tc-desc">Each call is a real conversation â€” it asks who's present, captures the reason for absence, and flags students who need follow-up. Results appear in your dashboard before the first period ends.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>Done in 8 minutes</span>
        </div>
      </div>

      <div className="transform-card reveal-right">
        <div className="tc-before">
          <span className="tc-label">Before</span>
          <h3 className="tc-title">A survey agency hires 40 callers for a week-long project</h3>
          <p className="tc-desc">Training takes two days. Half the callers quit mid-project. Data comes back inconsistent â€” some skipped questions, some added opinions. Analysis takes another week.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><path d="M13 17l5-5-5-5M6 17l5-5-5-5"/></svg>10 days, 40 people</span>
        </div>
        <div className="tc-divider"><div className="tc-arrow"><svg viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg></div></div>
        <div className="tc-after">
          <span className="tc-label">After</span>
          <h3 className="tc-title">Sarathi runs the entire survey, every question, every respondent</h3>
          <p className="tc-desc">Upload your question flow. Sarathi asks each question naturally, adapts to answers, and extracts structured responses with confidence scores. Every response is consistent, timestamped, and exportable.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>2 days, zero staff</span>
        </div>
      </div>

      <div className="transform-card reveal-left">
        <div className="tc-before">
          <span className="tc-label">Before</span>
          <h3 className="tc-title">A hospital's follow-up team calls 150 post-surgery patients</h3>
          <p className="tc-desc">Each call takes 3â€“5 minutes. The team gets through 30 per day. Patients who needed urgent attention get called back on day three â€” too late for some.</p>
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

      <div className="transform-card reveal-right">
        <div className="tc-before">
          <span className="tc-label">Before</span>
          <h3 className="tc-title">An events company sends 500 reminder calls before a conference</h3>
          <p className="tc-desc">Receptionists read from a script. Some forget to confirm attendance. The catering team gets the wrong count. Day-of chaos.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><path d="M13 17l5-5-5-5M6 17l5-5-5-5"/></svg>12 staff, 2 days</span>
        </div>
        <div className="tc-divider"><div className="tc-arrow"><svg viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg></div></div>
        <div className="tc-after">
          <span className="tc-label">After</span>
          <h3 className="tc-title">Sarathi confirms every attendee and updates your sheet in real time</h3>
          <p className="tc-desc">Each person gets a natural call â€” date, time, venue confirmed. Dietary preferences captured. Special requests logged. Your team sees a live dashboard with confirmed, declined, and pending â€” exported to CSV with one click.</p>
          <span className="tc-metric"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>500 calls, 6 hours</span>
        </div>
      </div>

    </div>
  </div>
</section>

{/* â”€â”€â”€ 3D Â· SIGNAL â†’ STRUCTURE â”€â”€â”€ */}
<section className="flow-band" aria-label="Conversations become structured data">
  <canvas className="flow-cv" id="flowGl"></canvas>
  <div className="flow-tags" aria-hidden="true">
    <span className="flow-tag">In<b>A conversation</b></span>
    <span className="flow-tag">Out<b>Your spreadsheet</b></span>
  </div>
</section>

{/* â”€â”€â”€ INTERACTIVE DEMO â”€â”€â”€ */}
<section className="demo" id="demo">
  <div className="wrap">
    <span className="kick">Try it yourself</span>
    <h2 className="section-title display">Don't read about it â€” hear it.</h2>
    <p className="section-sub">This is an attendance call exactly as Sarathi runs it. Interrupt the agent mid-sentence; it stops instantly, absorbs what you say, and picks up where it left off.</p>
    <div className="demo-box reveal-scale">
      <canvas id="demoGl"></canvas>
      <div className="demo-inner">
        <div className="demo-left">
          <div className="demo-bar">
            <span className="s-pill" id="dChip"><b></b><span id="dChipTxt">Idle</span></span>
            <span className="s-timer" id="dTimer">00:00</span>
          </div>
          <div className="s-waveform" id="dWave"></div>
          <div className="demo-transcript" id="dTranscript"></div>
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
          <div className="demo-fields" id="dFields"></div>
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

{/* â”€â”€â”€ CAMPAIGN SIMULATOR â”€â”€â”€ */}
<section className="lab" id="simulator">
  <div className="wrap">
    <div className="lab-head">
      <span className="kick" style={{justifyContent: "center"}}>Campaign simulator</span>
      <h2 className="display">Launch a campaign. Watch results land.</h2>
      <p className="sec-sub">This is the exact loop your team runs â€” upload a contact list, start the campaign, and watch conversations become structured rows you can export.</p>
    </div>
    <div className="sim-shell reveal-scale">
      <div className="sim-side">
        <div className="sim-side-h"><span>contacts Â· attendance.csv</span><span id="simClock">00:00</span></div>
        <div id="simList"></div>
      </div>
      <div className="sim-main">
        <div className="sim-counters">
          <div className="sim-counter"><b id="cQueued">8</b><span>Queued</span></div>
          <div className="sim-counter"><b id="cCalling">0</b><span>Calling</span></div>
          <div className="sim-counter"><b id="cDone">0</b><span>Completed</span></div>
          <div className="sim-counter"><b id="cMissed">0</b><span>Missed</span></div>
        </div>
        <div className="sim-progress"><i id="simBar"></i></div>
        <div className="sim-feed" id="simFeed"></div>
        <div className="sim-summary" id="simSummary"><span id="simSumTxt"></span><Link to="/campaigns"  className="conf" style={{textDecoration: "none", cursor: "pointer"}}>Open dashboard â†’</Link></div>
      </div>
    </div>
    <div className="sim-actions">
      <button className="btn-primary sm" id="simStart">Run this campaign</button>
      <button className="btn-ghost sm" id="simReset">Reset</button>
    </div>
  </div>
</section>

{/* â”€â”€â”€ LATENCY LAB â”€â”€â”€ */}
<section className="lab" id="latency" style={{paddingTop: "40px"}}>
  <div className="wrap">
    <div className="lab-head">
      <span className="kick" style={{justifyContent: "center"}}>Latency lab</span>
      <h2 className="display">Feel what two seconds does to a conversation.</h2>
      <p className="sec-sub">Same question, two systems. Watch how long each one takes to simply answer a person â€” then imagine every turn of a call feeling like the left column.</p>
    </div>
    <div className="lat-shell reveal-scale" id="latShell">
      <div className="lat-col sarathi" id="latColS">
        <span className="lat-tag"><i></i>Echo Sarathi</span>
        <div id="latRowsS"></div>
        <div className="lat-reply">
          <div className="lat-q">â€œHi â€” can we move my delivery to Friday?â€</div>
          <div className="lat-a" id="latAnsS"></div>
        </div>
      </div>
      <div className="lat-col bot">
        <span className="lat-tag"><i></i>Typical voicebot</span>
        <div id="latRowsB"></div>
        <div className="lat-reply">
          <div className="lat-q">â€œHi â€” can we move my delivery to Friday?â€</div>
          <div className="lat-a" id="latAnsB"></div>
        </div>
      </div>
    </div>
    <div className="sim-actions">
      <button className="btn-primary sm" id="latRun">Run the turn</button>
    </div>
    <p className="lat-note">End-to-end = caller stops speaking â†’ agent's voice responds. Hairline marks the 900 ms median target; second mark on End-to-end rows is the 1500 ms ceiling.</p>
  </div>
</section>

{/* â”€â”€â”€ BARGE-IN THEATER â”€â”€â”€ */}
<section className="lab" id="interrupt" style={{paddingTop: "40px"}}>
  <div className="wrap">
    <div className="lab-head">
      <span className="kick" style={{justifyContent: "center"}}>Interruption, visualized</span>
      <h2 className="display">Watch a barge-in land safely.</h2>
      <p className="sec-sub">Most bots talk over people, or crash mid-turn. Sarathi hears you coming, stops within 200&nbsp;ms, absorbs the new instruction â€” and continues from exactly where it left off.</p>
    </div>
    <div className="barge-shell reveal-scale">
      <canvas className="barge-cv" id="bargeGl"></canvas>
      <span className="barge-cap" id="bargeCap">Sarathi is speakingâ€¦</span>
      <span className="barge-state" id="bargeState">Live turn Â· response 240 ms</span>
    </div>
    <div className="sim-actions">
      <button className="btn-primary sm" id="bargeBtn">Interrupt mid-sentence</button>
    </div>
  </div>
</section>

{/* â”€â”€â”€ VOICE GALLERY â”€â”€â”€ */}
<section className="lab" id="voices" style={{paddingTop: "40px"}}>
  <div className="wrap">
    <div className="lab-head">
      <span className="kick" style={{justifyContent: "center"}}>Voice gallery</span>
      <h2 className="display">Six voices. One sounds like your brand.</h2>
      <p className="sec-sub">Every agent ships with studio-grade voices. Pick one and watch its signature while it speaks â€” this choice takes seconds, and changes everything.</p>
    </div>
    <div className="voice-grid reveal-scale" role="radiogroup" aria-label="Agent voice presets" id="voiceGrid"></div>
    <div className="voice-preview" id="voicePreview">
      <span className="vp-voice" id="vpVoice">Asha</span>
      <span className="vp-line" id="vpLine">Select a voice to hear how it introduces itselfâ€¦</span>
    </div>
  </div>
</section>

{/* â”€â”€â”€ LIVE CALL MONITOR â”€â”€â”€ */}
<section className="monitor" id="monitor">
  <div className="wrap">
    <div className="lab-head">
      <span className="kick" style={{justifyContent: "center"}}>Live dashboard</span>
      <h2 className="display">Every call, tracked in real time.</h2>
      <p className="sec-sub">Watch your campaign unfold as Sarathi makes calls â€” status, duration, and extracted data update as each conversation completes.</p>
    </div>
    <div className="monitor-shell reveal-scale" id="monShell">
      <div className="mon-head"><h4>Campaign: Student Attendance â€” Week 12</h4><span className="mon-live"><span className="dot"></span>Live</span></div>
      <div className="mon-counters">
        <div className="mc-tile accent"><b id="monTotal">48</b><span>Total</span></div>
        <div className="mc-tile"><b id="monDone">0</b><span>Completed</span></div>
        <div className="mc-tile"><b id="monActive">0</b><span>Active</span></div>
        <div className="mc-tile warn"><b id="monMiss">0</b><span>No answer</span></div>
        <div className="mc-tile"><b id="monBusy">0</b><span>Busy</span></div>
      </div>
      <div className="mon-body">
        <div className="mon-chart" id="monChart"></div>
        <div className="mon-bar-labels" id="monLabels"></div>
        <div className="mon-table">
          <div className="mon-row head"><span>Contact</span><span>Phone</span><span>Status</span><span>Duration</span></div>
          <div id="monRows"></div>
        </div>
      </div>
    </div>
  </div>
</section>

{/* â”€â”€â”€ CONVERSATION REPLAY â”€â”€â”€ */}
<section className="replay" id="replay">
  <div className="wrap">
    <div className="lab-head">
      <span className="kick" style={{justifyContent: "center"}}>Conversation replay</span>
      <h2 className="display">From voice to structured data â€” live.</h2>
      <p className="sec-sub">Watch a real call unfold: Sarathi listens, responds naturally, and extracts every data point with confidence scores. Transcript, fields, and waveform â€” all visible.</p>
    </div>
    <div className="replay-shell reveal-scale" id="replayShell">
      <div className="replay-transcript" id="replayTranscript"></div>
      <div className="replay-side">
        <h5>Extracted fields</h5>
        <div className="replay-fields" id="replayFields">
          <div className="rf-row"><span className="k">Student</span><span className="v pending" data-val="Aarav Kumar">â€”</span></div>
          <div className="rf-row"><span className="k">Status</span><span className="v pending" data-val="Absent">â€”</span></div>
          <div className="rf-row"><span className="k">Reason</span><span className="v pending" data-val="Medical appointment">â€”</span></div>
          <div className="rf-row"><span className="k">Parent</span><span className="v pending" data-val="Mrs. Kumar">â€”</span></div>
          <div className="rf-row"><span className="k">Follow-up</span><span className="v pending" data-val="Medical certificate requested">â€”</span></div>
          <div className="rf-row"><span className="k">Duration</span><span className="v pending" data-val="1:24">â€”</span></div>
        </div>
        <div className="replay-wave"><canvas id="replayWave"></canvas></div>
      </div>
    </div>
  </div>
</section>

{/* â”€â”€â”€ LANGUAGE FIELD â”€â”€â”€ */}
<section className="lang-band" id="languages">
  <div className="wrap">
    <span className="kick" style={{justifyContent: "center"}}>Built multilingual from day one</span>
    <h2 className="display">English today. Every Indian voice next.</h2>
    <canvas className="lang-cv" id="langGl" aria-hidden="true"></canvas>
    <p className="sec-sub">Phase 1 runs on English. Telugu, Teluguâ€“English code-switching and more Indian languages are already on the road â€” designed in from the start, not bolted on later.</p>
    <div className="sim-actions"><Link to="/roadmap" className="btn-ghost sm">See the language roadmap â†’</Link></div>
  </div>
</section>

{/* â”€â”€â”€ CTA â”€â”€â”€ */}
<section className="cta reveal">
  <canvas className="cta-orb" id="ctaOrb" aria-hidden="true"></canvas>
  <div className="wrap">
    <span className="kick" style={{justifyContent: "center"}}>Start in minutes</span>
    <h2 className="display">A thousand conversations are waiting.</h2>
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
        <a href="#" className="logo" aria-label="Echo Sarathi â€” home">
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
        <p>Voice infrastructure for real conversations â€” calls that listen, take turns, and return answers as data.</p>
      </div>
      <div className="f-col"><h6>Platform</h6><Link to="/">Overview</Link><Link to="/agents">Agents</Link><Link to="/campaigns">Campaigns</Link><Link to="/calls">Call history</Link></div>
      <div className="f-col"><h6>Experience</h6><Link to="/playground">Playground</Link><Link to="/agents/new">Agent builder</Link><Link to="/pricing">Pricing</Link><Link to="/roadmap">Roadmap</Link><Link to="/login">Sign in</Link></div>
      <div className="f-col"><h6>Company</h6><a href="mailto:hello@echosarathi.ai">hello@echosarathi.ai</a><Link to="/roadmap">Languages</Link><Link to="/guide">Guide</Link></div>
    </div>
    <div className="f-base">
      <span>&copy; 2026 Echo Sarathi Labs</span>
      <span className="tl">English today &middot; à°¤à±†à°²à±à°—à± next</span>
    </div>
  </div>
</footer>

{/* â”€â”€â”€ FLOATING AGENT WIDGET â”€â”€â”€ */}
<div className="agent-fab" id="agentFab"><span className="fab-pulse"></span>
  <span className="fab-mic"><svg width="24" height="24" viewBox="0 0 24 24" fill="none"><rect x="9" y="3" width="6" height="11" rx="3" fill="#e9e4da"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="#e9e4da" strokeWidth="1.8" strokeLinecap="round"/></svg></span>
</div>
<div className="agent-panel" id="agentPanel">
  <div className="ap-head"><span className="dot"></span><span className="info"><b>Sarathi Agent</b><span>Online &middot; ready to help</span></span><span className="close" id="apClose">&times;</span></div>
  <div className="ap-body" id="apBody"><div className="msg bot">Hi! I'm Sarathi â€” the voice agent behind Echo Sarathi. Ask me anything about how the platform works.</div></div>
  <div className="ap-foot"><input type="text" id="apInput" placeholder="Type a message..." autocomplete="off" /><button id="apSend" aria-label="Send"><svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M5 12h14m-6-6 6 6-6 6" stroke="#e9e4da" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg></button></div>
</div>
    </div>
  );
}


