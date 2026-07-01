import pytest
from pathlib import Path


def test_append_index_entry_creates_file(tmp_path):
    from pipeline.pass3_finalize import append_index_entry
    append_index_entry(str(tmp_path), "initiative", "initiatives/cca", "Community Choice Aggregation", "CCA program")
    idx = (tmp_path / "index.md").read_text()
    assert "## initiative" in idx
    assert "[[initiatives/cca|Community Choice Aggregation]]" in idx
    assert "CCA program" in idx


def test_append_index_entry_adds_to_existing_section(tmp_path):
    from pipeline.pass3_finalize import append_index_entry
    append_index_entry(str(tmp_path), "initiative", "initiatives/cca", "CCA")
    append_index_entry(str(tmp_path), "initiative", "initiatives/solar", "Community Solar")
    idx = (tmp_path / "index.md").read_text()
    assert idx.count("## initiative") == 1  # only one section header
    assert "initiatives/cca" in idx
    assert "initiatives/solar" in idx


def test_append_index_entry_creates_new_section(tmp_path):
    from pipeline.pass3_finalize import append_index_entry
    append_index_entry(str(tmp_path), "initiative", "initiatives/cca", "CCA")
    append_index_entry(str(tmp_path), "actor", "actors/osi", "OSI")
    idx = (tmp_path / "index.md").read_text()
    assert "## initiative" in idx
    assert "## actor" in idx


def test_append_log_creates_file(tmp_path):
    from pipeline.pass3_finalize import append_log
    append_log(str(tmp_path), "Ingested cap-2020", source_uuid="cap-2020", run_date="2026-06-23")
    log = (tmp_path / "log.md").read_text()
    assert "2026-06-23" in log
    assert "cap-2020" in log
    assert "Ingested cap-2020" in log


def test_append_log_is_append_only(tmp_path):
    from pipeline.pass3_finalize import append_log
    append_log(str(tmp_path), "First entry", run_date="2026-06-23")
    append_log(str(tmp_path), "Second entry", run_date="2026-06-24")
    log = (tmp_path / "log.md").read_text()
    assert "First entry" in log
    assert "Second entry" in log


def test_update_hot_overwrites(tmp_path):
    from pipeline.pass3_finalize import update_hot
    update_hot(str(tmp_path), "First summary.")
    update_hot(str(tmp_path), "Second summary.")
    hot = (tmp_path / "hot.md").read_text()
    assert "Second summary." in hot
    assert "First summary." not in hot


def test_rebuild_index_scans_pages(tmp_path):
    from pipeline.pass3_finalize import rebuild_index
    # Create two mock wiki pages
    (tmp_path / "initiatives").mkdir()
    (tmp_path / "initiatives" / "cca.md").write_text(
        "---\ntype: initiative\ntitle: CCA\n---\n\nBody.\n"
    )
    (tmp_path / "actors").mkdir()
    (tmp_path / "actors" / "osi.md").write_text(
        "---\ntype: actor\ntitle: OSI\n---\n\nBody.\n"
    )
    rebuild_index(str(tmp_path))
    idx = (tmp_path / "index.md").read_text()
    assert "## initiative" in idx
    assert "## actor" in idx
    assert "initiatives/cca" in idx
    assert "actors/osi" in idx
    assert "index.md" not in idx  # infrastructure file excluded


def test_rebuild_index_excludes_infrastructure_files(tmp_path):
    from pipeline.pass3_finalize import rebuild_index, update_hot, append_log
    update_hot(str(tmp_path), "some summary")
    append_log(str(tmp_path), "some log", run_date="2026-06-23")
    rebuild_index(str(tmp_path))
    idx = (tmp_path / "index.md").read_text()
    assert "log.md" not in idx
    assert "hot.md" not in idx
