import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from channels.message import Message


def test_message_is_frozen():
    from dataclasses import FrozenInstanceError

    msg = Message(
        severity="HIGH",
        confidence="high",
        business_summary="テスト業務説明",
        root_cause="原因",
        business_action="確認してください",
        technical_observation="観測事実",
        technical_hypothesis="仮説",
        technical_actions=[],
        alarm_name="hdw-sakura",
        ship_name="sakura",
        timestamp=datetime(2026, 5, 26, tzinfo=timezone.utc),
        error_id="lambda_failure",
    )
    with pytest.raises(FrozenInstanceError):
        msg.severity = "x"
