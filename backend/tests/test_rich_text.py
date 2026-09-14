"""Bounded rich-text normalization: the single write gate for CV prose.

Storage format is markdown — the subset the renderer's `inline_md`
parses (**bold**, *italic*, safe links, line breaks). User API input and
untrusted LLM output both pass `normalize_rich_text`; everything else is
stripped so HTML/DOCX/ATS exports stay consistent and injection-proof.
"""

from app.services.rich_text import normalize_rich_text


def test_keeps_the_supported_subset():
    assert (
        normalize_rich_text("**bold** *italic* [x](https://a.io)", 500)
        == "**bold** *italic* [x](https://a.io)"
    )


def test_strips_raw_tags_and_event_handlers():
    assert normalize_rich_text("<script>alert(1)</script>", 500) == "alert(1)"
    assert normalize_rich_text("<b onclick='x'>y</b>", 500) == "y"


def test_strips_block_constructs():
    text = "# Head\n## Sub\n- item\n1. num\n> quote\n```fenced```"
    assert normalize_rich_text(text, 500) == "Head\nSub\nitem\nnum\nquote\nfenced"


def test_drops_images_and_unsafe_links():
    assert normalize_rich_text("![x](https://a.io/i.png)", 500) == ""
    assert normalize_rich_text("[click](javascript:alert(1))", 500) == "click"
    assert normalize_rich_text("[keep](mailto:a@b.io)", 500) == "[keep](mailto:a@b.io)"
    assert normalize_rich_text("[drop](ftp://x)", 500) == "drop"


def test_unwraps_unsupported_emphasis():
    assert normalize_rich_text("___x___", 500) == "__x__"
    assert normalize_rich_text("snake_case_word", 500) == "snake_case_word"


def test_collapses_blank_runs_and_trims():
    assert normalize_rich_text("a\n\n\n\nb", 500) == "a\n\nb"
    assert normalize_rich_text("  spaced  ", 500) == "spaced"


def test_handles_empty_and_none():
    assert normalize_rich_text(None, 100) == ""
    assert normalize_rich_text("", 100) == ""
    assert normalize_rich_text("   \n ", 100) == ""


def test_hard_trims_to_the_bound():
    assert len(normalize_rich_text("x" * 300, 100)) == 100


def test_schemas_normalize_llm_and_user_input():
    from app.schemas.experience import ExperienceItemIn
    from app.schemas.cv_assistant import SetOverrideOp

    item = ExperienceItemIn.model_validate(
        {
            "title": "T",
            "kind": "project",
            "open_ended": True,
            "description": "<b>Bold</b> work with [x](https://a.io)",
        }
    )
    assert item.description == "Bold work with [x](https://a.io)"

    op = SetOverrideOp.model_validate(
        {
            "op": "set_override",
            "source_key": "summary",
            "item_id": "summary",
            "field": "summary",
            "value": "## Heading\ntext **bold**",
        }
    )
    assert op.value == "Heading\ntext **bold**"


def test_renderer_inline_md_stays_compatible():
    """The renderer's `inline_md` renders exactly what normalization keeps."""
    from app.services.rich_text import normalize_rich_text
    from app.services.cv_renderer import inline_md

    raw = "**Lead** with <em>something</em> and [docs](https://a.io/x)"
    assert "<strong>Lead</strong>" in inline_md(normalize_rich_text(raw, 500))
    assert "<em>" not in inline_md(normalize_rich_text(raw, 500))
    assert '<a href="https://a.io/x">docs</a>' in inline_md(
        normalize_rich_text(raw, 500)
    )
