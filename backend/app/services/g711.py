"""G.711 mu-law helpers for the phone media bridges (stdlib audioop)."""
from __future__ import annotations

import audioop
from typing import Any


def ulaw_to_pcm16(data: bytes) -> bytes:
    """Decode 8 kHz mu-law to 16-bit little-endian PCM (2 bytes per sample)."""
    return audioop.ulaw2lin(data, 2)


def pcm16_to_ulaw(data: bytes) -> bytes:
    """Encode 16-bit little-endian PCM to 8 kHz mu-law (1 byte per sample)."""
    return audioop.lin2ulaw(data, 2)


#: Telephony passband/stopband edges (Hz). PSTN carries ~300-3400 Hz, so the
#: filter keeps speech flat to 3400 and is fully attenuated by 4000 (the
#: 8 kHz output Nyquist) — anything above it would fold back as aliasing.
_PASSBAND_HZ = 3400.0
_STOPBAND_HZ = 4000.0


def _lowpass_taps(in_rate: int) -> Any:
    """Windowed-sinc low-pass for decimating ``in_rate`` -> 8 kHz.

    Transition width sets the length: a Hamming window needs ~3.3/(taps)
    cycles/sample, so 600 Hz of transition at 48 kHz means ~265 taps. Returns
    a float32 kernel normalised to unity DC gain.
    """
    import numpy as np

    transition = (_STOPBAND_HZ - _PASSBAND_HZ) / float(in_rate)
    taps = int(3.3 / transition) + 1
    taps = max(9, min(401, taps))
    if taps % 2 == 0:
        taps += 1
    cutoff = ((_PASSBAND_HZ + _STOPBAND_HZ) / 2.0) / float(in_rate)
    n = np.arange(taps, dtype=np.float64) - taps // 2
    kernel = 2.0 * cutoff * np.sinc(2.0 * cutoff * n) * np.hamming(taps)
    kernel /= kernel.sum()
    return kernel.astype(np.float32)


class PcmResampler:
    """Anti-aliased PCM resampler with continuity state across frames.

    The phone bridge decimates the agent's room track onto the 8 kHz PSTN
    leg. ``audioop.ratecv`` interpolates linearly and filters nothing, so
    every component above the 4 kHz output Nyquist folded straight back into
    the speech band; callers heard that as a harsh, buzzing "disturbance" and
    read it as the voice not sounding right. This low-passes with a
    windowed-sinc FIR and only then decimates, carrying both the filter tail
    and the decimation phase across frames so neither the joins nor the
    sample count drift.

    Rates that are not a whole multiple of the output (e.g. 44.1 kHz, or
    Sarvam's 22.05 kHz TTS) are band-limited by the same FIR first and only
    then handed to ``ratecv`` for the ratio, which is safe once nothing above
    4 kHz is left to fold. Only upsampling skips the filter — it cannot alias.

    One instance per audio track.
    """

    def __init__(self, in_rate: int, out_rate: int = 8000) -> None:
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self._state = None
        self._kernel = None
        self._tail = None
        self._centre = 0
        self._phase = 0
        self._step = 0
        if self.in_rate <= self.out_rate:
            return
        self._kernel = _lowpass_taps(self.in_rate)
        self._centre = len(self._kernel) // 2
        if self.in_rate % self.out_rate == 0:
            self._step = self.in_rate // self.out_rate

    def convert(self, pcm16: bytes) -> bytes:
        """Resample one frame of 16-bit LE PCM to the output rate."""
        if not pcm16 or self.in_rate == self.out_rate:
            return pcm16
        if self._kernel is None:
            out, self._state = audioop.ratecv(
                pcm16, 2, 1, self.in_rate, self.out_rate, self._state
            )
            return out

        import numpy as np

        x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32)
        if self._tail is None:
            self._tail = np.zeros(len(self._kernel) - 1, dtype=np.float32)
        x_ext = np.concatenate((self._tail, x))
        # ``valid`` convolution: filtered[i] is the kernel centred on x_ext[i +
        # centre], so every emitted sample has full filter support.
        filtered = np.convolve(x_ext, self._kernel, mode="valid")
        self._tail = x_ext[-(len(self._kernel) - 1):]
        if self._step == 0:
            # Non-integer ratio: the band-limiting above is what matters, and
            # ratecv now only interpolates a signal with no content to fold.
            y = np.clip(np.rint(filtered), -32768.0, 32767.0).astype("<i2")
            out, self._state = audioop.ratecv(
                y.tobytes(), 2, 1, self.in_rate, self.out_rate, self._state
            )
            return out

        step = self._step
        # Outputs sit at x_ext[centre + q] for q = phase, phase + step, ... The
        # frame starts at x_ext index (kernel-1) = 2*centre, so q is also the
        # offset into x, and q is allowed to run negative (into the carried
        # tail) exactly enough to keep every step-th sample without a gap.
        last_q = len(x) - 1 - self._centre
        count = 0
        if last_q >= self._phase:
            count = (last_q - self._phase) // step + 1
        if count <= 0:
            self._phase -= len(x)
            return b""
        idx = self._centre + self._phase + np.arange(count) * step
        y = np.clip(np.rint(filtered[idx]), -32768.0, 32767.0)
        self._phase += count * step - len(x)
        return y.astype("<i2").tobytes()