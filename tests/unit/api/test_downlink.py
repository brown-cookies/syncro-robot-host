"""Regression tests for the Phase 14 downlink pacer interface.

`ImmediateDownlinkPacer` is the scaffold stand-in named in
`api/ws/downlink.py`'s module docstring: correct delivery, no real
playback-rate pacing. These tests only pin down "correct delivery" --
`RealTimeDownlinkPacer` is intentionally unimplemented and is not tested
here beyond confirming it says so.
"""

from __future__ import annotations

import asyncio

import pytest

from api.ws.downlink import ImmediateDownlinkPacer, RealTimeDownlinkPacer


def test_immediate_pacer_sends_every_chunk_in_order():
    sent: list[bytes] = []

    async def fake_sender(chunk: bytes) -> None:
        sent.append(chunk)

    chunks = [b"aaaa", b"bbbb", b"cccc"]
    asyncio.run(ImmediateDownlinkPacer().send(chunks, fake_sender))

    assert sent == chunks


def test_immediate_pacer_handles_an_empty_chunk_list():
    calls: list[bytes] = []

    async def fake_sender(chunk: bytes) -> None:
        calls.append(chunk)

    asyncio.run(ImmediateDownlinkPacer().send([], fake_sender))

    assert calls == []


def test_real_time_pacer_is_an_explicit_placeholder():
    async def fake_sender(chunk: bytes) -> None:
        pass

    with pytest.raises(NotImplementedError):
        asyncio.run(RealTimeDownlinkPacer().send([b"x"], fake_sender))
