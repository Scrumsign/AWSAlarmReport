import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from channels.message import Message


def test_message_is_frozen():
    from dataclasses import FrozenInstanceError

    msg = Message(
        title="t",
        severity="HIGH",
        confidence="high",
        root_cause="r",
        actions=[],
        alarm_name="hdw-sakura",
        ship_name="sakura",
        timestamp=datetime(2026, 5, 26, tzinfo=timezone.utc),
    )
    with pytest.raises(FrozenInstanceError):
        msg.title = "x"
