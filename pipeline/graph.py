"""WP-103 LangGraph dialogue graph with WP-104 affect degradation."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from observability import NULL_EMITTER, Emitter, Severity
from pipeline.nodes.affect import make_affect_node
from pipeline.nodes.context import make_context_node
from pipeline.nodes.intent import make_intent_node
from pipeline.nodes.llm import make_llm_node
from pipeline.nodes.output import make_output_node
from pipeline.nodes.policy import make_policy_node
from pipeline.nodes.stt import make_stt_node
from pipeline.stage_obs import (
    describe_input,
    describe_output,
    diff_keys,
    diff_views,
    skip_reason,
)
from pipeline.state import DialogueState


@dataclass(frozen=True, slots=True)
class DialogueGraphResult:
    state: DialogueState
    stage_durations_s: dict[str, float]


def timed(
    name: str,
    node: Callable[[DialogueState], DialogueState],
    emitter: Emitter = NULL_EMITTER,
):
    """Wrap a graph node so its wall-clock duration lands in ``stage_timings_s``.

    OBS-LOG: the same wrapper is the stage-lifecycle boundary (FR-O4). The node
    runs inside ``emitter.stage``, which emits ``stage_started`` and then exactly
    one of ``stage_completed`` / ``stage_skipped`` / ``stage_failed``, and
    re-raises a node's exception untouched. ``stage_timings_s`` takes
    ``timer.elapsed_s`` -- the one monotonic reading the event's ``duration_ms``
    is also built from -- so the existing timing field and the event cannot
    disagree (FR-O10). This is the only stage-timing path: a state without a
    ``trace_id`` is an invalid invocation (FR-O1) and fails here, at the first
    stage, rather than late in the output node after the model work is done.
    What each stage records, and when it counts as skipped, is decided in
    ``pipeline/stage_obs.py``.

    Safe to apply to nodes that run in parallel within the same superstep, because
    ``stage_timings_s`` carries the ``merge_stage_timings`` reducer (see
    ``pipeline/state.py``, finding F5) instead of being a plain last-write-wins key.

    Deliberately left without an explicit return-type annotation: a ``Callable[...]``
    annotation here erases the ``state`` parameter name from the type LangGraph's
    ``add_node`` sees, and its overloads match nodes by that name. Letting the return
    type be inferred from ``wrapped``'s own signature keeps it structurally identical
    to every other node factory in this module (e.g. ``make_stt_node``), which are
    equally unannotated for the same reason.
    """

    def wrapped(state: DialogueState) -> DialogueState:
        trace_id = state.get("trace_id")
        if not trace_id:
            raise RuntimeError(
                f"Stage {name!r} requires trace_id in DialogueState; "
                "InteractionRunner.run mints it (OBS-LOG FR-O1)."
            )

        session_id = state.get("session_id")
        with emitter.stage(
            trace_id=trace_id,
            component=name,
            session_id=session_id,
            metadata=describe_input(name, state),
        ) as timer:
            reason = skip_reason(name, state)
            update = node(state)
            if reason is not None:
                timer.skip(reason)
            timer.output.update(describe_output(name, update))

        # FR-O5 variable tracing: DEBUG only, named keys only, after the timed
        # block so it can never inflate a stage duration.
        keys = diff_keys(name)
        if keys and emitter.level.rank <= Severity.DEBUG.rank:
            before, after, labels = diff_views(name, state, {**state, **update})
            emitter.diff(
                f"{name} state change",
                trace_id=trace_id,
                component=name,
                session_id=session_id,
                before=before,
                after=after,
                keys=labels,
            )
        return {**update, "stage_timings_s": {name: timer.elapsed_s}}

    return wrapped


def build_dialogue_graph(
    *,
    stt,
    intent_classifier,
    llm,
    store,
    affect_detector,
    confidence_threshold: float,
    context_top_k: int,
    deadline_proximity_hours: int,
    grace_window_minutes: int,
    default_lead_time: float,
    lead_time_min: float = 5.0,
    lead_time_max: float = 60.0,
    emitter: Emitter = NULL_EMITTER,
):
    """Build the dialogue graph and connect its dependency-injected nodes.

    ``emitter`` is the shared OBS-LOG emitter from the composition root; the
    default is a no-op so graphs built without observability (tests, scripts)
    behave exactly as before.
    """

    builder = StateGraph(DialogueState)
    # node1_stt and affect are the two branches LangGraph runs in the same
    # superstep off START; both are wrapped with timed() so their durations land
    # in the reducer-backed stage_timings_s key rather than a plain key (F5).
    builder.add_node("node1_stt", timed("stt", make_stt_node(stt, emitter), emitter))
    # Step 4 (latency): every remaining stage is wrapped with timed() so the
    # measurement table can split the total into wake->intent, intent->policy
    # and policy->TTS. Measurement only; no behavior change.
    builder.add_node(
        "node1_intent",
        timed(
            "intent",
            make_intent_node(intent_classifier, confidence_threshold, emitter),
            emitter,
        ),
    )
    builder.add_node(
        "node2_context",
        timed(
            "context",
            make_context_node(
                store, context_top_k, deadline_proximity_hours
            ),
            emitter,
        ),
    )
    builder.add_node(
        "node3_llm", timed("llm", make_llm_node(llm, emitter), emitter)
    )
    builder.add_node("affect", timed(
        "affect",
        make_affect_node(affect_detector, emitter=emitter),
        emitter,
    ))
    builder.add_node(
        "node4_policy",
        timed("policy", make_policy_node(
            grace_window_minutes=grace_window_minutes,
            default_lead_time=default_lead_time,
            store=store,
            lead_time_min=lead_time_min,
            lead_time_max=lead_time_max,
            emitter=emitter,
        ), emitter),
    )
    builder.add_node("output", timed("output", make_output_node(), emitter))

    # Same raw audio -> transcription branch + acoustic affect branch.
    builder.add_edge(START, "node1_stt")
    builder.add_edge(START, "affect")

    # Main dialogue path.
    builder.add_edge("node1_stt", "node1_intent")
    builder.add_edge("node1_intent", "node2_context")
    builder.add_edge("node2_context", "node3_llm")

    # Node 4 is the synchronization point for Node 3 + parallel affect.
    builder.add_edge(["node3_llm", "affect"], "node4_policy")
    builder.add_edge("node4_policy", "output")
    builder.add_edge("output", END)
    return builder.compile()


def invoke_dialogue(
    graph,
    *,
    trace_id: str,
    session_id: str,
    user_id: str,
    audio: Any,
    sample_rate: int,
) -> DialogueGraphResult:
    """Invoke the dialogue graph with the supplied request state.

    ``trace_id`` is minted once by ``InteractionRunner.run`` (OBS-LOG FR-O1) and
    only threaded through here; the graph must never mint its own.
    """
    started = monotonic()
    state = graph.invoke(
        {
            "trace_id": trace_id,
            "session_id": session_id,
            "user_id": user_id,
            "audio": audio,
            "sample_rate": sample_rate,
            "started_monotonic": started,
        }
    )
    return DialogueGraphResult(
        state=state,
        stage_durations_s={"dialogue_graph": monotonic() - started},
    )
