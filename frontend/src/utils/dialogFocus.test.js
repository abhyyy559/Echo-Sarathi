import { test } from 'node:test';
import assert from 'node:assert/strict';
import { containDialogFocus } from './dialogFocus.js';

function fixture(count = 2) {
  const document = { activeElement: null };
  const elements = Array.from({ length: count }, () => ({
    disabled: false,
    getClientRects: () => [1],
    closest: () => null,
    focus() { document.activeElement = this; },
  }));
  const container = {
    ownerDocument: document,
    querySelectorAll: () => elements,
    contains: (element) => elements.includes(element),
    focus() { document.activeElement = this; },
  };
  const event = { key: 'Tab', shiftKey: false, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  return { document, elements, container, event };
}

test('Tab wraps from the last control to the first', () => {
  const f = fixture();
  f.document.activeElement = f.elements[1];
  containDialogFocus(f.event, f.container);
  assert.equal(f.document.activeElement, f.elements[0]);
  assert.equal(f.event.defaultPrevented, true);
});

test('Shift Tab wraps from first control to last', () => {
  const f = fixture();
  f.document.activeElement = f.elements[0];
  f.event.shiftKey = true;
  containDialogFocus(f.event, f.container);
  assert.equal(f.document.activeElement, f.elements[1]);
});

test('normal tab progression is not intercepted', () => {
  const f = fixture(3);
  f.document.activeElement = f.elements[1];
  containDialogFocus(f.event, f.container);
  assert.equal(f.event.defaultPrevented, false);
});

test('dialog with no controls remains focusable', () => {
  const f = fixture(0);
  containDialogFocus(f.event, f.container);
  assert.equal(f.document.activeElement, f.container);
  assert.equal(f.event.defaultPrevented, true);
});

test('hidden and disabled controls are not focus targets', () => {
  const f = fixture(3);
  f.elements[0].disabled = true;
  f.elements[2].getClientRects = () => [];
  containDialogFocus(f.event, f.container);
  assert.equal(f.document.activeElement, f.elements[1]);
});

test('other keys and already handled events are not intercepted', () => {
  const f = fixture();
  f.event.key = 'Enter';
  containDialogFocus(f.event, f.container);
  assert.equal(f.document.activeElement, null);
  f.event.key = 'Tab';
  f.event.defaultPrevented = true;
  containDialogFocus(f.event, f.container);
  assert.equal(f.document.activeElement, null);
});
