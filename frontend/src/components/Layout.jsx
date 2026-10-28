import React, { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate, Link } from 'react-router-dom';
import { billingApi, clearSession, getStoredUser, getToken } from '../api.js';
import ThemeToggle from './ThemeToggle.jsx';

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

function IconPlayground() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 17v4" />
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

function IconCredits() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2.5" y="6" width="19" height="13" rx="3" />
      <path d="M2.5 10h19M16 15h2" />
      <path d="M17 6V5a2 2 0 0 0-2.4-2L5 5.4" />
    </svg>
  );
}

function IconTeam() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="9" cy="8" r="3.2" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0" />
      <path d="M16 5.5a3 3 0 0 1 0 5.8M17.5 14.2a5.5 5.5 0 0 1 4 5.3" />
    </svg>
  );
}

function IconAdmin() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3 4.5 6v6c0 4.4 3.2 7.7 7.5 9 4.3-1.3 7.5-4.6 7.5-9V6z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

/* --- nav model -------------------------------------------------------------- */

const NAV_ITEMS = [
  { to: '/', end: true, icon: <IconOverview />, label: 'Overview' },
  { to: '/agents', icon: <IconAgents />, label: 'Agents' },
  { to: '/campaigns', icon: <IconCampaigns />, label: 'Campaigns' },
  { to: '/calls', icon: <IconCalls />, label: 'Call History' },
  { to: '/playground', icon: <IconPlayground />, label: 'Playground' },
  { to: '/team', icon: <IconTeam />, label: 'Team' },
  { to: '/credits', icon: <IconCredits />, label: 'Billing' },
];

const ADMIN_ITEM = { to: '/admin', icon: <IconAdmin />, label: 'Platform admin' };

const UTILITY_LINKS = [
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
  if (pathname.startsWith('/playground')) return ['Playground', 'Talk or type for free, or dial a real phone to test the carrier leg'];
  if (pathname.startsWith('/dev')) return ['Developer tools', 'Service health, provider keys, API catalog'];
  if (pathname.startsWith('/credits')) return ['Billing & credits', 'Plan, invoices and the prepaid overage wallet'];
  if (pathname.match(/^\/invoices\/\d+\/?$/)) return ['Invoice', 'GST tax invoice for a plan or top-up payment'];
  if (pathname.startsWith('/team')) return ['Team', 'Members, roles and seats'];
  if (pathname.startsWith('/admin')) return ['Platform admin', 'Every organization, contracts and credit adjustments'];
  return ['Echo Sarathi', 'AI voice calling console'];
}

const navClass = ({ isActive }) => `nav-link${isActive ? ' active' : ''}`;

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const user = getStoredUser();
  const [title, subtitle] = titleFor(location.pathname);
  const [wallet, setWallet] = useState(null);

  // Balance chip in the topbar. Refetched on navigation so a campaign that
  // just burned minutes shows the new balance the moment the operator lands
  // on another page.
  useEffect(() => {
    if (!getToken()) return undefined;
    let alive = true;
    billingApi
      .summary()
      .then((data) => {
        if (alive) setWallet(data);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [location.pathname]);

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
          {user && user.is_platform_admin && (
            <NavLink to={ADMIN_ITEM.to} className={navClass} title={ADMIN_ITEM.label}>
              {ADMIN_ITEM.icon}
              <span>{ADMIN_ITEM.label}</span>
            </NavLink>
          )}
        </nav>
        {/* Utility surfaces — kept out of the main nav on purpose. */}
        <div className="sidebar-footlinks">
          {UTILITY_LINKS.map((link) => (
            <NavLink key={link.to} to={link.to} className="footlink">
              {link.icon}
              <span>{link.label}</span>
            </NavLink>
          ))}
        </div>
        <div className="sidebar-user">
          <div className="sidebar-user-email" title={user && user.email ? user.email : ''}>
            {(user && user.email) || 'Signed in'}
          </div>
          <button type="button" className="btn btn-ghost btn-sm sidebar-logout" onClick={logout}>
            Sign out
          </button>
        </div>
        <div className="sidebar-footer">Phase 1 · English · India</div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <div>
            <h1>{title}</h1>
            <div className="topbar-sub">{subtitle}</div>
          </div>
          <div className="topbar-right">
            <ThemeToggle />
            {wallet && (
              <Link
                to="/credits"
                className={`topbar-wallet${wallet.low_balance ? ' low' : ''}`}
                title={`${wallet.minutes_remaining} minutes left — click to top up`}
              >
                <span className="wallet-dot" />
                ₹{Number(wallet.balance_rupees).toLocaleString('en-IN', {
                  minimumFractionDigits: 0,
                  maximumFractionDigits: 2,
                })}
              </Link>
            )}
            <span className="topbar-tag">
              {user && user.role === 'owner'
                ? 'Owner'
                : user && user.role === 'admin'
                  ? 'Admin'
                  : 'Member'}
            </span>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
