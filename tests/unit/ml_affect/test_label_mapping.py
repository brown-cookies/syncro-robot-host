from ml.affect.label_mapping import (
    ALLOWED_LEVELS,
    RAVDESS_LABEL_MAP,
    TESS_LABEL_MAP,
    map_label,
)


def test_all_source_labels_map_to_allowed_levels():
    """Verify that all source labels map to allowed levels."""
    for mapping in (RAVDESS_LABEL_MAP, TESS_LABEL_MAP):
        assert mapping
        assert set(mapping.values()) <= set(ALLOWED_LEVELS)
        assert len(mapping) == len(set(mapping))


def test_surprise_labels_are_explicitly_distinct():
    """Verify that surprise labels are explicitly distinct."""
    assert map_label("RAVDESS", "Surprised") == "High"
    assert map_label("TESS", "Pleasant Surprise") == "Moderate"
