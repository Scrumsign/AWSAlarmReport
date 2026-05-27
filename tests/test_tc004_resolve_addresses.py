import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from channels.email import resolve_addresses


def test_resolve_addresses_returns_add_list():
    entries = [{"id": "scrumsign", "add": ["kitamura@scrumsign.com", "t.kimura@scrumsign.com"]}]
    assert resolve_addresses("scrumsign", entries) == ["kitamura@scrumsign.com", "t.kimura@scrumsign.com"]


def test_resolve_addresses_missing_group_returns_empty(caplog):
    entries = [{"id": "scrumsign", "add": ["kitamura@scrumsign.com"]}]
    result = resolve_addresses("missing", entries)
    assert result == []
    assert caplog.records
