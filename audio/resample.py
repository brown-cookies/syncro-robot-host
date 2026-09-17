"""Host-side downlink audio conversion (finding S5).

SPEC 8.4 requires the TTS downlink to be raw PCM, 16 kHz, 16-bit, mono,
little-endian, resampled host-side (the edge never resamples), chunked into
100 ms frames (3,200 bytes each at this format) and sent as they become
available. On trunk, `PiperTTSAdapter.synthesize` returns float32 audio at the
voice's native rate (22,050 Hz for the configured voice) as one whole
utterance -- nothing here existed to bridge the two.

This module is deliberately narrow: it converts one already-synthesized
buffer. It does not resample live/streaming audio, does not pace frames to
playback rate (that is the transport layer's job per SPEC 8.4's backpressure
clause), and does not touch the uplink (capture) path.

No new dependency is introduced. Linear interpolation is adequate for
resampling speech at the ratios this project uses (e.g. 22,050 -> 16,000 Hz)
and avoids adding scipy under the sprint freeze (arch review S5).

Known trade-off (no anti-alias filter): `np.interp` resampling below has no
low-pass/anti-alias stage before downsampling. Any source energy above the
new Nyquist frequency (8 kHz at this module's 16 kHz target) folds back into
the audible band as aliasing distortion rather than being removed. This is
accepted, not overlooked (SPEC 8.4): Piper's synthesized speech has limited
energy that high, and a proper anti-alias filter means adding `scipy` (or
hand-rolling one), which the arch review's S5 recommendation explicitly
avoided under the sprint freeze. If a future voice/synthesis change pushes
more energy above 8 kHz (e.g. a higher-quality Piper voice), this trade-off
should be revisited.
"""

from __future__ import annotations

import numpy as np

TARGET_SAMPLE_RATE_HZ = 16_000
FRAME_DURATION_S = 0.1  # 100 ms per SPEC 8.4
BYTES_PER_SAMPLE = 2  # int16
SAMPLES_PER_FRAME = int(TARGET_SAMPLE_RATE_HZ * FRAME_DURATION_S)  # 1,600
BYTES_PER_FRAME = SAMPLES_PER_FRAME * BYTES_PER_SAMPLE  # 3,200, per SPEC 8.4


def to_pcm16_16k(audio: np.ndarray, rate: int) -> np.ndarray:
    """Resample floating-point mono audio at ``rate`` Hz to 16 kHz int16 PCM.

    ``audio`` is expected to be a 1-D array of floats in [-1.0, 1.0], the
    convention every adapter in this codebase already uses (e.g.
    ``PiperTTSAdapter.synthesize``, ``adapters/stt``). Values outside that
    range are clipped rather than raising, since a resampled signal can
    briefly overshoot at transients even when the source did not.

    Uses linear interpolation over evenly spaced sample instants
    (``np.interp``), which clamps rather than extrapolates past either end of
    the source -- acceptable for the short, single-utterance buffers this
    converts, and is what the arch review's S5 recommendation specifies.

    Returns an empty ``int16`` array for empty input, and a same-length copy
    (converted, not resampled) when ``rate`` already equals 16 kHz.
    """
    samples = np.asarray(audio, dtype=np.float64)
    if samples.ndim != 1:
        raise ValueError(
            f"to_pcm16_16k expects mono (1-D) audio, got shape {samples.shape}")
    if rate <= 0:
        raise ValueError(
            f"to_pcm16_16k requires a positive sample rate, got {rate}")

    if samples.size == 0:
        return np.zeros(0, dtype=np.int16)

    if rate == TARGET_SAMPLE_RATE_HZ:
        resampled = samples
    else:
        target_length = max(
            1, round(samples.size * TARGET_SAMPLE_RATE_HZ / rate))
        source_times = np.arange(samples.size) / rate
        target_times = np.arange(target_length) / TARGET_SAMPLE_RATE_HZ
        resampled = np.interp(target_times, source_times, samples)

    clipped = np.clip(resampled, -1.0, 1.0)
    return np.round(clipped * 32767.0).astype(np.int16)


def chunk_100ms(pcm: np.ndarray) -> list[bytes]:
    """Split 16 kHz int16 PCM into little-endian 100 ms byte frames.

    Each full frame is exactly ``BYTES_PER_FRAME`` (3,200) bytes, matching
    SPEC 8.4's wire format -- the raw payload of one ``tts_audio_frame``
    message, with no JSON header, ready to send as-is. The final frame is
    shorter than 3,200 bytes when ``pcm``'s length is not an exact multiple of
    ``SAMPLES_PER_FRAME``; per SPEC 8.4's chunking decision, this trailing
    remainder is sent as-is, not padded up to a full frame -- see that
    section for why the edge's downlink playback buffer does not need
    fixed-size writes the way the uplink's 640-byte capture unit does, and
    the open item for WP-205 to confirm this against the real firmware.
    Returns an empty list for empty input.
    """
    pcm = np.asarray(pcm, dtype=np.int16)
    if pcm.ndim != 1:
        raise ValueError(
            f"chunk_100ms expects mono (1-D) PCM, got shape {pcm.shape}")

    little_endian = pcm.astype("<i2", copy=False)
    raw = little_endian.tobytes()
    return [
        raw[offset: offset + BYTES_PER_FRAME]
        for offset in range(0, len(raw), BYTES_PER_FRAME)
    ]
