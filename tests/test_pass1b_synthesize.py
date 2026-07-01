def test_split_strategy_sections_both_present():
    from pipeline.pass1b_synthesize import _split_strategy_sections
    body = "## Foundation\n\nFoundation text here.\n\n## Progress Synthesis\n\nProgress text here.\n"
    foundation, progress = _split_strategy_sections(body)
    assert foundation == "Foundation text here."
    assert progress == "Progress text here."


def test_split_strategy_sections_legacy_single_body():
    from pipeline.pass1b_synthesize import _split_strategy_sections
    body = "This is a legacy single-body strategy page with no section headers."
    foundation, progress = _split_strategy_sections(body)
    assert foundation is None
    assert progress is None


def test_assemble_strategy_body_round_trip():
    from pipeline.pass1b_synthesize import _split_strategy_sections, _assemble_strategy_body
    assembled = _assemble_strategy_body("Foundation text.", "Progress text.")
    foundation, progress = _split_strategy_sections(assembled)
    assert foundation == "Foundation text."
    assert progress == "Progress text."
