---
id: client-email-notification
spec_version: 0.5.0
rev: 2
title: S3データ不着検知時のクライアントへのメール通知 — 実装タスク
created_at: 2026-05-26
type: task
---

# S3データ不着検知時のクライアントへのメール通知 — 実装タスク

- **SPEC**: client-email-notification@0.5.0
- **rev**: 2

## 実装順序（依存関係）

```
TASK-001（Message / Channel 基底）
  ├─→ TASK-002（DiscordChannel）──────────────────────────────┐
  ├─→ TASK-003（error-profiles.yml + 読み込み + _resolve_error_id）┤
  └─→ TASK-004（email.yaml + resolve_addresses）               │
         └─→ TASK-005（SESEmailChannel 骨格）──────────────────┤
                  └─→ TASK-006（HTML テンプレート）             │
                                                              ▼
                              TASK-007（_dispatch + main.py 統合）
TASK-003, TASK-004 ──→ TASK-009（デプロイ設定）
TASK-008（SES / IAM セットアップ）: 並列実施可
```

## タスク一覧

### TASK-001: Message dataclass と Channel 基底クラスの実装 ✅

- **REQ**: REQ-002
- **依存**: なし
- **完了基準**: `src/channels/message.py` と `src/channels/base.py` が存在し mypy エラーがない。`msg.title = "x"` が `FrozenInstanceError` を送出する

`Message`（frozen dataclass）と `Channel`（ABC）を新設する。`send()` の引数型は `Message` とし、Discord にも SES にも依存しない。

実装ガイド:
```python
# src/channels/message.py
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

# src/channels/base.py
from abc import ABC, abstractmethod
from src.channels.message import Message

class Channel(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...

    @abstractmethod
    def send(self, message: Message) -> None: ...
```

---

### TASK-002: DiscordChannel の実装（既存コードの移植） ✅

- **REQ**: REQ-002
- **依存**: TASK-001
- **完了基準**: `DiscordChannel.send(message)` が既存と同等の Discord embed を送信する。`grep "DiscordWebhook\|DiscordEmbed" src/main.py` が 0 件（`_post_minimal_embed` / `_post_prompt_attachment` は除く）。`grep "DISCORD_SEVERITY_COLOR" src/main.py` が 0 件

main.py 内の Discord 送信ロジックを `src/channels/discord.py` に移植する。`Message → DiscordEmbed` の変換は `_to_embed()` 内部で行う。discord_webhook ライブラリへの依存はこのクラスに閉じ込める。

#### main.py から削除・移動するコード

| 対象 | 現在の場所 | 対応 |
|---|---|---|
| `from discord_webhook import DiscordEmbed, DiscordWebhook` | line 35 | discord.py 内に移動 |
| `DISCORD_SEVERITY_COLOR` 定数 | lines 66-73 | discord.py 内の定数として移動 |
| Discord embed 送信ブロック | lines 723-769 | TASK-007 で `_dispatch()` 呼び出しに置き換え |

#### main.py に残すコード（Channel 抽象化の対象外）

- `_post_minimal_embed()`: alarm 名不正・AssumeRole 失敗・Bedrock 失敗時の Discord 専用フォールバック
- `_post_prompt_attachment()`: Bedrock prompt を Discord に添付するデバッグ機能

実装ガイド:
```python
# src/channels/discord.py
DISCORD_SEVERITY_COLOR: dict[str, int] = {
    "LOW": 0x2ECC71,
    "MEDIUM": 0xF1C40F,
    "HIGH": 0xE74C3C,
}

class DiscordChannel(Channel):
    # 実装時に environment_name / target_function_name を追加（embed の author / field 表示用）
    def __init__(
        self,
        webhook_url: str,
        environment_name: str,
        target_function_name: str,
    ) -> None:
        self._webhook_url = webhook_url
        self._environment_name = environment_name
        self._target_function_name = target_function_name

    @property
    def id(self) -> str:
        return "discord"

    def send(self, message: Message) -> None:
        # severity → color、author/fields/timestamp を Message から組み立てて Webhook 送信
        ...
```

---

### TASK-003: error-profiles.yml の作成と読み込み・_resolve_error_id の実装 ✅

- **REQ**: REQ-005, REQ-007
- **依存**: なし
- **完了基準**: `config/error-profiles.yml` が4エントリ（s3_data_missing / lambda_failure / unknown / unknown_alarm）で存在する。`_load_error_profiles()` が `{error_id: entry}` の辞書を返す。`_resolve_error_id()` が4分岐（alarm_name パターン外・ログ0件・status:error あり・status:error なし）を正しく返す。`_resolve_channel_ids("unknown_id", profiles)` が `["discord"]` を返し WARNING ログが出る

実装ガイド:
```yaml
# config/error-profiles.yml
# 現時点では全エントリが discord のみ。SES 設定完了後に email.scrumsign 等を追加する。
- id: s3_data_missing
  channels:
    - discord
  description: |
    S3へのデータ不着を検知しました。対象Lambdaの実行ログが存在しないため、Lambda自体が起動していません。
    原因として、クライアント側のアップロード失敗またはイベントトリガー設定の不備が考えられます。

- id: lambda_failure
  channels:
    - discord
  description: |
    対象Lambdaが起動しましたが、処理中にエラーが発生しました。
    CloudWatch Logsにstatus=errorのログが記録されています。
    原因として、入力データの形式不正、依存サービスのタイムアウト、またはコードのバグが考えられます。

- id: unknown
  channels:
    - discord
  description: |
    エラー種別を特定できませんでした。Lambdaの実行ログは存在しますが、エラーログが含まれていません。
    手動での調査が必要です。

- id: unknown_alarm
  channels:
    - discord
  description: |
    想定外のアラーム名を受信しました。このシステムが処理対象としていないアラームが発火した可能性があります。
    アラーム設定・命名規則を確認してください。
```

```python
def _load_error_profiles() -> dict[str, dict]:
    path = Path(__file__).parent / "config" / "error-profiles.yml"
    entries: list[dict] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {e["id"]: e for e in entries}

def _resolve_channel_ids(error_id: str, profiles: dict[str, dict]) -> list[str]:
    entry = profiles.get(error_id)
    if entry is None:
        logger.warning("error_id %r not found in error-profiles.yml, falling back to discord", error_id)
        return ["discord"]
    return entry["channels"]

def _resolve_error_id(alarm_name: str, log_rows: list) -> str:
    if not ALARM_NAME_RE.match(alarm_name):
        logger.warning("unknown alarm_name pattern %r", alarm_name)
        return "unknown_alarm"
    if not log_rows:
        return "s3_data_missing"
    if any(
        f.get("field") == "status" and f.get("value") == "error"
        for row in log_rows
        for f in row
    ):
        return "lambda_failure"
    logger.warning("logs exist but no error status found for alarm %r", alarm_name)
    return "unknown"
```

---

### TASK-004: email.yaml の作成と resolve_addresses の実装 ✅

- **REQ**: REQ-006
- **依存**: なし
- **完了基準**: `config/email.yaml` が存在する。`resolve_addresses("scrumsign", entries)` が `add` リストを返す。group_id が存在しない場合は `[]` を返し WARNING ログが出る

実装ガイド:
```yaml
# config/email.yaml  — リスト of dict 形式
# 現時点では社内（scrumsign）グループのみ定義。クライアント向けは SES 設定完了後に追加。
- id: scrumsign
  add:
    - kitamura@scrumsign.com
    - t.kimura@scrumsign.com
```

```python
def resolve_addresses(group_id: str, entries: list[dict]) -> list[str]:
    by_id = {e["id"]: e for e in entries}
    entry = by_id.get(group_id)
    if entry is None:
        logger.warning("email group %r not found in email.yaml", group_id)
        return []
    return list(entry.get("add", []))
```

---

### TASK-005: SESEmailChannel の骨格実装 ✅

- **REQ**: REQ-001, REQ-002
- **依存**: TASK-001, TASK-004
- **完了基準**: `SESEmailChannel("dev").id` が `"email.dev"` を返す。`send()` が `boto3.client("ses").send_email` を呼ぶ。アドレスリストが空の場合は `send_email` を呼ばず WARNING ログが出る。`Source` が `SES_FROM_ADDRESS` 環境変数の値と一致する

HTML テンプレートの中身は TASK-006 で実装する。本タスクでは SES 呼び出し骨格のみ。

実装ガイド:
```python
# src/channels/email.py
class SESEmailChannel(Channel):
    def __init__(self, group_id: str) -> None:
        self._group_id = group_id
        entries: list[dict] = yaml.safe_load(
            (Path(__file__).parent.parent / "config" / "email.yaml").read_text()
        )
        self._addresses = resolve_addresses(group_id, entries)

    @property
    def id(self) -> str:
        return f"email.{self._group_id}"

    def send(self, message: Message) -> None:
        if not self._addresses:
            logger.warning("no email addresses for group %r, skipping", self._group_id)
            return
        boto3.client("ses").send_email(
            Source=os.environ["SES_FROM_ADDRESS"],
            Destination={"ToAddresses": self._addresses},
            Message={
                "Subject": {"Data": message.title, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": self._to_html(message), "Charset": "UTF-8"},
                    "Text": {"Data": self._to_plain(message), "Charset": "UTF-8"},
                },
            },
        )
```

---

### TASK-006: HTML・プレーンテキストテンプレートの実装 ✅

- **REQ**: REQ-003, REQ-004
- **依存**: TASK-005
- **完了基準**: `_to_html(message)` の返り値に ship_name・JST タイムスタンプ（"JST" を含む）・severity・actions の全アクション文字列が含まれる。`_to_plain(message)` も同内容を返す。SES リクエストに `Body.Html` と `Body.Text` の両方が含まれる

実装ガイド:
```python
def _to_html(self, message: Message) -> str:
    jst = message.timestamp.astimezone(ZoneInfo("Asia/Tokyo"))
    actions_html = "".join(f"<li>{a}</li>" for a in message.actions)
    return (
        f"<h2>[{message.severity}] {message.title}</h2>"
        f"<p><b>対象</b>: {message.ship_name}</p>"
        f"<p><b>検知時刻</b>: {jst:%Y-%m-%d %H:%M JST}</p>"
        f"<p><b>原因推定</b>: {message.root_cause}</p>"
        f"<ul>{actions_html}</ul>"
    )

def _to_plain(self, message: Message) -> str:
    jst = message.timestamp.astimezone(ZoneInfo("Asia/Tokyo"))
    actions = "\n".join(f"- {a}" for a in message.actions)
    return (
        f"[{message.severity}] {message.title}\n"
        f"対象: {message.ship_name}\n"
        f"検知時刻: {jst:%Y-%m-%d %H:%M JST}\n"
        f"原因推定: {message.root_cause}\n"
        f"推奨アクション:\n{actions}"
    )
```

---

### TASK-007: _dispatch と main.py への統合 ✅

- **REQ**: REQ-002, REQ-005, REQ-007
- **依存**: TASK-002, TASK-003, TASK-005
- **完了基準**: `_dispatch(alarm_name, message, error_id)` が3段階ルーティングを通じて正しいチャネルのみに送信する。いずれかのチャネルが例外を出しても他チャネルへの送信が継続する。`grep "no_logs" src/main.py` が 0 件。ログ有無にかかわらず Bedrock と `_dispatch` が呼ばれる

main.py の以下2箇所を変更する:

1. **削除**: 0件ログの早期 return ブロック（現 lines 649–662）
2. **置き換え**: Discord embed 送信ブロック（lines 723–769）→ 以下のフローに統合

#### main.py に追加する関数

```python
from src.channels.message import Message
from src.channels.discord import DiscordChannel
from src.channels.email import SESEmailChannel

# 実装時に env: Env を引数に追加（DiscordChannel の初期化に必要）
def _build_channel_registry(channel_ids: list[str], env: Env) -> dict[str, Channel]:
    registry: dict[str, Channel] = {
        "discord": DiscordChannel(
            webhook_url=env.discord_webhook_url,
            environment_name=env.environment_name,
            target_function_name=env.target_function_name,
        ),
    }
    for cid in channel_ids:
        if cid.startswith("email."):
            group_id = cid.split(".", 1)[1]
            registry[cid] = SESEmailChannel(group_id=group_id)
    return registry

def _dispatch(alarm_name: str, message: Message, error_id: str, env: Env) -> None:
    profiles    = _load_error_profiles()
    channel_ids = _resolve_channel_ids(error_id, profiles)
    registry    = _build_channel_registry(channel_ids, env)

    for cid in channel_ids:
        channel = registry.get(cid)
        if channel is None:
            logger.warning("channel_id %r not in registry, skipping", cid)
            continue
        try:
            channel.send(message)
        except Exception:
            logger.warning("channel %r send failed", cid, exc_info=True)
            # 再 raise しない（AC-007-5）
```

#### main.py の置き換え箇所

```python
# error_id を確定（Bedrock より先に確定してプロンプト注入に使う）
error_id = _resolve_error_id(alarm_name, log_rows)

# error-profiles.yml の description を Bedrock プロンプトに注入
profiles = _load_error_profiles()
error_description = profiles.get(error_id, {}).get("description", "")
# （既存の Bedrock 呼び出しブロック内のプロンプト構築箇所に error_description を渡す）

# Message 構築と全チャネルへのディスパッチ
message = Message(
    title=report["summary"],
    severity=report["severity"],
    confidence=report["confidence"],
    root_cause=report["root_cause_hypothesis"],
    actions=report["suggested_actions"],
    alarm_name=alarm_name,
    ship_name=ship_name,
    timestamp=center,
)
_dispatch(alarm_name, message, error_id)
```

#### report → Message フィールドマッピング

| Message フィールド | 変換元 | 備考 |
|---|---|---|
| `title` | `report["summary"]` | `_normalize_report()` で切り詰め済み |
| `severity` | `report["severity"]` | HIGH / MEDIUM / LOW |
| `confidence` | `report["confidence"]` | high / medium / low |
| `root_cause` | `report["root_cause_hypothesis"]` | |
| `actions` | `report["suggested_actions"]` | list[str] |
| `alarm_name` | `alarm_name` | SNS Message から取得済み |
| `ship_name` | `ship_name` | `_extract_ship_name_from_alarm_name()` の結果 |
| `timestamp` | `center` | Alarm 発火時刻（UTC aware datetime） |

---

### TASK-008: IAM ポリシーと SES セットアップ（インフラ） 🔄 一部完了

- **REQ**: REQ-001
- **依存**: なし（並列実施可）
- **完了基準**: Lambda 実行ロールに `ses:SendEmail` / `ses:SendRawEmail` が付与されている。SES サンドボックスが解除されており任意アドレスへの送信が可能

| # | 作業 | 状態 |
|---|---|---|
| 1 | `scrumsign.com` を SES に Identity 登録（DKIM トークン発行） | ✅ 完了（2026-05-26） |
| 2 | Sandbox 解除申請を AWS に送信 | ✅ 送信済み（PENDING・審査中） |
| 3 | Lambda 実行ロール（`hdw-lambda-execution-role`）に `ses:SendEmail` / `ses:SendRawEmail` 追加 | ✅ 完了（2026-05-26） |
| 4 | さくらのコントロールパネルで DKIM CNAME レコード3件を DNS に追加 | ❌ 保留 |
| 5 | 送信元アドレス確定後 `SES_FROM_ADDRESS` を deploy.yml 環境変数に追加 | ❌ 保留（アドレス未確定） |

詳細は `specs/client-email-notification/REPORT-001.md` を参照。

---

### TASK-009: config ファイルのデプロイ設定確認

- **REQ**: REQ-005, REQ-006
- **依存**: TASK-003, TASK-004
- **完了基準**: `docker run --rm <image> ls /var/task/config/` の出力に `error-profiles.yml` と `email.yaml` が含まれる。両ファイルを `yaml.safe_load` して正常終了する

`config/` ディレクトリは Dockerfile の既存 `COPY config/ ${LAMBDA_TASK_ROOT}/config/` で自動的にイメージに含まれる。ファイルを配置するだけでよい。
