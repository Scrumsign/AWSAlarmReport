---
id: client-email-notification
spec_version: 0.5.0
task_rev: 2
rev: 3
title: S3データ不着検知時のクライアントへのメール通知 — テスト項目
created_at: 2026-05-26
type: test
---

# S3データ不着検知時のクライアントへのメール通知 — テスト項目

- **SPEC**: client-email-notification@0.5.0
- **TASK rev**: 2
- **TEST rev**: 3

## 方針

- テストケースは TASK と 1:1 対応（TC-00N ↔ TASK-00N）
- 検証の起点は SPEC の AC であり、実装の内部詳細ではない
- 外部依存（SES API, Discord Webhook, ファイルシステム）は unit テストでは mock/stub する
- e2e・手動テストは実環境で一度だけ確認し、反復 CI に含めない

省略するもの:
- dataclass のフィールド名が宣言と一致すること（型システムが保証）
- 関数が非 None を返すこと
- YAML ファイルの構文正しさ（`yaml.safe_load` が例外なく完了すれば十分）

## テスト実行戦略

| フェーズ | 実行内容 | 頻度 |
|---|---|---|
| CI on PR | unit + static | PR 毎 |
| CI on merge | unit + static + integration | merge 毎 |
| 手動 | e2e（実環境） | デプロイ時 |

---

## TC-001: Message dataclass と Channel 基底クラス

- **TASK**: TASK-001
- **REQ**: REQ-002
- **type**: static + unit
- **重要度**: 中

**なぜ重要**: `Message` の frozen 制約と `Channel` の抽象インターフェースはすべてのチャネル実装の前提。破れると下流タスク全体に影響する。

```python
# static: mypy src/channels/message.py → エラーなし
# static: mypy src/channels/base.py    → エラーなし

def test_message_is_frozen():
    from dataclasses import FrozenInstanceError
    msg = Message(
        title="t", severity="HIGH", confidence="high", root_cause="r",
        actions=[], alarm_name="hdw-sakura", ship_name="sakura",
        timestamp=datetime(2026, 5, 26, tzinfo=timezone.utc),
    )
    with pytest.raises(FrozenInstanceError):
        msg.title = "x"
```

---

## TC-002: DiscordChannel の embed 構築と送信

- **TASK**: TASK-002
- **REQ**: REQ-002
- **type**: unit + static
- **重要度**: 高

**なぜ重要**: 既存 Discord 通知の継続性を保証する。main.py からの discord_webhook 依存が残っていないことも確認する。

```python
def make_discord_channel():
    # 実装時に environment_name / target_function_name が必須引数として追加された
    return DiscordChannel(
        webhook_url="https://example.com",
        environment_name="test",
        target_function_name="hdw-test-fn",
    )

def test_discord_channel_send_calls_webhook(mocker):
    mock_execute = mocker.patch("src.channels.discord.DiscordWebhook.execute")
    make_discord_channel().send(make_message(severity="HIGH"))
    mock_execute.assert_called_once()

def test_to_embed_color_by_severity():
    ch = make_discord_channel()
    for sev, color in DISCORD_SEVERITY_COLOR.items():
        embed = ch._to_embed(make_message(severity=sev))
        assert embed.color == color

def test_to_embed_title_contains_message_title():
    embed = make_discord_channel()._to_embed(make_message(title="テスト通知"))
    assert "テスト通知" in embed.title
```

```bash
# static: discord_webhook の直接使用が main.py に残っていないことを確認
# （_post_minimal_embed / _post_prompt_attachment は除く）
grep "DiscordWebhook\|DiscordEmbed" src/main.py   # → 0件
grep "DISCORD_SEVERITY_COLOR" src/main.py          # → 0件
```

---

## TC-003: error-profiles.yml 読み込みと _resolve_error_id の4分岐

- **TASK**: TASK-003
- **REQ**: REQ-005, REQ-007
- **type**: unit
- **重要度**: 高

**なぜ重要**: error_id の誤分類は誤った通知先・誤ったプロンプト注入につながる。4分岐と channels / description 両フィールドの存在をすべて検証する。

```python
def test_load_error_profiles_structure():
    profiles = _load_error_profiles()
    assert "s3_data_missing" in profiles
    entry = profiles["s3_data_missing"]
    assert "channels" in entry
    assert "description" in entry

def test_resolve_channel_ids_returns_channels():
    profiles = {"s3_data_missing": {"channels": ["discord", "email.dev"]}}
    result = _resolve_channel_ids("s3_data_missing", profiles)
    assert "email.dev" in result

def test_resolve_channel_ids_fallback_on_unknown(caplog):
    profiles = {}
    result = _resolve_channel_ids("nonexistent", profiles)
    assert result == ["discord"]
    assert caplog.records  # WARNING が出ていること

# _resolve_error_id: 4分岐
def test_resolve_error_id_empty_logs():
    assert _resolve_error_id("hdw-sakura", []) == "s3_data_missing"

def test_resolve_error_id_with_error_log():
    log_row = [{"field": "status", "value": "error"}]
    assert _resolve_error_id("hdw-sakura", [log_row]) == "lambda_failure"

def test_resolve_error_id_logs_without_error(caplog):
    log_row = [{"field": "status", "value": "success"}]
    result = _resolve_error_id("hdw-sakura", [log_row])
    assert result == "unknown"
    assert caplog.records  # WARNING が出ていること

def test_resolve_error_id_unknown_alarm(caplog):
    result = _resolve_error_id("other-system-alarm", [])
    assert result == "unknown_alarm"
    assert caplog.records  # WARNING が出ていること
```

---

## TC-004: resolve_addresses の境界条件

- **TASK**: TASK-004
- **REQ**: REQ-006
- **type**: unit
- **重要度**: 中

**なぜ重要**: アドレス解決の失敗は silent な送信スキップになる。group_id 不在の境界条件を明示的に検証する。

```python
def test_resolve_addresses_returns_add_list():
    # 実装時のグループ名は "scrumsign"
    entries = [{"id": "scrumsign", "add": ["kitamura@scrumsign.com", "t.kimura@scrumsign.com"]}]
    assert resolve_addresses("scrumsign", entries) == ["kitamura@scrumsign.com", "t.kimura@scrumsign.com"]

def test_resolve_addresses_missing_group_returns_empty(caplog):
    entries = [{"id": "scrumsign", "add": ["kitamura@scrumsign.com"]}]
    result = resolve_addresses("missing", entries)
    assert result == []
    assert caplog.records  # WARNING が出ていること
```

---

## TC-005: SESEmailChannel の SES API 呼び出し

- **TASK**: TASK-005
- **REQ**: REQ-001, REQ-002
- **type**: unit
- **重要度**: 高

**なぜ重要**: SES API への呼び出し引数の正確性（Source / ToAddresses）はクライアント通知の根幹。アドレスなし時の送信スキップも確認する。

```python
def test_ses_channel_id():
    ch = SESEmailChannel("dev")
    assert ch.id == "email.dev"

def test_ses_send_calls_send_email(mocker, monkeypatch):
    monkeypatch.setenv("SES_FROM_ADDRESS", "alerts@scrumsign.com")
    mocker.patch("src.channels.email.resolve_addresses", return_value=["a@x.com"])
    mock_client = mocker.patch("src.channels.email.boto3.client")
    SESEmailChannel("dev").send(make_message())
    call_kwargs = mock_client.return_value.send_email.call_args[1]
    assert call_kwargs["Source"] == "alerts@scrumsign.com"
    assert "a@x.com" in call_kwargs["Destination"]["ToAddresses"]

def test_ses_send_skips_when_no_addresses(mocker, caplog):
    mocker.patch("src.channels.email.resolve_addresses", return_value=[])
    mock_client = mocker.patch("src.channels.email.boto3.client")
    SESEmailChannel("missing").send(make_message())
    mock_client.return_value.send_email.assert_not_called()
    assert caplog.records  # WARNING が出ていること
```

---

## TC-006: HTML・プレーンテキストテンプレート

- **TASK**: TASK-006
- **REQ**: REQ-003, REQ-004
- **type**: unit
- **重要度**: 中

**なぜ重要**: クライアントが受け取るメールに必須フィールドが欠けていないことを確認する。HTML / Text 両方が SES リクエストに含まれることも検証する。

```python
def test_to_html_contains_required_fields():
    msg = make_message(
        ship_name="sakura", severity="HIGH",
        timestamp=datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc),
        actions=["アクション1", "アクション2"],
    )
    html = SESEmailChannel("dev")._to_html(msg)
    assert "sakura" in html
    assert "HIGH" in html
    assert "JST" in html
    assert "2026" in html
    assert "アクション1" in html
    assert "アクション2" in html

def test_to_plain_contains_required_fields():
    msg = make_message(
        ship_name="sakura", severity="LOW",
        timestamp=datetime(2026, 5, 26, 10, 0, tzinfo=timezone.utc),
        actions=["アクション1"],
    )
    plain = SESEmailChannel("dev")._to_plain(msg)
    assert "sakura" in plain
    assert "LOW" in plain
    assert "JST" in plain
    assert "アクション1" in plain

def test_send_email_has_html_and_text_body(mocker, monkeypatch):
    monkeypatch.setenv("SES_FROM_ADDRESS", "alerts@scrumsign.com")
    mocker.patch("src.channels.email.resolve_addresses", return_value=["a@x.com"])
    mock_client = mocker.patch("src.channels.email.boto3.client")
    SESEmailChannel("dev").send(make_message())
    body = mock_client.return_value.send_email.call_args[1]["Message"]["Body"]
    assert "Html" in body
    assert "Text" in body
```

---

## TC-007: _dispatch ルーティングアルゴリズムと main.py 統合

- **TASK**: TASK-007
- **REQ**: REQ-002, REQ-005, REQ-007
- **type**: integration + static
- **重要度**: 高

**なぜ重要**: ルーティング・フォールバック・例外継続はシステム全体の信頼性を左右する。チャネルをすべて mock して境界条件を網羅する。

#### static 確認

```bash
grep "no_logs" src/main.py            # → 0件（0件ログ早期 return の削除確認）
grep "Message(" src/main.py           # → ヒットあり
grep "_dispatch" src/main.py          # → ヒットあり
grep "_resolve_error_id" src/main.py  # → ヒットあり
```

#### ルーティング動作

```python
def test_dispatch_sends_to_all_registered_channels(mocker):
    mock_discord = mocker.MagicMock(spec=DiscordChannel)
    mock_email   = mocker.MagicMock(spec=SESEmailChannel)
    mocker.patch("src.main._load_error_profiles", return_value={
        "s3_data_missing": {"channels": ["discord", "email.dev"], "description": ""}
    })
    mocker.patch("src.main._build_channel_registry",
                 return_value={"discord": mock_discord, "email.dev": mock_email})
    _dispatch("hdw-sakura", make_message(), "s3_data_missing")
    mock_discord.send.assert_called_once()
    mock_email.send.assert_called_once()

def test_dispatch_fallback_discord_when_error_id_not_in_profiles(mocker, caplog):
    mock_discord = mocker.MagicMock(spec=DiscordChannel)
    mocker.patch("src.main._load_error_profiles", return_value={})
    mocker.patch("src.main._build_channel_registry", return_value={"discord": mock_discord})
    _dispatch("hdw-sakura", make_message(), "nonexistent_id")
    mock_discord.send.assert_called_once()
    assert caplog.records  # WARNING が出ていること

def test_dispatch_continues_after_channel_exception(mocker):
    mock_discord = mocker.MagicMock(spec=DiscordChannel)
    mock_email   = mocker.MagicMock(spec=SESEmailChannel)
    mock_email.send.side_effect = Exception("SES error")
    mocker.patch("src.main._load_error_profiles", return_value={
        "s3_data_missing": {"channels": ["email.dev", "discord"], "description": ""}
    })
    mocker.patch("src.main._build_channel_registry",
                 return_value={"discord": mock_discord, "email.dev": mock_email})
    _dispatch("hdw-sakura", make_message(), "s3_data_missing")
    mock_discord.send.assert_called_once()  # email 例外後も Discord は呼ばれる

def test_dispatch_does_not_raise_on_all_channel_failure(mocker):
    mock_ch = mocker.MagicMock()
    mock_ch.send.side_effect = Exception("fail")
    mocker.patch("src.main._load_error_profiles", return_value={
        "s3_data_missing": {"channels": ["discord", "email.dev"], "description": ""}
    })
    mocker.patch("src.main._build_channel_registry",
                 return_value={"discord": mock_ch, "email.dev": mock_ch})
    _dispatch("hdw-sakura", make_message(), "s3_data_missing")  # 例外なく完了

def test_unknown_channel_id_is_skipped_with_warning(mocker, caplog):
    mocker.patch("src.main._load_error_profiles", return_value={
        "s3_data_missing": {"channels": ["other_channel"], "description": ""}
    })
    mocker.patch("src.main._build_channel_registry", return_value={})
    _dispatch("hdw-sakura", make_message(), "s3_data_missing")
    assert caplog.records  # WARNING が出ていること
```

#### _build_channel_registry: email.* の解析

```python
def test_build_channel_registry_creates_ses_channel():
    registry = _build_channel_registry(["discord", "email.dev"])
    assert isinstance(registry.get("email.dev"), SESEmailChannel)
    assert registry["email.dev"]._group_id == "dev"

def test_build_channel_registry_skips_unknown_prefix():
    registry = _build_channel_registry(["unknown_channel"])
    assert registry.get("unknown_channel") is None
```

---

## TC-008: IAM ポリシーと SES セットアップ（手動確認）

- **TASK**: TASK-008
- **REQ**: REQ-001
- **type**: e2e（手動）
- **重要度**: 高

**なぜ重要**: IAM 権限不足と SES サンドボックスは unit テストでは検知できない。デプロイ前に必ず確認する。

| AC | 確認内容 | 状態 | 確認方法 |
|---|---|---|---|
| AC-001-1 | Lambda 実行ロールに `ses:SendEmail` / `ses:SendRawEmail` が付与されている | ✅ 完了 | `aws iam get-role-policy --role-name hdw-lambda-execution-role --policy-name SESendEmail` |
| AC-001-2 | `scrumsign.com` が SES Identity として登録されている | ✅ 完了 | `aws sesv2 get-email-identity --email-identity scrumsign.com` |
| AC-001-3 | DKIM CNAME レコード3件が DNS に登録されている | ❌ 保留 | `nslookup -type=CNAME j3ldawn4rjhlsvzybb3273ut23c2cyx4._domainkey.scrumsign.com` |
| AC-001-4 | SES サンドボックスが解除されており外部アドレスへ送信できる | 🔄 PENDING | SES コンソールの Account dashboard |
| AC-001-5 | 実際にテストメールが届く | ❌ 未実施（AC-001-3/4 完了後） | `aws sesv2 send-email --from-email-address <確定アドレス> --destination ToAddresses=<宛先> ...` |

---

## TC-009: Lambda コンテナイメージへの config ファイル包含

- **TASK**: TASK-009
- **REQ**: REQ-005, REQ-006
- **type**: static（Docker ビルド後確認）
- **重要度**: 中

**なぜ重要**: config ファイルがイメージに含まれなければ Lambda 起動時に `FileNotFoundError` で落ちる。

```bash
docker run --rm <image> ls /var/task/config/
# → error-profiles.yml と email.yaml が含まれること

docker run --rm <image> python -c \
  "import yaml; yaml.safe_load(open('/var/task/config/error-profiles.yml'))"
# → 正常終了すること

docker run --rm <image> python -c \
  "import yaml; yaml.safe_load(open('/var/task/config/email.yaml'))"
# → 正常終了すること
```
