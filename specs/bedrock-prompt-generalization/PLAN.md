---
id: bedrock-prompt-generalization
version: 0.5.0
plan_rev: 5
title: Bedrock アラーム原因解析プロンプトの汎用化 — 実装計画
created_at: 2026-05-22
type: plan
---

# Bedrock アラーム原因解析プロンプトの汎用化 — 実装計画

- **SPEC**: bedrock-prompt-generalization@0.5.0
- **rev**: 5
- **Created at**: 2026-05-22

> **NOTE**: open_decisions のうち O-1 / O-2 / O-3 / O-7 / A-7 は SPEC v0.5.0 で確定済。残る未確定は O-4 / O-5 / O-6。O-6 確定時に本 PLAN 内の `<CONTEXT_PREFIX>` / `<PROFILE_FILE>` を一括実名化する。

各 TASK には実装着手時のガイドとして具体的な Python コード断片を埋め込む。Python 3.12 / AWS Lambda runtime (Docker image) / aws-lambda-powertools / boto3 を前提とする。

> **本 PLAN と原文 issue の関係**: 本 PLAN は原文「実装タスク」セクションの 8 項目を出発点として、SPEC v0.5.0 の決定事項に従って 14 個の TASK に分解・具体化したものである。各 TASK に `> **原文対応**:` ブロックで原文との対応関係を明示する。

## 原文「実装タスク」との対応マップ

原文の 8 項目を本 PLAN の TASK にどう分配したかの一覧。

| 原文 実装タスク | 本 PLAN の TASK | 補足 |
|---|---|---|
| #1 システムプロンプト（静的）の作成 — メタ手続きのみ。監視対象固有語彙ゼロ。既定 failure_taxonomy（b1〜b4）を含む | TASK-007 | `STATIC_SYSTEM_PROMPT` に b1〜b4 と字数制限と出力 JSON スキーマを全て含める |
| #2 動的コンテキストテンプレートの定義（プレースホルダ: アラーム情報 / health_signal / 調査時間窓 / 抽出ログ） | TASK-007 | `render_dynamic_context()` で 6 セクションを順序固定で合成 |
| #3 リソースプロファイルのスキーマ定義と格納先の決定 | TASK-001 (スキーマ) + TASK-002 (取得経路) + TASK-003 (configs/) | 原文「格納先未決」に対し「運用 Lambda 既存 S3」(profile) +「リポジトリ内 YAML」(configs/) の 2 段構成で確定 |
| #4 HDW_Backend_Processor_0001 のプロファイル登録（現行プロンプトの埋め込み知識を移植） | TASK-011 | 原文「参考スキーマ」を本仕様の signal_kind 配列形式に変換して移植 |
| #5 出力 JSON スキーマの定義 | TASK-008 | 字数制限 (summary<=80 / detail<=300 / actions[].text<=80) を truncate 処理として実装 |
| #6 レポートレンダリングテンプレートの実装 | TASK-010 | 原文テンプレ準拠。Title の中身は `response.summary` 昇格と確定 |
| #7 オーケストレーター実装 | TASK-013 | 原文「処理フロー」を Python に具体化 |
| #8 フォールバック処理の実装。(a) プロファイル未登録時 (b) signal_selector 解決失敗時。いずれも Errors メトリクス + traceback を既定 health_signal とする | TASK-005 (fallback_generic 定数) + TASK-013 (main 側分岐) | 「Errors メトリクス + traceback を既定 health_signal とする」を `fallback_generic` 定数として具体化 |

### 本 PLAN で新設した TASK (原文に対応記述なし)

| 本 PLAN の TASK | 新設理由 |
|---|---|
| TASK-004: load_config + Config dataclass | profile 取得を 2 段化 (configs → profile) するための 1 段目を実装 |
| TASK-009: DISCORD_WEBHOOK_URLS + env_label | 通知配信先の管理を Lambda env var 1 個に集約。原文では通知配信先について沈黙 |
| TASK-012: 旧コード削除 + env var 整理 | 「特定 Lambda の事情を材料側へ追い出す」(原文 概要) を達成するための既存コード撤去 |
| TASK-014: 新規アラーム追加手順を PLAN に文書化 | 原文「3. リソースプロファイルのレジストリ化」の意図 (新しいアラーム種別が増えても変更箇所最小) を運用手順として明文化 |

## profile YAML 具体例

本セクションは profile スキーマ (SPEC.md「profile スキーマ完全形」参照) に対する**具体的なインスタンス例**を集める。実装時のリファレンス + TASK-011 のデプロイ対象。

### 例 1: HDW_Backend_Processor_0001 (現行運用、最小構成)

現状の Reporter Lambda の埋め込み知識を移植した v1 構成。1 つの verdict (`completion_success`) + 3 つの ignored signal_kind を持つ。alarm `hdw-sakura` のみが対応。

```yaml
# 運用 Lambda S3: <client-bucket>/<CONTEXT_PREFIX>/<PROFILE_FILE>
function_name: HDW_Backend_Processor_0001

signal_kind:
  # ─── verdict 系 (判定に使う) ───
  - name: completion_success
    type: verdict
    mechanism: log_marker
    locator: 'event="lambda_complete" 行の status フィールド'
    success_condition: 'status == "success" のレコードが 1 件以上存在'
    failure_condition: 'status == "error"、または stack_trace/traceback が存在'
    absence_hypothesis: 'S3 への ZIP アップロード自体が発生せず Lambda 未起動'
    max_severity_on_success: MEDIUM
    severity_on_absence: MEDIUM

  # ─── ignored 系 (障害根拠としない) ───
  - name: ng_file
    type: ignored
    mechanism: log_marker
    locator: 'message に "NG file" を含む行'
    description: '設計上の許容分岐 — 障害根拠としない'

  - name: pia_data_none
    type: ignored
    mechanism: log_marker
    locator: 'message に "pia_data is None" を含む行'
    description: '上流のデータ品質問題 — 障害根拠としない'

  - name: csv_parse_failed
    type: ignored
    mechanism: log_marker
    locator: 'message に "csv parse failed" を含む行'
    description: '上流のデータ品質問題 — 障害根拠としない'

signal:
  - name: hdw-sakura
    kind: completion_success

input_identifiers: [ship_name, ship_timestamp, input_key]
```

**この profile を引く対応する configs/*.yaml**:

```yaml
# configs/hdw-sakura.yaml
function_name: HDW_Backend_Processor_0001
account_id: "920373030024"
aws_region: ap-northeast-1
assume_role_arn: arn:aws:iam::920373030024:role/HDWNotifyLogReader
log_group: /aws/lambda/HDW_Backend_Processor_0001
profile_location: s3://<client-bucket>/<CONTEXT_PREFIX>/<PROFILE_FILE>
bedrock_model_id: <現行 BEDROCK_MODEL_ID env var の値>
bedrock_max_tokens: <現行 BEDROCK_MAX_TOKENS env var の値>
cloudwatch_logs_query_poll_interval_sec: 2.0
```

### 例 2: 同一 Lambda に複数アラーム (将来拡張、HDW + Duration p99)

将来 `HDW_Backend_Processor_0001` に Duration p99 監視アラームを追加する場合の構成。`latency` の verdict signal_kind を追加し、`signal[]` に新 alarm `hdw-duration-p99` のマッピングを追加する。

```yaml
function_name: HDW_Backend_Processor_0001

signal_kind:
  - name: completion_success
    type: verdict
    mechanism: log_marker
    locator: 'event="lambda_complete" 行の status フィールド'
    success_condition: 'status == "success" のレコードが 1 件以上存在'
    failure_condition: 'status == "error"、または stack_trace/traceback が存在'
    absence_hypothesis: 'S3 への ZIP アップロード自体が発生せず Lambda 未起動'
    max_severity_on_success: MEDIUM
    severity_on_absence: MEDIUM

  - name: latency
    type: verdict
    mechanism: metric
    locator: 'CloudWatch メトリクス AWS/Lambda Duration の p99'
    success_condition: 'p99 Duration <= 30000ms'
    failure_condition: 'p99 Duration > 30000ms'
    absence_hypothesis: 'メトリクスデータ無し — Lambda invocation が発生していない可能性'
    max_severity_on_success: LOW
    severity_on_absence: MEDIUM

  # ignored 系は例 1 と同じため省略 (実際の profile には記載する)

signal:
  - name: hdw-sakura
    kind: completion_success
  - name: hdw-duration-p99
    kind: latency

input_identifiers: [ship_name, ship_timestamp, input_key]
```

**ポイント**:
- `latency` は metric 系で `max_severity_on_success: LOW` (レイテンシ正常時は LOW で十分という運用判断)
- `hdw-duration-p99` 用に `configs/hdw-duration-p99.yaml` を別途新設し、その profile_location は同じ profile YAML を指す (1 profile = 1 Lambda の原則を維持)
- 既存の `hdw-sakura` の挙動は不変

### 例 3: 新クライアント (別運用 Lambda)

別クライアントの別運用 Lambda (例: `BENGAL_Backend_Processor_0001`) を追加する場合。識別子の命名が違うため `input_identifiers` も異なる。

```yaml
# 別クライアントの S3 に配置
function_name: BENGAL_Backend_Processor_0001

signal_kind:
  - name: ingestion_complete
    type: verdict
    mechanism: log_marker
    locator: 'event="ingestion_done" 行の result フィールド'
    success_condition: 'result == "ok"'
    failure_condition: 'result == "ng"、または exception が存在'
    absence_hypothesis: 'Kinesis stream 経由のトリガーが届いていない可能性'
    max_severity_on_success: MEDIUM
    severity_on_absence: HIGH    # この Lambda は不在が即重大

signal:
  - name: bengal-vessel-a
    kind: ingestion_complete

input_identifiers: [vessel_id, ingest_at, source_topic]
```

`input_identifiers` を `[vessel_id, ingest_at, source_topic]` に差し替えただけで、Reporter Lambda の Python コードに変更なく Insights クエリが追従する (REQ-006)。

### 例 4: スキーマ違反 (検証関数で弾かれるケース)

参考までに、`ProfileSchemaError` で弾かれる NG パターンの例:

```yaml
# NG: signal[].name に "-test" 末尾を含む (整合性制約 #3 違反)
signal:
  - name: hdw-sakura-test          # ✗ "-test" を含む
    kind: completion_success

# NG: signal[].kind が type=ignored を指す (整合性制約 #5 違反)
signal_kind:
  - name: ng_file
    type: ignored
    mechanism: log_marker
    locator: '...'
    description: '...'
signal:
  - name: hdw-x
    kind: ng_file                  # ✗ ignored を指している

# NG: type=verdict なのに severity フィールド欠落 (整合性制約 #6 違反)
signal_kind:
  - name: completion_success
    type: verdict
    mechanism: log_marker
    locator: '...'
    success_condition: '...'
    failure_condition: '...'
    absence_hypothesis: '...'
    # max_severity_on_success / severity_on_absence 欠落 ✗
```

> **原文対応**: 上記例 1 は原文「実装タスク #4: HDW_Backend_Processor_0001 のプロファイル登録（現行プロンプトの埋め込み知識を移植）」の具体化。原文「参考スキーマ」を本仕様の signal_kind 配列形式 + signal マッピングに変換した。例 2 (latency 拡張) は原文「概念図」(hdw-sakura-test → completion_success, hdw-duration-p99 → latency) を本仕様の構造で表現した形。例 3 (別クライアント) は原文「概要: どの Lambda でも使い回せる形」の動作例で、本仕様で新規に提示する。例 4 は本仕様のスキーマ検証 (REQ-002 整合性制約) を理解するための NG パターン。

## TASK 一覧

### TASK-001: profile スキーマと検証関数 (REQ-002)

> **原文対応**: 原文「実装タスク #3: リソースプロファイルのスキーマ定義と格納先の決定」のうち**スキーマ定義部分**を担う。原文「参考スキーマ」を本仕様で再構成 (`health_signals` 辞書 → `signal_kind` 配列、`secondary_signals` リスト → `signal_kind[type=ignored]` 統合、`type` → `mechanism` リネーム) した結果のスキーマを Python の検証関数として実装する。`-test` 末尾の禁止 (signal[].name) と severity フィールド必須化 (type=verdict) は本仕様で追加した制約。

`src/utils/profile.py` を新設:

```python
# src/utils/profile.py
from __future__ import annotations
from typing import Any

VALID_SIGNAL_TYPES = ("verdict", "ignored")
VALID_MECHANISMS = ("log_marker", "metric", "structured_result")
VALID_SEVERITIES = ("LOW", "MEDIUM", "HIGH")


class ProfileSchemaError(Exception):
    """Resource profile schema violation."""


def validate_profile(data: dict[str, Any]) -> None:
    # 1. トップレベル必須
    for key in ("function_name", "signal_kind", "signal", "input_identifiers"):
        if key not in data:
            raise ProfileSchemaError(
                f"missing required top-level field: {key!r}"
            )

    if not isinstance(data["function_name"], str) or not data["function_name"]:
        raise ProfileSchemaError("function_name must be a non-empty str")

    if not isinstance(data["signal_kind"], list) or not data["signal_kind"]:
        raise ProfileSchemaError("signal_kind must be a non-empty list")

    kind_names: set[str] = set()
    for i, kind in enumerate(data["signal_kind"]):
        _validate_signal_kind_entry(kind, i, kind_names)
        kind_names.add(kind["name"])

    verdict_kind_names = {
        k["name"] for k in data["signal_kind"] if k["type"] == "verdict"
    }

    if not isinstance(data["signal"], list):
        raise ProfileSchemaError("signal must be a list")

    signal_names: set[str] = set()
    for i, s in enumerate(data["signal"]):
        if not isinstance(s, dict):
            raise ProfileSchemaError(f"signal[{i}] must be a dict")
        for f in ("name", "kind"):
            if f not in s:
                raise ProfileSchemaError(
                    f"signal[{i}] missing field {f!r}"
                )
        if s["name"].endswith("-test"):
            raise ProfileSchemaError(
                f"signal[{i}].name={s['name']!r} ends with '-test'; "
                f"use normalized alarm name"
            )
        if s["name"] in signal_names:
            raise ProfileSchemaError(
                f"duplicate signal[].name: {s['name']!r}"
            )
        signal_names.add(s["name"])
        if s["kind"] not in kind_names:
            raise ProfileSchemaError(
                f"signal[{i}].kind={s['kind']!r} not in signal_kind"
            )
        if s["kind"] not in verdict_kind_names:
            raise ProfileSchemaError(
                f"signal[{i}].kind={s['kind']!r} is not type=verdict"
            )

    ids = data["input_identifiers"]
    if not isinstance(ids, list) or not ids:
        raise ProfileSchemaError(
            "input_identifiers must be a non-empty list of str"
        )
    for i, v in enumerate(ids):
        if not isinstance(v, str) or not v:
            raise ProfileSchemaError(
                f"input_identifiers[{i}] must be a non-empty str"
            )


def _validate_signal_kind_entry(
    kind: Any, index: int, seen_names: set[str]
) -> None:
    if not isinstance(kind, dict):
        raise ProfileSchemaError(f"signal_kind[{index}] must be a dict")

    for f in ("name", "type", "mechanism", "locator"):
        if f not in kind:
            raise ProfileSchemaError(
                f"signal_kind[{index}] missing field {f!r}"
            )

    name = kind["name"]
    if not isinstance(name, str) or not name:
        raise ProfileSchemaError(
            f"signal_kind[{index}].name must be a non-empty str"
        )
    if name in seen_names:
        raise ProfileSchemaError(
            f"duplicate signal_kind name: {name!r}"
        )

    if kind["type"] not in VALID_SIGNAL_TYPES:
        raise ProfileSchemaError(
            f"signal_kind[{index}].type={kind['type']!r} "
            f"not in {VALID_SIGNAL_TYPES}"
        )
    if kind["mechanism"] not in VALID_MECHANISMS:
        raise ProfileSchemaError(
            f"signal_kind[{index}].mechanism={kind['mechanism']!r} "
            f"not in {VALID_MECHANISMS}"
        )

    if kind["type"] == "verdict":
        for f in ("success_condition", "failure_condition",
                  "absence_hypothesis",
                  "max_severity_on_success", "severity_on_absence"):
            if f not in kind:
                raise ProfileSchemaError(
                    f"signal_kind[{index}] (type=verdict) "
                    f"missing field {f!r}"
                )
        for f in ("max_severity_on_success", "severity_on_absence"):
            if kind[f] not in VALID_SEVERITIES:
                raise ProfileSchemaError(
                    f"signal_kind[{index}].{f}={kind[f]!r} "
                    f"not in {VALID_SEVERITIES}"
                )
    elif kind["type"] == "ignored":
        if "description" not in kind:
            raise ProfileSchemaError(
                f"signal_kind[{index}] (type=ignored) "
                f"missing field 'description'"
            )
```

### TASK-002: profile 取得 (S3 GetObject) + 検証 (REQ-003, REQ-005)

> **原文対応**: 原文「実装タスク #3」の**格納先**に対する具体実装。原文「処理フロー: レジストリから profile を引き当て」を「運用 Lambda S3 + cross-account AssumeRole 経由 S3 GetObject」として具体化。原文では格納先未決 (確認事項#1) のため、本仕様で確定した経路を実装する。IAM 変更 (S3 GetObject / KMS Decrypt) は本仕様の新設要件 (REQ-003 由来)。

同 `src/utils/profile.py` に追加:

```python
import yaml
from botocore.exceptions import BotoCoreError, ClientError


def fetch_profile(s3_client, profile_location: str) -> dict[str, Any]:
    """profile_location (s3:// URI) から YAML を取得し検証して dict を返す。

    取得失敗・YAML 構文エラー・スキーマ違反は ProfileSchemaError に統一。
    """
    if not profile_location.startswith("s3://"):
        raise ProfileSchemaError(
            f"profile_location must start with s3://, got {profile_location!r}"
        )
    _, _, rest = profile_location.partition("s3://")
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ProfileSchemaError(f"invalid s3 URI: {profile_location!r}")

    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read().decode("utf-8")
    except (BotoCoreError, ClientError) as e:
        raise ProfileSchemaError(
            f"s3 get_object failed: {profile_location!r}: {e}"
        ) from e

    try:
        data = yaml.safe_load(body) or {}
    except yaml.YAMLError as e:
        raise ProfileSchemaError(
            f"yaml parse failed for {profile_location!r}: {e}"
        ) from e

    if not isinstance(data, dict):
        raise ProfileSchemaError(
            f"profile root must be a mapping, got {type(data).__name__}"
        )

    validate_profile(data)
    return data
```

**運用 Lambda 側 IAM 変更** (AssumeRole 対象 Role の Permission Policy に追加):

```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject"],
  "Resource": "arn:aws:s3:::<client-bucket>/<CONTEXT_PREFIX>/*"
},
{
  "Effect": "Allow",
  "Action": ["s3:ListBucket"],
  "Resource": "arn:aws:s3:::<client-bucket>",
  "Condition": {
    "StringLike": { "s3:prefix": "<CONTEXT_PREFIX>/*" }
  }
}
```

KMS CMK 暗号化バケットの場合は CMK 側に cross-account `kms:Decrypt` grant を追加。

### TASK-003: configs/ ディレクトリ移行 (REQ-004, REQ-013)

> **原文対応**: 本 PLAN で新設の構成要素。原文「3. リソースプロファイルのレジストリ化 (`function_name` をキーに引く)」を本仕様では「alarm_name キーの `configs/<正規化名>.yaml` (AWS インフラ情報のみ)」+「`profile_location` 経由の profile 取得 (観測ロジック)」の 2 段構成に分割。`configs/` はその 1 段目を担う新規ディレクトリ。既存 `config/alarm_log_groups.yml` および cross-account-architecture REQ-004 の `LOG_GROUP_MAP` env var は本 TASK で削除する。

1. リポジトリに `configs/` ディレクトリを新設。
2. `configs/hdw-sakura.yaml` を作成 (現行 env var の値を移植):

   ```yaml
   function_name: HDW_Backend_Processor_0001
   account_id: "920373030024"
   aws_region: ap-northeast-1
   assume_role_arn: arn:aws:iam::920373030024:role/HDWNotifyLogReader
   log_group: /aws/lambda/HDW_Backend_Processor_0001
   profile_location: s3://<client-bucket>/<CONTEXT_PREFIX>/<PROFILE_FILE>
   bedrock_model_id: <現行 BEDROCK_MODEL_ID env var の値を移植>
   bedrock_max_tokens: <現行 BEDROCK_MAX_TOKENS env var の値を移植>
   cloudwatch_logs_query_poll_interval_sec: 2.0
   ```

3. Dockerfile を更新:

   ```dockerfile
   COPY configs/ /var/task/configs/
   ```

4. `config/alarm_log_groups.yml` と `src/main.py` の `_load_alarm_log_groups()` / `_ALARM_LOG_GROUPS` 関連を削除。
5. cross-account-architecture REQ-004 の `LOG_GROUP_MAP` env var 処理も削除。

### TASK-004: load_config + Config dataclass (REQ-015, REQ-004)

> **原文対応**: 本 PLAN で新設。原文「処理フロー: レジストリから profile を引き当て」を本仕様では 2 段化したうちの 1 段目 (`configs/<alarm>.yaml` → `Config`) を実装。原文の未決事項 #1 (プロファイル格納先) に対する本仕様の解答 (リポジトリ内 YAML) を具体化する。`-test` 末尾正規化を `normalize_alarm_name()` として独立関数化することで、`-test` 統合不変条件の単一実装点を確立する。

`src/utils/config.py` を新設:

```python
# src/utils/config.py
from __future__ import annotations
import dataclasses
import os
import yaml
from pathlib import Path
from typing import Any


class ConfigNotFoundError(Exception):
    """configs/<name>.yaml が見つからない。"""


class ConfigSchemaError(Exception):
    """configs/<name>.yaml のスキーマ違反。"""


@dataclasses.dataclass(slots=True, frozen=True)
class Config:
    function_name: str
    account_id: str
    aws_region: str
    assume_role_arn: str
    log_group: str
    profile_location: str
    bedrock_model_id: str
    bedrock_max_tokens: int
    cloudwatch_logs_query_poll_interval_sec: float


_TEST_SUFFIX = "-test"


def normalize_alarm_name(alarm_name: str) -> str:
    """alarm 名末尾の "-test" を除去した正規化名を返す。"""
    if alarm_name.endswith(_TEST_SUFFIX):
        return alarm_name[: -len(_TEST_SUFFIX)]
    return alarm_name


def _configs_dir() -> Path:
    if "LAMBDA_TASK_ROOT" in os.environ:
        return Path(os.environ["LAMBDA_TASK_ROOT"]) / "configs"
    return Path(__file__).resolve().parents[2] / "configs"


_REQUIRED_FIELDS: dict[str, type] = {
    "function_name": str,
    "account_id": str,
    "aws_region": str,
    "assume_role_arn": str,
    "log_group": str,
    "profile_location": str,
    "bedrock_model_id": str,
    "bedrock_max_tokens": int,
    "cloudwatch_logs_query_poll_interval_sec": float,
}


def load_config(alarm_name: str) -> Config:
    """alarm_name から configs/<正規化名>.yaml を読み Config を返す。"""
    normalized = normalize_alarm_name(alarm_name)
    path = _configs_dir() / f"{normalized}.yaml"
    if not path.exists():
        raise ConfigNotFoundError(
            f"config file not found: {path} "
            f"(alarm_name={alarm_name!r}, normalized={normalized!r})"
        )
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigSchemaError(f"yaml parse failed for {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigSchemaError(
            f"config root must be a mapping, got {type(data).__name__}"
        )

    for key, expected_type in _REQUIRED_FIELDS.items():
        if key not in data:
            raise ConfigSchemaError(
                f"{path}: missing required field {key!r}"
            )
        value = data[key]
        if expected_type is float and isinstance(value, int):
            value = float(value)
        elif not isinstance(value, expected_type):
            raise ConfigSchemaError(
                f"{path}: field {key!r} expected "
                f"{expected_type.__name__}, got {type(value).__name__}"
            )

    return Config(
        function_name=data["function_name"],
        account_id=data["account_id"],
        aws_region=data["aws_region"],
        assume_role_arn=data["assume_role_arn"],
        log_group=data["log_group"],
        profile_location=data["profile_location"],
        bedrock_model_id=data["bedrock_model_id"],
        bedrock_max_tokens=data["bedrock_max_tokens"],
        cloudwatch_logs_query_poll_interval_sec=float(
            data["cloudwatch_logs_query_poll_interval_sec"]
        ),
    )
```

### TASK-005: signal_kind 解決と fallback_generic (REQ-005, REQ-008)

> **原文対応**: 原文「4. (リソース × アラーム) によるシグナル選択 — `signal_selector`」+ 原文「実装タスク #8: フォールバック処理」を統合実装する TASK。
> - 原文 4. の「signal_selector の値の出どころ 3 候補」のうち**「`alarm_name → selector` のマッピング表」**を採用し、その表を `profile.signal[]` として profile 内に格納
> - 原文「解決失敗時の扱い: 汎用フォールバック (Errors メトリクス + traceback を既定 health_signal とする)」を `FALLBACK_GENERIC` 定数として具体化
> - 原文「LLM には解決済みの health_signal を 1 個だけ渡し、どれを使うかの判断は LLM にさせない」を `resolve_signal_kind()` のコード側決定論的解決で担保

`src/utils/signal.py` を新設:

```python
# src/utils/signal.py
from __future__ import annotations
from typing import Any
from .config import normalize_alarm_name


class SignalUnresolvedError(Exception):
    """profile から alarm に対応する signal_kind が引けない。"""


FALLBACK_GENERIC: dict[str, Any] = {
    "name": "fallback_generic",
    "type": "verdict",
    "mechanism": "metric",
    "locator": "CloudWatch メトリクス AWS/Lambda Errors",
    "success_condition": "時間窓内に Errors > 0 のサンプルが存在しない",
    "failure_condition": (
        "Errors > 0、または stack_trace/traceback が抽出ログに存在"
    ),
    "absence_hypothesis": (
        "Lambda invocation 自体が発生しておらず、"
        "メトリクスもログも生成されていない可能性"
    ),
    "max_severity_on_success": "MEDIUM",
    "severity_on_absence": "MEDIUM",
}


def resolve_signal_kind(
    alarm_name: str, profile: dict[str, Any]
) -> dict[str, Any]:
    """profile.signal[] と profile.signal_kind[] から該当 kind を返す。"""
    normalized = normalize_alarm_name(alarm_name)

    entry = None
    for s in profile.get("signal", []):
        if s.get("name") == normalized:
            entry = s
            break
    if entry is None:
        raise SignalUnresolvedError(
            f"alarm {normalized!r} not in profile.signal[]"
        )

    kind_name = entry.get("kind")

    for k in profile.get("signal_kind", []):
        if k.get("name") == kind_name:
            if k.get("type") != "verdict":
                raise SignalUnresolvedError(
                    f"signal_kind {kind_name!r} has type "
                    f"{k.get('type')!r}, expected 'verdict'"
                )
            return k

    raise SignalUnresolvedError(
        f"signal_kind {kind_name!r} not found in profile.signal_kind[]"
    )


def extract_ignored_signals(
    profile: dict[str, Any]
) -> list[dict[str, Any]]:
    """profile.signal_kind[] から type=ignored を全抽出する。"""
    return [
        k for k in profile.get("signal_kind", [])
        if k.get("type") == "ignored"
    ]
```

### TASK-006: Insights クエリ動的生成 (REQ-006)

> **原文対応**: 原文「スコープ外: CloudWatch Logs Insights のクエリ自体の設計・最適化（既存の抽出処理を流用）」を尊重しつつ、フィールド名ハードコード (`ship_name` 等) のみを撤去する範囲を実装。原文「参考スキーマ」の `input_identifiers: [ship_name, ship_timestamp, input_key]` を「Bedrock に渡すだけ」ではなく「コード側でクエリ生成に使う」と明示化する (REQ-006 description 参照)。

`src/utils/insights.py` を新設:

```python
# src/utils/insights.py
from __future__ import annotations

_BASE_FIELDS: list[str] = [
    "@timestamp", "@message", "level",
    "function_request_id", "cold_start",
    "phase", "exception_name", "message", "exception",
    "xray_trace_id",
]


def build_insights_query(
    input_identifiers: list[str],
    filter_value: str,
    limit: int = 200,
) -> str:
    if not input_identifiers:
        raise ValueError("input_identifiers must be non-empty")

    all_fields = _BASE_FIELDS + list(input_identifiers)
    fields_clause = "fields " + ", ".join(all_fields)
    filter_key = input_identifiers[0]
    filter_clause = f'filter {filter_key} = "{filter_value}"'

    return "\n".join([
        fields_clause,
        f"| {filter_clause}",
        "| sort @timestamp desc",
        f"| limit {limit}",
    ]) + "\n"
```

### TASK-007: 静的システムプロンプト + 動的コンテキスト合成 (REQ-001, REQ-007, REQ-011, REQ-017)

> **原文対応**: 原文「実装タスク #1 (システムプロンプト)」+「実装タスク #2 (動的コンテキストテンプレート)」+「実装タスク #7 (オーケストレーター実装) の一部としてケース分岐撤去」を統合実装する TASK。
> - `STATIC_SYSTEM_PROMPT` に「メタ手続き (verdict 3 分岐)」+「failure_taxonomy b1〜b4」+「severity 既定規則」+「出力 JSON スキーマと字数制限 <=80/<=300/<=80」を全て含める (原文 #1 要件「既定 failure_taxonomy（b1〜b4）を含む」を満たす)
> - `render_dynamic_context()` で原文「動的コンテキスト」テンプレ準拠の 6 セクションを順序固定で合成。ただし「secondary_signals / input_identifiers」は本仕様で 2 セクションに分離 (original ではまとめて 1 セクションだったが、ignored signal_kind と input_identifiers は別軸の情報なので分離する判断)
> - 既存の `render_prompt_case_no_logs` / `render_prompt_case_lambda_failure` 等を完全撤去 (REQ-011)
> - `pre_classification` フィールドは原文「動的コンテキスト」テンプレに従い「アラーム情報」セクションに含める (用途は REQ-017 で再定義)

`src/utils/prompt.py` を全面書き換え (既存ケース分岐撤去):

```python
# src/utils/prompt.py
"""Bedrock への入力プロンプトを生成する純関数群。"""
from __future__ import annotations
from typing import Any


STATIC_SYSTEM_PROMPT = """\
あなたは AWS Lambda の障害分析担当です。提供される動的コンテキスト
(権威シグナル 1 個 + 障害根拠としない情報 + 抽出ログ等) を読み、
以下のメタ手続きで verdict を決定してください。

# メタ手続き (verdict 3 分岐)

1. 動的コンテキストの「権威シグナル」セクションに含まれる
   success_condition / failure_condition / absence_hypothesis と
   抽出ログを照合する。

2. success_condition を満たすレコードが時間窓内に存在する:
   → verdict = "healthy"
   severity は最大 MEDIUM (HIGH 禁止)。

3. failure_condition を満たすレコード、または stack_trace /
   traceback が抽出ログに存在する: → verdict = "failed"
   severity = HIGH 固定。
   failure_taxonomy で原因分類すること (b1〜b4 のいずれか)。

4. 上記いずれでもなく、権威シグナルが時間窓内に 1 件も観測されない:
   → verdict = "absent"
   severity = MEDIUM、confidence = "low" 固定。

# 補正規則

- 「障害根拠としない情報」セクション (ignored 系シグナル) に
  列挙された情報を verdict=failed の根拠としないこと。
  これらは設計上の許容分岐または上流データ品質問題で、本 Lambda の
  責務外。
- secondary signals のログが見えても healthy 判断を妨げてはならない。

# failure_taxonomy (verdict=failed のとき必須分類)

- b1 コードバグ: KeyError / ValueError / AttributeError /
  TypeError 等。stack_trace の最深フレーム (file:line) を特定する。
- b2 入力データ異常: 構造不整合 / 必須フィールド欠落 / 想定外の値域。
- b3 設定欠落: os.environ KeyError / ImportError / 設定ファイル不在。
- b4 外部依存障害: AWS API 失敗 / DynamoDB throttle / AccessDenied 等。

# 出力 JSON スキーマ (必ず厳守)

{
  "verdict":    "healthy" | "failed" | "absent",
  "severity":   "HIGH" | "MEDIUM" | "LOW",
  "confidence": "high" | "medium" | "low",
  "summary":    "string (<=80 文字。冒頭で verdict を識別)",
  "detail":     "string (<=300 文字)",
  "actions": [
    {
      "phase": "即時対応" | "調査手順" | "恒久対策",
      "text":  "string (<=80 文字)"
    }
  ]
}

スキーマ外のキーを混ぜないこと。コードブロックや余計な前置きも禁止。
"""


def render_dynamic_context(
    *,
    alarm_name: str,
    alarm_description: str,
    fire_time_jst: str,
    pre_classification: str,
    signal_kind: dict[str, Any],
    ignored_signals: list[dict[str, Any]],
    input_identifiers: list[str],
    research_window_jst: str,
    formatted_logs: str,
) -> str:
    parts: list[str] = []

    # 1. アラーム情報
    parts.append("# アラーム情報")
    parts.append(f"alarm_name:         {alarm_name}")
    parts.append(f"alarm_description:  {alarm_description or '(none)'}")
    parts.append(f"fire_time_jst:      {fire_time_jst}")
    parts.append(f"pre_classification: {pre_classification}")
    parts.append("")

    # 2. 権威シグナル
    parts.append("# 権威シグナル (signal_kind, 1 個)")
    parts.append(f"name:                    {signal_kind['name']}")
    parts.append(f"type:                    {signal_kind['type']}")
    parts.append(f"mechanism:               {signal_kind['mechanism']}")
    parts.append(f"locator:                 {signal_kind['locator']}")
    parts.append(f"success_condition:       {signal_kind['success_condition']}")
    parts.append(f"failure_condition:       {signal_kind['failure_condition']}")
    parts.append(f"absence_hypothesis:      {signal_kind['absence_hypothesis']}")
    parts.append(f"max_severity_on_success: {signal_kind['max_severity_on_success']}")
    parts.append(f"severity_on_absence:     {signal_kind['severity_on_absence']}")
    parts.append("")

    # 3. 障害根拠としない情報
    parts.append("# 障害根拠としない情報")
    if ignored_signals:
        for sig in ignored_signals:
            parts.append(f"- name={sig['name']} mechanism={sig['mechanism']}")
            parts.append(f"  locator: {sig['locator']}")
            parts.append(f"  description: {sig['description']}")
    else:
        parts.append("(なし)")
    parts.append("")

    # 4. 実行識別フィールド
    parts.append("# 実行識別フィールド (input_identifiers)")
    parts.append(", ".join(input_identifiers))
    parts.append("")

    # 5. 調査時間窓
    parts.append("# 調査時間窓 (JST)")
    parts.append(research_window_jst)
    parts.append("")

    # 6. 抽出ログ
    parts.append("# 抽出ログ (時間窓内・時刻昇順)")
    parts.append(formatted_logs.rstrip())

    return "\n".join(parts)
```

撤去対象: `_SYSTEM_PROMPT_TEMPLATE` / `render_prompt_case_no_logs` / `render_prompt_case_lambda_failure` / `render_prompt_system_base` / `render_prompt_user`。

### TASK-008: 出力 JSON 正規化 + severity 補正 (REQ-007, REQ-009)

> **原文対応**: 原文「実装タスク #5 (出力 JSON スキーマの定義)」+ 原文「2. health_signal 抽象化 (severity 規約)」を統合実装する TASK。
> - 原文の字数制限 (summary <=80字 / detail <=300字 / actions[*].text <=80字) を **コード側の truncate 処理**として実装 (システムプロンプトに明記する制限と二重防御)
> - severity 補正 (verdict=healthy で max_severity_on_success clamp / absent で severity_on_absence + confidence=low / failed で不変) は原文「2. health_signal 抽象化」の severity 規約をコード側で強制する仕組み。原文「参考スキーマ」の `max_severity_on_success` / `severity_on_absence` が signal_kind の中に存在することと整合
> - `verdict` / `severity` / `confidence` の enum 違反、`actions[*].phase` の enum 違反は安全側既定値 (absent / MEDIUM / low / スキップ) で丸める。通知欠落を回避

`src/utils/response.py` を新設:

```python
# src/utils/response.py
from __future__ import annotations
import json
from typing import Any


_VALID_VERDICTS = ("healthy", "failed", "absent")
_VALID_SEVERITIES = ("HIGH", "MEDIUM", "LOW")
_VALID_CONFIDENCES = ("high", "medium", "low")
_VALID_PHASES = ("即時対応", "調査手順", "恒久対策")

_MAX_SUMMARY_CHARS = 80
_MAX_DETAIL_CHARS = 300
_MAX_ACTION_TEXT_CHARS = 80

_SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def normalize_bedrock_response(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    verdict = data.get("verdict")
    if verdict not in _VALID_VERDICTS:
        verdict = "absent"

    severity = (str(data.get("severity") or "")).upper()
    if severity not in _VALID_SEVERITIES:
        severity = "MEDIUM"

    confidence = (str(data.get("confidence") or "")).lower()
    if confidence not in _VALID_CONFIDENCES:
        confidence = "low"

    summary = str(data.get("summary") or "(要約取得失敗)")[:_MAX_SUMMARY_CHARS]
    detail = str(data.get("detail") or "(詳細取得失敗)")[:_MAX_DETAIL_CHARS]

    raw_actions = data.get("actions") or []
    actions: list[dict[str, str]] = []
    if isinstance(raw_actions, list):
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            phase = item.get("phase")
            if phase not in _VALID_PHASES:
                continue
            text_value = str(item.get("text") or "")[:_MAX_ACTION_TEXT_CHARS]
            if not text_value:
                continue
            actions.append({"phase": phase, "text": text_value})

    return {
        "verdict": verdict,
        "severity": severity,
        "confidence": confidence,
        "summary": summary,
        "detail": detail,
        "actions": actions,
    }


def apply_severity_policy(
    response: dict[str, Any], signal_kind: dict[str, Any]
) -> dict[str, Any]:
    verdict = response["verdict"]
    if verdict == "healthy":
        ceiling = signal_kind.get("max_severity_on_success", "MEDIUM")
        response["severity"] = _clamp_severity(response["severity"], ceiling)
    elif verdict == "absent":
        response["severity"] = signal_kind.get("severity_on_absence", "MEDIUM")
        response["confidence"] = "low"
    # failed: no-op
    return response


def _clamp_severity(value: str, ceiling: str) -> str:
    v_rank = _SEVERITY_ORDER.get(value, 1)
    c_rank = _SEVERITY_ORDER.get(ceiling, 1)
    if v_rank <= c_rank:
        return value
    return ceiling
```

### TASK-009: DISCORD_WEBHOOK_URLS 解決 + env_label 導出 (REQ-016, REQ-013)

> **原文対応**: 本 PLAN で新設。原文には**通知配信先の管理方式について記述なし**。Lambda の唯一の env var として `DISCORD_WEBHOOK_URLS` を残す方針 (REQ-016) を実装。`ENVIRONMENT_NAME` を alarm 名末尾 `-test` から `derive_env_label()` で導出する仕組みも本仕様で新設 (REQ-013 で `ENVIRONMENT_NAME` env var を廃止する代替経路)。

`src/utils/webhooks.py` を新設:

```python
# src/utils/webhooks.py
from __future__ import annotations
import json
import os
from .config import normalize_alarm_name


class WebhookConfigError(Exception):
    """DISCORD_WEBHOOK_URLS が不正。"""


def _load_webhook_map() -> dict[str, str]:
    raw = os.environ.get("DISCORD_WEBHOOK_URLS")
    if not raw:
        raise WebhookConfigError("DISCORD_WEBHOOK_URLS env var is not set")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise WebhookConfigError(
            f"DISCORD_WEBHOOK_URLS is not valid JSON: {e}"
        ) from e
    if not isinstance(parsed, dict):
        raise WebhookConfigError(
            f"DISCORD_WEBHOOK_URLS must be a JSON object, "
            f"got {type(parsed).__name__}"
        )
    return {str(k): str(v) for k, v in parsed.items()}


WEBHOOK_MAP: dict[str, str] = _load_webhook_map()


def resolve_webhook_url(alarm_name: str) -> str | None:
    normalized = normalize_alarm_name(alarm_name)
    return WEBHOOK_MAP.get(normalized)


def derive_env_label(alarm_name: str) -> str:
    """alarm 名末尾の "-test" 有無から "test" / "prod" を返す。"""
    return "test" if alarm_name.endswith("-test") else "prod"
```

cold start で `_load_webhook_map()` を即実行することで不正 JSON は import 時の `WebhookConfigError` で Lambda が明確 fail する (AC-016-1 silent failure 防止)。

### TASK-010: レポートヘッダーレンダリング (REQ-010)

> **原文対応**: 原文「実装タスク #6 (レポートレンダリングテンプレート)」+ 原文「レポートレンダリングテンプレート (呼び出し側)」+ 原文「5. 出力とレンダリングの分離」を統合実装する TASK。
> - 原文テンプレ準拠: `Title` / `Target` / `ResearchWindow` / `Alarm` をコード側で決定論的にレンダリング (LLM 出力依存ゼロ)
> - 原文 `{{title}}` は本仕様で「`response.summary` を昇格して使う」と確定 (原文では `{{title}}` の出どころ未指定)
> - 原文 `Action` セクション 3 行 `[即時対応][調査手順][恒久対策]` を実装。該当 phase 欠落時の `(なし)` 表示は本仕様で追加
> - `embed.color` (severity 連動) と `embed.footer` (フォールバック印) は本仕様で追加

`src/utils/report.py` を新設:

```python
# src/utils/report.py
from __future__ import annotations
from typing import Any
from discord_webhook import DiscordEmbed
from .webhooks import derive_env_label


_SEVERITY_COLOR = {
    "HIGH": 0xE74C3C,
    "MEDIUM": 0xF1C40F,
    "LOW": 0x2ECC71,
}


def render_report_embed(
    *,
    alarm_name: str,
    alarm_description: str,
    function_name: str,
    research_window_jst: str,
    response: dict[str, Any],
    fallback_kind: str | None,
    representative_request_id: str | None,
    fire_timestamp_iso: str,
) -> DiscordEmbed:
    embed = DiscordEmbed(
        title=response["summary"][:256],
        color=_SEVERITY_COLOR.get(response["severity"], 0x95A5A6),
    )
    env_label = derive_env_label(alarm_name)
    embed.set_author(name=f"HDW Notify · {env_label}")

    embed.add_embed_field(name="Target", value=function_name, inline=True)
    embed.add_embed_field(
        name="Alarm",
        value=f"{alarm_name} [{alarm_description or '(none)'}]",
        inline=True,
    )
    embed.add_embed_field(
        name="verdict",
        value=response["verdict"],
        inline=True,
    )
    embed.add_embed_field(
        name="ResearchWindow",
        value=research_window_jst,
        inline=False,
    )
    embed.add_embed_field(
        name=f"Report (confidence: {response['confidence']})",
        value=response["summary"],
        inline=False,
    )
    embed.add_embed_field(
        name="Detail",
        value=response["detail"] or "(none)",
        inline=False,
    )

    actions_by_phase = {a["phase"]: a["text"] for a in response.get("actions", [])}
    action_text = "\n".join([
        f"[即時対応] {actions_by_phase.get('即時対応', '(なし)')}",
        f"[調査手順] {actions_by_phase.get('調査手順', '(なし)')}",
        f"[恒久対策] {actions_by_phase.get('恒久対策', '(なし)')}",
    ])
    embed.add_embed_field(name="Action", value=action_text, inline=False)

    footer_parts: list[str] = []
    if representative_request_id:
        footer_parts.append(f"req-id: {representative_request_id}")
    if fallback_kind:
        footer_parts.append(f"fallback: {fallback_kind}")
    if footer_parts:
        embed.set_footer(text=" / ".join(footer_parts))
    embed.set_timestamp(fire_timestamp_iso)
    return embed
```

### TASK-011: HDW_Backend_Processor_0001 profile YAML 作成 + S3 配置 (REQ-002, REQ-003)

> **原文対応**: 原文「実装タスク #4: HDW_Backend_Processor_0001 のプロファイル登録（現行プロンプトの埋め込み知識を移植）」と一致する TASK。原文「参考スキーマ」の HDW 例を本仕様の signal_kind 配列形式に変換して移植する。配置先 (運用 Lambda S3) は本仕様で確定 (REQ-003)。
>
> 原文の参考スキーマと本 TASK の YAML の差分:
> - `health_signals.completion_success` → `signal_kind` 配列の name=completion_success エントリ (type=verdict)
> - `secondary_signals` フラットリスト → `signal_kind` 配列の type=ignored エントリ群 (NG file / pia_data_none / csv_parse_failed を個別エントリ化)
> - `signal` 配列を新設 (alarm `hdw-sakura` → kind `completion_success` のマッピング)
> - `latency` エントリは将来の Duration p99 アラーム導入時に追加可能な形で省略

profile YAML 内容:

```yaml
function_name: HDW_Backend_Processor_0001

signal_kind:
  - name: completion_success
    type: verdict
    mechanism: log_marker
    locator: 'event="lambda_complete" 行の status フィールド'
    success_condition: 'status == "success" のレコードが 1 件以上存在'
    failure_condition: 'status == "error"、または stack_trace/traceback が存在'
    absence_hypothesis: 'S3 への ZIP アップロード自体が発生せず Lambda 未起動'
    max_severity_on_success: MEDIUM
    severity_on_absence: MEDIUM

  - name: ng_file
    type: ignored
    mechanism: log_marker
    locator: 'message に "NG file" を含む行'
    description: '設計上の許容分岐 — 障害根拠としない'

  - name: pia_data_none
    type: ignored
    mechanism: log_marker
    locator: 'message に "pia_data is None" を含む行'
    description: '上流のデータ品質問題 — 障害根拠としない'

  - name: csv_parse_failed
    type: ignored
    mechanism: log_marker
    locator: 'message に "csv parse failed" を含む行'
    description: '上流のデータ品質問題 — 障害根拠としない'

signal:
  - name: hdw-sakura
    kind: completion_success

input_identifiers: [ship_name, ship_timestamp, input_key]
```

配置コマンド (Phase A 手動):

```bash
aws s3 cp profile.yaml \
  s3://<client-bucket>/<CONTEXT_PREFIX>/<PROFILE_FILE> \
  --profile hanshin-t.kimura --region ap-northeast-1
```

### TASK-012: 旧コード削除と env var 整理 (REQ-011, REQ-012, REQ-013)

> **原文対応**: 本 PLAN で新設の整理 TASK (原文には対応する明示記述なし)。原文「概要: 今は手順の中に特定 Lambda の事情がベタ書きされているので、それを「材料」側へ追い出す」を達成するために、現行コードの「手順側に紛れた特定 Lambda の事情」を完全削除する。後方互換シムを残さない方針 (REQ-012) は constitution PRIN-XXX (簡素優先) に準拠。

**src/main.py から削除**:
- Env dataclass 全削除
- `_load_alarm_log_groups()` / `_ALARM_LOG_GROUPS`
- `INSIGHTS_QUERY_TEMPLATE` (TASK-006 に置換)
- `DISCORD_SEVERITY_COLOR` (TASK-010 に集約)
- `ENVIRONMENT_NAME` 参照
- `_normalize_report` (TASK-008 に置換)

**src/utils/prompt.py から削除** (TASK-007 と統合):
- `_SYSTEM_PROMPT_TEMPLATE`
- `render_prompt_system_base`
- `render_prompt_case_no_logs`
- `render_prompt_case_lambda_failure`
- `render_prompt_user`

**設定削除**:
- `config/alarm_log_groups.yml`
- Dockerfile の `config/` COPY (configs/ に変更)

**GitHub Actions からの env var 配信削除**:
`CROSS_ACCOUNT_ROLE_ARN` / `TARGET_FUNCTION_NAME` / `BEDROCK_MODEL_ID` / `BEDROCK_MAX_TOKENS` / `CLOUDWATCH_LOGS_QUERY_POLL_INTERVAL_SEC` / `DISCORD_WEBHOOK_URL` (無印) / `ENVIRONMENT_NAME` / `LOG_GROUP_MAP`。残るのは `DISCORD_WEBHOOK_URLS` のみ。

### TASK-013: src/main.py を新オーケストレーターに書き換える (ALL)

> **原文対応**: 原文「実装タスク #7: オーケストレーター実装」+ 原文「処理フロー（呼び出し側オーケストレーター）」と一致する TASK。原文の擬似コード「アラーム発火 → function_name + alarm_name を取得 → レジストリから profile を引き当て → signal_selector で health_signals から1個を解決 → 動的コンテキストに展開 → Bedrock 呼び出し → 応答 JSON をパース → レポートテンプレートにレンダリング → 通知」を Python に具体化する。本仕様の差分:
> - 「レジストリから profile を引き当て」を 2 段化: load_config (configs/<alarm>.yaml) → fetch_profile (S3 GetObject)
> - 「signal_selector で health_signals から 1 個を解決」を `resolve_signal_kind()` で実装 (profile.signal[] + profile.signal_kind[] の 2 段引き)
> - 3 種類のフォールバック (config 不在 / profile 取得失敗 / signal 解決失敗) を REQ-008 の (a)(b) に従って実装
> - 既存の AssumeRole / Insights / Bedrock 失敗 fallback (cross-account-architecture PRIN-003 由来) は引き続き残す

```python
# src/main.py
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from botocore.exceptions import BotoCoreError, ClientError
from discord_webhook import DiscordWebhook, DiscordEmbed

from utils.config import (
    Config, load_config, normalize_alarm_name,
    ConfigNotFoundError, ConfigSchemaError,
)
from utils.profile import fetch_profile, ProfileSchemaError
from utils.signal import (
    resolve_signal_kind, extract_ignored_signals,
    FALLBACK_GENERIC, SignalUnresolvedError,
)
from utils.insights import build_insights_query
from utils.prompt import STATIC_SYSTEM_PROMPT, render_dynamic_context
from utils.response import normalize_bedrock_response, apply_severity_policy
from utils.report import render_report_embed
from utils.webhooks import resolve_webhook_url, derive_env_label
from utils.log_format import format_log_rows_pretty  # 既存実装を移植

logger = Logger()
JST = timezone(timedelta(hours=9))
INSIGHTS_QUERY_TIMEOUT_SEC = 60.0
SHIP_LOG_WINDOW_MIN = 330
ALARM_NAME_RE = re.compile(r"^hdw-(?P<ship_name>[a-z][a-z0-9]*)(?:-test)?$")


def _format_window_jst(start: datetime, end: datetime) -> str:
    s = start.astimezone(JST)
    e = end.astimezone(JST)
    return f"{s.strftime('%Y-%m-%d %H:%M')}–{e.strftime('%H:%M')} JST"


def _extract_ship_name(alarm_name: str) -> str | None:
    m = ALARM_NAME_RE.fullmatch(alarm_name)
    return m.group("ship_name") if m else None


def _extract_first_request_id(rows: list[list[dict[str, str]]]) -> str | None:
    if not rows:
        return None
    for item in rows[0]:
        if item.get("field") == "function_request_id":
            return item.get("value")
    return None


def _post_minimal_fallback(
    webhook_url: str | None,
    alarm_name: str,
    fire_time_iso: str,
    note: str,
    color: int = 0xF1C40F,
) -> None:
    if not webhook_url:
        logger.warning(
            "webhook not set, skip discord post",
            extra={"alarm_name": alarm_name},
        )
        return
    webhook = DiscordWebhook(url=webhook_url)
    embed = DiscordEmbed(title=note[:256], color=color)
    embed.set_author(name=f"HDW Notify · {derive_env_label(alarm_name)}")
    embed.add_embed_field(name="Alarm", value=alarm_name, inline=False)
    embed.set_timestamp(fire_time_iso)
    webhook.add_embed(embed)
    webhook.execute()


@logger.inject_lambda_context(log_event=True)
def main(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    # 1. SNS event 解析
    sns_msg = json.loads(event["Records"][0]["Sns"]["Message"])
    alarm_name = sns_msg["AlarmName"]
    alarm_description = sns_msg.get("AlarmDescription", "")
    fire_time_iso = sns_msg["StateChangeTime"]
    fire_time = datetime.fromisoformat(fire_time_iso.replace("Z", "+00:00"))
    start = fire_time - timedelta(minutes=SHIP_LOG_WINDOW_MIN)
    end = fire_time
    research_window_jst = _format_window_jst(start, end)
    webhook_url = resolve_webhook_url(alarm_name)
    logger.append_keys(alarm=alarm_name)

    # 2. Config 取得
    fallback_kind: str | None = None
    try:
        config = load_config(alarm_name)
    except (ConfigNotFoundError, ConfigSchemaError) as e:
        logger.exception("config load failed")
        _post_minimal_fallback(
            webhook_url, alarm_name, fire_time_iso,
            note=f"設定不在: {type(e).__name__}",
        )
        return {"ok": True, "alarm": alarm_name, "fallback": "profile_missing"}

    # 3. AssumeRole
    try:
        sts_resp = boto3.client("sts").assume_role(
            RoleArn=config.assume_role_arn,
            RoleSessionName=f"hdw-notify-{context.aws_request_id}",
            DurationSeconds=900,
        )
        creds = sts_resp["Credentials"]
    except (BotoCoreError, ClientError) as e:
        logger.exception("assume_role failed")
        _post_minimal_fallback(
            webhook_url, alarm_name, fire_time_iso,
            note=f"AssumeRole 失敗: {type(e).__name__}",
            color=0xE74C3C,
        )
        return {"ok": True, "alarm": alarm_name, "fallback": "assume_role_failed"}

    s3_client = boto3.client(
        "s3",
        region_name=config.aws_region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    logs_client = boto3.client(
        "logs",
        region_name=config.aws_region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )

    # 4. profile 取得
    try:
        profile = fetch_profile(s3_client, config.profile_location)
    except ProfileSchemaError as e:
        logger.exception("profile fetch/schema failed")
        _post_minimal_fallback(
            webhook_url, alarm_name, fire_time_iso,
            note=f"プロファイル取得失敗: {type(e).__name__}",
        )
        return {"ok": True, "alarm": alarm_name, "fallback": "profile_missing"}

    # 5. signal_kind 解決
    try:
        signal_kind = resolve_signal_kind(alarm_name, profile)
    except SignalUnresolvedError as e:
        logger.warning("signal unresolved", extra={"error": str(e)})
        signal_kind = FALLBACK_GENERIC
        fallback_kind = "signal_unresolved"

    ignored_signals = extract_ignored_signals(profile)
    pre_classification = signal_kind["name"]

    # 6. Insights クエリ
    ship_name = _extract_ship_name(alarm_name) or "unknown"
    query = build_insights_query(
        input_identifiers=profile["input_identifiers"],
        filter_value=ship_name,
    )
    query_id = logs_client.start_query(
        logGroupName=config.log_group,
        startTime=int(start.timestamp()),
        endTime=int(end.timestamp()),
        queryString=query,
    )["queryId"]
    log_rows: list[list[dict[str, str]]] = []
    deadline = time.monotonic() + INSIGHTS_QUERY_TIMEOUT_SEC
    while True:
        result = logs_client.get_query_results(queryId=query_id)
        if result["status"] == "Complete":
            log_rows = result.get("results", [])
            break
        if result["status"] in ("Failed", "Cancelled", "Timeout"):
            logger.warning("insights query failed",
                           extra={"status": result["status"]})
            log_rows = []
            break
        if time.monotonic() >= deadline:
            logger.warning("insights query timed out")
            log_rows = []
            break
        time.sleep(config.cloudwatch_logs_query_poll_interval_sec)

    formatted_logs = format_log_rows_pretty(log_rows)

    # 7. 動的コンテキスト合成
    user_prompt = render_dynamic_context(
        alarm_name=alarm_name,
        alarm_description=alarm_description,
        fire_time_jst=fire_time.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        pre_classification=pre_classification,
        signal_kind=signal_kind,
        ignored_signals=ignored_signals,
        input_identifiers=profile["input_identifiers"],
        research_window_jst=research_window_jst,
        formatted_logs=formatted_logs,
    )

    # 8. Bedrock 呼び出し
    try:
        br = boto3.client("bedrock-runtime").converse(
            modelId=config.bedrock_model_id,
            system=[{"text": STATIC_SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={"maxTokens": config.bedrock_max_tokens},
        )
        report_text = br["output"]["message"]["content"][0]["text"]
    except (BotoCoreError, ClientError, KeyError) as e:
        logger.exception("bedrock call failed")
        _post_minimal_fallback(
            webhook_url, alarm_name, fire_time_iso,
            note=f"Bedrock 失敗: {type(e).__name__}",
        )
        return {"ok": True, "alarm": alarm_name, "fallback": "bedrock_failed"}

    # 9. 応答正規化 + severity 補正
    response = normalize_bedrock_response(report_text)
    response = apply_severity_policy(response, signal_kind)

    # 10. レポートレンダリング + Discord 投稿
    representative_request_id = _extract_first_request_id(log_rows)
    embed = render_report_embed(
        alarm_name=alarm_name,
        alarm_description=alarm_description,
        function_name=config.function_name,
        research_window_jst=research_window_jst,
        response=response,
        fallback_kind=fallback_kind,
        representative_request_id=representative_request_id,
        fire_timestamp_iso=fire_time_iso,
    )
    if webhook_url:
        webhook = DiscordWebhook(url=webhook_url)
        webhook.add_embed(embed)
        webhook.execute()
    else:
        logger.warning("webhook not registered", extra={"alarm_name": alarm_name})

    return {
        "ok": True,
        "alarm": alarm_name,
        "verdict": response["verdict"],
        "severity": response["severity"],
        "fallback": fallback_kind,
    }
```

既存の `_format_log_rows_pretty` は `src/utils/log_format.py` に移植して再利用 (本 SPEC スコープ外、清書のみ)。

### TASK-014: 新規アラーム追加デプロイ手順 (REQ-014)

> **原文対応**: 本 PLAN で新設 (原文には新規 alarm 追加手順について記述なし)。原文「3. リソースプロファイルのレジストリ化 (新しいアラーム種別が増えても、変更箇所はプロファイルへの追記と selector のマッピングだけで済み、システムプロンプトは不変のまま保てる)」の意図を運用手順として明文化する。本仕様の構成 (configs/ + profile + DISCORD_WEBHOOK_URLS の 3 層) に従って、新クライアント追加と既存クライアントの新アラーム追加の 2 ケースで手順を分岐する。

#### 全ケース共通手順

1. `configs/<正規化 alarm 名>.yaml` を新規作成し PR → merge (必須 9 フィールド)。
5. GitHub Actions secrets の `DISCORD_WEBHOOK_URLS` (JSON) に `"<正規化 alarm 名>": "<webhook URL>"` を追加。
6. Reporter Lambda を再ビルド・再デプロイ。

#### 新クライアント追加時の追加手順

2. クライアント S3 に `<PROFILE_FILE>` を手動配置:

   ```bash
   aws s3 cp profile.yaml \
     s3://<client-bucket>/<CONTEXT_PREFIX>/<PROFILE_FILE> \
     --profile <client-profile>
   ```

3. クライアント側 AssumeRole 対象 Role に追加:

   ```json
   {
     "Effect": "Allow",
     "Action": ["s3:GetObject"],
     "Resource": "arn:aws:s3:::<client-bucket>/<CONTEXT_PREFIX>/*"
   },
   {
     "Effect": "Allow",
     "Action": ["s3:ListBucket"],
     "Resource": "arn:aws:s3:::<client-bucket>",
     "Condition": { "StringLike": { "s3:prefix": "<CONTEXT_PREFIX>/*" } }
   }
   ```

4. バケット KMS CMK 暗号化時のみ。CMK 側に cross-account `kms:Decrypt` grant を追加。

5'. クライアント側 SNS Topic / CloudWatch Alarm 配線 (cross-account-architecture PLAN を踏襲)。

#### 既存クライアントの新アラーム追加時

手順 2〜4 をスキップ。

#### 不変条件 (両ケース共通)

- 運用 Lambda のコード / 実行 IAM Role / CI/CD パイプライン定義に変更を加えない (REQ-003 AC-003-2)
- 手順 1 / 5 / 6 は自社側作業、手順 2 / 3 / 4 はクライアント側作業

#### 失敗モード (片方欠落時)

- **手順 1 欠落**: `load_config()` が `ConfigNotFoundError` → REQ-008 (a) フォールバック
- **手順 5 欠落**: `resolve_webhook_url()` が None → CloudWatch Logs warning のみ (REQ-016 AC-016-3)

---

## 補足: 原文「実装タスク」を起点とした実装の進め方

原文の 8 項目を起点に、実装着手順序として推奨する流れ:

1. **基盤 (TASK-001 → TASK-004)**: profile スキーマ検証 + configs ディレクトリ + load_config を先に固める。これらは他 TASK の前提となる。
2. **取得経路 (TASK-002)**: profile 取得を AssumeRole + S3 GetObject で実装。IAM 変更依頼を運用チームに出す。
3. **コア解析 (TASK-005 → TASK-007 → TASK-008)**: signal_kind 解決 + fallback_generic + システムプロンプト + 応答正規化を実装。Bedrock とのつなぎ込みは TASK-013 でやる。
4. **周辺ユーティリティ (TASK-006, TASK-009, TASK-010)**: Insights クエリ生成 / Webhook 解決 / レポートレンダリングを並行で実装。
5. **データ移植 (TASK-011)**: HDW プロファイル YAML を作成し S3 に配置 (デプロイ前に運用 Lambda の S3 に置いておく)。
6. **整理 (TASK-012)**: 旧コード削除と env var 整理。
7. **統合 (TASK-013)**: src/main.py を新オーケストレーターに書き換え、全 TASK を統合。
8. **手順書 (TASK-014)**: 新規アラーム追加手順を本 PLAN に文書化 (実装完了後に確定可能)。

> **原文対応**: 上記の順序は原文「実装タスク」の 8 項目に直接対応していないが、依存関係を考慮した実装順として整理した。原文の項目 #3 (スキーマ) → #4 (HDW 登録) → #1, #2 (プロンプト) → #5 (出力 JSON) → #6 (レポート) → #7 (オーケストレーター) → #8 (フォールバック) の順は本 PLAN の TASK 順序 (TASK-001 → 011 → 007 → 008 → 010 → 013 → 005, 008 統合) におおむね対応する。
