from __future__ import annotations

import math
import struct
from dataclasses import dataclass


class HighPassFilter:
    def __init__(self, alpha: float = 0.97) -> None:
        self.alpha = alpha
        self._prev_input = 0.0
        self._prev_output = 0.0

    def process(self, pcm: bytes) -> bytes:
        if len(pcm) < 2:
            return pcm
        output = bytearray(pcm)
        for index in range(0, len(output) - 1, 2):
            x = struct.unpack_from("<h", output, index)[0] / 32768.0
            y = self.alpha * (self._prev_output + x - self._prev_input)
            self._prev_input = x
            self._prev_output = y
            struct.pack_into("<h", output, index, _float_to_pcm16(y))
        return bytes(output)


class AutoGainControl:
    def __init__(self, target_rms: float = 0.15, max_gain: float = 2.5, min_gain: float = 0.5) -> None:
        self.target_rms = target_rms
        self.max_gain = max_gain
        self.min_gain = min_gain
        self._current_gain = 1.0

    def process(self, pcm: bytes) -> bytes:
        if len(pcm) < 2:
            return pcm
        samples = [sample / 32768.0 for (sample,) in struct.iter_unpack("<h", pcm[: len(pcm) - (len(pcm) % 2)])]
        if not samples:
            return pcm
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        if rms < 0.001:
            return pcm
        target_gain = max(self.min_gain, min(self.max_gain, self.target_rms / rms))
        self._current_gain = self._current_gain * 0.7 + target_gain * 0.3
        output = bytearray(pcm)
        for index in range(0, len(output) - 1, 2):
            x = struct.unpack_from("<h", output, index)[0] / 32768.0
            struct.pack_into("<h", output, index, _float_to_pcm16(x * self._current_gain))
        return bytes(output)


class SoftLimiter:
    def __init__(self, threshold: float = 0.85, ratio: float = 3.0, attack: float = 0.005, release: float = 0.05) -> None:
        self.threshold = threshold
        self.ratio = ratio
        self.attack = attack
        self.release = release
        self._envelope = 0.0

    def process(self, pcm: bytes, sample_rate: int = 8000) -> bytes:
        if len(pcm) < 2:
            return pcm
        dt = 1.0 / sample_rate
        output = bytearray(pcm)
        for index in range(0, len(output) - 1, 2):
            x = struct.unpack_from("<h", output, index)[0] / 32768.0
            abs_x = abs(x)
            smoothing = dt / (self.attack if abs_x > self._envelope else self.release)
            self._envelope += (abs_x - self._envelope) * min(1.0, smoothing)
            gain = 1.0
            if self._envelope > self.threshold:
                over = self._envelope - self.threshold
                gain = 1.0 - over * (1.0 - 1.0 / self.ratio) / max(self._envelope, 1e-6)
                gain = max(0.1, min(1.0, gain))
            struct.pack_into("<h", output, index, _float_to_pcm16(x * gain))
        return bytes(output)


@dataclass
class AudioStats:
    rms: int
    peak: int
    clipped: int


class RealtimeAudioQualityChain:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.high_pass = HighPassFilter()
        self.agc = AutoGainControl()
        self.limiter = SoftLimiter()

    def process(self, pcm: bytes) -> bytes:
        if not self.enabled or len(pcm) < 2:
            return pcm
        processed = self.high_pass.process(pcm)
        processed = self.agc.process(processed)
        return self.limiter.process(processed)


def analyze_pcm16(pcm: bytes) -> AudioStats:
    usable = len(pcm) - (len(pcm) % 2)
    if usable <= 0:
        return AudioStats(rms=0, peak=0, clipped=0)
    total = 0
    peak = 0
    clipped = 0
    count = 0
    for (sample,) in struct.iter_unpack("<h", pcm[:usable]):
        absolute = abs(sample)
        total += sample * sample
        peak = max(peak, absolute)
        if absolute >= 32600:
            clipped += 1
        count += 1
    rms = int(math.sqrt(total / max(1, count)))
    return AudioStats(rms=rms, peak=peak, clipped=clipped)


def _float_to_pcm16(value: float) -> int:
    return int(max(-1.0, min(1.0, value)) * 32767)
