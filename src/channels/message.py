from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Message:
    title: str
    severity: str        # HIGH / MEDIUM / LOW
    confidence: str      # high / medium / low
    root_cause: str
    actions: list[str]
    alarm_name: str
    ship_name: str
    timestamp: datetime
