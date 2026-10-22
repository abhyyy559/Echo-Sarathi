"""g711 mu-law codec roundtrips and the anti-aliased bridge resampler."""
import math

import numpy as np

from app.services.g711 import PcmResampler, pcm16_to_ulaw, ulaw_to_pcm16


def _pcm16(samples) -> bytes:
    return np.asarray(samples, dtype="<i2").tobytes()


def _decode(pcm16: bytes) -> np.ndarray:
    return np.frombuffer(pcm16, dtype="<i2").astype(np.float64)


def _goertzel(x: np.ndarray, freq: float, rate: int = 8000) -> float:
    """Amplitude of ``freq`` in ``x`` (single-bin DFT, normalised to a sine peak)."""
    n = np.arange(len(x))
    return float(abs(np.sum(x * np.exp(-2j * np.pi * freq * n / rate))) * 2.0 / len(x))


def _stream(resampler: PcmResampler, samples: list[int], frame: int) -> np.ndarray:
    out: list[np.ndarray] = []
    for i in range(0, len(samples), frame):
        out.append(_decode(resampler.convert(_pcm16(samples[i : i + frame]))))
    return np.concatenate(out)


def test_roundtrip_silence():
    raw = bytes([0xFF]) * 160  # mu-law silence
    assert len(ulaw_to_pcm16(raw)) == 320
    assert pcm16_to_ulaw(ulaw_to_pcm16(raw))[:160] == raw


def test_roundtrip_tone_lengths():
    pcm = b"\x00\x40" * 320  # tiny positive samples, 20ms @8k
    ulaw = pcm16_to_ulaw(pcm)
    assert len(ulaw) == 320
    back = ulaw_to_pcm16(ulaw)
    assert len(back) == len(pcm)


def test_resampler_passthrough_at_target_rate():
    pcm = _pcm16([0, 1000, -1000, 2000])
    assert PcmResampler(8000, 8000).convert(pcm) == pcm


def test_resampler_empty_frame_is_noop():
    assert PcmResampler(48000).convert(b"") == b""


def test_resampler_emits_one_sample_per_step_without_gaps():
    """Decimation must keep the exact 6:1 sample count across frame joins.

    Regression guard: a resampler that restarts its phase each frame silently
    drops the samples between the end of one frame's filter support and the
    start of the next, which plays back as stuttering speed-up. The FIR holds
    back a fixed ``taps/step`` look-ahead forever, so the stream is short by
    that constant — but it must not be short by *per-frame* gaps.
    """
    rng = np.random.default_rng(7)
    x = rng.integers(-8000, 8000, size=6000).astype("<i2")
    resampler = PcmResampler(48000, 8000)
    out = b""
    per_frame: list[int] = []
    for i in range(0, len(x), 480):  # 10ms frames, like the LiveKit drain
        chunk = resampler.convert(x[i : i + 480].tobytes())
        per_frame.append(len(_decode(chunk)))
        out += chunk
    expected = len(x) // 6
    # 265 taps at step 6 = 22 samples of held look-ahead, once, for good.
    assert abs(len(_decode(out)) - expected) <= 24
    # Steady state: every full frame yields exactly 480/6 samples.
    assert per_frame[1:-1] == [80] * (len(per_frame) - 2), per_frame


def test_resampler_keeps_a_1khz_tone_intact():
    rate = 48000
    src = [int(12000 * math.sin(2 * math.pi * 1000 * n / rate)) for n in range(rate // 2)]
    out = _stream(PcmResampler(rate, 8000), src, 480)
    body = out[800:]  # skip the filter's start-up transient
    assert 10000 < np.abs(body).max() <= 13000
    # The 1 kHz component survives at full amplitude (no pitch shift, no loss).
    assert _goertzel(body, 1000) > 10000


def test_resampler_rejects_content_above_nyquist_instead_of_aliasing_it():
    """A 7 kHz tone cannot exist on an 8 kHz phone leg.

    Decimating it without a low-pass folds it down to 1 kHz (7 kHz mirrors to
    8000-7000 = 1 kHz) — the metallic buzz callers reported. With the
    anti-aliasing filter the tone and its alias must both be gone.
    """
    rate = 48000
    src = [int(12000 * math.sin(2 * math.pi * 7000 * n / rate)) for n in range(rate // 2)]
    out = _stream(PcmResampler(rate, 8000), src, 480)
    body = out[800:]
    assert np.abs(body).max() < 1500, np.abs(body).max()
    assert _goertzel(body, 1000) < 200, _goertzel(body, 1000)


def test_resampler_handles_non_integer_ratio():
    """44.1 kHz cannot be decimated by an integer step: band-limit, then ratecv."""
    src = [int(6000 * math.sin(2 * math.pi * 800 * n / 44100)) for n in range(4410)]
    out = _decode(PcmResampler(44100, 8000).convert(_pcm16(src)))
    expected = len(src) * 8000 // 44100
    assert abs(len(out) - expected) <= 2
    assert np.abs(out).max() > 3000


def test_resampler_antialiases_a_non_integer_ratio_too():
    """44.1 kHz (and Sarvam's 22.05 kHz) must be filtered, not just resampled.

    ratecv on an unfiltered 7 kHz tone folds it to 1 kHz — the same metallic
    buzz as the 48 kHz case, just via a different ratio. The filter has to run
    before the ratio change, otherwise only rooms that happen to be 48 kHz get
    the fix.
    """
    for rate in (44100, 22050):
        src = [int(12000 * math.sin(2 * math.pi * 7000 * n / rate)) for n in range(rate // 2)]
        out = _stream(PcmResampler(rate, 8000), src, rate // 100)  # 10ms frames
        body = out[400:]
        assert np.abs(body).max() < 1500, (rate, np.abs(body).max())
        assert _goertzel(body, 1000) < 200, (rate, _goertzel(body, 1000))


def test_resampler_keeps_a_1khz_tone_intact_at_a_non_integer_ratio():
    """The non-integer path must not sacrifice the speech band either."""
    rate = 22050
    src = [int(12000 * math.sin(2 * math.pi * 1000 * n / rate)) for n in range(rate // 2)]
    out = _stream(PcmResampler(rate, 8000), src, rate // 100)
    body = out[400:]
    assert _goertzel(body, 1000) > 9000