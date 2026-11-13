import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { fileURLToPath } from 'node:url';

let server;
let DataTable;
let Modal;

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('../../', import.meta.url)),
    server: { middlewareMode: true, watch: null },
    appType: 'custom',
  });
  ({ default: DataTable } = await server.ssrLoadModule('/src/components/DataTable.jsx'));
  ({ default: Modal } = await server.ssrLoadModule('/src/components/Modal.jsx'));
});

after(async () => {
  await server?.close();
});

const columns = [{ key: 'name', label: 'Agent' }, { key: 'calls', label: 'Calls' }];
const renderTable = (props) => renderToStaticMarkup(React.createElement(DataTable, { columns, ...props }));

test('table headers preserve table semantics and declare column scope', () => {
  assert.match(renderTable({ rows: [] }), /<th scope="col"/);
});

test('clickable rows are keyboard reachable without converting cells into buttons', () => {
  const html = renderTable({ rows: [{ id: 1, name: 'Sample agent' }], onRowClick() {} });
  assert.match(html, /<tr[^>]*tabindex="0"/);
  assert.doesNotMatch(html, /role="button"/);
  assert.match(html, /Sample agent/);
});

test('noninteractive rows do not add a tab stop', () => {
  assert.doesNotMatch(renderTable({ rows: [{ id: 1 }] }), /<tr[^>]*tabindex/);
});

test('a missing value stays unknown while zero remains zero', () => {
  const html = renderTable({ rows: [{ id: 1, calls: 0 }] });
  assert.match(html, /<td>—<\/td>/);
  assert.match(html, /<td>0<\/td>/);
});

test('loading state is announced and does not show an empty action', () => {
  const html = renderTable({ rows: [], loading: true, emptyAction: 'Create agent' });
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /role="status"/);
  assert.doesNotMatch(html, /Create agent/);
});

test('empty state retains caller copy and action', () => {
  const html = renderTable({ rows: [], empty: 'No agents yet', emptyAction: 'Create agent' });
  assert.match(html, /No agents yet/);
  assert.match(html, /Create agent/);
});

test('dialog has an accessible name, focus target and labelled close action', () => {
  const html = renderToStaticMarkup(React.createElement(Modal, { title: 'Review campaign', wide: true }, 'Review only'));
  assert.match(html, /role="dialog"/);
  assert.match(html, /aria-modal="true"/);
  assert.match(html, /aria-label="Review campaign"/);
  assert.match(html, /tabindex="-1"/);
  assert.match(html, /aria-label="Close dialog"/);
  assert.match(html, /modal-wide/);
});
