---
title: Discord 埋め込みの表示内容を 5W1H で洗練する (PLAN)
date: 2026-05-18
status: plan
type: information-design
scope: discord-embed
author: t.kimura@scrumsign.com
source_draft: ./DRAFT.md
related:
  - ../../05/15/lambda-error-report-mvp/PLAN.md
  - ../../05/15/report-content-by-case/DRAFT.md
tags:
  - discord
  - embed
  - information-design
  - 5w1h
  - llm-prompt-design
  - incident-response
audience: 運用Lambda(hdw-ingest)の開発・運用担当者
decisions:
  severity_decision: llm
  layout: static
  actions_scope: aws-resource-level
  confidence_display: inline-with-field-name
  mentions: none
  env_distinction: title-prefix
files_to_modify:
  - src/utils/prompt.py
  - src/main.py
  - deploy/config.yml
  - deploy/config-prod.yml
---

# Discord 埋め込みの表示内容を 5W1H で洗練する (PLAN)

## 0. このドキュメントの位置づけ

[DRAFT.md](./DRAFT.md) で 5W1H 採点と論点を洗い出し、対話で全争点を決め切った成果物。
本 PLAN は **何を作るか** と **どのファイルをどう変えるか** を確定させ、コード変更タスクへ落とすための実装契約とする。

> **本 PLAN を読めば、別の人がプロンプト改訂と Embed 改造を完遂できる**ことが完了条件。

---

## 1. 決定事項サマリ

DRAFT §3 の論点に対する確定回答。

| # | 論点 | 決定 | 根拠 |
|---|---|---|---|
| 1 | 情報量の原則 | **簡潔・正確・有用**の 3 条件。判断に貢献しない情報は載せない | 30 秒判断の目的関数 |
| 2 | 解釈層（LLM）の役割 | **圧縮 / 世界知識による翻訳 / 情報不足下での仮説生成** に限定 | 機械でできることは機械で（hallucination 抑制） |
| 3 | severity の決定主体 | **LLM 判断**（LOW / MEDIUM / HIGH） | メンション自動化を入れない決定により、誤判定の不可逆コストが許容範囲に収まる |
| 4 | レイアウト | **静的固定**（confidence で field を消さない） | 受信者の認知負荷削減（毎回同じ場所を見る） |
| 5 | `suggested_actions` の粒度 | **AWS リソース/サービス操作レベルのみ**。コードベース固有の関数名・変数名・モジュール名は禁止 | LLM は hdw-ingest のコードを知らない |
| 6 | confidence の表示 | field 名に併記（`🧭 原因仮説 [confidence: medium]`） | 視線移動なしで信頼度が分かる |
| 7 | メンション機構 | **入れない**。color と title prefix の視覚強調のみ | 少人数・常駐前提のため不要 |
| 8 | dev/prod の表現 | **title prefix** で表現（`[prod] ...`） | color は severity に割り当て済み |
| 9 | ケース判定の自動化 | **本 PLAN のスコープ外**。`render_prompt_case_generic` 固定継続 | 段階導入 |

---

## 2. 最終 Embed 構造（静的）

```
┌──────────────────────────────────────────────────────────────┐
│ [prod] HDW_Backend_Processor_0001 · ⚠ <alarm_name>  [color]  │  title (機械)
│ <summary>                                                    │  description (LLM, ≤60字)
├──────────────────────────────────────────────────────────────┤
│ 📊 件数             │ 🕐 集計時間窓                          │  field × 2 (inline, 機械)
│ 3 件                │ 14:30–14:32 JST                        │
├──────────────────────────────────────────────────────────────┤
│ 🧭 原因仮説 [confidence: medium]                             │  field (LLM, ≤200字)
│ <root_cause_hypothesis>                                      │
├──────────────────────────────────────────────────────────────┤
│ ✅ 推奨アクション                                             │  field (LLM, ≤80字×3)
│ - <AWS-level action 1>                                       │
│ - <AWS-level action 2>                                       │
│ - <AWS-level action 3>                                       │
├──────────────────────────────────────────────────────────────┤
│ 🔍 詳細リンク                                                 │  field (機械)
│ [Logs] · [Insights] · [Metrics]                              │
├──────────────────────────────────────────────────────────────┤
│ req-id: abc12345 · 2026-05-18 14:30:00 JST          (footer) │  footer (機械)
└──────────────────────────────────────────────────────────────┘
```

**5W1H の対応**:

| W/H | 担当要素 | 起源 |
|---|---|---|
| **When** | 集計時間窓 field / footer の timestamp / Embed 標準の相対時刻 | 機械 |
| **Where** | title の `[env]` + 関数名 / 詳細リンクの先 | 機械 |
| **Who** | （明示せず — チャネル受信者全員） | — |
| **What** | description (summary) + 件数 field | LLM + 機械 |
| **Why** | 原因仮説 field (confidence 併記) | LLM |
| **How** | 推奨アクション field + 詳細リンク field | LLM + 機械 |

---

## 3. 字数 / フィールド予算

| 項目 | 上限 | 強制方法 |
|---|---|---|
| Embed 全体 | 800 字以内（目安） | 各 field 上限の合算で自然に収まる |
| field 数 | 5（うち 2 つは inline） | 静的レイアウトで固定 |
| `summary` | 60 字以内 | プロンプト + LLM 出力 schema で誘導 |
| `root_cause_hypothesis` | 200 字以内 | 同上 |
| `suggested_actions` | 各 80 字 × 最大 3 件 | 同上 |
| title | 256 字（Discord 仕様） | 組立時に `title[:256]` で截断 |
| field value | 1024 字（Discord 仕様） | 上記の 200 / 80×3 で十分余裕 |

---

## 4. LLM 出力 JSON Schema

```jsonc
{
  "summary": "60文字以内の1行要約",
  "severity": "LOW" | "MEDIUM" | "HIGH",
  "confidence": "low" | "medium" | "high",
  "root_cause_hypothesis": "原因仮説 (200文字以内、優先順で複数仮説可)",
  "suggested_actions": [
    "即時対応 (AWS リソース/サービス操作レベル, 80字以内)",
    "調査手順 (AWS リソース/サービス操作レベル, 80字以内)",
    "恒久対策 (AWS リソース/サービス操作レベル, 80字以内)"
  ]
}
```

**バリデーション方針（本 PLAN スコープ）**:
- 必須フィールド: `summary`, `severity`, `confidence`, `root_cause_hypothesis`, `suggested_actions`
- 欠落時は `report.get(...)` のデフォルト値で吸収（既存パターン踏襲）
- JSON 自体が逸脱した場合は `json.loads` で例外 → Lambda エラー終了（fallback Embed はスコープ外）

---

## 5. システムプロンプト改訂 — `src/utils/prompt.py`

### 5.1 改訂ポイント

| # | 既存 | 新規 |
|---|---|---|
| 1 | summary 30 字以内 | **60 字以内** |
| 2 | root_cause_hypothesis 字数指定なし | **200 字以内**を明記 |
| 3 | suggested_actions に粒度制約なし | **AWS リソース/サービス操作レベルのみ**、コードベース固有名禁止、各 80 字以内・最大 3 件 |
| 4 | 「即時対応 / 調査手順 / 恒久対策」3 段構成 | 維持 |
| 5 | 「情報不足は捏造せず confidence: low + 情報不足 — <何が足りないか>」 | 維持 |
| 6 | 「コードベース固有の根本原因は知らない前提で、仮説として複数提示」 | 維持 |

### 5.2 改訂後の `_SYSTEM_PROMPT_TEMPLATE`（フルテキスト）

```python
_SYSTEM_PROMPT_TEMPLATE = """
あなたはAWS Lambda障害分析の専門家です。
このアラートは事前判定で「{case_name}」に分類されました。
{case_specific_instructions}

# 役割
- 機械的に抽出済みのログ・メトリクスを読み、開発者が最初の30秒で
  「対応すべきか / 何が起きたか / どこを見るか」を判断できる材料を出す。
- ケース判定・件数集計・request_id 抽出・deeplink 生成は呼び出し側が
  既に済ませているため、それらの再計算や推測は不要。

# 制約
- 必ず下記JSON Schemaに従ってください。スキーマ外の出力は禁止。
- コードベース固有の根本原因は知らない前提で、仮説として複数提示してください。
  断定はせず、もっともらしさの順で並べる。
- 情報不足で判断できない場合は、捏造せず confidence: "low" と
  root_cause_hypothesis に「情報不足 — <何が足りないか>」と書いてください。

# summary
- 60文字以内、1行で「何が起きたか」。

# root_cause_hypothesis
- 200文字以内。優先順で複数仮説を可。

# suggested_actions の制約 (重要)
- 各項目 80文字以内、最大3件。
- 「即時対応」「調査手順」「恒久対策」の3段で並べる。
- AWS リソース / サービス操作レベルでのみ提案する。
  例: 「Lambda の Timeout 設定を 30s → 60s に引き上げる」
      「DynamoDB テーブル X の WCU を一時的に増やす」
      「IAM Role に s3:GetObject 権限が付与されているか確認する」
      「CloudWatch Logs Insights で同一 request_id のログ系列を確認する」
- 以下は禁止:
  - hdw-ingest のコード内の関数名・変数名・モジュール名・ファイル名の言及
  - 「<関数名>を修正する」「<変数名>に対する null チェックを追加する」のような
    コードベース固有の修正提案
  - 「リトライ処理を実装する」のような実装レベルの提案（AWS の retry config
    変更などサービス設定レベルなら可）

# 出力スキーマ
{{
  "summary": "60文字以内の1行要約",
  "severity": "LOW" | "MEDIUM" | "HIGH",
  "confidence": "low" | "medium" | "high",
  "root_cause_hypothesis": "原因仮説 (200文字以内、優先順で複数仮説可)",
  "suggested_actions": [
    "即時対応 (AWSリソース/サービス操作レベル, 80字以内)",
    "調査手順 (AWSリソース/サービス操作レベル, 80字以内)",
    "恒久対策 (AWSリソース/サービス操作レベル, 80字以内)"
  ]
}}
"""
```

ケース別追加指示（`render_prompt_case_generic`, `render_prompt_case_timeout`, `render_prompt_case_dependency`）は**現状維持**。

---

## 6. `src/main.py` 改訂

### 6.1 `Env` dataclass 拡張

`os.environ` から読む値を 2 つ追加:

```python
@dataclasses.dataclass(slots=True, frozen=True)
class Env:
    # 既存フィールド
    discord_webhook_url: str
    cloudwatch_logs_group: str
    cloudwatch_logs_window_before_min: int
    cloudwatch_logs_window_after_min: int
    cloudwatch_logs_query_poll_interval_sec: float
    bedrock_model_id: str
    bedrock_max_tokens: int
    # 新規
    environment_name: str         # "dev" | "staging" | "prod"
    target_function_name: str     # 監視対象 Lambda 名 (例: "HDW_Backend_Processor_0001")

    @classmethod
    def from_environ(cls) -> "Env":
        return cls(
            # 既存…
            environment_name=os.environ["ENVIRONMENT_NAME"],
            target_function_name=os.environ["TARGET_FUNCTION_NAME"],
        )
```

AWS リージョンは Lambda 自動設定の `os.environ["AWS_REGION"]` を deeplink 関数内で直接参照（dataclass 不要）。

### 6.2 追加するヘルパ関数（同ファイル内）

```python
def _format_window_jst(start: datetime, end: datetime) -> str:
    """集計時間窓を 'HH:MM–HH:MM JST' で返す。"""

def _format_jst(timestamp_iso: str) -> str:
    """ISO timestamp を 'YYYY-MM-DD HH:MM:SS JST' で返す。"""

def _extract_first_request_id(log_rows: list[list[dict[str, str]]]) -> str | None:
    """Logs Insights 結果の先頭行から function_request_id を取り出す。
    無ければ None。"""

def _build_deeplinks_markdown(
    env: Env, start: datetime, end: datetime
) -> str:
    """CloudWatch Logs / Insights / Metrics への deeplink を
    '[Logs](url) · [Insights](url) · [Metrics](url)' で返す。"""
```

deeplink URL テンプレート（参考。実装時 URL エンコードに注意）:

- Logs: `https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{encoded_log_group}`
- Insights: `https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#logsV2:logs-insights$3FqueryDetail=...$26start={start_unix}$26end={end_unix}$26logGroups={encoded_log_group}`
- Metrics: `https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#metricsV2:graph=~()` — まずは関数の `AWS/Lambda` Errors メトリクスへの簡易リンクで可

### 6.3 Embed 組立部の置換（`src/main.py:166-187`）

```python
# --- Discord 通知投稿 ---
title = f"[{env.environment_name}] {env.target_function_name} · ⚠ {alarm_name}"

webhook = DiscordWebhook(url=env.discord_webhook_url)
embed = DiscordEmbed(
    title=title[:256],
    description=report["summary"],
    color=DISCORD_SEVERITY_COLOR.get(report["severity"], 0x95A5A6),
)

# 機械事実 (When + What)
embed.add_embed_field(
    name="📊 件数", value=f"{len(log_rows)} 件", inline=True
)
embed.add_embed_field(
    name="🕐 集計時間窓", value=_format_window_jst(start, end), inline=True
)

# LLM 解釈 (Why) — confidence を field 名に併記
confidence = report.get("confidence", "low")
embed.add_embed_field(
    name=f"🧭 原因仮説 [confidence: {confidence}]",
    value=report.get("root_cause_hypothesis", "(不明)"),
    inline=False,
)

# LLM 解釈 (How) — AWS-level actions
actions = report.get("suggested_actions") or []
if actions:
    embed.add_embed_field(
        name="✅ 推奨アクション",
        value="\n".join(f"- {a}" for a in actions),
        inline=False,
    )

# 機械事実 (How: 深掘り動線)
embed.add_embed_field(
    name="🔍 詳細リンク",
    value=_build_deeplinks_markdown(env, start, end),
    inline=False,
)

# footer
representative_request_id = _extract_first_request_id(log_rows) or "(なし)"
embed.set_footer(
    text=f"req-id: {representative_request_id} · {_format_jst(timestamp)}"
)
embed.set_timestamp(timestamp)

webhook.add_embed(embed)
webhook.execute()
```

`DISCORD_SEVERITY_COLOR` 定数（`src/main.py:56-60`）は現状維持。

---

## 7. `deploy/config*.yml` への影響

新規環境変数を 2 つ追加する必要がある:

| key | dev (`deploy/config.yml`) | prod (`deploy/config-prod.yml`) |
|---|---|---|
| `ENVIRONMENT_NAME` | `dev` | `prod` |
| `TARGET_FUNCTION_NAME` | `HDW_Backend_Processor_0001`（または dev 用関数名） | `HDW_Backend_Processor_0001` |

GitHub Actions のデプロイジョブ（`.github/workflows/deploy.yml`）が `aws lambda update-function-configuration --environment` で投入する既存パスに乗る。

---

## 8. 段階導入順序とスコープ

### 8.1 本 PLAN で実装する範囲

1. `src/utils/prompt.py` のプロンプト改訂（§5）
2. `src/main.py` の `Env` 拡張・ヘルパ関数追加・Embed 組立差し替え（§6）
3. `deploy/config.yml` / `deploy/config-prod.yml` への env 追加（§7）

### 8.2 スコープ外（後追い）

| 項目 | 後追い理由 |
|---|---|
| ケース判定自動化（Timeout/Memory/Dependency/Config 等の分類器） | 現状 Generic 固定で運用観察し、頻度の高いケースから順に着手 |
| invocation_count / error_rate の機械抽出 | CW Metrics の追加 API 呼び出しが必要、コスト・レイテンシ評価後に判断 |
| fallback Embed（LLM 失敗時の最低限通知） | JSON 逸脱率を運用で観測してから設計 |
| メンション機構 | 受信者の規模・運用形態が変わったら再検討 |
| dedupe / 連続発火抑制 | 連発が問題化したら設計 |
| 過去レポート参照（"先週も同じエラーが出た"） | S3+DDB 保存とセット、価値が顕在化してから |

---

## 9. 動作確認（Verification）

### 9.1 ローカル単体実行

`src/main.py` を CW Alarm 模擬 event で直接呼び出す。必要な環境変数:

```
DISCORD_WEBHOOK_URL=<テストチャネルの webhook>
CLOUDWATCH_LOGS_GROUP=/aws/lambda/HDW_Backend_Processor_0001
CLOUDWATCH_LOGS_WINDOW_BEFORE_MIN=5
CLOUDWATCH_LOGS_WINDOW_AFTER_MIN=1
CLOUDWATCH_LOGS_QUERY_POLL_INTERVAL_SEC=1.0
BEDROCK_MODEL_ID=apac.anthropic.claude-sonnet-4-5-20250929-v2:0
BEDROCK_MAX_TOKENS=1024
ENVIRONMENT_NAME=dev
TARGET_FUNCTION_NAME=HDW_Backend_Processor_0001
AWS_REGION=ap-northeast-1
```

### 9.2 確認項目

| # | 確認内容 | 期待 |
|---|---|---|
| 1 | title prefix | `[dev] HDW_Backend_Processor_0001 · ⚠ ...` の形 |
| 2 | description | `summary` (≤60字) が表示される |
| 3 | 件数 / 集計時間窓 field | inline で横並びに表示 |
| 4 | confidence の field 名併記 | `🧭 原因仮説 [confidence: medium]` の形 |
| 5 | suggested_actions の粒度 | コードベース固有名が出ていないこと（プロンプト制約の効きを目視確認） |
| 6 | 詳細リンク | Logs / Insights / Metrics の 3 リンクが時間窓・関数名を正しく指す |
| 7 | footer | `req-id: <値> · YYYY-MM-DD HH:MM:SS JST` の形 |
| 8 | color | severity=`LOW`/`MEDIUM`/`HIGH` で緑/黄/赤に切り替わる |
| 9 | 字数 | field value が 1024 字制限を超えない（200字制約で十分） |

### 9.3 統合確認

1. dev 環境にデプロイ
2. `HDW_Backend_Processor_0001` で意図的にエラーを起こすか、過去の Alarm を再発火させて Reporter Lambda を駆動
3. Discord で実 Embed を目視確認
4. 問題なければ prod へ昇格

---

## 10. 残課題 / オープン論点

- **suggested_actions の品質**: AWS レベル制約がプロンプトで本当に効くかは実出力で要観察。逸脱が頻発するなら制約文を強化（few-shot 化）。
- **deeplink の Insights URL**: クエリ文字列の URL エンコードが Discord 表示で崩れないか実機確認が要る（特に `$` 記号の二重エスケープ）。
- **invocation_count の追加優先度**: 「件数 / 全体に対する比率」を出すと判断が早くなる。CW Metrics 1 本追加のコストと天秤。
- **multilingual 化**: 現状日本語固定。将来必要なら summary / actions のみ多言語化（schema は同じ）。
- **PLAN 完遂後**: 本 PLAN を `status: plan → status: executed` に更新し、運用観察フェーズへ。

---

## 11. クリティカルパス（実装順）

1. `src/utils/prompt.py` 改訂
2. `src/main.py` 改訂（Env 拡張 → ヘルパ関数追加 → Embed 組立置換）
3. `deploy/config.yml` / `deploy/config-prod.yml` に env 追加
4. ローカル動作確認（§9.1, 9.2）
5. dev デプロイ → 実 Alarm で観察（§9.3）
6. prod 昇格
7. 本 PLAN の `status` 更新
