import React from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { clearSession, getStoredUser } from '../api.js';

/* --- inline SVG icon set (16px, currentColor) ------------------------------ */

function IconOverview() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  );
}

function IconAgents() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="4" y="8" width="16" height="12" rx="3" />
      <path d="M12 8V4M9 14h.01M15 14h.01" />
      <circle cx="12" cy="3" r="1" />
    </svg>
  );
}

function IconCampaigns() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 12h-4l-3 8L9 4l-3 8H2" />
    </svg>
  );
}

function IconCalls() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1.5 1.5 0 0 1 1.6-.33c1.2.4 2.5.62 3.6.62a1.5 1.5 0 0 1 1.5 1.5V20a1.5 1.5 0 0 1-1.5 1.5C10.6 21.5 2.5 13.4 2.5 3.5A1.5 1.5 0 0 1 4 2h3.1a1.5 1.5 0 0 1 1.5 1.5c0 1.2.2 2.4.6 3.6a1.5 1.5 0 0 1-.33 1.6l-2.27 2.1z" transform="scale(0.92) translate(1,0)" />
      <path d="M14.5 4.5 21 11M21 5v6h-6" opacity="0" />
    </svg>
  );
}

function IconPhone() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />
    </svg>
  );
}

function IconGuide() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z" />
      <path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5" />
    </svg>
  );
}

function IconPlayground() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 17v4" />
    </svg>
  );
}

function IconTestCall() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 3h4l.6 3-2 1.2a10.5 10.5 0 0 0 5.2 5.2L18 10.4 21 11v4a2 2 0 0 1-2 2A14 14 0 0 1 5 3a2 2 0 0 1 2-2h2z" opacity="0" />
      <path d="M10 2v6l-2.5 1.5a11 11 0 0 0 5 5L14 12l6 2v4a2 2 0 0 1-2 2A16 16 0 0 1 4 6a2 2 0 0 1 2-2h4z" opacity="0" />
      <path d="m6 15 4-6 3 4 2-2.5 3 4.5" />
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
    </svg>
  );
}

function IconDev() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m8 9-4 3 4 3M16 9l4 3-4 3M13.5 5l-3 14" />
    </svg>
  );
}

/* --- nav model -------------------------------------------------------------- */

const NAV_ITEMS = [
  { to: '/', end: true, icon: <IconOverview />, label: 'Overview' },
  { to: '/agents', icon: <IconAgents />, label: 'Agents' },
  { to: '/campaigns', icon: <IconCampaigns />, label: 'Campaigns' },
  { to: '/calls', icon: <IconCalls />, label: 'Call History' },
  { to: '/phone-numbers', icon: <IconPhone />, label: 'Phone Numbers', soon: true },
  { to: '/guide', icon: <IconGuide />, label: 'Guide' },
];

const UTILITY_LINKS = [
  { to: '/playground', icon: <IconPlayground />, label: 'Playground' },
  { to: '/test-call', icon: <IconTestCall />, label: 'Test Call' },
  { to: '/dev', icon: <IconDev />, label: 'Dev' },
];

/** Topbar [title, subtitle] derived from the current path. */
function titleFor(pathname) {
  if (pathname === '/') return ['Overview', 'Usage, latency and recent activity for your organization'];
  if (pathname === '/agents/new' || pathname.match(/^\/agents\/new\/?$/)) {
    return ['New agent', 'Six-step builder wizard — saving creates version 1'];
  }
  if (pathname.match(/^\/agents\/\d+\/edit\/?$/)) return ['Edit agent', 'Builder wizard — every save snapshots a new immutable version'];
  if (pathname.match(/^\/agents\/\d+\/?$/)) return ['Agent workspace', 'Configure the next version and test it side by side'];
  if (pathname.startsWith('/agents')) return ['Agents', 'Your AI caller personas and their versions'];
  if (pathname.match(/^\/calls\/\d+\/?$/)) return ['Call detail', 'Transcript, extracted fields and latency for one call'];
  if (pathname.startsWith('/calls')) return ['Call history', 'Every call this organization has placed or simulated'];
  if (pathname.match(/^\/campaigns\/\d+\/?$/)) return ['Campaign dashboard', 'Live progress, contacts and calls for one campaign'];
  if (pathname.startsWith('/campaigns')) return ['Campaigns', 'Batch outbound calling against pinned agent versions'];
  if (pathname.startsWith('/playground')) return ['Playground', 'Talk or type with any saved agent version — zero minutes used'];
  if (pathname.startsWith('/test-call')) return ['Test call', 'Place a single sandbox call to your own number'];
  if (pathname.startsWith('/dev')) return ['Developer tools', 'Service health, provider keys, API catalog'];
  if (pathname.startsWith('/phone-numbers')) return ['Phone numbers', 'Provision and manage DIDs'];
  if (pathname.startsWith('/guide')) return ['Guide', 'From empty account to first campaign'];
  return ['Echo Sarathi', 'AI voice calling console'];
}

const navClass = ({ isActive }) => `nav-link${isActive ? ' active' : ''}`;

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const user = getStoredUser();
  const [title, subtitle] = titleFor(location.pathname);

  function logout() {
    clearSession();
    navigate('/login', { replace: true });
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 12h2l3-8 4 16 4-12 3 6h4" />
            </svg>
          </div>
          <div>
            <div className="brand-name">Echo Sarathi</div>
            <div className="brand-sub">AI voice calling console</div>
          </div>
        </div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={navClass} title={item.soon ? `${item.label} — coming soon` : item.label}>
              {item.icon}
              <span>{item.label}</span>
              {item.soon && <span className="nav-soon">soon</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-user">
          <div className="sidebar-user-email" title={user && user.email ? user.email : ''}>
            {(user && user.email) || 'Signed in'}
          </div>
          <button type="button" className="btn btn-ghost btn-sm sidebar-logout" onClick={logout}>
            Sign out
          </button>
        </div>
        {/* Utility surfaces — kept out of the main nav on purpose. */}
        <div className="sidebar-footlinks">
          {UTILITY_LINKS.map((link) => (
            <NavLink key={link.to} to={link.to} className="footlink">
              {link.icon}
              <span>{link.label}</span>
            </NavLink>
          ))}
        </div>
        <div className="sidebar-footer">Phase 1 · English · India</div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div>
            <h1>{title}</h1>
            <div className="topbar-sub">{subtitle}</div>
          </div>
          <span className="topbar-tag">Admin</span>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
