from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


VALID_SEVERITIES: frozenset[str] = frozenset({"HIGH", "MEDIUM", "LOW"})

SEVERITY_JA: dict[str, str] = {"HIGH": "重要", "MEDIUM": "注意", "LOW": "情報"}
CONFIDENCE_JA: dict[str, str] = {"high": "高", "medium": "中", "low": "低"}


@dataclass(frozen=True)
class Message:
    severity: str                # HIGH / MEDIUM / LOW（error_id から固定決定）
    confidence: str              # high / medium / low
    business_summary: str        # 非技術者向け: 業務上何が起きているか
    root_cause: str              # 非技術者向け: 原因の見立て
    technical_observation: str   # 技術者向け: ログから確認できた事実
    technical_hypothesis: str    # 技術者向け: 原因仮説と対処の方向性
    actions: list[str]
    alarm_name: str
    ship_name: str
    timestamp: datetime
    error_id: str
