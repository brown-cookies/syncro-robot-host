"""WP-103 Node 1B: intent classification."""

from __future__ import annotations

from pipeline.state import DialogueState


def make_intent_node(classifier, confidence_threshold: float, reference_clarification_store=None):
    """Create the intent graph node with its injected classifier."""
    def intent_node(state: DialogueState) -> DialogueState:
        """Classify the request intent and store the result in dialogue state."""
        transcript = state.get("transcript")
        if transcript is None:
            raise RuntimeError("Node 1 intent classification requires transcript in DialogueState.")

        user_id = state.get("user_id")
        if reference_clarification_store is not None and isinstance(user_id, str):
            pending = reference_clarification_store.get(user_id)
            if pending is not None:
                return {
                    "intent": pending.intent,
                    "intent_confidence": pending.intent_confidence,
                    "slots": dict(pending.slots),
                    "reference_clarification_active": True,
                }

        intent, confidence, slots = classifier.classify(transcript)
        result: DialogueState = {"intent": intent, "intent_confidence": confidence, "slots": slots}
        if confidence < confidence_threshold:
            result["final_response"] = "I'm not confident I understood that. Could you please say it another way?"
            result["proposed_action"] = "clarify"
        return result
    return intent_node
