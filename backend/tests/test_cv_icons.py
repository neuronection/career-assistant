"""Print-SVG icon registry sanity: every registered glyph must be
well-formed, self-contained stroke geometry."""

from app.services.cv_icons import PATHS, SECTION_KIND_ICONS, icon


def test_every_section_kind_maps_to_a_registered_icon():
    for kind, name in SECTION_KIND_ICONS.items():
        assert name in PATHS, kind
        svg = icon(name)
        assert svg.startswith('<svg class="icn"'), kind
        assert svg.endswith("</svg>"), kind


def test_wrench_uses_the_real_feather_tool_geometry():
    """A corrupted path once rendered the skills glyph as a mangled
    polygon — pin the correct Feather 'tool' geometry."""
    path = PATHS["wrench"]
    assert path.count("<path") == 1, "one stroke path, no polygons"
    assert "a6 6 0 0 1-7.94 7.94" in path
    assert "6.91-6.91" in path
    assert 'z"/>' in path
