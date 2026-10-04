from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np
import pytest

from adapters.llm.ollama_adapter import LLMAdapterError
from adapters.tts.piper_adapter import TTSAdapterError
from audio.resample import to_pcm16_16k
from pipeline.executor import ActionExecutor
from pipeline.graph import make_executor_node
from pipeline.interaction import InteractionError, InteractionRunner, SessionContext
from pipeline.state import CommittedOutcomeSink, DialogueState
from storage.sqlite_store import SQLiteStore


def make_executor(store, *, adaptive=True):
    return ActionExecutor(
        store,
        reminder_response_window_minutes=10,
        adaptive_lead_time_enabled=adaptive,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15,
    )


def seed_pending_reminder(store, *, user_id="u1", trace_id=None):
    trace_id = trace_id or str(uuid4())
    now = datetime.now(timezone.utc)
    store.ensure_user(user_id)
    with store.database.connection() as conn:
        conn.execute(
            """
            INSERT INTO decision_trace(
                trace_id, session_id, user_id, timestamp, intent,
                intent_confidence, retrieved_context_ids, affect_level,
                deadline_proximity, policy_rule, action_taken, lead_time_min,
                reminder_outcome, degradation_reason, network_event,
                latency_ms, latency_basis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                "reminder-session",
                user_id,
                now.isoformat(),
                "request_summary",
                0.99,
                "[]",
                "Moderate",
                "not_imminent",
                "R2",
                "defer",
                15.0,
                "pending",
                None,
                None,
                1.0,
                "host_observed_only",
            ),
        )
    return trace_id


def test_add_task_creates_real_row_and_returns_generated_id(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "add_task",
        "slots": {
            "title": "Submit thesis draft",
            "deadline": "2026-09-24T09:00:00+08:00",
            "priority": "high",
        },
    })

    assert outcome.succeeded is True
    assert outcome.intent == "add_task"
    assert outcome.target_id
    assert outcome.error_code is None

    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT task_id, user_id, title, deadline, priority FROM tasks WHERE task_id = ?",
            (outcome.target_id,),
        ).fetchone()
    assert row is not None
    assert tuple(row) == (
        outcome.target_id,
        "u1",
        "Submit thesis draft",
        "2026-09-24T09:00:00+08:00",
        "high",
    )


def test_add_task_invalid_slots_never_mutates_storage(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "add_task",
        "slots": {"title": ""},
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "invalid_slots"
    with store.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_reschedule_task_resolves_exact_title_from_pre_mutation_context(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    task_id = store.save_task(
        "u1", "Team meeting", deadline=datetime(2026, 9, 25, 9, tzinfo=timezone.utc)
    )
    executor = make_executor(store)

    context = {
        "tasks": [{
            "task_id": task_id,
            "title": "Team meeting",
            "deadline": "2026-09-25T09:00:00+00:00",
            "priority": "normal",
            "status": "pending",
        }],
        "overdue_tasks": [],
        "recent_routine": None,
    }
    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_reference": "  TEAM   meeting ",
            "new_deadline": "2026-09-26T14:30:00+00:00",
        },
        "context": context,
    })

    assert outcome.succeeded is True
    assert outcome.target_id == task_id
    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT deadline FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    assert row[0] == "2026-09-26T14:30:00+00:00"


def test_reschedule_task_rejects_raw_task_id_even_with_matching_reference(tmp_path):
    """Open item 3: a raw `task_id` slot must never reach the store, even
    when a valid `task_reference` is also present and would otherwise
    resolve to a *different* task. Upstream slot data must not be able to
    bypass semantic target resolution by supplying `task_id` directly."""
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    real_task_id = store.save_task("u1", "Team meeting")
    other_task_id = store.save_task("u1", "Submit thesis")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_id": other_task_id,
            "task_reference": "Team meeting",
            "new_deadline": "2026-09-26T14:30:00+00:00",
        },
        "context": {
            "tasks": [
                {"task_id": real_task_id, "title": "Team meeting"},
                {"task_id": other_task_id, "title": "Submit thesis"},
            ],
            "overdue_tasks": [],
        },
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "invalid_slots"
    with store.database.connection() as conn:
        for tid in (real_task_id, other_task_id):
            assert conn.execute(
                "SELECT deadline FROM tasks WHERE task_id = ?", (tid,)
            ).fetchone()[0] is None


def test_reschedule_task_not_found_does_not_touch_storage(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Existing task")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_reference": "Missing task",
            "new_deadline": "2026-09-26T14:30:00+00:00",
        },
        "context": {
            "tasks": [{"task_id": task_id, "title": "Existing task"}],
            "overdue_tasks": [],
        },
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "task_not_found"
    with store.database.connection() as conn:
        assert conn.execute(
            "SELECT deadline FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()[0] is None


def test_reschedule_task_ambiguous_reference_does_not_guess(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    t1 = store.save_task("u1", "Call John")
    t2 = store.save_task("u1", "Call John")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_reference": "Call John",
            "new_deadline": "2026-09-26T14:30:00+00:00",
        },
        "context": {
            "tasks": [
                {"task_id": t1, "title": "Call John"},
                {"task_id": t2, "title": "Call John"},
            ],
            "overdue_tasks": [],
        },
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "ambiguous_task"


def test_snooze_reminder_updates_existing_trace_and_ema(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    trace_id = seed_pending_reminder(store)
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "snooze_reminder",
        "slots": {"reference_trace_id": trace_id, "snooze_minutes": 10},
    })

    assert outcome.succeeded is True
    assert outcome.target_id == trace_id
    assert outcome.snooze_minutes == 10
    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT reminder_outcome, lead_time_min FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    assert row[0] == "snoozed"
    assert row[1] == 12.0


def test_dismiss_reminder_requires_explicit_reference(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "dismiss_reminder",
        "slots": {},
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "invalid_slots"


def test_dismiss_reminder_updates_referenced_pending_trace(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    trace_id = seed_pending_reminder(store)
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "dismiss_reminder",
        "slots": {"reference_trace_id": trace_id},
    })

    assert outcome.succeeded is True
    assert outcome.target_id == trace_id
    assert outcome.snooze_minutes is None
    with store.database.connection() as conn:
        row = conn.execute(
            "SELECT reminder_outcome, lead_time_min FROM decision_trace WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    assert row[0] == "accepted"
    assert row[1] == 15.0


def test_executor_uses_same_store_instance_passed_at_construction(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    executor = make_executor(store)
    assert executor.store is store


def test_reschedule_task_parses_natural_language_deadline(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Team meeting")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_reference": "Team meeting",
            "new_deadline": "tomorrow at 9am",
        },
        "context": {
            "tasks": [{"task_id": task_id, "title": "Team meeting"}],
            "overdue_tasks": [],
        },
    })

    assert outcome.succeeded is True
    with store.database.connection() as conn:
        deadline = conn.execute(
            "SELECT deadline FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()[0]
    from datetime import datetime

    parsed = datetime.fromisoformat(deadline)
    assert parsed.hour == 9
    assert parsed.minute == 0


def test_reschedule_task_rejects_unparseable_natural_language_deadline(tmp_path):
    store = SQLiteStore(str(tmp_path / "exec.db"))
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Team meeting")
    executor = make_executor(store)

    outcome = executor.execute({
        "user_id": "u1",
        "intent": "reschedule_task",
        "slots": {
            "task_reference": "Team meeting",
            "new_deadline": "sometime when the moon is full",
        },
        "context": {
            "tasks": [{"task_id": task_id, "title": "Team meeting"}],
            "overdue_tasks": [],
        },
    })

    assert outcome.succeeded is False
    assert outcome.error_code == "invalid_slots"


def _state(key, *, user="u1", intent="add_task", slots=None, session="s1"):
    state = {
        "user_id": user,
        "session_id": session,
        "intent": intent,
        "slots": slots if slots is not None else {"title": "Buy milk"},
    }
    if key is not None:
        state["interaction_key"] = key
    return state


@pytest.fixture
def store(tmp_path):
    s = SQLiteStore(str(tmp_path / "idem.db"))
    s.ensure_user("u1")
    return s


def _task_count(store):
    with store.database.connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]


def test_replayed_add_task_does_not_create_a_second_task(store):
    executor = make_executor(store)
    first = executor.execute(_state("k1"))
    second = executor.execute(_state("k1"))

    assert first.succeeded and second.succeeded
    assert second.target_id == first.target_id
    assert "created" in first.detail
    assert "already existed" in second.detail
    assert _task_count(store) == 1


def test_new_utterance_with_same_content_is_a_new_task(store):
    """Saying 'add buy milk' twice on purpose must still create two tasks."""
    executor = make_executor(store)
    a = executor.execute(_state("k1"))
    b = executor.execute(_state("k2"))

    assert a.target_id != b.target_id
    assert _task_count(store) == 2


def test_without_interaction_key_behaviour_is_unchanged(store):
    executor = make_executor(store)
    executor.execute(_state(None))
    executor.execute(_state(None))
    assert _task_count(store) == 2


def test_failed_add_task_leaves_no_key_so_a_retry_can_succeed(store):
    executor = make_executor(store)
    bad = executor.execute(_state("k1", slots={"title": "   "}))
    assert not bad.succeeded

    good = executor.execute(_state("k1"))
    assert good.succeeded
    assert _task_count(store) == 1


def test_replayed_snooze_still_cannot_mutate_twice(store):
    """Reminders need no extra guard: the storage layer already rejects a second
    outcome on a reminder that is no longer pending."""
    trace_id = seed_pending_reminder(store)
    executor = make_executor(store)
    slots = {"reference_trace_id": trace_id, "snooze_minutes": 10}

    first = executor.execute(
        _state("k1", intent="snooze_reminder", slots=slots))
    second = executor.execute(
        _state("k1", intent="snooze_reminder", slots=slots))

    assert first.succeeded
    assert not second.succeeded  # no second mutation


def test_idempotency_adds_no_new_tables(store):
    """SPEC section 9 is the schema's source of truth; this must not extend it."""
    with store.database.connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "mutation_ledger" not in tables


def test_save_task_client_write_id_is_idempotent(store):
    a = store.save_task("u1", "Buy milk", client_write_id="cw-1")
    b = store.save_task("u1", "Buy milk", client_write_id="cw-1")
    assert a == b
    assert _task_count(store) == 1


def test_interaction_key_is_stable_and_utterance_specific():
    base = dict(session_id="s1", user_id="u1", started_monotonic=0.0,
                wake_word_detected_at=1000)
    a = SessionContext(**base)
    same = SessionContext(**{**base, "interaction_sequence": 99,
                             "started_monotonic": 5.0})
    other_utterance = SessionContext(**{**base, "wake_word_detected_at": 2000})
    other_user = SessionContext(**{**base, "user_id": "u2"})

    assert a.interaction_key == same.interaction_key  # sequence/clock ignored
    assert a.interaction_key != other_utterance.interaction_key
    assert a.interaction_key != other_user.interaction_key


def test_interaction_key_is_none_without_wake_word_timestamp():
    s = SessionContext(session_id="s1", user_id="u1", started_monotonic=0.0)
    assert s.interaction_key is None


def _pending_trace():
    return {
        "trace_id": uuid4(),
        "session_id": "s1",
        "user_id": "u1",
        "timestamp": datetime.now(timezone.utc),
        "intent": "add_task",
        "intent_confidence": 0.9,
        "retrieved_context_ids": [],
        "affect_level": "Low",
        "deadline_proximity": "n/a",
        "policy_rule": "n/a",
        "action_taken": "deliver",
        "lead_time_min": 15.0,
        "reminder_outcome": "n/a",
        "degradation_reason": None,
        "network_event": None,
    }


class _ExecutorThenGraph:
    """Runs the real executor node, then either raises (a graph-stage failure:
    LLM, policy, affect, output) or returns a complete, valid graph result so the
    runner's own later stages (TTS, trace save) are what fail."""

    def __init__(self, executor, *, raise_after=None):
        self._node = make_executor_node(executor)
        self._raise_after = raise_after

    def invoke(self, state):
        outcome = self._node(
            {**state, "intent": "add_task", "slots": {"title": "Buy milk"}})
        if self._raise_after is not None:
            raise self._raise_after
        return {
            "response_payload": {
                "type": "response", "session_id": state["session_id"],
                "tts_text": "Added.", "state_tag": "speaking",
                "policy_rule": "n/a", "lead_time_min": 15.0},
            "pending_trace": _pending_trace(),
            "stage_timings_s": {},
            "execution_outcome": outcome["execution_outcome"],
        }


class _TTS:
    def __init__(self, error=None):
        self._error = error

    def synthesize(self, text):
        if self._error is not None:
            raise self._error
        return np.zeros(100, dtype=np.float32), 22_050


def _runner(store, graph, *, tts=None):
    return InteractionRunner(graph=graph, store=store, tts=tts or _TTS(),
                             resampler=to_pcm16_16k, console=lambda _m: None)


def _session(**kw):
    fields = dict(session_id="s1", user_id="u1", started_monotonic=0.0,
                  wake_word_detected_at=1000)
    fields.update(kw)
    return SessionContext(**fields)


def _run(runner, session):
    return runner.run(session=session, audio=np.zeros(160, dtype=np.float32),
                      sample_rate=16_000)


def _failing_runner(store, executor, scenario):
    """Build a runner whose pipeline fails at `scenario` AFTER the executor commits."""
    if scenario == "llm":
        return _runner(store, _ExecutorThenGraph(
            executor, raise_after=LLMAdapterError("llm timeout")))
    if scenario == "policy":
        return _runner(store, _ExecutorThenGraph(
            executor, raise_after=ValueError("policy evaluation failed")))
    if scenario == "affect":
        return _runner(store, _ExecutorThenGraph(
            executor, raise_after=RuntimeError("affect detector crashed")))
    if scenario == "tts":
        return _runner(store, _ExecutorThenGraph(executor),
                       tts=_TTS(error=TTSAdapterError("piper crashed")))
    if scenario == "trace_save":
        def boom(_record):
            raise RuntimeError("database is locked")
        store.save_decision_trace = boom  # type: ignore[method-assign]
        return _runner(store, _ExecutorThenGraph(executor))
    raise AssertionError(scenario)


# (scenario, stage the runner's failure map should report)
FAILURE_SCENARIOS = [
    ("llm", "llm"),
    ("policy", "pipeline"),
    ("affect", "pipeline"),
    ("tts", "tts"),
    ("trace_save", "pipeline"),
]


@pytest.mark.parametrize("scenario,stage", FAILURE_SCENARIOS)
def test_failure_after_commit_reports_the_committed_mutation(store, scenario, stage):
    runner = _failing_runner(store, make_executor(store), scenario)

    with pytest.raises(InteractionError) as info:
        _run(runner, _session())

    err = info.value
    assert err.stage == stage
    assert err.wire_code == "pipeline_failure"
    assert len(err.committed_outcomes) == 1
    assert err.committed_outcomes[0]["intent"] == "add_task"
    assert err.committed_outcomes[0]["succeeded"] is True
    assert "already carried out" in err.committed_message
    assert "repeat" in err.committed_message
    assert _task_count(store) == 1
    # The degraded trace is still written (SPEC section 13).
    traces = store.list_decision_traces("u1")
    assert any(t["degradation_reason"] == "pipeline_failure" for t in traces)


@pytest.mark.parametrize("scenario,stage", FAILURE_SCENARIOS)
def test_retry_of_same_utterance_after_failure_creates_no_duplicate(
    store, scenario, stage
):
    executor = make_executor(store)
    session = _session()

    with pytest.raises(InteractionError):
        _run(_failing_runner(store, executor, scenario), session)
    # The edge replays the identical utterance after the failure.
    with pytest.raises(InteractionError) as info:
        _run(_failing_runner(store, executor, scenario), session)

    assert _task_count(store) == 1
    assert "already existed" in info.value.committed_outcomes[0]["detail"]


def test_respoken_request_after_failure_is_a_new_utterance(store):
    """Pins the known limit: a user who re-speaks gets a new wake timestamp, so
    dedup cannot (and must not) merge it. The failure message is what tells them
    not to repeat the request."""
    executor = make_executor(store)

    with pytest.raises(InteractionError) as first:
        _run(_failing_runner(store, executor, "llm"),
             _session(wake_word_detected_at=1000))
    assert "You do not need to repeat it" in first.value.committed_message

    with pytest.raises(InteractionError):
        _run(_failing_runner(store, executor, "llm"),
             _session(wake_word_detected_at=9000))

    assert _task_count(store) == 2


def test_failure_without_mutation_has_no_committed_outcomes(store):
    class FailEarly:
        def invoke(self, state):
            raise LLMAdapterError("boom")

    with pytest.raises(InteractionError) as info:
        _run(_runner(store, FailEarly()), _session())
    assert info.value.committed_outcomes == ()
    assert info.value.committed_message is None


def test_failed_mutation_is_not_reported_as_committed(store):
    """A rejected add_task (invalid slots) changed nothing, so a later failure
    must not claim the request was carried out."""

    class BadSlotsThenFail:
        def __init__(self, executor):
            self._node = make_executor_node(executor)

        def invoke(self, state):
            self._node({**state, "intent": "add_task",
                       "slots": {"title": "  "}})
            raise LLMAdapterError("llm timeout")

    with pytest.raises(InteractionError) as info:
        _run(_runner(store, BadSlotsThenFail(make_executor(store))), _session())

    assert info.value.committed_outcomes == ()
    assert _task_count(store) == 0


def test_sink_survives_a_real_langgraph_node_failure(store):
    """The graph's own state is lost when a node raises; the sink must not be."""
    from langgraph.graph import END, START, StateGraph

    def failing(_state):
        raise LLMAdapterError("llm timeout")

    builder = StateGraph(DialogueState)
    builder.add_node("executor", make_executor_node(make_executor(store)))
    builder.add_node("llm", failing)
    builder.add_edge(START, "executor")
    builder.add_edge("executor", "llm")
    builder.add_edge("llm", END)
    graph = builder.compile()

    sink = CommittedOutcomeSink()
    with pytest.raises(LLMAdapterError):
        graph.invoke({
            "user_id": "u1", "session_id": "s1", "intent": "add_task",
            "slots": {"title": "Buy milk"}, "outcome_sink": sink,
        })

    assert len(sink.snapshot()) == 1
    assert _task_count(store) == 1
