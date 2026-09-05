"""WP-104 integration placeholder.

The real integration test is enabled once a trained artifact and local sample audio
are available. It should exercise the full graph with ClassifierAffectDetector and
assert the decision trace contains one allowed affect level.
"""

import os

import pytest


@pytest.mark.skipif(
    not os.getenv("SYNCRO_WP104_INTEGRATION"),
    reason="requires a local WP-104 model artifact and real audio fixture",
)
def test_wp104_real_graph_integration():
    pytest.fail("Enable this test only after the trained WP-104 artifact is available")
