"""Vobiz answer XML must be parseable by the provider.

REGRESSION: the Stream URL was emitted with a raw ``&`` in element text
(``...?call_id=108&bridge_token=...``), which is malformed XML. Vobiz could
not read the media URL, never connected the stream, and hung up ~3 seconds
after answer. The websocket itself was fine - only the XML was broken.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

from app.routers.vobiz import _build_answer_xml


def test_answer_xml_parses_and_stream_url_decodes() -> None:
    xml = _build_answer_xml(
        "wss://example.trycloudflare.com",
        108,
        "https://example.trycloudflare.com/vobiz/stream-status",
        "tok123",
    )
    # Must be well-formed XML - a strict provider parser rejects anything else.
    root = ET.fromstring(xml)
    stream = root.find("Stream")
    assert stream is not None
    assert stream.get("bidirectional") == "true"
    url = (stream.text or "").strip()
    parsed = urlparse(url)
    assert parsed.scheme == "wss"
    assert parsed.path == "/vobiz/media"
    params = parse_qs(parsed.query)
    # The provider must see BOTH parameters - before the fix the raw & broke
    # parsing and the token never arrived.
    assert params.get("call_id") == ["108"]
    assert params.get("bridge_token") == ["tok123"]
    assert "&amp;" in xml  # the & is escaped in the document


def test_answer_xml_without_token_has_no_query_separator() -> None:
    xml = _build_answer_xml("wss://example.trycloudflare.com", 7, "", "")
    root = ET.fromstring(xml)
    url = (root.find("Stream").text or "").strip()
    assert urlparse(url).query == "call_id=7"
