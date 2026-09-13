/**
 * Strip leaked tool-call markup from raw transcript text before rendering.
 *
 * The LLM sometimes emits function calls as inline text (e.g.
 * `<tool_call><function=record_extracted_field><parameter=confidence>0.6...`)
 * instead of through the tool-calling channel. This helper removes that
 * markup so it never shows up in bubbles/transcript rows.
 *
 * Pure function — takes a string (or null/undefined) and returns a trimmed,
 * cleaned string. Non-string input yields ''.
 */
export function cleanTranscriptText(text) {
  if (text == null) return '';
  let out = String(text);

  // Drop multi-token tool-call blocks: <tool_call> ... </tool_call>
  out = out.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '');

  // Drop stray opening tool-call tags (unclosed blocks).
  out = out.replace(/<tool_call>/gi, '');

  // Drop <function=...> and <parameter=...> tags (with optional closing form).
  out = out.replace(/<\/?(?:function|parameter)\b[^>]*>/gi, '');

  // Drop leftover literal [function=...] text.
  out = out.replace(/\[function=[^\]]*\]/gi, '');

  // Collapse repeated whitespace left behind and trim.
  out = out.replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, '\n').trim();

  return out;
}
