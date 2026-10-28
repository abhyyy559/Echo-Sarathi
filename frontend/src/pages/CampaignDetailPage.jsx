import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, agentsApi, campaignExportUrl } from '../api.js';
import usePoll from '../hooks/usePoll.js';
import StatusBadge, { statusLabel } from '../components/StatusBadge.jsx';
import Modal from '../components/Modal.jsx';
import DataTable from '../components/DataTable.jsx';
import ContactImport from '../components/ContactImport.jsx';
import { agentOptionLabel } from '../utils/agentPurpose.js';

const PAGE_SIZE = 50;
const CONTACT_STATUS_FILTERS = [
  'pending_review',
  'invalid',
  'queued',
  'calling',
  'completed',
  'no_answer',
  'busy',
  'failed',
  'opted_out',
  'skipped',
];
const LAUNCHABLE = ['draft', 'created', 'paused'];
const CANCELED_like = ['canceled', 'cancelled'];

// Calling window enforced by POST /api/campaigns/{id}/launch (PRD §8):
// 9 AM – 9 PM IST, start inclusive / end exclusive. Mirrored client-side so
// users get told WHY launching is blocked instead of a bare 422 after clicking.
const CALLING_HOURS_START = 9;
const CALLING_HOURS_END = 21;

function istNow() {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    hour: 'numeric',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(new Date());
  const get = (type) => Number(parts.find((p) => p.type === type)?.value);
  let hour = get('hour');
  if (hour === 24) hour = 0;
  return {
    hour,
    label: `${String(hour).padStart(2, '0')}:${String(get('minute')).padStart(2, '0')}`,
  };
}

function fmtDateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return '—';
  const s = Math.max(0, Math.round(Number(seconds)));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

function consentValue(v) {
  if (v === true || v === 'true' || v === 1 || v === '1') return true;
  if (v === false || v === 'false' || v === 0 || v === '0') return false;
  return null;
}

function ruleText(rule) {
  if (rule == null) return '';
  if (typeof rule === 'string') return rule;
  const trigger = rule.trigger || '';
  const action = rule.action || '';
  return action ? `${trigger} → ${action}` : String(trigger);
}

function friendlyActionError(e) {
  const msg = e?.message || 'Action failed.';
  if (msg.startsWith('outside calling hours')) {
    return `Launch blocked: calls only run between 9 AM and 9 PM IST. ${msg} — try again once the window opens.`;
  }
  if (msg === 'campaign has no contacts to call') {
    return 'This campaign has no contacts yet — upload a contact list on the Contacts tab, then launch.';
  }
  return msg;
}

export default function CampaignDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState('contacts');

  // ---- campaign + dashboard (poll every 3s while running) ----
  const [campaignStatus, setCampaignStatus] = useState(null);
  const running = campaignStatus === 'running';

  const {
    data: campaign,
    error: campaignError,
    loading: campaignLoading,
    reload: reloadCampaign,
  } = usePoll(`/api/campaigns/${id}`, 3000, running);
  const { data: dash, error: dashError, reload: reloadDash } = usePoll(`/api/campaigns/${id}/dashboard`, 3000, running);

  useEffect(() => {
    if (campaign && campaign.status) setCampaignStatus(campaign.status);
  }, [campaign]);
  useEffect(() => {
    if (dash && dash.campaign && dash.campaign.status) setCampaignStatus(dash.campaign.status);
  }, [dash]);

  // ---- lifecycle actions ----
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  async function runAction(fn) {
    setActionBusy(true);
    setActionError(null);
    try {
      await fn();
      reloadCampaign();
      reloadDash();
    } catch (e) {
      setActionError(friendlyActionError(e));
    } finally {
      setActionBusy(false);
      setShowCancelConfirm(false);
    }
  }

  // ---- launch pre-checks (server stays the source of truth; this just
  // explains the common rejections BEFORE the click instead of after) ----
  const [istClock, setIstClock] = useState(istNow);
  useEffect(() => {
    const timer = setInterval(() => setIstClock(istNow()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const contactTotal = campaign?.counts?.total;
  const hasContacts = contactTotal == null ? true : contactTotal > 0;
  const withinCallingHours =
    istClock.hour >= CALLING_HOURS_START && istClock.hour < CALLING_HOURS_END;
  const launchBlockedReason = !hasContacts
    ? 'Upload contacts first — a campaign needs at least one contact before it can be launched.'
    : (campaign?.counts?.pending_review || 0) === 0
      ? 'Nobody is pending review — include at least one contact (Skip/Include on the Contacts tab) before launching.'
      : !withinCallingHours
        ? `Calls only run between 9 AM and 9 PM IST. It is currently ${istClock.label} IST, so launching is paused until the window opens.`
        : null;

  // ---- contacts list ----
  const [contactsData, setContactsData] = useState(null);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [contactsError, setContactsError] = useState(null);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('all');
  const [contactsNonce, setContactsNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setContactsLoading(true);
    api
      .listContacts(id, {
        page,
        pageSize: PAGE_SIZE,
        status: statusFilter === 'all' ? '' : statusFilter,
      })
      .then((d) => {
        if (!cancelled) {
          setContactsData(d);
          setContactsError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setContactsError(e.message);
      })
      .finally(() => {
        if (!cancelled) setContactsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, page, statusFilter, contactsNonce]);

  const refreshContacts = () => setContactsNonce((n) => n + 1);
  const totalPages = contactsData ? Math.max(1, Math.ceil((contactsData.total || 0) / (contactsData.page_size || PAGE_SIZE))) : 1;

  // ---- import / copy from another campaign ----
  const [importResult, setImportResult] = useState(null);
  const [copyResult, setCopyResult] = useState(null);
  const [copyModal, setCopyModal] = useState(false);
  const [copySources, setCopySources] = useState([]);
  const [copyPick, setCopyPick] = useState('');
  const [copyBusy, setCopyBusy] = useState(false);
  const [copyError, setCopyError] = useState(null);

  async function openCopyModal() {
    setCopyModal(true);
    setCopyPick('');
    setCopyError(null);
    try {
      const list = await api.listCampaigns();
      setCopySources(
        (Array.isArray(list) ? list : []).filter((c) => String(c.id) !== String(id))
      );
    } catch (e) {
      setCopyError(e.message || 'Could not load campaigns.');
    }
  }

  async function runCopy() {
    if (!copyPick) return;
    setCopyBusy(true);
    setCopyError(null);
    try {
      const result = await api.copyContacts(id, Number(copyPick));
      setCopyModal(false);
      setCopyResult(result);
      setPage(1);
      refreshContacts();
      reloadDash();
      reloadCampaign();
    } catch (e) {
      setCopyError(e.message || 'Copy failed.');
    } finally {
      setCopyBusy(false);
    }
  }

  // ---- agent pinned to this campaign ----
  const [agents, setAgents] = useState([]);
  const [agentModal, setAgentModal] = useState(false);
  const [agentPick, setAgentPick] = useState('');
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentError, setAgentError] = useState(null);

  async function openAgentModal() {
    setAgentModal(true);
    setAgentError(null);
    setAgentPick(campaign?.agent_version_id ? String(campaign.agent_version_id) : '');
    try {
      const list = await agentsApi.list();
      setAgents(
        (Array.isArray(list) ? list : []).filter(
          (a) => a.current_version_id != null && a.status !== 'archived'
        )
      );
    } catch (e) {
      setAgentError(e.message || 'Could not load agents.');
    }
  }

  async function saveAgent() {
    if (!agentPick) return;
    setAgentBusy(true);
    setAgentError(null);
    try {
      await api.patchCampaign(id, { agent_version_id: Number(agentPick) });
      setAgentModal(false);
      reloadCampaign();
      reloadDash();
    } catch (e) {
      setAgentError(e.message || 'Could not change the agent.');
    } finally {
      setAgentBusy(false);
    }
  }

  // ---- escalation rules of the pinned version ----
  const rulesVersionId = campaign?.agent_version_id ?? null;
  const [rulesVersion, setRulesVersion] = useState(null);
  const [rulesError, setRulesError] = useState(null);
  const [rulesNotice, setRulesNotice] = useState(null);
  const [rulesBusy, setRulesBusy] = useState(false);
  const [removedRules, setRemovedRules] = useState([]);

  useEffect(() => {
    let cancelled = false;
    setRulesVersion(null);
    setRulesError(null);
    setRulesNotice(null);
    setRemovedRules([]);
    if (!rulesVersionId) return () => { cancelled = true; };
    agentsApi
      .getVersion(rulesVersionId)
      .then((v) => {
        if (!cancelled) setRulesVersion(v);
      })
      .catch((e) => {
        if (!cancelled) setRulesError(e.message || 'Could not load the agent rules.');
      });
    return () => {
      cancelled = true;
    };
  }, [rulesVersionId]);

  function toggleRule(index) {
    setRemovedRules((prev) =>
      prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index]
    );
    setRulesNotice(null);
  }

  async function saveRules() {
    if (!rulesVersion || removedRules.length === 0) return;
    setRulesBusy(true);
    setRulesError(null);
    setRulesNotice(null);
    try {
      const version = await agentsApi.createVersion(rulesVersion.agent_id, {
        system_prompt: rulesVersion.system_prompt,
        company_context: rulesVersion.company_context || {},
        question_flow: rulesVersion.question_flow || [],
        extraction_schema: rulesVersion.extraction_schema || {},
        disclosure_script: rulesVersion.disclosure_script,
        escalation_rules: (rulesVersion.escalation_rules || []).filter(
          (_, i) => !removedRules.includes(i)
        ),
        voice_settings: rulesVersion.voice_settings || {},
      });
      await api.patchCampaign(id, { agent_version_id: version.id });
      setRulesNotice(
        `Saved as ${campaign?.agent_name || 'agent'} v${version.version} — this campaign now dials with it.`
      );
      reloadCampaign();
      reloadDash();
    } catch (e) {
      setRulesError(e.message || 'Could not save the rules.');
    } finally {
      setRulesBusy(false);
    }
  }

  function onImported(result) {
    setImportResult(result || {});
    setPage(1);
    refreshContacts();
    reloadDash();
  }

  // ---- edit / delete contact ----
  const [editContact, setEditContact] = useState(null);
  const [editForm, setEditForm] = useState({ name: '', phone: '', consent: false });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState(null);

  function openEdit(c) {
    setEditContact(c);
    setEditError(null);
    setEditForm({
      name: c.name || '',
      phone: c.phone || '',
      consent: consentValue(c.consent) === true,
    });
  }

  async function saveEdit() {
    setEditSaving(true);
    setEditError(null);
    try {
      await api.updateContact(editContact.id, {
        name: editForm.name.trim(),
        phone: editForm.phone.trim(),
        consent: editForm.consent,
      });
      setEditContact(null);
      refreshContacts();
    } catch (e) {
      setEditError(e.message || 'Could not save changes.');
    } finally {
      setEditSaving(false);
    }
  }

  async function confirmDelete() {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.deleteContact(deleteTarget.id);
      setDeleteTarget(null);
      refreshContacts();
    } catch (e) {
      setDeleteError(e.message || 'Could not delete contact.');
    } finally {
      setDeleteBusy(false);
    }
  }

  // ---- include / skip (faculty picks who gets called this run) ----
  // pending_review = will be called on launch; skipped = stays on the roster
  // but is never dialed. Only pre-call states are toggleable here.
  const TOGGLEABLE = ['pending_review', 'skipped', 'invalid', 'opted_out'];
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState(null);

  async function setContactStatus(contact, status) {
    await api.updateContact(contact.id, { status });
  }

  async function toggleSkip(contact) {
    setBulkError(null);
    try {
      await setContactStatus(contact, contact.status === 'skipped' ? 'pending_review' : 'skipped');
      refreshContacts();
    } catch (e) {
      setBulkError(e.message || 'Could not update contact.');
    }
  }

  async function bulkSetStatus(status) {
    const rows = (contactsData && contactsData.items) || [];
    const targets = rows.filter((c) => TOGGLEABLE.includes(c.status) && c.status !== status);
    if (targets.length === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    try {
      await Promise.all(targets.map((c) => setContactStatus(c, status)));
      refreshContacts();
    } catch (e) {
      setBulkError(e.message || 'Some contacts could not be updated — refresh and retry.');
      refreshContacts();
    } finally {
      setBulkBusy(false);
    }
  }

  // ---- derived ----
  const canLaunch = LAUNCHABLE.includes(campaignStatus);
  const canPause = campaignStatus === 'running';
  const canCancel =
    campaignStatus != null && campaignStatus !== 'completed' && !CANCELED_like.includes(campaignStatus);

  const contactColumns = [
    {
      key: 'name',
      label: 'Name',
      render: (c) => <span className="cell-strong">{c.name || '—'}</span>,
    },
    { key: 'phone', label: 'Phone' },
    { key: 'external_id', label: 'External ID', render: (c) => c.external_id || '—' },
    { key: 'status', label: 'Status', render: (c) => <StatusBadge status={c.status} /> },
    {
      key: 'consent',
      label: 'Consent',
      render: (c) => {
        const v = consentValue(c.consent);
        if (v === true) return <span className="chip chip-green">Yes</span>;
        if (v === false) return <span className="chip chip-red">No</span>;
        return <span className="text-muted">—</span>;
      },
    },
    { key: 'attempt_count', label: 'Attempts' },
    {
      key: 'custom_fields',
      label: 'Custom fields',
      render: (c) => {
        const cf = c.custom_fields;
        if (!cf || typeof cf !== 'object' || Array.isArray(cf) || Object.keys(cf).length === 0) {
          return <span className="text-muted">—</span>;
        }
        const entries = Object.entries(cf);
        return (
          <span className="cf-chips" title={JSON.stringify(cf, null, 2)}>
            {entries.slice(0, 2).map(([k, v]) => (
              <span key={k} className="chip">
                {k}: {String(v)}
              </span>
            ))}
            {entries.length > 2 && <span className="chip chip-more">+{entries.length - 2}</span>}
          </span>
        );
      },
    },
    {
      key: 'select',
      label: (() => {
        const visible = ((contactsData && contactsData.items) || []).filter((c) => TOGGLEABLE.includes(c.status));
        const allChecked = visible.length > 0 && visible.every((c) => c.status !== 'skipped');
        const noneChecked = visible.length > 0 && visible.every((c) => c.status === 'skipped');
        return visible.length > 0 ? (
          <input
            type="checkbox"
            aria-label="Select all visible contacts"
            title="Select/deselect everyone on this page"
            checked={allChecked}
            ref={(el) => { if (el) el.indeterminate = !allChecked && !noneChecked; }}
            onChange={() => bulkSetStatus(allChecked ? 'skipped' : 'pending_review')}
          />
        ) : '';
      })(),
      render: (c) =>
        TOGGLEABLE.includes(c.status) ? (
          <input
            type="checkbox"
            aria-label={`Select ${c.name || c.phone} to call`}
            checked={c.status !== 'skipped'}
            onChange={() => toggleSkip(c)}
            onClick={(e) => e.stopPropagation()}
            title={c.status === 'skipped' ? 'Select for calling' : 'Selected for calling'}
          />
        ) : null,
      className: 'nowrap select-cell',
    },
    {
      key: 'actions',
      label: '',
      render: (c) => (
        <div className="row-actions" onClick={(e) => e.stopPropagation()}>
          {TOGGLEABLE.includes(c.status) && (
            <button
              className="btn btn-secondary btn-sm"
              title={c.status === 'skipped' ? 'Include this contact in the calling run' : 'Skip this contact for this run (kept on the roster)'}
              onClick={() => toggleSkip(c)}
            >
              {c.status === 'skipped' ? 'Include' : 'Skip'}
            </button>
          )}
          <button className="btn btn-secondary btn-sm" onClick={() => openEdit(c)}>
            Edit
          </button>
          <button className="btn btn-danger-outline btn-sm" onClick={() => setDeleteTarget(c)}>
            Delete
          </button>
        </div>
      ),
      className: 'nowrap',
    },
  ];

  // ---- render ----
  if (campaignError && !campaign) {
    return (
      <div>
        <Link to="/" className="back-link">
          ← Campaigns
        </Link>
        <div className="banner banner-error">
          {campaignError}{' '}
          <button className="btn btn-secondary btn-sm" onClick={reloadCampaign}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (campaignLoading && !campaign) {
    return (
      <div className="loading-page">
        <span className="spinner" /> Loading campaign…
      </div>
    );
  }

  const pickedAgent =
    agents.find((a) => String(a.current_version_id) === String(agentPick)) || null;
  const pickedAgentRole =
    pickedAgent?.description ||
    (String(agentPick) === String(campaign?.agent_version_id ?? '') ? campaign?.agent_role : '');

  return (
    <div>
      <Link to="/" className="back-link">
        ← Campaigns
      </Link>

      <div className="page-head detail-head">
        <div>
          <div className="title-row">
            <h2 className="page-title">{campaign.name || `Campaign ${id}`}</h2>
            <StatusBadge status={campaignStatus || campaign.status} />
            {running && (
              <span className="live-indicator">
                <span className="live-dot" /> Live
              </span>
            )}
          </div>
          <p className="meta-line">
            <span>
              <strong>Agent:</strong>{' '}
              {campaign.agent_name ? (
                <>
                  {campaign.agent_name}
                  {campaign.agent_version != null ? ` · v${campaign.agent_version}` : ''}
                  {campaign.agent_role ? <span className="text-muted"> — {campaign.agent_role}</span> : null}
                </>
              ) : (
                <span className="text-muted">none pinned</span>
              )}{' '}
              <button
                type="button"
                className="link-btn"
                onClick={openAgentModal}
                disabled={running}
                title={running ? 'Pause the campaign to change its agent' : 'Dial this campaign with a different agent'}
              >
                Change
              </button>
            </span>
            <span>
              <strong>Domain:</strong> {campaign.domain_config_name || '—'}
            </span>
            <span>
              <strong>Created:</strong> {fmtDateTime(campaign.created_at)}
            </span>
            <span>
              <strong>ID:</strong> {campaign.id}
            </span>
          </p>
        </div>
        <div className="head-actions">
          {canLaunch && (
            <button
              className="btn btn-primary"
              disabled={actionBusy || !!launchBlockedReason}
              title={launchBlockedReason || undefined}
              onClick={() => runAction(() => api.launchCampaign(id))}
            >
              Launch campaign
            </button>
          )}
          {canPause && (
            <button className="btn btn-secondary" disabled={actionBusy} onClick={() => runAction(() => api.pauseCampaign(id))}>
              Pause
            </button>
          )}
          {canCancel && (
            <button className="btn btn-danger-outline" disabled={actionBusy} onClick={() => setShowCancelConfirm(true)}>
              Cancel
            </button>
          )}
          <div className="export-group">
            <span className="export-label">Export:</span>
            <button className="btn btn-secondary btn-sm" onClick={() => window.open(campaignExportUrl(id, 'csv'), '_blank')}>
              CSV
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => window.open(campaignExportUrl(id, 'xlsx'), '_blank')}>
              XLSX
            </button>
          </div>
        </div>
      </div>

      {actionError && <div className="banner banner-error">{actionError}</div>}
      {canLaunch && launchBlockedReason && !actionError && (
        <div className="banner banner-info">{launchBlockedReason}</div>
      )}

      <div className="tabs">
        <button className={`tab${tab === 'contacts' ? ' active' : ''}`} onClick={() => setTab('contacts')}>
          Contacts
        </button>
        <button className={`tab${tab === 'dashboard' ? ' active' : ''}`} onClick={() => setTab('dashboard')}>
          Dashboard
        </button>
      </div>

      {tab === 'contacts' && (
        <div className="stack">
          <ContactImport campaignId={id} onImported={onImported} />

          {importResult && (
            <div className={`banner ${importResult.imported > 0 ? 'banner-success' : 'banner-error'}`}>
              <strong>
                Imported {importResult.imported ?? 0} contact{importResult.imported === 1 ? '' : 's'}
              </strong>
              {importResult.invalid ? ` · ${importResult.invalid} skipped as invalid` : ''}
              {importResult.errors && importResult.errors.length > 0 && (
                <ul className="error-list">
                  {importResult.errors.slice(0, 8).map((err, i) => (
                    <li key={i}>{String(err)}</li>
                  ))}
                  {importResult.errors.length > 8 && <li>… and {importResult.errors.length - 8} more</li>}
                </ul>
              )}
            </div>
          )}

          {copyResult && (
            <div className={`banner ${copyResult.copied > 0 ? 'banner-success' : 'banner-info'}`}>
              <strong>
                Copied {copyResult.copied} contact{copyResult.copied === 1 ? '' : 's'}
              </strong>
              {copyResult.skipped ? ` · ${copyResult.skipped} skipped (phone already on this roster)` : ''}
            </div>
          )}

          <div className="card flush">
            <div className="table-toolbar">
              <h3 className="card-title">Contacts</h3>
              <div className="toolbar-right">
                <span className="hint inline-hint" title="Skipped contacts stay on the roster but are never dialed">
                  Launch calls everyone pending review — skip the rest
                </span>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={contactsLoading}
                  title="Copy contacts from another campaign into this one"
                  onClick={openCopyModal}
                >
                  Copy from campaign…
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={bulkBusy || contactsLoading}
                  title="Skip every toggleable contact on this page"
                  onClick={() => bulkSetStatus('skipped')}
                >
                  Skip listed
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={bulkBusy || contactsLoading}
                  title="Include every skipped contact on this page back into the run"
                  onClick={() => bulkSetStatus('pending_review')}
                >
                  Include listed
                </button>
                <label className="filter-label" htmlFor="status-filter">
                  Status
                </label>
                <select
                  id="status-filter"
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value);
                    setPage(1);
                  }}
                >
                  <option value="all">All</option>
                  {CONTACT_STATUS_FILTERS.map((s) => (
                    <option key={s} value={s}>
                      {statusLabel(s)}
                    </option>
                  ))}
                </select>
                <button className="btn btn-secondary btn-sm" onClick={refreshContacts} disabled={contactsLoading}>
                  Refresh
                </button>
              </div>
            </div>
            {bulkError && <div className="banner banner-error inset">{bulkError}</div>}
            {contactsError && <div className="banner banner-error inset">{contactsError}</div>}
            <DataTable
              columns={contactColumns}
              rows={(contactsData && contactsData.items) || []}
              rowKey={(c) => c.id}
              loading={contactsLoading}
              empty={statusFilter === 'all' ? 'No contacts yet — import a list above.' : 'No contacts match this filter.'}
            />
            <div className="pagination">
              <span className="page-info">
                {contactsData
                  ? contactsData.total === 0
                    ? '0 contacts'
                    : `Showing ${((contactsData.page || page) - 1) * (contactsData.page_size || PAGE_SIZE) + 1}–${Math.min(
                        (contactsData.page || page) * (contactsData.page_size || PAGE_SIZE),
                        contactsData.total
                      )} of ${contactsData.total}`
                  : ''}
              </span>
              <div className="page-btns">
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={page <= 1 || contactsLoading}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Previous
                </button>
                <span className="page-num">
                  Page {page}
                  {totalPages > 1 ? ` of ${totalPages}` : ''}
                </span>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={page >= totalPages || contactsLoading}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'dashboard' && (
        <div className="stack">
          {dashError && !dash && <div className="banner banner-error">{dashError}</div>}
          {!dash ? (
            <div className="loading-page">
              <span className="spinner" /> Loading dashboard…
            </div>
          ) : (
            <>
              <div className="banner brand">Tiles update live as the dialer works through the queue.</div>

              <div className="tiles">
                {Object.entries(dash.counts || {}).map(([key, value]) => (
                  <div
                    key={key}
                    className={`card tile${key === 'calling' ? ' t-cyan' : ''}${key === 'completed' ? ' t-green' : ''}`}
                  >
                    <div className="n">{value ?? 0}</div>
                    <div className="l">{statusLabel(key)}</div>
                  </div>
                ))}
              </div>

              <div className="card">
                <div className="table-toolbar">
                  <div>
                    <h3 className="card-title">Escalation rules</h3>
                    <p className="hint">
                      {campaign.agent_name
                        ? `${campaign.agent_name}${campaign.agent_version != null ? ` · v${campaign.agent_version}` : ''}`
                        : 'No agent pinned'}
                      {' '}— removing a rule saves a new agent version and repoints this campaign at it.
                    </p>
                  </div>
                  <div className="toolbar-right">
                    <button
                      className="btn btn-primary btn-sm"
                      disabled={rulesBusy || removedRules.length === 0}
                      onClick={saveRules}
                    >
                      {rulesBusy
                        ? 'Saving…'
                        : removedRules.length
                          ? `Save rules (${removedRules.length} removed)`
                          : 'Save rules'}
                    </button>
                  </div>
                </div>
                {rulesError && <div className="banner banner-error inset">{rulesError}</div>}
                {rulesNotice && <div className="banner banner-success inset">{rulesNotice}</div>}
                {!rulesVersion && !rulesError && <p className="hint">Loading rules…</p>}
                {rulesVersion && (rulesVersion.escalation_rules || []).length === 0 && (
                  <p className="hint">This agent has no escalation rules.</p>
                )}
                {rulesVersion && (rulesVersion.escalation_rules || []).length > 0 && (
                  <ul className="rule-list">
                    {(rulesVersion.escalation_rules || []).map((rule, i) => {
                      const removed = removedRules.includes(i);
                      return (
                        <li key={i} className={`rule-row${removed ? ' removed' : ''}`}>
                          <span className="rule-text">{ruleText(rule)}</span>
                          <button type="button" className="link-btn" onClick={() => toggleRule(i)}>
                            {removed ? 'Undo' : 'Remove'}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>

              <div className="card" style={{ overflowX: 'auto' }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Contact</th>
                      <th>Phone</th>
                      <th>Agent</th>
                      <th>Status</th>
                      <th>Last outcome</th>
                      <th>Duration</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(dash.recent_calls || []).length === 0 ? (
                      <tr>
                        <td colSpan={7} className="table-state">No calls yet for this campaign.</td>
                      </tr>
                    ) : (
                      (dash.recent_calls || []).map((c) => (
                        <tr key={c.id} onClick={() => navigate(`/calls/${c.id}`)}>
                          <td><span className="cell-strong">{c.contact_name || '—'}</span></td>
                          <td className="mono">{c.phone || '—'}</td>
                          <td>
                            {c.agent_name
                              ? `${c.agent_name}${c.agent_version != null ? ` · v${c.agent_version}` : ''}`
                              : '—'}
                          </td>
                          <td><StatusBadge status={c.status} /></td>
                          <td>{c.outcome ? <span className="chip">{String(c.outcome)}</span> : '—'}</td>
                          <td className="mono">{fmtDuration(c.duration_seconds)}</td>
                          <td><Link to={`/calls/${c.id}`} style={{ color: 'var(--brand)', fontSize: '13px' }}>Call →</Link></td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {copyModal && (
        <Modal
          title="Copy contacts from another campaign"
          onClose={() => setCopyModal(false)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setCopyModal(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" disabled={copyBusy || !copyPick} onClick={runCopy}>
                {copyBusy ? 'Copying…' : 'Copy contacts'}
              </button>
            </>
          }
        >
          <p className="hint">
            Copies every contact from the source campaign, keeping names, fields and consent. Phones already on this
            roster are skipped.
          </p>
          {copyError && <div className="banner banner-error">{copyError}</div>}
          <div className="field">
            <label htmlFor="copy-source">Source campaign</label>
            <select id="copy-source" value={copyPick} onChange={(e) => setCopyPick(e.target.value)}>
              <option value="">Select a campaign…</option>
              {copySources.map((c) => {
                const total = (c.counts && c.counts.total) || 0;
                return (
                  <option key={c.id} value={c.id}>
                    {c.name} ({total} contact{total === 1 ? '' : 's'})
                  </option>
                );
              })}
            </select>
          </div>
        </Modal>
      )}

      {agentModal && (
        <Modal
          title="Change the agent"
          onClose={() => setAgentModal(false)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setAgentModal(false)}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                disabled={
                  agentBusy ||
                  !agentPick ||
                  String(agentPick) === String(campaign?.agent_version_id ?? '')
                }
                onClick={saveAgent}
              >
                {agentBusy ? 'Saving…' : 'Use this agent'}
              </button>
            </>
          }
        >
          <p className="hint">
            Calls already placed keep the agent recorded on them; your next launch dials with the agent you pick here.
          </p>
          {agentError && <div className="banner banner-error">{agentError}</div>}
          <div className="field">
            <label htmlFor="campaign-agent">Agent</label>
            <select id="campaign-agent" value={agentPick} onChange={(e) => setAgentPick(e.target.value)}>
              <option value="">Select an agent…</option>
              {campaign?.agent_version_id &&
                !agents.some(
                  (a) => String(a.current_version_id) === String(campaign.agent_version_id)
                ) && (
                  <option value={campaign.agent_version_id}>
                    {agentOptionLabel({
                      name: campaign.agent_name,
                      description: campaign.agent_role,
                    })}{' '}
                    (currently pinned)
                  </option>
                )}
              {agents.map((a) => (
                <option key={a.id} value={a.current_version_id}>
                  {agentOptionLabel(a)} (latest)
                </option>
              ))}
            </select>
            {pickedAgentRole && <p className="hint">{pickedAgentRole}</p>}
          </div>
        </Modal>
      )}

      {showCancelConfirm && (
        <Modal
          title="Cancel this campaign?"
          onClose={() => setShowCancelConfirm(false)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setShowCancelConfirm(false)}>
                Keep campaign
              </button>
              <button
                className="btn btn-danger"
                disabled={actionBusy}
                onClick={() => runAction(() => api.cancelCampaign(id))}
              >
                {actionBusy ? 'Canceling…' : 'Yes, cancel campaign'}
              </button>
            </>
          }
        >
          <p>
            Canceling stops all calling for <strong>{campaign.name}</strong>. Contacts still queued will not be called,
            and this cannot be undone.
          </p>
        </Modal>
      )}

      {editContact && (
        <Modal
          title="Edit contact"
          onClose={() => setEditContact(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setEditContact(null)}>
                Cancel
              </button>
              <button className="btn btn-primary" disabled={editSaving || !editForm.phone.trim()} onClick={saveEdit}>
                {editSaving ? 'Saving…' : 'Save changes'}
              </button>
            </>
          }
        >
          <div className="field">
            <label htmlFor="edit-name">Name</label>
            <input
              id="edit-name"
              type="text"
              value={editForm.name}
              onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="edit-phone">Phone</label>
            <input
              id="edit-phone"
              type="text"
              value={editForm.phone}
              onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
            />
          </div>
          <label className="check-row">
            <input
              type="checkbox"
              checked={editForm.consent}
              onChange={(e) => setEditForm({ ...editForm, consent: e.target.checked })}
            />
            <span>This contact has a recorded consent basis</span>
          </label>
          {editError && <div className="banner banner-error">{editError}</div>}
        </Modal>
      )}

      {deleteTarget && (
        <Modal
          title="Delete contact?"
          onClose={() => setDeleteTarget(null)}
          footer={
            <>
              <button className="btn btn-secondary" onClick={() => setDeleteTarget(null)}>
                No, keep it
              </button>
              <button className="btn btn-danger" disabled={deleteBusy} onClick={confirmDelete}>
                {deleteBusy ? 'Deleting…' : 'Yes, delete'}
              </button>
            </>
          }
        >
          <p>
            Delete <strong>{deleteTarget.name || deleteTarget.phone}</strong>
            {deleteTarget.phone ? ` (${deleteTarget.phone})` : ''} from this campaign? This cannot be undone.
          </p>
          {deleteError && <div className="banner banner-error">{deleteError}</div>}
        </Modal>
      )}
    </div>
  );
}
