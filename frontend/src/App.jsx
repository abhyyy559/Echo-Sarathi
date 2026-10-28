import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { getToken } from './api.js';
import Layout from './components/Layout.jsx';
import Login from './pages/Login.jsx';
import OverviewPage from './pages/OverviewPage.jsx';
import AgentsPage from './pages/AgentsPage.jsx';
import AgentDetailPage from './pages/AgentDetailPage.jsx';
import AgentBuilderPage from './pages/AgentBuilderPage.jsx';
import CampaignsPage from './pages/CampaignsPage.jsx';
import CampaignDetailPage from './pages/CampaignDetailPage.jsx';
import CallDetailPage from './pages/CallDetailPage.jsx';
import CallsIndexPage from './pages/CallsIndexPage.jsx';
import GuidePage from './pages/GuidePage.jsx';
import CreditsPage from './pages/CreditsPage.jsx';
import TeamPage from './pages/TeamPage.jsx';
import AdminPage from './pages/AdminPage.jsx';
import InvoicePage from './pages/InvoicePage.jsx';
import {
  AcceptInvitePage,
  ForgotPasswordPage,
  ResetPasswordPage,
} from './pages/PasswordPages.jsx';

// three.js (~600 kB) ships only on the marketing pages — keep it out of the
// initial bundle the same way livekit-client is kept out.
const LandingPage = lazy(() => import('./pages/LandingPage.jsx'));
const PricingPage = lazy(() => import('./pages/PricingPage.jsx'));
const RoadmapPage = lazy(() => import('./pages/RoadmapPage.jsx'));

// livekit-client (~700 kB minified) is only needed on the Playground route —
// keep it out of the initial bundle.
const PlaygroundPage = lazy(() => import('./pages/PlaygroundPage.jsx'));
const DevToolsPage = lazy(() => import('./pages/DevToolsPage.jsx'));

function RouteFallback() {
  return (
    <div className="loading-page">
      <span className="spinner" /> Loading…
    </div>
  );
}

function NotFound() {
  return <div className="empty-state">Page not found.</div>;
}

/**
 * Route shell for everything behind login. Logged-out visitors get the public
 * landing page at "/" and a redirect to /login everywhere else.
 */
function AuthShell() {
  const location = useLocation();
  if (!getToken()) {
    if (location.pathname === '/') return <LandingPage />;
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Layout />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/accept-invite" element={<AcceptInvitePage />} />
          {/* Public marketing pages. LandingPage itself bounces signed-in users home. */}
          <Route path="/landing" element={<LandingPage />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/roadmap" element={<RoadmapPage />} />
          <Route element={<AuthShell />}>
            <Route index element={<OverviewPage />} />
            <Route path="agents" element={<AgentsPage />} />
            {/* Agent workspace: tabbed config editor + sticky test rail.
                Declared before agents/new & :id/edit — React Router ranks
                routes, but explicit ordering keeps the intent obvious. */}
            <Route path="agents/:id" element={<AgentDetailPage />} />
            {/* No key prop: navigating /agents/new -> /agents/:id/edit after
                creation must preserve the wizard's in-memory state. */}
            <Route path="agents/new" element={<AgentBuilderPage />} />
            <Route path="agents/:id/edit" element={<AgentBuilderPage />} />
            <Route path="playground" element={<PlaygroundPage />} />
            <Route path="playground/:agentVersionId" element={<PlaygroundPage />} />
            <Route path="campaigns" element={<CampaignsPage />} />
            <Route path="campaigns/:id" element={<CampaignDetailPage />} />
            <Route path="calls" element={<CallsIndexPage />} />
            <Route path="calls/:id" element={<CallDetailPage />} />
            <Route path="guide" element={<GuidePage />} />
            <Route path="credits" element={<CreditsPage />} />
            <Route path="invoices/:id" element={<InvoicePage />} />
            <Route path="team" element={<TeamPage />} />
            <Route path="admin" element={<AdminPage />} />
            {/* Phone tests are a Playground mode now; keep old links working. */}
            <Route path="test-call" element={<Navigate to="/playground?mode=phone" replace />} />
            <Route path="dev" element={<DevToolsPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
