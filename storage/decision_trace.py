"""Decision-trace persistence for WP-103."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pipeline.contracts import (
    DegradedTraceRecord,
    DecisionTraceRecord,
    ExecutableIntent,
    ExecutionOutcome,
)
from storage.database import SQLiteDatabase


TRACE_FIELDS = (
    "trace_id", "session_id", "user_id", "timestamp", "intent",
    "intent_confidence", "retrieved_context_ids", "affect_level",
    "deadline_proximity", "policy_rule", "action_taken", "lead_time_min",
    "reminder_outcome", "degradation_reason", "network_event", "latency_ms",
    "latency_basis",
)


def compute_lead_time_ema(
    current_L: float,
    outcome: Literal["accepted", "snoozed"],
    snooze_minutes: int | None = None,
    *,
    alpha: float = 0.3,
    lo: float = 5,
    hi: float = 60,
) -> float:
    """Implement techdocs/SPEC.md Section 11.2's adaptive lead-time EMA,
    exactly as quoted there -- not from memory of "EMA" in general.

    ``L = clamp((1 - alpha) * L + alpha * L_hat, lo, hi)``: the *old* ``L``
    carries weight ``(1 - alpha)``, ``L_hat`` carries ``alpha``. A prior
    draft of this function had the two terms swapped, which silently
    inverts how fast the parameter adapts -- this is the corrected order.

    ``delivery_miss`` is deliberately not a valid ``outcome`` here: Section
    11.2's own pseudocode leaves ``L`` untouched for an ignored reminder
    ("no update to L; still logged, not silently dropped"), and per the
    Phase 17 plan that transition is written by the Phase 18 policy-tick
    scheduler, never through this function.
    """
    if outcome == "accepted":
        l_hat = current_L
    elif outcome == "snoozed":
        if snooze_minutes is None:
            raise ValueError(
                "snooze_minutes is required when outcome == 'snoozed'"
            )
        l_hat = current_L - snooze_minutes
    else:
        raise ValueError(
            f"compute_lead_time_ema does not handle outcome={outcome!r}; "
            "'delivery_miss' never updates L and is scheduler-owned "
            "(Phase 18), so it never reaches this function"
        )

    updated = (1 - alpha) * current_L + alpha * l_hat
    return max(lo, min(hi, updated))


class DecisionTraceRepository:
    """Validates and persists complete Section 8.3 trace records."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Initialize the DecisionTraceRepository and establish its runtime state."""
        self._database = database

    def save(self, record: dict[str, Any]) -> None:
        """Persist the current decision-trace data to storage."""
        validated = DecisionTraceRecord.model_validate(record)
        record_json = validated.model_dump(mode="json")
        values = [record_json[name] for name in TRACE_FIELDS]
        values[6] = json.dumps(values[6])

        with self._database.connection() as conn:
            conn.execute(
                f"INSERT INTO decision_trace ({', '.join(TRACE_FIELDS)}) "
                f"VALUES ({', '.join('?' for _ in TRACE_FIELDS)})",
                values,
            )

    def save_degraded(self, record: dict[str, Any]) -> None:
        """Persist a validated degraded trace in the shared decision_trace table."""
        validated = DegradedTraceRecord.model_validate(record)
        record_json = validated.model_dump(mode="json")
        values = [record_json.get(name) for name in TRACE_FIELDS]
        values[6] = json.dumps(values[6]) if values[6] is not None else None

        with self._database.connection() as conn:
            conn.execute(
                f"INSERT INTO decision_trace ({', '.join(TRACE_FIELDS)}) "
                f"VALUES ({', '.join('?' for _ in TRACE_FIELDS)})",
                values,
            )


    def suppress_pending_reminder_traces(self, user_id: str) -> int:
        """Suppress other pending reminder traces when policy requires it."""
        if not user_id:
            raise ValueError("user_id is required")
        with self._database.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE decision_trace
                   SET action_taken = 'suppress'
                 WHERE user_id = ?
                   AND reminder_outcome = 'pending'
                   AND action_taken <> 'suppress'
                """,
                (user_id,),
            )
            return cursor.rowcount

    def update_reminder_outcome(
        self,
        *,
        user_id: str,
        trace_id: str,
        outcome: Literal["accepted", "snoozed"],
        snooze_minutes: int | None,
        response_window_minutes: int,
        adaptive_lead_time_enabled: bool,
        alpha: float,
        lead_time_min: float,
        lead_time_max: float,
        default_lead_time: float,
    ) -> ExecutionOutcome:
        """Atomically resolve one pending reminder to accepted/snoozed and
        update the adaptive lead-time parameter (Phase 17 plan, Phase 2).

        Everything below runs inside a single
        ``with self._database.connection() as conn:`` block -- one
        transaction, not the two separate ``.connection()`` calls (two
        transactions) an earlier draft of this plan used -- so a caller
        never observes the ``decision_trace`` row updated without the
        matching ``lead_time_state`` write, or vice versa; on any rejection
        below, nothing is written at all.

        The four rejection conditions the plan names -- missing, not
        pending, outside the response window, owned by another user -- map
        onto the Phase 1 vocabulary's five closed error codes (never an
        invented sixth):

        - **Owned by another user** is folded into ``reminder_not_found``:
          the lookup below is scoped by ``user_id`` in the same ``WHERE``
          clause as ``trace_id``, so another user's row is indistinguishable
          from a missing one here, deliberately, to avoid leaking
          cross-user row existence through the error code.
        - **Outside the response window** is folded into
          ``reminder_not_pending``: a row whose response window (SPEC
          Section 11.3, ``response_window_minutes``) has elapsed but that
          the Phase 18 scheduler hasn't yet swept to ``delivery_miss`` is,
          from this method's perspective, simply not actionable -- which is
          exactly what ``reminder_not_pending`` already means. There is no
          separate code for this case; the vocabulary is deliberately
          closed at five.

        ``outcome="delivery_miss"`` is rejected outright (``ValueError``,
        not a failed ``ExecutionOutcome``): it is a programmer/caller
        contract violation, not a runtime storage condition -- see
        ``compute_lead_time_ema``'s docstring for why that transition is
        scheduler-owned and never reaches here.
        """
        if outcome not in ("accepted", "snoozed"):
            raise ValueError(
                f"update_reminder_outcome does not accept outcome={outcome!r}; "
                "'delivery_miss' is written by the Phase 18 policy-tick "
                "scheduler, never through this dismiss/snooze-intent path"
            )
        if not user_id:
            raise ValueError("user_id is required")
        if not trace_id:
            raise ValueError("trace_id is required")
        if outcome == "snoozed" and (snooze_minutes is None or snooze_minutes <= 0):
            raise ValueError(
                "snooze_minutes must be a positive int when outcome == 'snoozed'"
            )

        intent: ExecutableIntent = (
            "snooze_reminder" if outcome == "snoozed" else "dismiss_reminder"
        )
        now = datetime.now(timezone.utc)

        with self._database.connection() as conn:
            row = conn.execute(
                "SELECT reminder_outcome, timestamp FROM decision_trace "
                "WHERE trace_id = ? AND user_id = ?",
                (trace_id, user_id),
            ).fetchone()

            if row is None:
                return ExecutionOutcome(
                    succeeded=False,
                    intent=intent,
                    error_code="reminder_not_found",
                    detail=f"no reminder trace {trace_id!r} found for this user",
                )

            if row["reminder_outcome"] != "pending":
                return ExecutionOutcome(
                    succeeded=False,
                    intent=intent,
                    error_code="reminder_not_pending",
                    detail=(
                        f"reminder trace {trace_id!r} is not pending "
                        f"(reminder_outcome={row['reminder_outcome']!r})"
                    ),
                )

            dispatched_at = datetime.fromisoformat(row["timestamp"])
            if dispatched_at.tzinfo is None:
                dispatched_at = dispatched_at.replace(tzinfo=timezone.utc)
            if now - dispatched_at > timedelta(minutes=response_window_minutes):
                return ExecutionOutcome(
                    succeeded=False,
                    intent=intent,
                    error_code="reminder_not_pending",
                    detail=(
                        f"reminder trace {trace_id!r} is outside its "
                        f"{response_window_minutes}-minute response window"
                    ),
                )

            current_l_row = conn.execute(
                "SELECT current_L FROM lead_time_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            current_l = (
                float(current_l_row["current_L"])
                if current_l_row is not None
                else float(default_lead_time)
            )

            if adaptive_lead_time_enabled:
                new_l = compute_lead_time_ema(
                    current_l,
                    outcome,
                    snooze_minutes,
                    alpha=alpha,
                    lo=lead_time_min,
                    hi=lead_time_max,
                )
            else:
                # SPEC Section 11.2: "the host must support both modes via a
                # single configuration flag ... rather than hardcode one
                # behavior" -- L stays fixed, and lead_time_state is left
                # untouched below (no UPSERT) rather than rewritten with the
                # same value it already held.
                new_l = current_l

            conn.execute(
                "UPDATE decision_trace SET reminder_outcome = ?, lead_time_min = ? "
                "WHERE trace_id = ?",
                (outcome, new_l, trace_id),
            )

            if adaptive_lead_time_enabled:
                conn.execute(
                    """
                    INSERT INTO lead_time_state(user_id, current_L, last_updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        current_L = excluded.current_L,
                        last_updated_at = excluded.last_updated_at
                    """,
                    (user_id, new_l, now.isoformat()),
                )

        return ExecutionOutcome(
            succeeded=True,
            intent=intent,
            target_id=trace_id,
            detail=f"reminder trace {trace_id!r} marked {outcome!r}",
            snooze_minutes=snooze_minutes if outcome == "snoozed" else None,
        )

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Retrieve decision traces belonging to the requested user."""
        with self._database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM decision_trace WHERE user_id = ? ORDER BY timestamp ASC",
                (user_id,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item["retrieved_context_ids"] is not None:
                item["retrieved_context_ids"] = json.loads(item["retrieved_context_ids"])
            result.append(item)
        return result
