from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pipeline.executor import ActionExecutor
from pipeline.nodes.intent import make_intent_node
from pipeline.nodes.reference_resolution import make_reference_resolution_node
from pipeline.reference_resolution import (
    AMBIGUOUS,
    PendingReferenceClarification,
    ReferenceCandidate,
    ReferenceClarificationStore,
    build_clarification_prompt,
    resolve_clarification_answer,
)
from storage.sqlite_store import SQLiteStore


def make_executor(store):
    return ActionExecutor(
        store,
        reminder_response_window_minutes=10,
        adaptive_lead_time_enabled=True,
        alpha=0.3,
        lead_time_min=5,
        lead_time_max=60,
        default_lead_time=15,
    )


def seed_pending(store, *, user_id, task_id, title, trace_id=None):
    trace_id = trace_id or str(uuid4())
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
                f"session-{trace_id}",
                user_id,
                datetime.now(timezone.utc).isoformat(),
                "request_summary",
                0.96,
                f'["{task_id}"]',
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


def test_clarification_store_is_bounded_and_user_scoped():
    store = ReferenceClarificationStore(max_entries=2)
    candidates = (ReferenceCandidate("r1", "Reminder 1", "Reminder 1"),)

    for user_id in ("u1", "u2", "u3"):
        store.put(
            PendingReferenceClarification(
                user_id=user_id,
                intent="dismiss_reminder",
                intent_confidence=0.9,
                slots={},
                candidates=candidates,
            )
        )

    assert store.get("u1") is None
    assert store.get("u2") is not None
    assert store.get("u3") is not None


def test_clarification_answer_resolves_unique_candidate_by_title():
    candidates = (
        ReferenceCandidate("r1", "Submit thesis [r1]", "Submit thesis"),
        ReferenceCandidate("r2", "Team meeting [r2]", "Team meeting"),
    )
    result = resolve_clarification_answer("the thesis one", candidates)
    assert result.trace_id == "r1"


def test_clarification_answer_reports_ambiguous_overlap():
    candidates = (
        ReferenceCandidate("r1", "Call John [r1]", "Call John"),
        ReferenceCandidate("r2", "Call Jane [r2]", "Call Jane"),
    )
    result = resolve_clarification_answer("the call one", candidates)
    assert result is AMBIGUOUS


def test_reference_resolution_auto_resolves_single_active_candidate(tmp_path):
    store = SQLiteStore(str(tmp_path / "single.db"))
    store.ensure_user("u1")
    task_id = store.save_task("u1", "Submit thesis")
    trace_id = seed_pending(store, user_id="u1", task_id=task_id, title="Submit thesis")
    clarification = ReferenceClarificationStore()
    node = make_reference_resolution_node(
        store,
        clarification,
        reminder_response_window_minutes=10,
    )

    result = node({
        "user_id": "u1",
        "intent": "snooze_reminder",
        "intent_confidence": 0.95,
        "slots": {"snooze_minutes": 10},
        "transcript": "snooze that reminder",
    })

    assert result["reference_resolution_status"] == "resolved"
    assert result["slots"]["reference_trace_id"] == trace_id
    assert clarification.get("u1") is None


def test_reference_resolution_clarification_prompt_uses_numbered_candidates(tmp_path):
    store = SQLiteStore(str(tmp_path / "prompt.db"))
    store.ensure_user("u1")
    t1 = store.save_task("u1", "Submit thesis")
    t2 = store.save_task("u1", "Team meeting")
    seed_pending(store, user_id="u1", task_id=t1, title="Submit thesis")
    seed_pending(store, user_id="u1", task_id=t2, title="Team meeting")
    clarification = ReferenceClarificationStore()
    node = make_reference_resolution_node(
        store, clarification, reminder_response_window_minutes=10
    )
    result = node({
        "user_id": "u1",
        "intent": "dismiss_reminder",
        "intent_confidence": 0.95,
        "slots": {},
        "transcript": "dismiss that reminder",
    })
    assert result["final_response"].startswith("Which reminder do you mean? 1.")


def test_reference_resolution_asks_when_multiple_candidates_are_ambiguous(tmp_path):
    store = SQLiteStore(str(tmp_path / "multi.db"))
    store.ensure_user("u1")
    t1 = store.save_task("u1", "Submit thesis")
    t2 = store.save_task("u1", "Team meeting")
    seed_pending(store, user_id="u1", task_id=t1, title="Submit thesis")
    seed_pending(store, user_id="u1", task_id=t2, title="Team meeting")
    clarification = ReferenceClarificationStore()
    node = make_reference_resolution_node(
        store,
        clarification,
        reminder_response_window_minutes=10,
    )

    result = node({
        "user_id": "u1",
        "intent": "dismiss_reminder",
        "intent_confidence": 0.95,
        "slots": {},
        "transcript": "dismiss that reminder",
    })

    assert result["reference_resolution_status"] == "needs_clarification"
    assert result["proposed_action"] == "clarify"
    assert result["final_response"].startswith("Which reminder do you mean?")
    assert "Submit thesis" in result["final_response"]
    assert "Team meeting" in result["final_response"]
    assert clarification.get("u1") is not None


def test_reference_resolution_clarification_turn_restores_original_action(tmp_path):
    store = SQLiteStore(str(tmp_path / "continue.db"))
    store.ensure_user("u1")
    t1 = store.save_task("u1", "Submit thesis")
    t2 = store.save_task("u1", "Team meeting")
    r1 = seed_pending(store, user_id="u1", task_id=t1, title="Submit thesis")
    seed_pending(store, user_id="u1", task_id=t2, title="Team meeting")
    clarification = ReferenceClarificationStore()
    clarification.put(
        PendingReferenceClarification(
            user_id="u1",
            intent="snooze_reminder",
            intent_confidence=0.96,
            slots={"snooze_minutes": 10},
            candidates=(
                ReferenceCandidate(r1, "Submit thesis [a]", "Submit thesis"),
            ),
        )
    )
    node = make_reference_resolution_node(
        store,
        clarification,
        reminder_response_window_minutes=10,
    )

    result = node({
        "user_id": "u1",
        "intent": "snooze_reminder",
        "intent_confidence": 0.96,
        "slots": {"snooze_minutes": 10},
        "transcript": "the thesis one",
        "reference_clarification_active": True,
    })

    assert result["reference_resolution_status"] == "resolved"
    assert result["slots"] == {
        "snooze_minutes": 10,
        "reference_trace_id": r1,
    }
    assert clarification.get("u1") is None


def test_intent_node_restores_pending_clarification_without_reclassifying(tmp_path):
    clarification = ReferenceClarificationStore()
    clarification.put(
        PendingReferenceClarification(
            user_id="u1",
            intent="snooze_reminder",
            intent_confidence=0.96,
            slots={"snooze_minutes": 10},
            candidates=(ReferenceCandidate("r1", "Submit thesis", "Submit thesis"),),
        )
    )

    class ExplodingClassifier:
        def classify(self, transcript):
            raise AssertionError("classifier must not run during clarification")

    node = make_intent_node(
        ExplodingClassifier(),
        0.60,
        reference_clarification_store=clarification,
    )
    result = node({"user_id": "u1", "transcript": "the thesis one"})

    assert result["intent"] == "snooze_reminder"
    assert result["slots"] == {"snooze_minutes": 10}
    assert result["reference_clarification_active"] is True


def test_reference_resolution_no_active_candidates_reaches_executor_as_not_found(tmp_path):
    store = SQLiteStore(str(tmp_path / "none.db"))
    store.ensure_user("u1")
    clarification = ReferenceClarificationStore()
    node = make_reference_resolution_node(
        store,
        clarification,
        reminder_response_window_minutes=10,
    )

    resolution = node({
        "user_id": "u1",
        "intent": "dismiss_reminder",
        "intent_confidence": 0.95,
        "slots": {},
        "transcript": "dismiss that reminder",
    })
    assert resolution["reference_resolution_status"] == "not_found"

    outcome = make_executor(store).execute({
        "user_id": "u1",
        "intent": "dismiss_reminder",
        "slots": {},
        **resolution,
    })
    assert outcome.succeeded is False
    assert outcome.error_code == "reminder_not_found"
