# tests/test_merge_pages.py
import json
import pytest
from unittest.mock import MagicMock, patch


EXISTING_BODY = """The Office of Sustainability and Innovations (OSI) leads A2Zero. ([[sources/cap/cap-2020|cap-2020]])"""

NEW_BODY = """OSI coordinates partner organizations and public engagement events. ([[sources/cap/cap-2020|cap-2020]])"""

MERGED_BODY = """The Office of Sustainability and Innovations (OSI) leads A2Zero and coordinates partner organizations and public engagement events. ([[sources/cap/cap-2020|cap-2020]])"""


def test_merge_pages_calls_chat():
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.chat") as mock_chat:
        mock_chat.return_value = MERGED_BODY
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    assert mock_chat.called
    assert result == MERGED_BODY


def test_merge_pages_returns_existing_on_api_failure():
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.chat") as mock_chat:
        mock_chat.side_effect = Exception("API error")
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    assert result == EXISTING_BODY


def test_merge_pages_strips_whitespace():
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.chat") as mock_chat:
        mock_chat.return_value = "  " + MERGED_BODY + "  "
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    assert result == MERGED_BODY
