"""WP-103 Node 1B: intent classification."""

from __future__ import annotations

from pipeline.state import DialogueState


def make_intent_node(classifier, confidence_threshold: float):
    """Create the intent graph node with its injected classifier."""
    def intent_node(state: DialogueState) -> DialogueState:
        """Classify the request intent and store the result in dialogue state."""
        transcript = state.get("transcript")
        if transcript is None:
            raise RuntimeError("Node 1 intent classification requires transcript in DialogueState.")
        intent, confidence, slots = classifier.classify(transcript)
        result: DialogueState = {"intent": intent, "intent_confidence": confidence, "slots": slots}
        if confidence < confidence_threshold:
            result["final_response"] = "I'm not confident I understood that. Could you please say it another way?"
            result["proposed_action"] = "clarify"
        return result
    return intent_node
