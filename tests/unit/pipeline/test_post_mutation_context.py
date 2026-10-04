"""Stale context after a successful mutation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from langgraph.graph import END, START, StateGraph

from pipeline.graph import make_executor_node
from pipeline.nodes.context import make_context_node, retrieve_context_payload
from pipeline.nodes.llm import make_llm_node
from pipeline.state import DialogueState
from tests.unit.pipeline.test_executor import make_executor, seed_pending_reminder
from storage.sqlite_store import SQLiteStore


class CapturingLLM:
    def __init__(self):
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"response_text": "Okay, that's handled.",
                           "proposed_action": "respond"})

    def context_the_llm_saw(self) -> dict:
        line = next(l for l in self.prompts[-1].splitlines()
                    if l.startswith("Retrieved context: "))
        return json.loads(line[len("Retrieved context: "):])


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(str(tmp_path / "stale.db"))
    s.ensure_user("u1")
    return s


def _run_context_executor_llm(store, llm, state):
    """context -> executor -> llm, in the same order as the production graph."""
    builder = StateGraph(DialogueState)
    builder.add_node("node2_context", make_context_node(store, 5, 2))
    builder.add_node("executor", make_executor_node(
        make_executor(store),
        refresh_context=lambda uid: retrieve_context_payload(store, uid, 5, 2)[
            "context"],
    ))
    builder.add_node("node3_llm", make_llm_node(llm))
    builder.add_edge(START, "node2_context")
    builder.add_edge("node2_context", "executor")
    builder.add_edge("executor", "node3_llm")
    builder.add_edge("node3_llm", END)
    return builder.compile().invoke({
        "user_id": "u1", "session_id": "s1", "intent_confidence": 0.95, **state})


def test_llm_does_not_see_old_deadline_after_reschedule(store):
    now = datetime.now(timezone.utc)
    old_deadline = (now - timedelta(days=1)).isoformat()
    new_deadline = (now + timedelta(days=3)).isoformat()
    task_id = store.save_task("u1", "Finish thesis",
                              deadline=datetime.fromisoformat(old_deadline))
    llm = CapturingLLM()

    result = _run_context_executor_llm(store, llm, {
        "intent": "reschedule_task",
        "transcript": "Move my thesis deadline to Friday",
        "slots": {"task_reference": "Finish thesis", "new_deadline": new_deadline},
    })

    # Control: the mutation really happened and the database is the truth.
    assert result["execution_outcome"]["succeeded"] is True
    assert store.list_tasks("u1")[0]["deadline"] == datetime.fromisoformat(
        new_deadline).isoformat()

    seen = llm.context_the_llm_saw()
    overdue_ids = [t["task_id"] for t in seen["overdue_tasks"]]
    seen_deadlines = [t["deadline"] for t in seen["tasks"] + seen["overdue_tasks"]
                      if t["task_id"] == task_id]
    assert task_id not in overdue_ids, "task shown as overdue after being rescheduled"
    assert datetime.fromisoformat(
        old_deadline).isoformat() not in seen_deadlines


def test_llm_sees_the_new_task_after_add_task(store):
    store.save_task("u1", "Finish thesis")
    llm = CapturingLLM()

    result = _run_context_executor_llm(store, llm, {
        "intent": "add_task",
        "transcript": "Add buy milk to my tasks",
        "slots": {"title": "Buy milk"},
    })

    assert result["execution_outcome"]["succeeded"] is True
    # DB truth
    assert any(t["title"] == "Buy milk" for t in store.list_tasks("u1"))

    seen = llm.context_the_llm_saw()
    titles = [t["title"] for t in seen["tasks"] + seen["overdue_tasks"]]
    assert "Buy milk" in titles, "retrieved context omits the task just added"


def test_policy_and_trace_inputs_stay_pre_mutation(store):
    """The refresh is for Node 3 only: context / retrieved_context_ids /
    deadline_proximity must still describe what the decision was based on."""
    store.save_task("u1", "Finish thesis")
    before = store.retrieve_context("u1", top_k=5, deadline_proximity_hours=2)
    llm = CapturingLLM()

    result = _run_context_executor_llm(store, llm, {
        "intent": "add_task",
        "transcript": "Add buy milk to my tasks",
        "slots": {"title": "Buy milk"},
    })

    assert [t["title"]
            for t in result["context"]["tasks"]] == ["Finish thesis"]
    assert result["retrieved_context_ids"] == before.ids
    assert result["deadline_proximity"] == before.deadline_proximity
    assert "Buy milk" in [t["title"]
                          for t in result["post_execution_context"]["tasks"]]


def test_refresh_failure_propagates_and_never_reaches_the_llm(store, monkeypatch):
    """No swallowing: a failed refresh fails the node. The LLM is never prompted
    (so it cannot see a stale snapshot) and the committed mutation is already in
    the outcome sink, so the failure path can still report it."""
    from pipeline.state import CommittedOutcomeSink

    store.save_task("u1", "Finish thesis")
    real = store.retrieve_context
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:  # Node 2 succeeds; the post-mutation refresh fails
            raise RuntimeError("database is locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "retrieve_context", flaky)
    llm = CapturingLLM()
    sink = CommittedOutcomeSink()

    with pytest.raises(RuntimeError, match="database is locked"):
        _run_context_executor_llm(store, llm, {
            "intent": "add_task",
            "transcript": "Add buy milk to my tasks",
            "slots": {"title": "Buy milk"},
            "outcome_sink": sink,
        })

    assert llm.prompts == []  # Node 3 never ran
    assert len(sink.snapshot()) == 1  # ...but the mutation is on record
    assert any(t["title"] == "Buy milk" for t in store.list_tasks("u1"))


def test_refresh_failure_through_the_runner_is_audited_and_reports_the_commit(
    store, monkeypatch
):
    """End to end: refresh failure -> degraded trace + InteractionError that says
    the request was already carried out, with exactly one task in the database."""
    import numpy as np
    from audio.resample import to_pcm16_16k
    from pipeline.interaction import InteractionError, InteractionRunner, SessionContext

    store.save_task("u1", "Finish thesis")
    real = store.retrieve_context
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("database is locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "retrieve_context", flaky)
    llm = CapturingLLM()
    graph = _full_graph(store, llm, transcript="Add buy milk to my tasks",
                        intent="add_task", slots={"title": "Buy milk"})

    class TTS:
        def synthesize(self, text):
            return np.zeros(100, dtype=np.float32), 22_050

    runner = InteractionRunner(graph=graph, store=store, tts=TTS(),
                               resampler=to_pcm16_16k, console=lambda _m: None)
    session = SessionContext(session_id="s1", user_id="u1", started_monotonic=0.0,
                             wake_word_detected_at=1000)

    with pytest.raises(InteractionError) as info:
        runner.run(session=session, audio=np.zeros(160, dtype=np.float32),
                   sample_rate=16_000)

    err = info.value
    assert err.wire_code == "pipeline_failure"
    assert "database is locked" in str(err.cause)
    assert len(err.committed_outcomes) == 1
    assert "already carried out" in err.committed_message
    assert llm.prompts == []
    assert [t["title"] for t in store.list_tasks("u1")].count("Buy milk") == 1
    assert any(t["degradation_reason"] == "pipeline_failure"
               for t in store.list_decision_traces("u1"))


def test_failed_mutation_keeps_original_context_and_does_not_refresh(store, monkeypatch):
    store.save_task("u1", "Finish thesis")
    real = store.retrieve_context
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "retrieve_context", counting)
    llm = CapturingLLM()

    result = _run_context_executor_llm(store, llm, {
        "intent": "reschedule_task",
        "transcript": "Move the thing to whenever",
        "slots": {"task_reference": "Finish thesis", "new_deadline": "whenever the moon is full"},
    })

    assert result["execution_outcome"]["succeeded"] is False
    # only Node 2's read; nothing changed, so no refresh
    assert calls["n"] == 1
    assert "post_execution_context" not in result
    assert [t["title"] for t in llm.context_the_llm_saw()["tasks"]] == [
        "Finish thesis"]


@pytest.mark.parametrize("intent,extra_slots,stored_outcome", [
    ("dismiss_reminder", {}, "accepted"),
    ("snooze_reminder", {"snooze_minutes": 10}, "snoozed"),
])
def test_reminder_mutations_leave_no_stale_state_for_node3(
    store, intent, extra_slots, stored_outcome
):
    """Snooze/dismiss (the policy-governed intents) change reminder state in
    decision_trace, but Node 3's context is built only from tasks and routine_log,
    so there is no reminder state in it to go stale. This pins that fact.

    Tripwire: if reminder state is ever added to the retrieved context, the key
    assertion below fails and forces the stale-context question to be answered
    for it (extend the refresh and this test) instead of silently regressing.
    """
    store.save_task("u1", "Finish thesis")
    trace_id = seed_pending_reminder(store)
    before = store.retrieve_context("u1", top_k=5, deadline_proximity_hours=2)
    llm = CapturingLLM()

    result = _run_context_executor_llm(store, llm, {
        "intent": intent,
        "transcript": "dismiss that reminder" if intent == "dismiss_reminder"
        else "snooze that reminder",
        "slots": {"reference_trace_id": trace_id, **extra_slots},
    })

    # Control: the reminder really changed state in storage.
    assert result["execution_outcome"]["succeeded"] is True
    with store.database.connection() as conn:
        stored = conn.execute(
            "SELECT reminder_outcome FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()[0]
    assert stored == stored_outcome

    seen = llm.context_the_llm_saw()
    # Tripwire: Node 3 only ever sees task / routine context, never reminders.
    assert set(seen) == {"tasks", "recent_routine", "overdue_tasks"}
    assert trace_id not in json.dumps(seen)
    # The refresh ran for these intents too, and (nothing it reads changed) it
    # equals the pre-mutation snapshot.
    assert result["post_execution_context"] == result["context"]
    # Policy/trace inputs for the governed intents are untouched.
    assert result["retrieved_context_ids"] == before.ids
    assert result["deadline_proximity"] == before.deadline_proximity


def test_prompt_forbids_state_claims_outside_the_context_and_totals(store):
    llm = CapturingLLM()
    _run_context_executor_llm(store, llm, {
        "intent": "add_task",
        "transcript": "Add buy milk to my tasks",
        "slots": {"title": "Buy milk"},
    })
    prompt = llm.prompts[-1]
    assert "ONLY if they appear in the retrieved context" in prompt
    assert "Never state or imply a total number" in prompt
    assert "re-read AFTER the mutation" in prompt


def _full_graph(store, llm, *, transcript, intent, slots):
    import numpy as np  # noqa: F401  (audio is built by the caller)
    from pipeline.graph import build_dialogue_graph

    class STT:
        def transcribe(self, audio, sample_rate):
            return transcript

    class Intent:
        def classify(self, _transcript):
            return intent, 0.95, slots

    class Affect:
        def detect(self, audio, sample_rate):
            return "Low"

    return build_dialogue_graph(
        stt=STT(), intent_classifier=Intent(), llm=llm, store=store,
        affect_detector=Affect(), confidence_threshold=0.60, context_top_k=5,
        deadline_proximity_hours=2, grace_window_minutes=15, default_lead_time=15,
        executor=make_executor(store),
    )


def _invoke(graph):
    import numpy as np
    return graph.invoke({"session_id": "s1", "user_id": "u1",
                         "audio": np.zeros(160, dtype=np.float32),
                         "sample_rate": 16000})


def test_full_graph_reschedule_shows_node3_the_new_deadline(store):
    now = datetime.now(timezone.utc)
    task_id = store.save_task("u1", "Finish thesis",
                              deadline=now - timedelta(days=1))
    new_deadline = (now + timedelta(days=3)).isoformat()
    llm = CapturingLLM()
    graph = _full_graph(
        store, llm, transcript="Move my thesis deadline to Friday",
        intent="reschedule_task",
        slots={"task_reference": "Finish thesis", "new_deadline": new_deadline})

    result = _invoke(graph)

    assert result["execution_outcome"]["succeeded"] is True
    seen = llm.context_the_llm_saw()
    assert task_id not in [t["task_id"] for t in seen["overdue_tasks"]]
    assert [t["deadline"] for t in seen["tasks"] if t["task_id"] == task_id] == [
        datetime.fromisoformat(new_deadline).isoformat()]


def test_full_graph_read_only_intent_does_not_refresh(store, monkeypatch):
    store.save_task("u1", "Finish thesis")
    real = store.retrieve_context
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "retrieve_context", counting)
    llm = CapturingLLM()
    graph = _full_graph(store, llm, transcript="what should I focus on",
                        intent="ask_status", slots={})

    result = _invoke(graph)

    assert calls["n"] == 1
    assert "post_execution_context" not in result
