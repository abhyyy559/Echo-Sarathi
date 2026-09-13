#!/usr/bin/env node
/** Local inventory, routing-policy, and dashboard utility for coding agents. */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)));
const OUT = join(ROOT, 'out');
const POLICY_FILE = join(ROOT, 'config', 'routing-policy.json');
const INVENTORY_FILE = join(OUT, 'inventory.json');
const MODELS_FILE = join(OUT, 'openrouter-models.json');
const now = () => new Date().toISOString();
const readJson = (file, fallback) => existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : fallback;
const writeJson = (file, value) => { mkdirSync(dirname(file), { recursive: true }); writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`); };
const esc = (value) => String(value ?? '—').replace(/[&<>'"]/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' })[char]);

function walk(base, filename, result = []) {
  if (!existsSync(base)) return result;
  for (const entry of readdirSync(base, { withFileTypes: true })) {
    const path = join(base, entry.name);
    if (entry.isDirectory()) walk(path, filename, result);
    else if (entry.name === filename) result.push(path);
  }
  return result;
}
function manifestName(path) {
  try { return readFileSync(path, 'utf8').split(/\r?\n/).slice(0, 30).find(line => line.startsWith('name:'))?.split(':').slice(1).join(':').trim().replace(/^"|"$/g, '') || path.split(/[\\/]/).at(-2); }
  catch { return path.split(/[\\/]/).at(-2); }
}
function findCommand(command) {
  try { return execFileSync('where.exe', [command], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).split(/\r?\n/).find(Boolean) || null; }
  catch { return null; }
}
function inventory() {
  const home = homedir();
  const agents = [['codex', 'Codex'], ['claude', 'Claude Code'], ['opencode', 'OpenCode']].map(([command, name]) => ({ name, command, installed: Boolean(findCommand(command)), path: findCommand(command) }));
  const roots = [[join(home, '.codex', 'skills'), 'Codex system/global'], [join(home, '.codex', 'plugins', 'cache'), 'Codex plugin cache'], [join(home, '.claude', 'plugins'), 'Claude plugin cache']];
  const seen = new Map();
  for (const [base, source] of roots) for (const path of walk(base, 'SKILL.md')) seen.set(path, { name: manifestName(path), source, path });
  return { generatedAt: now(), agents, skills: [...seen.values()].sort((a, b) => a.name.localeCompare(b.name) || a.source.localeCompare(b.source)) };
}
function isFree(model) {
  const pricing = model.pricing || {};
  const values = ['prompt', 'completion', 'request', 'image', 'web_search'].map(key => pricing[key]).filter(value => value !== undefined && value !== null).map(String);
  return values.length > 0 && values.every(value => ['0', '0.0', '0.00'].includes(value));
}
const supports = (model, parameter) => (model.supported_parameters || []).includes(parameter);
function rankFreeModels(models, policy) {
  let candidates = models.filter(isFree);
  if (policy.requireToolCalling) { const tools = candidates.filter(model => supports(model, 'tools')); if (tools.length) candidates = tools; }
  return candidates.sort((a, b) => (Number(supports(b, 'tools')) - Number(supports(a, 'tools'))) || ((b.context_length || 0) - (a.context_length || 0)) || String(a.name || a.id).localeCompare(String(b.name || b.id)));
}
async function refreshOpenRouter() {
  const headers = { Accept: 'application/json' };
  if (process.env.OPENROUTER_API_KEY) headers.Authorization = `Bearer ${process.env.OPENROUTER_API_KEY}`;
  let response;
  try { response = await fetch('https://openrouter.ai/api/v1/models', { headers, signal: AbortSignal.timeout(30000) }); }
  catch (error) { throw new Error(`OpenRouter catalog refresh failed: ${error.message}`); }
  if (!response.ok) throw new Error(`OpenRouter catalog refresh failed: HTTP ${response.status}`);
  const payload = await response.json();
  const policy = readJson(POLICY_FILE, {});
  const models = payload.data || [];
  const output = { generatedAt: now(), authenticated: Boolean(process.env.OPENROUTER_API_KEY), source: 'https://openrouter.ai/api/v1/models', policy, totalModels: models.length, freeEligibleModels: rankFreeModels(models, policy).length, fallback: policy.fallback, models: rankFreeModels(models, policy) };
  writeJson(MODELS_FILE, output); return output;
}
function dashboard() {
  const inv = readJson(INVENTORY_FILE, inventory());
  const models = readJson(MODELS_FILE, { models: [], fallback: 'openrouter/free', generatedAt: null, freeEligibleModels: 0 });
  const policy = readJson(POLICY_FILE, {});
  const agents = inv.agents.map(a => `<tr><td>${esc(a.name)}</td><td>${a.installed ? 'Installed' : 'Not found'}</td><td>${esc(a.path)}</td></tr>`).join('');
  const skills = inv.skills.map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.source)}</td></tr>`).join('');
  const rows = models.models.slice(0, 100).map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.id)}</td><td>${esc(m.context_length)}</td><td>${supports(m, 'tools') ? 'Yes' : 'No'}</td></tr>`).join('') || `<tr><td colspan="4">No live catalog yet. Run refresh-openrouter.</td></tr>`;
  const page = `<!doctype html><html><head><meta charset="utf-8"><title>Agent Control Center</title><style>body{font-family:system-ui;max-width:1200px;margin:2rem auto;background:#10141c;color:#e9edf5;padding:0 1rem}h1,h2{color:#8dd6ff}.card{background:#19212e;padding:1rem 1.25rem;margin:1rem 0;border-radius:10px}table{border-collapse:collapse;width:100%}td,th{padding:.55rem;border-bottom:1px solid #344154;text-align:left}code{color:#a7f3d0}</style></head><body><h1>Agent Control Center</h1><p>Generated ${esc(now())}. Local-only dashboard; secrets are never displayed.</p><div class="card"><h2>Routing policy</h2><p>Mode: <code>${esc(policy.mode)}</code> · Paid models: <code>${policy.allowPaidModels ? 'allowed' : 'blocked'}</code> · Fallback: <code>${esc(models.fallback)}</code></p><p>OpenRouter snapshot: ${esc(models.generatedAt || 'not refreshed')} · Free eligible models: ${esc(models.freeEligibleModels)}</p></div><div class="card"><h2>Coding agents</h2><table><tr><th>Agent</th><th>Status</th><th>Command</th></tr>${agents}</table></div><div class="card"><h2>Skills (${inv.skills.length})</h2><table><tr><th>Name</th><th>Source</th></tr>${skills}</table></div><div class="card"><h2>OpenRouter free-model ranking</h2><table><tr><th>Model</th><th>ID</th><th>Context</th><th>Tools</th></tr>${rows}</table></div></body></html>`;
  const path = join(OUT, 'dashboard.html'); mkdirSync(OUT, { recursive: true }); writeFileSync(path, page); return path;
}
function exportAdapters() {
  const source = join(ROOT, 'adapters'); const destination = join(OUT, 'adapters'); const files = [];
  const copy = base => { for (const entry of readdirSync(base, { withFileTypes: true })) { const path = join(base, entry.name); if (entry.isDirectory()) copy(path); else if (entry.name.endsWith('.md')) { const target = join(destination, relative(source, path)); mkdirSync(dirname(target), { recursive: true }); writeFileSync(target, readFileSync(path)); files.push(target); } } };
  copy(source); const workflow = join(destination, 'AGENT_WORKFLOW.md'); writeFileSync(workflow, readFileSync(join(ROOT, 'shared', 'AGENT_WORKFLOW.md'))); return [...files, workflow];
}
const command = process.argv[2];
if (!['inventory', 'refresh-openrouter', 'dashboard', 'export-adapters', 'all'].includes(command)) { console.error('Usage: node agent-control-center.mjs <inventory|refresh-openrouter|dashboard|export-adapters|all>'); process.exit(1); }
if (['inventory', 'all'].includes(command)) { const data = inventory(); writeJson(INVENTORY_FILE, data); console.log(`Inventory: ${data.agents.length} agents, ${data.skills.length} skills`); }
if (['refresh-openrouter', 'all'].includes(command)) { if (process.env.OPENROUTER_API_KEY) { const data = await refreshOpenRouter(); console.log(`OpenRouter: ${data.freeEligibleModels} free eligible models`); } else console.log('OpenRouter skipped: OPENROUTER_API_KEY is not set.'); }
if (['dashboard', 'all'].includes(command)) console.log(`Dashboard: ${dashboard()}`);
if (['export-adapters', 'all'].includes(command)) console.log(`Adapters exported: ${exportAdapters().length}`);
