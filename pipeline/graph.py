"""WP-103 LangGraph dialogue graph with WP-104 affect degradation."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from pipeline.nodes.affect import make_affect_node
from pipeline.nodes.context import make_context_node
from pipeline.nodes.intent import make_intent_node
from pipeline.nodes.llm import make_llm_node
from pipeline.nodes.output import make_output_node
from pipeline.nodes.policy import make_policy_node
from pipeline.nodes.stt import make_stt_node
from pipeline.state import DialogueState


@dataclass(frozen=True, slots=True)
class DialogueGraphResult:
    state: DialogueState
    stage_durations_s: dict[str, float]


def timed(name: str, node: Callable[[DialogueState], DialogueState]):
    """Wrap a graph node so its wall-clock duration lands in ``stage_timings_s``.

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
        started = monotonic()
        update = node(state)
        return {**update, "stage_timings_s": {name: monotonic() - started}}

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
):
    """Build the dialogue graph and connect its dependency-injected nodes."""

    builder = StateGraph(DialogueState)
    # node1_stt and affect are the two branches LangGraph runs in the same
    # superstep off START; both are wrapped with timed() so their durations land
    # in the reducer-backed stage_timings_s key rather than a plain key (F5).
    builder.add_node("node1_stt", timed("stt", make_stt_node(stt)))
    builder.add_node(
        "node1_intent",
        make_intent_node(intent_classifier, confidence_threshold),
    )
    builder.add_node(
        "node2_context",
        make_context_node(store, context_top_k, deadline_proximity_hours),
    )
    builder.add_node("node3_llm", make_llm_node(llm))
    builder.add_node("affect", timed(
        "affect", make_affect_node(affect_detector)))
    builder.add_node(
        "node4_policy",
        make_policy_node(
            grace_window_minutes=grace_window_minutes,
            default_lead_time=default_lead_time,
            store=store,
        ),
    )
    builder.add_node("output", make_output_node(store))

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
    session_id: str,
    user_id: str,
    audio: Any,
    sample_rate: int,
) -> DialogueGraphResult:
    """Invoke the dialogue graph with the supplied request state."""
    started = monotonic()
    state = graph.invoke(
        {
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
