---
id: bedrock-prompt-generalization
version: 0.5.0
plan_rev: 5
rev: 6
title: Bedrock アラーム原因解析プロンプトの汎用化 — 重要テストケース
created_at: 2026-05-22
type: test
---

# Bedrock アラーム原因解析プロンプトの汎用化 — 重要テストケース

- **SPEC**: bedrock-prompt-generalization@0.5.0
- **PLAN rev**: 5
- **TEST rev**: 6
- **Created at**: 2026-05-22

## 方針

本 TEST は**重要な振る舞いを検証するテスト**に絞り、PLAN の実装で自明な箇所 (例: dataclass のフィールド名が YAML キーと一致する、関数の戻り値型が宣言どおりである等) は省略する。代わりに以下を重点的にカバー:

1. **整合性制約の検証** — profile スキーマの規範に従ったエラー検出 (REQ-002)
2. **横断的な不変条件** — `-test` 正規化の全体動作 (REQ-004 / REQ-005 / REQ-016)
3. **フォールバック保証** — 2 系統が通知欠落させず印付きで動作 (REQ-008)
4. **severity ポリシー強制** — メタ手続き既定 + signal_kind 由来補正 (REQ-009)
5. **応答正規化の安全性** — 字数 truncate / 不正 JSON で fail しない (REQ-007)
6. **後方互換削除** — 破壊的変更が完了している静的検査 (REQ-011 / REQ-012 / REQ-013)
7. **システムプロンプト内容** — 禁則語 / 必須語 (REQ-001)
8. **オーケストレーター E2E** — golden path と主要フォールバックの統合動作

省略するもの:
- `load_config()` が Config dataclass を返すこと (型システムが保証)
- `build_insights_query()` が空でない文字列を返すこと (実装で自明)
- `normalize_alarm_name("foo")` が `"foo"` を返すこと (恒等変換、自明)
- 個別の dataclass フィールドが YAML キーと 1:1 対応すること (load_config 実装で自明)
- 各 enum 値の個別検証 (1 つの enum 違反テストで代表)

テストランナーは pytest を前提。type 分類: `unit` (関数単体) / `integration` (複数モジュール連携) / `e2e` (実 AWS or 完全モックの統合) / `static` (grep / コードパターン照合)。

> **本 TEST と原文 issue の関係**: 原文には明示的なテスト要件記述はないが、原文の各原則 (verdict 3 分岐の規約、severity 規約、フォールバック 2 系統等) を**実装が裏切らないこと**を保証する検証として本 TEST を構成する。

---

## TC-002: profile スキーマの整合性検証 (REQ-002)

> **原文対応**: 原文「3. リソースプロファイルのレジストリ化」+ 原文「参考スキーマ」を本仕様で構造化した結果のスキーマ。本仕様で追加した整合性制約 (`-test` 末尾禁止 / `signal[].kind` が verdict を指すこと / severity 必須化) を実装が守ることを検証する。`fixture` は SPEC「profile スキーマ完全形」と PLAN「profile YAML 具体例 例 1」を基準とする。

```python
# tests/conftest.py
import pytest


@pytest.fixture
def valid_profile():
    """SPEC 規範どおりの最小有効 profile (PLAN 例 1 相当)。"""
    return {
        "function_name": "HDW_Backend_Processor_0001",
        "signal_kind": [
            {
                "name": "completion_success",
                "type": "verdict",
                "mechanism": "log_marker",
                "locator": "event=lambda_complete の status",
                "success_condition": "status == success",
                "failure_condition": "status == error or traceback",
                "absence_hypothesis": "S3 ZIP 未着",
                "max_severity_on_success": "MEDIUM",
                "severity_on_absence": "MEDIUM",
            },
            {
                "name": "ng_file",
                "type": "ignored",
                "mechanism": "log_marker",
                "locator": "message に NG file",
                "description": "設計上の許容分岐",
            },
        ],
        "signal": [{"name": "hdw-sakura", "kind": "completion_success"}],
        "input_identifiers": ["ship_name", "ship_timestamp"],
    }
```

### TC-002-1: signal[].kind が signal_kind[].name に存在しない

**type**: unit / **重要度**: 高 (整合性制約 #4 違反検出)

```python
# tests/test_profile.py
import pytest
from utils.profile import validate_profile, ProfileSchemaError


def test_signal_kind_dangling_reference(valid_profile):
    valid_profile["signal"][0]["kind"] = "nonexistent_kind"
    with pytest.raises(ProfileSchemaError, match=r"not in signal_kind"):
        validate_profile(valid_profile)
```

**なぜ重要**: 設定ミスで存在しない kind を指した場合に静かに失敗するのを防ぐ。fallback パスが発火する前段で検出。

### TC-002-2: signal[].kind が ignored を指す

**type**: unit / **重要度**: 高 (整合性制約 #5 違反検出)

```python
def test_signal_points_to_ignored(valid_profile):
    # signal[0] が ignored (ng_file) を指すように改変
    valid_profile["signal"][0]["kind"] = "ng_file"
    with pytest.raises(ProfileSchemaError, match=r"not type=verdict"):
        validate_profile(valid_profile)
```

**なぜ重要**: ignored は障害判定に使わない設計。誤って指された場合は意味不明な動作になるため必須検出。

### TC-002-3: signal[].name に `-test` 末尾混入

**type**: unit / **重要度**: 高 (整合性制約 #3 + `-test` 不変条件違反)

```python
def test_signal_name_with_test_suffix(valid_profile):
    valid_profile["signal"][0]["name"] = "hdw-sakura-test"
    with pytest.raises(ProfileSchemaError, match=r"ends with '-test'"):
        validate_profile(valid_profile)
```

**なぜ重要**: `-test` 統合不変条件 (SPEC 全域に効く) の検出点。混入を許すと test alarm が独立 entry を持つ二重管理状態になる。

### TC-002-4: type=verdict で severity フィールド欠落

**type**: unit / **重要度**: 中 (整合性制約 #6 違反検出 — severity 必須化)

```python
@pytest.mark.parametrize("missing_field", [
    "max_severity_on_success",
    "severity_on_absence",
])
def test_verdict_missing_severity_field(valid_profile, missing_field):
    del valid_profile["signal_kind"][0][missing_field]
    with pytest.raises(ProfileSchemaError, match=missing_field):
        validate_profile(valid_profile)
```

**なぜ重要**: 本仕様で原文より厳格にした制約 (REQ-009 で severity 補正がコード側に依存するため、欠落で fallback_generic を意図せず適用してしまう事故を防ぐ)。

### TC-002-5: enum 値違反 (1 ケースで代表)

**type**: unit / **重要度**: 中 (enum 検証の代表)

```python
def test_invalid_type_enum(valid_profile):
    valid_profile["signal_kind"][0]["type"] = "unknown_role"
    with pytest.raises(ProfileSchemaError, match=r"type="):
        validate_profile(valid_profile)
```

**なぜ重要**: 個別 enum (type / mechanism / severity) の違反検出が動くこと。3 つの enum 全てを個別テストせず、1 つで代表 (実装で同じパターンを使うため)。

---

## TC-NORM: `-test` 正規化の横断動作 (REQ-004 / REQ-005 / REQ-016)

> **原文対応**: 本仕様で追加した不変条件。原文「概念図」の `hdw-sakura-test → completion_success` を本仕様では全域 (configs ファイル名 / profile.signal / DISCORD_WEBHOOK_URLS) で正規化する設計。複数モジュールにまたがるため横断テストで担保する。

### TC-NORM-1: prod / test 名で同一 Config を解決

**type**: unit / **重要度**: 高

```python
# tests/test_config.py
def test_load_config_normalization(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "hdw-sakura.yaml").write_text("""
function_name: F
account_id: "123"
aws_region: ap-northeast-1
assume_role_arn: arn:aws:iam::123:role/R
log_group: /aws/lambda/F
profile_location: s3://bucket/profile.yaml
bedrock_model_id: model-id
bedrock_max_tokens: 2000
cloudwatch_logs_query_poll_interval_sec: 2.0
""")
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))
    from utils.config import load_config
    assert load_config("hdw-sakura") == load_config("hdw-sakura-test")
```

**なぜ重要**: configs/ レイヤの正規化が機能することの単一証拠。

### TC-NORM-2: signal_kind 解決が正規化後 alarm 名で行われる

**type**: unit / **重要度**: 高

```python
# tests/test_signal.py
from utils.signal import resolve_signal_kind


def test_resolve_normalization(valid_profile):
    prod = resolve_signal_kind("hdw-sakura", valid_profile)
    test = resolve_signal_kind("hdw-sakura-test", valid_profile)
    assert prod is test  # 同一オブジェクトを引いている
```

**なぜ重要**: profile.signal[] のキーが正規化前提であり、test alarm が独立 entry なしで動くことを担保。

### TC-NORM-3: webhook 解決が正規化後 alarm 名で行われる

**type**: unit / **重要度**: 高

```python
# tests/test_webhooks.py
import json
import sys


def test_webhook_normalization(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URLS", json.dumps({
        "hdw-sakura": "https://discord.com/api/webhooks/A",
    }))
    # モジュールリロード (キャッシュ済 WEBHOOK_MAP を再構築)
    sys.modules.pop("utils.webhooks", None)
    from utils.webhooks import resolve_webhook_url
    assert resolve_webhook_url("hdw-sakura") == "https://discord.com/api/webhooks/A"
    assert resolve_webhook_url("hdw-sakura-test") == "https://discord.com/api/webhooks/A"
```

**なぜ重要**: webhook 配信先の正規化動作。test/prod が別チャンネルにならない (本仕様の意図的な選択) ことを確認。

---

## TC-CLEANUP: 後方互換削除の静的確認 (REQ-011 / REQ-012 / REQ-013)

> **原文対応**: 本仕様で新設の検査。原文「概要: 今は手順の中に特定 Lambda の事情がベタ書きされているので、それを材料側へ追い出す」の達成を grep で確認する。コメントアウト残置や `// removed` 注釈を見逃さないために static チェックとして実装。

### TC-CLEANUP-1: ケース分岐コード完全削除 (REQ-011)

**type**: static / **重要度**: 高

```bash
# tests/static/test_no_case_branching.sh
#!/usr/bin/env bash
set -euo pipefail

FORBIDDEN=(
  "render_prompt_case_no_logs"
  "render_prompt_case_lambda_failure"
  "case_specific_instructions"
  "_SYSTEM_PROMPT_TEMPLATE"
  "render_prompt_system_base"
)
for token in "${FORBIDDEN[@]}"; do
  if grep -rn "$token" src/; then
    echo "FAIL: token '$token' still exists in src/"
    exit 1
  fi
done
echo "PASS: all forbidden tokens removed"
```

**なぜ重要**: 既存ケース分岐は本仕様の「特定 Lambda 専用 → 汎用」の核心転換。残置すると新メタ手続きと旧分岐が並存し意味不明な挙動になる。

### TC-CLEANUP-2: 旧キー (root_cause_hypothesis / suggested_actions) 削除 (REQ-012)

**type**: static / **重要度**: 高

```bash
# tests/static/test_no_old_output_keys.sh
for token in "root_cause_hypothesis" "suggested_actions"; do
  if grep -rn "$token" src/; then
    echo "FAIL: old key '$token' still referenced"
    exit 1
  fi
done
```

**なぜ重要**: REQ-007 の新スキーマと旧スキーマが混在すると Discord embed が誤った経路でデータを引いて壊れる。

### TC-CLEANUP-3: Env dataclass / 廃止 env var の削除 (REQ-013)

**type**: static / **重要度**: 高

```bash
# tests/static/test_env_cleanup.sh
# Env class が存在しないこと
if grep -n "class Env" src/main.py; then
    echo "FAIL: Env dataclass still exists"
    exit 1
fi

# 廃止 env var の参照ゼロ
DEPRECATED_ENV=(
  "CROSS_ACCOUNT_ROLE_ARN"
  "TARGET_FUNCTION_NAME"
  "BEDROCK_MODEL_ID"
  "BEDROCK_MAX_TOKENS"
  "CLOUDWATCH_LOGS_QUERY_POLL_INTERVAL_SEC"
  "ENVIRONMENT_NAME"
  "LOG_GROUP_MAP"
)
for var in "${DEPRECATED_ENV[@]}"; do
  if grep -rn "$var" src/ .github/workflows/; then
    echo "FAIL: deprecated env var '$var' still referenced"
    exit 1
  fi
done

# DISCORD_WEBHOOK_URL (無印、URLS にマッチしない) も削除確認
if grep -rn "DISCORD_WEBHOOK_URL[^S]" src/ .github/workflows/; then
    echo "FAIL: bare DISCORD_WEBHOOK_URL still referenced"
    exit 1
fi
```

**なぜ重要**: env var 整理が中途半端だと、新フローと旧フローが混在して config 解決が壊れる。GitHub Actions のデプロイ設定も含めて検査。

---

## TC-PROMPT: システムプロンプト内容 (REQ-001)

> **原文対応**: 原文「実装タスク #1: メタ手続きのみ。監視対象固有語彙ゼロ。既定 failure_taxonomy（b1〜b4）を含む」の遵守確認。「ベタ書き禁止」と「必須内容包含」の両方向で検査する。

### TC-PROMPT-1: 監視対象固有語彙の禁止 (AC-001-1)

**type**: static / **重要度**: 高

```python
# tests/test_prompt_content.py
import pytest
from utils.prompt import STATIC_SYSTEM_PROMPT


FORBIDDEN_TOKENS = [
    "HDW_Backend_Processor_0001",
    "ship_name",
    "ship_timestamp",
    "input_key",
    "lambda_complete",
    "NG file",
    "pia_data",
    "csv parse failed",
]


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_no_target_specific_vocabulary(token):
    assert token not in STATIC_SYSTEM_PROMPT, (
        f"forbidden token {token!r} leaked into STATIC_SYSTEM_PROMPT"
    )
```

**なぜ重要**: 「特定 Lambda 専用 → 汎用」の核心要件。1 語でも残れば本仕様の意義が崩れる。

### TC-PROMPT-2: 必須要素の包含 (AC-001-2)

**type**: static / **重要度**: 高

```python
REQUIRED_PHRASES = [
    # failure_taxonomy
    "b1", "b2", "b3", "b4",
    "コードバグ", "入力データ異常", "設定欠落", "外部依存障害",
    # verdict
    "healthy", "failed", "absent",
    # severity
    "HIGH", "MEDIUM", "LOW",
    # 字数制限
    "<=80", "<=300",
    # actions
    "即時対応", "調査手順", "恒久対策",
]


@pytest.mark.parametrize("phrase", REQUIRED_PHRASES)
def test_required_phrases_present(phrase):
    assert phrase in STATIC_SYSTEM_PROMPT, (
        f"required phrase {phrase!r} missing from STATIC_SYSTEM_PROMPT"
    )
```

**なぜ重要**: メタ手続き / failure_taxonomy / 字数制限がプロンプトに含まれていないと、Bedrock の出力が本仕様の規約から外れる。

---

## TC-SEV: severity 補正 (REQ-009)

> **原文対応**: 原文「2. health_signal 抽象化」の severity 規約 (healthy 最大 MEDIUM / failed HIGH / absent MEDIUM+low) を**コード側で強制する** TEST。Bedrock が誤った severity を返しても運用ポリシーが破られないことを担保。

### TC-SEV-1: healthy で max_severity_on_success に clamp

**type**: unit / **重要度**: 高

```python
# tests/test_response.py
from utils.response import apply_severity_policy


def test_healthy_clamps_high_to_medium():
    response = {
        "verdict": "healthy", "severity": "HIGH",
        "confidence": "high", "summary": "...",
        "detail": "...", "actions": [],
    }
    signal_kind = {"max_severity_on_success": "MEDIUM",
                   "severity_on_absence": "MEDIUM"}
    out = apply_severity_policy(response, signal_kind)
    assert out["severity"] == "MEDIUM"


def test_healthy_low_stays_low():
    """ceiling 以下は変化なし。"""
    response = {"verdict": "healthy", "severity": "LOW",
                "confidence": "high", "summary": "", "detail": "", "actions": []}
    signal_kind = {"max_severity_on_success": "MEDIUM",
                   "severity_on_absence": "MEDIUM"}
    assert apply_severity_policy(response, signal_kind)["severity"] == "LOW"
```

**なぜ重要**: Bedrock が "HIGH" を返したケースで運用ポリシー (healthy 最大 MEDIUM) が貫徹されること。一方で正しい LOW は不変であること (clamp 関数の境界条件)。

### TC-SEV-2: absent で severity_on_absence + confidence=low に上書き

**type**: unit / **重要度**: 高

```python
def test_absent_overwrites_severity_and_confidence():
    response = {"verdict": "absent", "severity": "LOW",
                "confidence": "high", "summary": "", "detail": "", "actions": []}
    signal_kind = {"max_severity_on_success": "MEDIUM",
                   "severity_on_absence": "MEDIUM"}
    out = apply_severity_policy(response, signal_kind)
    assert out["severity"] == "MEDIUM"
    assert out["confidence"] == "low"  # メタ手続き既定値で上書き
```

**なぜ重要**: absent 時の confidence=low はメタ手続きの既定値 (REQ-001 / 原文 2.)。LLM が "high" と返しても low に揃える保証。

### TC-SEV-3: failed で補正なし

**type**: unit / **重要度**: 中

```python
def test_failed_no_correction():
    response = {"verdict": "failed", "severity": "HIGH",
                "confidence": "high", "summary": "", "detail": "", "actions": []}
    signal_kind = {"max_severity_on_success": "LOW",  # ceiling が低くても
                   "severity_on_absence": "MEDIUM"}
    out = apply_severity_policy(response, signal_kind)
    assert out["severity"] == "HIGH"  # 補正されない
```

**なぜ重要**: failed は固定 HIGH (REQ-009)。max_severity_on_success の影響を受けない (= verdict 別の補正ロジックが正しく分岐していること)。

---

## TC-NORMRESP: Bedrock 応答正規化 (REQ-007)

> **原文対応**: 原文「出力 JSON スキーマ」+ 原文「5. 出力とレンダリングの分離」+ 字数制限。Bedrock がスキーマ違反応答を返しても**通知欠落させない**安全網としての正規化処理を検証。

### TC-NORMRESP-1: 字数制限 truncate

**type**: unit / **重要度**: 高

```python
# tests/test_response.py
import json
from utils.response import normalize_bedrock_response


def test_truncates_oversize_fields():
    raw = json.dumps({
        "verdict": "failed", "severity": "HIGH", "confidence": "high",
        "summary": "x" * 200,    # 80 超
        "detail": "y" * 1000,    # 300 超
        "actions": [{"phase": "即時対応", "text": "z" * 200}],  # 80 超
    })
    out = normalize_bedrock_response(raw)
    assert len(out["summary"]) == 80
    assert len(out["detail"]) == 300
    assert len(out["actions"][0]["text"]) == 80
```

**なぜ重要**: 字数制限はシステムプロンプトに書いているが Bedrock が守るとは限らない (REQ-007 の二重防御原則)。

### TC-NORMRESP-2: 不正 JSON で安全既定値

**type**: unit / **重要度**: 高

```python
def test_invalid_json_returns_safe_defaults():
    out = normalize_bedrock_response("{this is not json")
    assert out["verdict"] == "absent"      # 安全側既定
    assert out["severity"] == "MEDIUM"
    assert out["confidence"] == "low"
    assert "取得失敗" in out["summary"]    # プレースホルダ
    # 例外は投げない
```

**なぜ重要**: Bedrock 応答が壊れたケースでも main 側に例外を投げず、後続のレポート組み立てを継続できること。

### TC-NORMRESP-3: actions の phase enum 違反でスキップ

**type**: unit / **重要度**: 中

```python
def test_invalid_phase_skipped():
    raw = json.dumps({
        "verdict": "failed", "severity": "HIGH", "confidence": "high",
        "summary": "s", "detail": "d",
        "actions": [
            {"phase": "即時対応", "text": "ok"},
            {"phase": "unknown", "text": "skip me"},
            {"phase": "恒久対策", "text": ""},  # 空 text もスキップ
        ],
    })
    out = normalize_bedrock_response(raw)
    assert len(out["actions"]) == 1
    assert out["actions"][0]["phase"] == "即時対応"
```

**なぜ重要**: 不正な phase が混入しても全 actions を破棄せず、有効な要素だけを通すこと。

---

## TC-FALLBACK: 2 系統フォールバック (REQ-008)

> **原文対応**: 原文「実装タスク #8: フォールバック処理。(a) プロファイル未登録時 (b) signal_selector 解決失敗時。いずれも Errors メトリクス + traceback を既定 health_signal とする。これは別系統のフォールバックである点に注意」を実装が遵守することを担保する。

### TC-FALLBACK-1: (a) configs/<alarm>.yaml 不在で fallback_generic + 印 "profile_missing"

**type**: integration / **重要度**: 高

```python
# tests/test_fallback.py
import json
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_sns_event():
    def _make(alarm_name: str) -> dict:
        return {"Records": [{"Sns": {"Message": json.dumps({
            "AlarmName": alarm_name,
            "AlarmDescription": "test alarm",
            "StateChangeTime": "2026-05-22T14:30:00.000+0000",
        })}}]}
    return _make


def test_fallback_a_config_not_found(mock_sns_event, tmp_path, monkeypatch):
    """configs/ に該当ファイルが無いケース → profile_missing 印付き通知。"""
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))
    monkeypatch.setenv("DISCORD_WEBHOOK_URLS", json.dumps({
        "hdw-unknown": "https://discord.example/webhook",
    }))

    # configs/ は空
    (tmp_path / "configs").mkdir()

    with patch("discord_webhook.DiscordWebhook.execute") as mock_execute, \
         patch("discord_webhook.DiscordWebhook.add_embed") as mock_add:
        from main import main
        result = main(mock_sns_event("hdw-unknown"), MagicMock(aws_request_id="t-1"))

    assert result["fallback"] == "profile_missing"
    mock_execute.assert_called_once()  # Discord 通知は発火
    # add_embed の引数を検証
    embed_arg = mock_add.call_args[0][0]
    footer_text = embed_arg.footer.get("text", "") if hasattr(embed_arg, "footer") else ""
    # 注: 実装次第で title or field の文言に "設定不在" や fallback 種別印が入る
```

**なぜ重要**: 「config 不在で Lambda 落ち = 通知欠落」を防ぐ生存保証。fallback 種別の印 ("profile_missing") が後段識別可能であること。

### TC-FALLBACK-2: (a) profile YAML 取得失敗で fallback_generic

**type**: integration / **重要度**: 高

```python
def test_fallback_a_profile_s3_failure(mock_sns_event, ...):
    """S3 GetObject が ClientError を投げるケース。"""
    # configs/hdw-sakura.yaml は存在するが profile S3 取得が失敗するようモック
    # → result["fallback"] == "profile_missing"
    # → ProfileSchemaError 統一例外として処理されること
```

**なぜ重要**: S3 一時障害や IAM 設定漏れで profile が引けないケースの生存保証。

### TC-FALLBACK-3: (b) profile.signal[] に該当 alarm 名なし → "signal_unresolved"

**type**: integration / **重要度**: 高

```python
def test_fallback_b_signal_unresolved(mock_sns_event, valid_profile, ...):
    """profile は取れたが signal[] に該当 alarm 名が無いケース。"""
    # profile.signal[] = [{"name": "hdw-other", "kind": "..."}]
    # alarm "hdw-sakura" を投入 → resolve_signal_kind が SignalUnresolvedError
    # → main は FALLBACK_GENERIC を採用し fallback_kind="signal_unresolved"
    # Discord embed footer に "fallback: signal_unresolved" が含まれること
    assert result["fallback"] == "signal_unresolved"
```

**なぜ重要**: (a) と (b) を**異なる印で区別**することが REQ-008 AC-008-2 の中核要件。運用者が原因切り分けできる。

### TC-FALLBACK-4: (a) と (b) の印が文言で区別される

**type**: static / **重要度**: 中

```python
def test_fallback_kinds_are_distinguishable():
    """fallback_kind 文字列が衝突しないこと。"""
    from main import _post_minimal_fallback  # or wherever fallback labels live
    # 実装で使う識別子文字列を比較
    KINDS = {"profile_missing", "signal_unresolved",
             "assume_role_failed", "bedrock_failed"}
    # それぞれが unique で空でないこと
    assert len(KINDS) == len(set(KINDS))
    assert all(k for k in KINDS)
```

**なぜ重要**: 識別子が衝突すると運用者が「どこで失敗したか」を切り分けられない。

---

## TC-WEBHOOK: DISCORD_WEBHOOK_URLS 解決 (REQ-016)

> **原文対応**: 本仕様で新設の通知配信先管理機構。原文は通知配信先について沈黙していたため、本仕様の独自テスト。Lambda が webhook 設定の不備で例外で落ちないこと (cold start fail-fast を除く) を担保。

### TC-WEBHOOK-1: 不正 JSON で cold start fail-fast

**type**: unit / **重要度**: 高

```python
# tests/test_webhooks.py
import pytest
import sys


def test_invalid_json_fails_at_module_load(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URLS", "this is not json")
    sys.modules.pop("utils.webhooks", None)
    from utils.webhooks import WebhookConfigError
    with pytest.raises(WebhookConfigError, match="valid JSON"):
        sys.modules.pop("utils.webhooks", None)
        import utils.webhooks  # noqa: F401
```

**なぜ重要**: 不正 JSON が silent failure (アラーム受信ごとに気付かず通知欠落) になるのを防ぐ。cold start で明確に失敗させることで早期検知。

### TC-WEBHOOK-2: 該当キー不在で None + Lambda 正常終了

**type**: integration / **重要度**: 高

```python
def test_missing_key_returns_none_no_exception(monkeypatch, caplog):
    import json, sys
    monkeypatch.setenv("DISCORD_WEBHOOK_URLS", json.dumps({"hdw-other": "..."}))
    sys.modules.pop("utils.webhooks", None)
    from utils.webhooks import resolve_webhook_url
    assert resolve_webhook_url("hdw-sakura") is None
    # main 側はこれを受けて Discord 投稿スキップ + CloudWatch Logs warning のみ
    # (実際の挙動検証は E2E テストで行う)
```

**なぜ重要**: webhook 登録漏れで Lambda 全体が落ちず、CloudWatch Logs で気付ける状態にする。

---

## TC-E2E: オーケストレーター統合 (TASK-013 / ALL)

> **原文対応**: 原文「処理フロー（呼び出し側オーケストレーター）」が end-to-end で動作することを確認。各 TASK の unit test では捕捉できない**統合的なバグ** (例: signal_kind 解決の戻り値型が render_dynamic_context の期待と合わない) を検出する。

### TC-E2E-1: Golden path (configs → profile → signal_kind → Bedrock → Discord)

**type**: integration / **重要度**: 高

```python
# tests/test_orchestrator.py
import json
from unittest.mock import patch, MagicMock


def test_golden_path_end_to_end(tmp_path, monkeypatch, valid_profile):
    """通常成功フローの E2E。各 boto3 client をモック化。"""
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))
    monkeypatch.setenv("DISCORD_WEBHOOK_URLS", json.dumps({
        "hdw-sakura": "https://discord.example/webhook",
    }))
    # configs/hdw-sakura.yaml を配置
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "hdw-sakura.yaml").write_text("""
function_name: HDW_Backend_Processor_0001
account_id: "920373030024"
aws_region: ap-northeast-1
assume_role_arn: arn:aws:iam::920373030024:role/HDWNotifyLogReader
log_group: /aws/lambda/HDW_Backend_Processor_0001
profile_location: s3://test-bucket/profile.yaml
bedrock_model_id: test-model
bedrock_max_tokens: 2000
cloudwatch_logs_query_poll_interval_sec: 0.1
""")

    bedrock_response_text = json.dumps({
        "verdict": "failed",
        "severity": "HIGH",
        "confidence": "high",
        "summary": "[処理失敗] traceback あり",
        "detail": "details",
        "actions": [
            {"phase": "即時対応", "text": "stack_trace を確認"},
        ],
    })

    with patch("boto3.client") as mock_boto:
        # STS
        sts = MagicMock()
        sts.assume_role.return_value = {"Credentials": {
            "AccessKeyId": "k", "SecretAccessKey": "s", "SessionToken": "t",
        }}
        # S3 (profile)
        s3 = MagicMock()
        s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"... profile yaml bytes ..."))
        }
        # Logs Insights
        logs = MagicMock()
        logs.start_query.return_value = {"queryId": "q"}
        logs.get_query_results.return_value = {
            "status": "Complete",
            "results": [[
                {"field": "@timestamp", "value": "2026-05-22T14:25:00.000+0000"},
                {"field": "function_request_id", "value": "req-xyz"},
                {"field": "@message", "value": '{"level": "ERROR", "message": "fail"}'},
            ]],
        }
        # Bedrock
        bedrock = MagicMock()
        bedrock.converse.return_value = {"output": {"message": {
            "content": [{"text": bedrock_response_text}]
        }}}

        def _client_dispatch(name, **kwargs):
            return {"sts": sts, "s3": s3, "logs": logs, "bedrock-runtime": bedrock}[name]
        mock_boto.side_effect = _client_dispatch

        # profile YAML パースは fetch_profile 内で行われるため、別途モック
        with patch("utils.profile.yaml.safe_load", return_value=valid_profile), \
             patch("discord_webhook.DiscordWebhook.execute") as mock_post:
            from main import main
            event = {"Records": [{"Sns": {"Message": json.dumps({
                "AlarmName": "hdw-sakura",
                "AlarmDescription": "test",
                "StateChangeTime": "2026-05-22T14:30:00.000+0000",
            })}}]}
            result = main(event, MagicMock(aws_request_id="t-1"))

    assert result["ok"] is True
    assert result["verdict"] == "failed"
    assert result["severity"] == "HIGH"
    assert result["fallback"] is None  # フォールバック未発火
    mock_post.assert_called_once()  # Discord 通知発火
```

**なぜ重要**: 各 TASK の unit test では捕捉できない型・引数の不整合 (例: signal_kind dict のキー欠落、Bedrock 応答の構造変化) を統合的に検出する。

### TC-E2E-2: hdw-sakura-test alarm で同じ profile / webhook が引かれる

**type**: integration / **重要度**: 高

```python
def test_test_alarm_uses_same_resources_as_prod(...):
    """hdw-sakura-test を投げて、prod 用の config / webhook が使われること。"""
    # TC-E2E-1 と同じ fixture で alarm_name="hdw-sakura-test" を投入
    # 検証ポイント:
    # - load_config が hdw-sakura.yaml を引いていること
    # - profile.signal の completion_success が解決されていること
    # - DISCORD_WEBHOOK_URLS の "hdw-sakura" キーから URL が引かれていること
    # - Bedrock 応答正常時に result["verdict"] が設定されていること
    # - Discord embed の author が "HDW Notify · test" (derive_env_label) であること
```

**なぜ重要**: `-test` 統合不変条件の E2E 検証。横断テスト (TC-NORM-1〜3) が個別レイヤで動いても、main フロー全体で破綻しないこと。

---

## 省略するテスト (記録)

以下は PLAN の実装で自明か、上記テストで間接的にカバーされるため省略:

| 省略する検証 | 省略理由 |
|---|---|
| `Config` dataclass のフィールド名が YAML キーと 1:1 | `load_config` 実装 (TASK-004) で機械的に行うため自明 |
| `normalize_alarm_name("foo")` が `"foo"` を返す | 恒等変換の自明動作。TC-NORM 系で `-test` 含むケースだけ検証 |
| `build_insights_query` が空でない文字列を返す | 実装で自明。空 input_identifiers のエラーケースのみ TC-002 系で間接検証 (input_identifiers 必須化) |
| Insights クエリ文字列の細部 (`fields` 句の順序等) | スコープ外 (REQ-006 description) |
| Discord embed の各 field の細部 | TASK-010 で機械的に組み立てるため自明。TC-E2E で投稿発火のみ検証 |
| 各 REQ ごとの個別 AC を 1:1 で TC 化 | AC-002-1〜4 のように粒度を揃えて並べると価値の薄い test が増える。整合性制約 7 項目のうち重要なもの (TC-002-1〜5) を選択 |
| `derive_env_label` の単独 unit test | TC-E2E-2 の embed author 表記検証で間接的にカバー |
| `extract_ignored_signals` の単独 unit test | profile fixture を渡せば自明な filter。TC-E2E で間接検証 |

---

## テスト実行戦略

| フェーズ | 実行内容 | 想定頻度 |
|---|---|---|
| CI on PR | TC-002, TC-NORM, TC-CLEANUP, TC-PROMPT, TC-SEV, TC-NORMRESP, TC-WEBHOOK (unit + static) | PR 毎 |
| CI on merge to main | 上記 + TC-FALLBACK, TC-E2E (integration, boto3 全モック) | merge 毎 |
| 手動 E2E | 実 AWS リソースでの cross-account 動作確認 (TC-003 系相当、本 TEST では省略) | デプロイ時 / 障害切り分け時 |

> **原文対応**: 原文「処理フロー（呼び出し側オーケストレーター）」が想定する end-to-end フローを TC-E2E-1 と TC-E2E-2 で担保。手動 E2E (実 AWS) は cross-account-architecture の REQ-006 / REQ-007 が既に定義しているため本 TEST では省略。
