from pipeline.synthesis_validation import BrokenRef, ValidationReport


def test_broken_ref_dataclass():
    b = BrokenRef(slug="actors/foo", location="core-actors", display="Foo", context="")
    assert b.slug == "actors/foo"
    assert b.location == "core-actors"


def test_validation_report_is_clean_when_empty():
    report = ValidationReport(broken=[])
    assert report.is_clean is True


def test_validation_report_is_dirty_when_broken_present():
    report = ValidationReport(broken=[
        BrokenRef(slug="actors/foo", location="core-actors", display="Foo", context="")
    ])
    assert report.is_clean is False
