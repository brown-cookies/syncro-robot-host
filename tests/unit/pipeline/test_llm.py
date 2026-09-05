from pipeline.nodes.llm import make_llm_node


class CaptureLLM:
    def __init__(self, response='{"response_text":"You have one overdue task.","proposed_action":"deliver"}'):
        """Initialize the CaptureLLM and establish its runtime state."""
        self.prompt = None
        self.response = response

    def generate(self, prompt):
        """Generate an LLM response from the supplied conversation state and context."""
        self.prompt = prompt
        return self.response


def test_overdue_request_limits_llm_context_to_overdue_tasks():
    """Verify that overdue request limits llm context to overdue tasks."""
    llm = CaptureLLM()
    node = make_llm_node(llm)

    result = node({
        "transcript": "What is my overdue task?",
        "intent": "request_summary",
        "intent_confidence": 0.99,
        "slots": {},
        "context": {
            "tasks": [
                {"task_id": "t1", "title": "Future task", "status": "pending"},
            ],
            "overdue_tasks": [
                {"task_id": "t2", "title": "Overdue task", "status": "overdue"},
            ],
            "recent_routine": None,
        },
    })

    assert result["draft_response"] == "You have one overdue task."
    assert '"Overdue task"' in llm.prompt
    assert '"Future task"' not in llm.prompt
    assert "overdue_tasks" in llm.prompt
