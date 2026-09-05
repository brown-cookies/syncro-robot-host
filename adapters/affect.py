"""WP-103 affect adapter boundary.

WP-103 only provides the graph-facing affect contract. The production acoustic
classifier is intentionally deferred to WP-104.
"""

from __future__ import annotations

from typing import Any


class DevelopmentAffectDetector:
    """Deterministic WP-103 scaffold detector.

    WP-104 replaces this implementation with the production affect classifier.
    Keeping the detector behind the adapter boundary lets WP-103 exercise the
    graph fan-out/join and policy wiring without coupling this work package to
    the classifier implementation.
    """

    def detect(self, audio: Any, sample_rate: int) -> str:
        if audio is None:
            raise ValueError("audio is required")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        return "Low"
