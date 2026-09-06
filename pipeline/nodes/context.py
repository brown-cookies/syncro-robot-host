"""WP-103 Node 2: SQLite memory/context retrieval."""

from __future__ import annotations

from pipeline.state import DialogueState


def make_context_node(store, top_k: int, deadline_proximity_hours: int):
    def context_node(state: DialogueState) -> DialogueState:
        # Low-confidence interactions are clarification-only. They still flow
        # through the graph so they receive a decision trace, but no context
        # lookup is needed and no downstream action can execute.
        if state.get("proposed_action") == "clarify":
            return {
                "context": {"tasks": [], "recent_routine": None, "overdue_tasks": []},
                "retrieved_context_ids": [],
                "deadline_proximity": "n/a",
            }

        user_id = state.get("user_id")
        if user_id is None:
            raise RuntimeError("Node 2 context retrieval requires user_id in DialogueState.")
        result = store.retrieve_context(
            user_id,
            top_k=top_k,
            deadline_proximity_hours=deadline_proximity_hours,
        )
        return {
            "context": {
                "tasks": result.tasks,
                "recent_routine": result.recent_routine,
                "overdue_tasks": result.overdue_tasks,
            },
            "retrieved_context_ids": result.ids,
            "deadline_proximity": result.deadline_proximity,
        }

    return context_node
