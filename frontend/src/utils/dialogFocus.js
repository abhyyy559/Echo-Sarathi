const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

export function containDialogFocus(event, container) {
  if (!event || event.key !== 'Tab' || event.defaultPrevented || !container) return;
  const doc = container.ownerDocument;
  const items = Array.from(container.querySelectorAll(FOCUSABLE)).filter(
    (element) => !element.disabled && element.getClientRects().length > 0,
  );
  if (items.length === 0) {
    event.preventDefault();
    container.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const active = doc.activeElement;
  const outside = !container.contains(active);
  if (event.shiftKey) {
    if (active === first || outside) {
      event.preventDefault();
      last.focus();
    }
  } else if (active === last || outside) {
    event.preventDefault();
    first.focus();
  }
}
