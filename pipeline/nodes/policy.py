"""WP-103 Node 4: deterministic production affect-to-action policy."""

from __future__ import annotations

from pipeline.state import DialogueState

ALLOWED_AFFECT_LEVELS = frozenset({"Low", "Moderate", "High"})
ALLOWED_DEADLINE_PROXIMITY = frozenset({"imminent", "not_imminent", "n/a"})
POLICY_RULES: dict[tuple[str, str], str] = {
    ("Moderate", "not_imminent"): "R2",
    ("Moderate", "imminent"): "R3",
    ("High", "not_imminent"): "R4",
    ("High", "imminent"): "R5",
}

# Section 8.3 explicitly excludes these interactions from the R1-R5 policy
# domain. Keeping this set centralized prevents fabricated policy decisions.
NON_POLICY_INTENTS = frozenset({"ask_status", "request_summary"})
POLICY_GOVERNED_INTENTS = frozenset({"dismiss_reminder", "snooze_reminder"})


def apply_policy(affect_level: str, deadline_proximity: str) -> str:
    """Apply the production policy mapping to the current dialogue state."""
    if affect_level not in ALLOWED_AFFECT_LEVELS:
        raise ValueError(f"Invalid affect level: {affect_level!r}")
    if deadline_proximity not in ALLOWED_DEADLINE_PROXIMITY:
        raise ValueError(f"Invalid deadline proximity: {deadline_proximity!r}")
    if deadline_proximity == "n/a":
        return "n/a"
    if affect_level == "Low":
        return "R1"
    return POLICY_RULES[(affect_level, deadline_proximity)]


def make_policy_node(grace_window_minutes: int, default_lead_time: float, store=None):
    """Create the policy graph node with its injected policy logic."""
    def policy_node(state: DialogueState) -> DialogueState:
        """Apply policy decisions to the current dialogue state."""
        intent = state.get("intent")
        if intent is None:
            raise RuntimeError("Node 4 policy requires intent in DialogueState.")

        # Clarification and summary/status interactions never enter the policy
        # domain. This is required by SPEC §8.3 (policy_rule/deadline both n/a).
        governed = intent in POLICY_GOVERNED_INTENTS
        affect = state.get("affect_level")
        proximity = state.get("deadline_proximity", "n/a")
        if affect is None:
            raise RuntimeError("Node 4 requires the parallel affect result.")

        rule = apply_policy(affect, proximity) if governed else "n/a"
        if not governed:
            proximity = "n/a"

        draft = str(state.get("draft_response", state.get("final_response", ""))).strip()
        if not draft:
            raise RuntimeError("Node 4 requires a non-empty Node 3 draft response.")

        action = "deliver"
        if rule == "R1":
            final = draft
        elif rule == "R2":
            final = f"I’ll give you a little more time. {draft}"
            action = "defer"
        elif rule == "R3":
            final = f"This is time-sensitive. {draft}"
            action = "soften"
        elif rule == "R4":
            final = f"Let’s take this gently. {draft}"
            action = "break_prompt"
        elif rule == "R5":
            # The triggering reminder is delivered; other pending reminder
            # traces are suppressed separately, as required by §8.3.
            final = f"Let’s focus on the most important item first. {draft}"
            action = "deliver"
            if store is not None:
                store.suppress_pending_reminder_traces(
                    user_id=state.get("user_id"),
                )
        else:
            final = draft

        user_id = state.get("user_id")
        lead_time = (
            store.get_lead_time(user_id, default_lead_time)
            if store is not None and isinstance(user_id, str)
            else float(default_lead_time)
        )

        return {
            "final_response": final,
            "deadline_proximity": proximity,
            "policy_rule": rule,
            "action_taken": action,
            "lead_time_min": lead_time,
            "reminder_outcome": (
                "pending" if governed else "n/a"
            ),
        }

    return policy_node
