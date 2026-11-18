import React from 'react';

/**
 * Generic table.
 * columns: [{ key, label, render?(row), className?, width? }]
 * emptyAction: optional CTA (button/link node) rendered under the empty message.
 */
export default function DataTable({ columns, rows, rowKey, onRowClick, loading, empty, emptyAction }) {
  const isEmpty = !rows || rows.length === 0;
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={c.width ? { width: c.width } : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && isEmpty ? (
            <tr>
              <td colSpan={columns.length} className="table-state">
                <span className="spinner spinner-inline" /> Loading…
              </td>
            </tr>
          ) : isEmpty ? (
            <tr>
              <td colSpan={columns.length} className="table-state">
                {empty || 'Nothing here yet.'}
                {!loading && emptyAction && <div className="empty-action">{emptyAction}</div>}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={rowKey ? rowKey(row) : row.id}
                className={onRowClick ? 'clickable' : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((c) => (
                  <td key={c.key} className={c.className || undefined}>
                    {c.render ? c.render(row) : row[c.key] != null ? String(row[c.key]) : '—'}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
