"""Phase 14 (WP-105 transport scaffold): the paced TTS downlink interface.

`audio/resample.py` (Phase 4, S5) converts one whole synthesized utterance
into a list of 100 ms PCM byte chunks (`chunk_100ms`) but says explicitly
that it "does not pace frames to playback rate (that is the transport
layer's job per SPEC 8.4's backpressure clause)". SPEC 8.4 itself (see
`techdocs/SPEC.md` around "paces `tts_audio_frame` transmission to the
edge's playback rate rather than sending the whole clip at once") is where
that job lands -- this module is that seam.

Scope note (per the Phase 14 plan): this is the *interface* only. Real
pacing -- holding each chunk back so it reaches the edge roughly every
100 ms instead of all at once, and backing off if the edge's playback
ring buffer can't keep up -- is explicitly "out of scope for this phase"
per the plan's own words ("real pacing... etc. is out of scope"). Sending
every chunk back-to-back is a correct, if naive, implementation of the
interface: nothing downstream (the edge's own ring buffer, per SPEC 8.4)
requires the host to *also* pace, it only becomes a real bandwidth/battery
concern once actual devices are in the loop. `RealTimeDownlinkPacer` below
is left unimplemented on purpose rather than guessed at, so it isn't
mistaken for a decision already made.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, Sequence

from audio.resample import FRAME_DURATION_S

Sender = Callable[[bytes], Awaitable[None]]


class DownlinkPacer(Protocol):
    """Sends a synthesized utterance's PCM chunks to one edge connection.

    `sender` is injected (matching this codebase's existing pattern for
    `Connection.authenticate` and `InteractionRunner.resampler`) rather
    than this class calling a WebSocket directly, so a test can supply a
    plain list-appending stand-in without a real socket, and so `stream.py`
    doesn't have to know which pacing strategy is in use to call it.
    """

    async def send(self, chunks: Sequence[bytes], sender: Sender) -> None:
        """Deliver every chunk in order via `sender`, then return.

        Implementations own whatever timing/backoff policy they add
        between calls to `sender`; callers should not assume this returns
        before or after any particular wall-clock delay.
        """
        ...


class ImmediateDownlinkPacer:
    """Scaffold `DownlinkPacer`: sends every chunk back-to-back, no delay.

    This is the stand-in named in this module's docstring -- correct
    (chunks arrive complete, in order) but not paced. `stream.py` depends
    only on the `DownlinkPacer` protocol, so swapping this for a real
    rate-matching implementation later is a one-line change at the
    composition root, not a rewrite of the transport handler.
    """

    async def send(self, chunks: Sequence[bytes], sender: Sender) -> None:
        for chunk in chunks:
            await sender(chunk)


class RealTimeDownlinkPacer:
    """Not implemented. Placeholder for the real SPEC 8.4 pacing policy.

    Left as an explicit `NotImplementedError` rather than a guessed-at
    `asyncio.sleep(FRAME_DURATION_S)` between chunks: real pacing needs to
    account for the edge's actual ring-buffer fill level (SPEC 8.4's
    backpressure clause, `playback_underrun`), which this scaffold has no
    signal for yet -- a fixed per-chunk sleep would just be a different,
    equally-guessed placeholder wearing a more convincing name. Whoever
    builds this should start from `FRAME_DURATION_S` (imported above so
    the eventual implementation and `audio/resample.py`'s chunk size can't
    silently drift apart) and SPEC 8.4's `playback_underrun` condition.
    """

    async def send(self, chunks: Sequence[bytes], sender: Sender) -> None:
        raise NotImplementedError(
            "RealTimeDownlinkPacer is a placeholder (Phase 14 scaffold); "
            "use ImmediateDownlinkPacer until real playback-rate pacing "
            f"(target frame duration {FRAME_DURATION_S}s) is implemented"
        )


__all__ = ["DownlinkPacer", "Sender", "ImmediateDownlinkPacer", "RealTimeDownlinkPacer"]
