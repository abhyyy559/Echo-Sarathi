"""G.711 mu-law helpers for the Twilio media bridge (stdlib audioop)."""
from __future__ import annotations

import audioop


def ulaw_to_pcm16(data: bytes) -> bytes:
    """Decode 8 kHz mu-law to 16-bit little-endian PCM (2 bytes per sample)."""
    return audioop.ulaw2lin(data, 2)


def pcm16_to_ulaw(data: bytes) -> bytes:
    """Encode 16-bit little-endian PCM to 8 kHz mu-law (1 byte per sample)."""
    return audioop.lin2ulaw(data, 2)


def downsample_pcm16(data: bytes, factor: int = 6) -> bytes:
    """Decimate 16-bit LE PCM per SAMPLE, keeping every `factor`-th sample
    (48k -> 8k uses factor=6).

    Output length is ``ceil(n_samples / factor) * 2`` bytes. Aliasing is
    acceptable for v1 speech.
    """
    if factor <= 1:
        return data
    step = 2 * factor
    return b"".join(data[i : i + 2] for i in range(0, len(data) - 1, step))


class PcmResampler:
    """Filtered PCM resampler with continuity state across frames.

    Naive decimation folds high frequencies into the speech band (harsh,
    metallic artifacts callers hear as 'disturbance'). ``audioop.ratecv``
    applies a proper low-pass, and the carried filter state keeps frame
    boundaries click-free. One instance per audio track.
    """

    def __init__(self, in_rate: int, out_rate: int = 8000) -> None:
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self._state = None

    def convert(self, pcm16: bytes) -> bytes:
        """Resample one frame of 16-bit LE PCM to the output rate."""
        if not pcm16 or self.in_rate == self.out_rate:
            return pcm16
        out, self._state = audioop.ratecv(
            pcm16, 2, 1, self.in_rate, self.out_rate, self._state
        )
        return out
