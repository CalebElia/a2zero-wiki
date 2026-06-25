# tests/test_merge_pages.py
import json
import pytest
from unittest.mock import MagicMock, patch


def _make_response(text: str, stop_reason: str = "end_turn"):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.stop_reason = stop_reason
    return msg


EXISTING_BODY = """The Office of Sustainability and Innovations (OSI) leads A2Zero. ([[sources/cap/cap-2020|cap-2020]])"""

NEW_BODY = """OSI coordinates partner organizations and public engagement events. ([[sources/cap/cap-2020|cap-2020]])"""

MERGED_BODY = """The Office of Sustainability and Innovations (OSI) leads A2Zero and coordinates partner organizations and public engagement events. ([[sources/cap/cap-2020|cap-2020]])"""


def test_merge_pages_calls_anthropic():
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        mock_client.messages.create.return_value = _make_response(MERGED_BODY)
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    assert mock_client.messages.create.called
    assert result == MERGED_BODY


def test_merge_pages_returns_existing_on_api_failure():
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        mock_client.messages.create.side_effect = Exception("API error")
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    assert result == EXISTING_BODY


def test_merge_pages_returns_existing_on_truncation():
    from pipeline.merge_pages import merge_pages
    with patch("pipeline.merge_pages.anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        mock_client.messages.create.return_value = _make_response("partial", stop_reason="max_tokens")
        result = merge_pages(
            canonical_slug="actors/osi",
            existing_body=EXISTING_BODY,
            new_body=NEW_BODY,
            source_uuid="cap-2020",
        )
    assert result == EXISTING_BODY
