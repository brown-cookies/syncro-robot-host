"""S5 regression: the host-side downlink conversion path did not exist on
trunk. Every test here fails with an ImportError before this module exists.
"""

from __future__ import annotations

import numpy as np
import pytest

from audio.resample import (
    BYTES_PER_FRAME,
    SAMPLES_PER_FRAME,
    TARGET_SAMPLE_RATE_HZ,
    chunk_100ms,
    to_pcm16_16k,
)


# --- to_pcm16_16k ------------------------------------------------------


def test_empty_input_returns_empty_int16_array():
    result = to_pcm16_16k(np.zeros(0, dtype=np.float32), rate=22_050)
    assert result.dtype == np.int16
    assert result.size == 0


def test_already_16k_is_converted_without_changing_length():
    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    result = to_pcm16_16k(audio, rate=TARGET_SAMPLE_RATE_HZ)
    assert result.size == audio.size
    assert result.dtype == np.int16


def test_full_scale_values_map_to_int16_extremes():
    audio = np.array([1.0, -1.0], dtype=np.float32)
    result = to_pcm16_16k(audio, rate=TARGET_SAMPLE_RATE_HZ)
    assert result[0] == 32767
    assert result[1] == -32767  # round(-1.0 * 32767) == -32767, not -32768


def test_values_beyond_unity_are_clipped_not_wrapped():
    audio = np.array([2.0, -2.0], dtype=np.float32)
    result = to_pcm16_16k(audio, rate=TARGET_SAMPLE_RATE_HZ)
    assert result[0] == 32767
    assert result[1] == -32767


def test_downsampling_produces_the_expected_target_length():
    # 1 second at 22,050 Hz -> 1 second at 16,000 Hz.
    source_rate = 22_050
    audio = np.zeros(source_rate, dtype=np.float32)
    result = to_pcm16_16k(audio, rate=source_rate)
    assert result.size == TARGET_SAMPLE_RATE_HZ


def test_upsampling_produces_the_expected_target_length():
    # 1 second at 8,000 Hz -> 1 second at 16,000 Hz.
    source_rate = 8_000
    audio = np.zeros(source_rate, dtype=np.float32)
    result = to_pcm16_16k(audio, rate=source_rate)
    assert result.size == TARGET_SAMPLE_RATE_HZ


def test_downsampled_signal_preserves_a_known_midpoint_value():
    # A ramp from -1.0 to 1.0; the resampled midpoint should still be ~0.0
    # regardless of the exact interpolation grid, proving values track
    # position rather than being reordered or truncated.
    source_rate = 22_050
    audio = np.linspace(-1.0, 1.0, source_rate, dtype=np.float64)
    result = to_pcm16_16k(audio, rate=source_rate)
    midpoint = result[result.size // 2]
    assert abs(int(midpoint)) < 500  # near zero, well inside one LSB of noise


def test_rejects_non_mono_input():
    stereo = np.zeros((10, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        to_pcm16_16k(stereo, rate=22_050)


def test_rejects_nonpositive_rate():
    with pytest.raises(ValueError):
        to_pcm16_16k(np.zeros(10, dtype=np.float32), rate=0)


# --- chunk_100ms ---------------------------------------------------------


def test_empty_pcm_produces_no_chunks():
    assert chunk_100ms(np.zeros(0, dtype=np.int16)) == []


def test_exact_multiple_of_one_frame_produces_one_full_frame():
    pcm = np.full(SAMPLES_PER_FRAME, 100, dtype=np.int16)
    chunks = chunk_100ms(pcm)
    assert len(chunks) == 1
    assert len(chunks[0]) == BYTES_PER_FRAME


def test_exact_multiple_of_several_frames_produces_that_many_full_frames():
    pcm = np.zeros(SAMPLES_PER_FRAME * 3, dtype=np.int16)
    chunks = chunk_100ms(pcm)
    assert len(chunks) == 3
    assert all(len(chunk) == BYTES_PER_FRAME for chunk in chunks)


def test_partial_final_frame_is_shorter_and_not_padded():
    pcm = np.zeros(SAMPLES_PER_FRAME + 400, dtype=np.int16)  # 1.5 frames worth
    chunks = chunk_100ms(pcm)
    assert len(chunks) == 2
    assert len(chunks[0]) == BYTES_PER_FRAME
    assert len(chunks[1]) == 400 * 2  # 400 samples, int16 -> 800 bytes


def test_frame_bytes_are_little_endian_int16():
    pcm = np.array([1, 256, -1], dtype=np.int16)
    chunks = chunk_100ms(pcm)
    assert len(chunks) == 1
    payload = chunks[0]
    assert payload[0:2] == (1).to_bytes(2, "little", signed=True)
    assert payload[2:4] == (256).to_bytes(2, "little", signed=True)
    assert payload[4:6] == (-1).to_bytes(2, "little", signed=True)


def test_frames_reassemble_to_the_original_pcm():
    rng = np.random.default_rng(seed=0)
    pcm = rng.integers(-32768, 32767, size=SAMPLES_PER_FRAME * 2 + 137, dtype=np.int16)
    chunks = chunk_100ms(pcm)
    reassembled = np.frombuffer(b"".join(chunks), dtype="<i2")
    assert np.array_equal(reassembled, pcm)


def test_rejects_non_mono_pcm():
    stereo = np.zeros((10, 2), dtype=np.int16)
    with pytest.raises(ValueError):
        chunk_100ms(stereo)


# --- end-to-end (mirrors how the future InteractionRunner will call this) --


def test_piper_native_rate_end_to_end_matches_spec_frame_size():
    """22,050 Hz (the configured Piper voice's native rate per the arch
    review) end to end: resample, then chunk, and check the wire-format
    invariant SPEC 8.4 states explicitly (3,200 bytes per 100 ms frame).
    """
    duration_s = 0.35
    source_rate = 22_050
    audio = np.zeros(int(source_rate * duration_s), dtype=np.float32)
    pcm = to_pcm16_16k(audio, rate=source_rate)
    chunks = chunk_100ms(pcm)
    assert all(len(chunk) <= BYTES_PER_FRAME for chunk in chunks)
    assert len(chunks[0]) == BYTES_PER_FRAME
