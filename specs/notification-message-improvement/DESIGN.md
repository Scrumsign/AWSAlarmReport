# 通知メッセージ改善 設計

GitHub Issue: #4

## 背景

このシステムの通知は、運用Lambda（HDW_Backend_Processor_0001）で発生した問題を自動分析し、Discord / Email で関係者に知らせるものである。

運用Lambdaの業務内容:
- クライアントが S3 にファイルをアップロードする
- 運用Lambda がそのファイルを読み取り、処理し、別のフォルダに配置する
- 4時間に1回、直近のログに正常完了記録がなければアラームが発火する

通知の受信者には技術者だけでなく、業務担当者やクライアント関係者も含まれる可能性がある。

## 受信者と伝えるべきこと

### 受信者

| 受信者 | 関心事 |
|---|---|
| 非技術者（業務担当者・クライアント） | 「今どういう状態か」「業務に影響があるか」「自分が何かすべきか」 |
| 技術者（開発・運用） | 「何が原因か」「どこを見ればいいか」「どう対処するか」 |

### 4パターンの業務的な意味

| パターン | error_id | 重要度（固定） | 受信者に伝えるべき業務的な意味 |
|---|---|---|---|
| ログなし | s3_data_missing | 注意（MEDIUM） | ファイルが届いていないか、処理が開始されていない。出力データが生成されない状態。 |
| 処理エラー | lambda_failure | 重要（HIGH） | ファイルの処理中にエラーが発生した。出力データが欠損している可能性がある。 |
| 状態不明 | unknown | 注意（MEDIUM） | 処理の結果が確認できない。正常に完了したかどうか判断がつかない状態。 |
| 想定外アラーム | unknown_alarm | 情報（LOW） | システム設定の問題であり、業務データへの直接的な影響はない見込み。 |

## 通知の構成原則

1. **上部は業務メッセージ** — 受信者が最初に目にする部分で「業務上何が起きているか」「原因の見立て」を平易な日本語で示す
2. **下部は技術詳細** — エラー発生状況・原因分析・対応提案などの技術情報を区切って表示する
3. **1つの通知で両方の読者に対応** — 非技術者は上部で完結、技術者は下部にスクロールして詳細を確認する
4. **ラベルから専門用語を排除** — 「Lambda」「Alarm」「AssumeRole」等のAWS用語はラベルに出さない
5. **重要度は error_id から固定で決定** — Bedrock の判断に委ねず、パターンごとに一意に決まる

## 用語方針

| 避ける表現 | 代わりに使う表現 |
|---|---|
| Lambda | 処理システム / 監視対象システム |
| Alarm / アラーム発火 | 異常検知 / 検知アラーム |
| AssumeRole | 接続 / 権限設定 |
| CloudWatch Logs Insights | ログ検索 |
| S3 | ファイル送信 / アップロード |
| config/xxx.yml | システム設定 |
| severity: HIGH / MEDIUM / LOW | 重要 / 注意 / 情報 |
| confidence: high / medium / low | 確度: 高 / 中 / 低 |

## スコープ

- Bedrock 成功パスの通知改善（Discord embed / Email）
- fallback 通知（`_post_minimal_embed`）のラベル・文言改善
- **スコープ外**: fallback の `_dispatch` 統合（別 issue）

## Bedrock 出力スキーマ

### 変更前

```json
{
  "business_summary": "...",
  "summary": "...",
  "severity": "LOW | MEDIUM | HIGH",
  "confidence": "low | medium | high",
  "root_cause_hypothesis": "...",
  "suggested_actions": ["..."]
}
```

### 変更後

```json
{
  "business_summary": "業務上何が起きているか (100文字以内、技術用語禁止)",
  "root_cause_hypothesis": "原因の見立て (100文字以内、技術用語禁止)",
  "confidence": "low | medium | high",
  "technical_observation": "ログから確認できた技術的事実 (200文字以内)",
  "technical_hypothesis": "技術的な原因仮説と対処の方向性 (200文字以内)",
  "suggested_actions": ["最大3件、各80字以内"]
}
```

**削除フィールド:**
- `severity` → error_id から固定で決定するため Bedrock に判断させない
- `summary` → `technical_observation` に役割を統合

**変更フィールド:**
- `root_cause_hypothesis` → 非技術者向けに制約変更（技術用語禁止、100文字以内）

**新設フィールド:**
- `technical_observation` — ログから読み取れた技術的事実（例外クラス、発生箇所、エラーメッセージ）
- `technical_hypothesis` — 技術的な原因仮説と対処の方向性（仮説、コード修正提案）

### プロンプト指示

```
# business_summary
- 100 文字以内。非技術者向け
- AWS 用語・技術用語（Lambda、Alarm、S3、CloudWatch 等）は使わない
- 「ファイル処理」「データ」「送信」など受信者が理解できる日本語で書く
- 対応の要否・業務への影響が伝わるようにする
- 例: 「sakura のデータ処理中にエラーが発生しました。出力データが欠損している可能性があります。」

# root_cause_hypothesis
- 100 文字以内。原因を非技術者にも分かる言葉で説明する
- コード参照（ファイル名、行番号、関数名）やAWS用語は使わない
- 「何が原因で」「どうなったか」を業務の言葉で伝える
- 例: 「送信されたファイルの形式に問題があり、正しく処理できませんでした。」
- 例: 「ファイルが届いていないため、処理が開始されていません。」

# confidence
- low / medium / high

# technical_observation
- 200 文字以内。ログから読み取れた技術的事実のみ
- 例外クラス名、発生箇所（file:line）、エラーメッセージを含める
- 仮説や推測は含めない。観測できた事実だけを書く
- 例: 「store.py:87 で KeyError('data') が発生。request_id=abc123 の実行で
  frontend_paths['data'][key] へのアクセス時に例外。」

# technical_hypothesis
- 200 文字以内。技術的な原因の仮説と対処の方向性
- もっともらしい順に複数仮説を並べてよい
- コード修正レベルの指摘を歓迎する
- 例: 「入力 ZIP 内のデータ構造が想定と異なる可能性が高い。
  store.py:87 の辞書アクセスを .get() に変更し KeyError 耐性を向上させることを推奨。」

# suggested_actions の制約
- 各項目 80 文字以内、最大 3 件
- 「即時対応」「調査手順」「恒久対策」の 3 段で並べる
```

## 通知表示イメージ

各パターンの通知経路と通知先:

| パターン | error_id | 重要度 | 通知経路 | 通知先 |
|---|---|---|---|---|
| 1. 想定外アラーム | unknown_alarm | 情報（LOW） | `_post_minimal_embed`（fallback） | Discord のみ |
| 2. ログなし | s3_data_missing | 注意（MEDIUM） | Bedrock → `_to_embed` | Discord のみ |
| 3. 処理エラー | lambda_failure | 重要（HIGH） | Bedrock → `_to_embed` | Discord のみ |
| 4. 状態不明 | unknown | 注意（MEDIUM） | Bedrock → `_to_embed` | Discord + Email |

---

### パターン 1: 想定外アラーム（unknown_alarm）

Bedrock 分析なし。`_post_minimal_embed` による fallback 通知。

#### Discord embed

```
┌──────────────────────────────────────────────────┐
│ HDW Notify · production                     [黄] │
├──────────────────────────────────────────────────┤
│ 想定外のアラームを受信しました                    │
│ （対象外の監視設定の可能性あり）                   │
├───────────────────────┬──────────────────────────┤
│ 監視対象システム       │ 検知アラーム              │
│ HDW_Backend_           │ legacy-alarm-001         │
│ Processor_0001         │                          │
├───────────────────────┴──────────────────────────┤
│ 取得ログ件数                                      │
│ 0 件                                              │
├──────────────────────────────────────────────────┤
│ アラーム理由                                      │
│ Threshold Crossed: 1 out of the last 1 datapoints │
│ [1.0 (28/05/26 06:00:00)] was greater than the    │
│ threshold (0.0)                                   │
├──────────────────────────────────────────────────┤
│                        2026-05-28 15:00:00+00:00 │
└──────────────────────────────────────────────────┘
```

※ Email 通知なし

---

### パターン 2: ログなし — データ未着疑い（s3_data_missing）

#### Bedrock 出力例

```json
{
  "business_summary": "sakura のデータ処理が開始されていません。ファイルが届いていない可能性があります。",
  "root_cause_hypothesis": "ファイルが届いていないため、処理が開始されていません。",
  "confidence": "medium",
  "technical_observation": "直近 5h30m の時間窓に Lambda 実行ログが 0 件。error / success いずれのステータスも記録されていない。",
  "technical_hypothesis": "最有力: 上流からの ZIP アップロードが未到着。副次: S3 イベント通知設定の破損により Lambda が起動しなかった可能性。",
  "suggested_actions": [
    "S3 バケットの sakura-*.zip 直近着信を確認する",
    "CloudTrail で PutObject イベントの有無を確認する",
    "上流のデータ送信プロセスの稼働状況を確認する"
  ]
}
```

#### Discord embed

```
┌──────────────────────────────────────────────────┐
│ HDW Notify · production                     [黄] │
├──────────────────────────────────────────────────┤
│ [注意] sakura のデータ処理が開始されていません。   │
│ ファイルが届いていない可能性があります。           │
├──────────────────────────────────────────────────┤
│ 原因の見立て                                      │
│ ファイルが届いていないため、処理が開始されて       │
│ いません。                                        │
├──────────────────────────────────────────────────┤
│ ── 技術詳細 ──────────────────────────────────── │
├───────────────────┬──────────────┬────────────────┤
│ 監視対象システム   │ 検知アラーム  │ エラー種別      │
│ HDW_Backend_      │ hdw-sakura   │ s3_data_missing│
│ Processor_0001    │              │                │
├───────────────────┴──────────────┴────────────────┤
│ 発生状況                                          │
│ 直近 5h30m の時間窓に Lambda 実行ログが 0 件。     │
│ error / success いずれのステータスも記録されて      │
│ いない。                                          │
├──────────────────────────────────────────────────┤
│ 原因分析（確度: 中）                              │
│ 最有力: 上流からの ZIP アップロードが未到着。      │
│ 副次: S3 イベント通知設定の破損により Lambda が    │
│ 起動しなかった可能性。                             │
├──────────────────────────────────────────────────┤
│ 対応の提案                                        │
│ - S3 バケットの sakura-*.zip 直近着信を確認する   │
│ - CloudTrail で PutObject イベントの有無を確認    │
│ - 上流のデータ送信プロセスの稼働状況を確認する    │
├──────────────────────────────────────────────────┤
│                        2026-05-28 15:00:00+00:00 │
└──────────────────────────────────────────────────┘
```

※ Email 通知なし

---

### パターン 3: 処理エラー（lambda_failure）

#### Bedrock 出力例

```json
{
  "business_summary": "sakura のデータ処理中にエラーが発生しました。出力データが欠損している可能性があります。",
  "root_cause_hypothesis": "送信されたファイルの形式に問題があり、正しく処理できませんでした。",
  "confidence": "high",
  "technical_observation": "store.py:87 で KeyError('data') が発生。request_id=abc123 の実行で frontend_paths['data'][key] へのアクセス時に例外。",
  "technical_hypothesis": "入力 ZIP 内のデータ構造が想定と異なる可能性が高い。特定 ZIP 依存の問題と推定。store.py:87 の辞書アクセスを .get() に変更し KeyError 耐性を向上させることを推奨。",
  "suggested_actions": [
    "対象 ZIP (sakura-20260528T0600.zip) の内容を確認する",
    "store.py:87 の辞書アクセスを .get() に変更し KeyError 耐性を向上",
    "入力データのバリデーション処理を追加して異常データを早期検知する"
  ]
}
```

#### Discord embed

```
┌──────────────────────────────────────────────────┐
│ HDW Notify · production                     [赤] │
├──────────────────────────────────────────────────┤
│ [重要] sakura のデータ処理中にエラーが発生しまし   │
│ た。出力データが欠損している可能性があります。     │
├──────────────────────────────────────────────────┤
│ 原因の見立て                                      │
│ 送信されたファイルの形式に問題があり、正しく       │
│ 処理できませんでした。                             │
├──────────────────────────────────────────────────┤
│ ── 技術詳細 ──────────────────────────────────── │
├───────────────────┬──────────────┬────────────────┤
│ 監視対象システム   │ 検知アラーム  │ エラー種別      │
│ HDW_Backend_      │ hdw-sakura   │ lambda_failure │
│ Processor_0001    │              │                │
├───────────────────┴──────────────┴────────────────┤
│ 発生状況                                          │
│ store.py:87 で KeyError('data') が発生。           │
│ request_id=abc123 の実行で frontend_paths          │
│ ['data'][key] へのアクセス時に例外。               │
├──────────────────────────────────────────────────┤
│ 原因分析（確度: 高）                              │
│ 入力 ZIP 内のデータ構造が想定と異なる可能性が      │
│ 高い。特定 ZIP 依存の問題と推定。store.py:87 の    │
│ 辞書アクセスを .get() に変更し KeyError 耐性を     │
│ 向上させることを推奨。                             │
├──────────────────────────────────────────────────┤
│ 対応の提案                                        │
│ - 対象 ZIP (sakura-20260528T0600.zip) の内容を    │
│   確認する                                        │
│ - store.py:87 の辞書アクセスを .get() に変更し    │
│   KeyError 耐性を向上                              │
│ - 入力データのバリデーション処理を追加して異常      │
│   データを早期検知する                              │
├──────────────────────────────────────────────────┤
│                        2026-05-28 15:00:00+00:00 │
└──────────────────────────────────────────────────┘
```

※ Email 通知なし

---

### パターン 4: 状態不明（unknown）

Discord + Email の両方に通知。

#### Bedrock 出力例

```json
{
  "business_summary": "sakura のデータ処理の状態が確認できません。調査が必要です。",
  "root_cause_hypothesis": "処理が正常に完了したかどうか確認が取れていない状態です。",
  "confidence": "low",
  "technical_observation": "Lambda 実行ログは存在するが status=error が確認できない。lambda_complete イベントに status=success の記録なし。",
  "technical_hypothesis": "処理は完了した可能性があるが、success ログの出力漏れまたは Alarm のメトリクスフィルタ条件のずれも考えられる。",
  "suggested_actions": [
    "該当時間帯の出力フォルダにファイルが生成されているか確認する",
    "Lambda の直近メトリクス (Duration, Errors) を確認する",
    "Alarm のメトリクスフィルタ条件を再確認する"
  ]
}
```

#### Discord embed

```
┌──────────────────────────────────────────────────┐
│ HDW Notify · production                     [黄] │
├──────────────────────────────────────────────────┤
│ [注意] sakura のデータ処理の状態が確認できません。 │
│ 調査が必要です。                                  │
├──────────────────────────────────────────────────┤
│ 原因の見立て                                      │
│ 処理が正常に完了したかどうか確認が取れていない     │
│ 状態です。                                        │
├──────────────────────────────────────────────────┤
│ ── 技術詳細 ──────────────────────────────────── │
├───────────────────┬──────────────┬────────────────┤
│ 監視対象システム   │ 検知アラーム  │ エラー種別      │
│ HDW_Backend_      │ hdw-sakura   │ unknown        │
│ Processor_0001    │              │                │
├───────────────────┴──────────────┴────────────────┤
│ 発生状況                                          │
│ Lambda 実行ログは存在するが status=error が確認    │
│ できない。lambda_complete イベントに               │
│ status=success の記録なし。                        │
├──────────────────────────────────────────────────┤
│ 原因分析（確度: 低）                              │
│ 処理は完了した可能性があるが、success ログの        │
│ 出力漏れまたは Alarm のメトリクスフィルタ条件の    │
│ ずれも考えられる。                                 │
├──────────────────────────────────────────────────┤
│ 対応の提案                                        │
│ - 該当時間帯の出力フォルダにファイルが生成されて   │
│   いるか確認する                                   │
│ - Lambda の直近メトリクス (Duration, Errors) を    │
│   確認する                                        │
│ - Alarm のメトリクスフィルタ条件を再確認する       │
├──────────────────────────────────────────────────┤
│                        2026-05-28 15:00:00+00:00 │
└──────────────────────────────────────────────────┘
```

#### Email（プレーンテキスト）

```
[注意] sakura のデータ処理の状態が確認できません。調査が必要です。
対象船舶: sakura
検知時刻: 2026-05-28 15:00 JST

原因の見立て:
処理が正常に完了したかどうか確認が取れていない状態です。

--- 技術詳細 ---
エラー種別: unknown
発生状況: Lambda 実行ログは存在するが status=error が確認できない。lambda_complete イベントに status=success の記録なし。
原因分析（確度: 低）: 処理は完了した可能性があるが、success ログの出力漏れまたは Alarm のメトリクスフィルタ条件のずれも考えられる。
対応の提案:
- 該当時間帯の出力フォルダにファイルが生成されているか確認する
- Lambda の直近メトリクス (Duration, Errors) を確認する
- Alarm のメトリクスフィルタ条件を再確認する
```

## 実装設計

### 1. severity 固定マッピング（`src/main.py`）

```python
ERROR_ID_SEVERITY: dict[str, str] = {
    "s3_data_missing": "MEDIUM",
    "lambda_failure": "HIGH",
    "unknown": "MEDIUM",
    "unknown_alarm": "LOW",
}
```

### 2. Bedrock 出力スキーマ変更（`src/utils/prompt.py`）

- `severity` / `summary` を削除
- `technical_observation` / `technical_hypothesis` を新設
- `root_cause_hypothesis` の制約を非技術者向けに変更

### 3. Message dataclass 更新（`src/channels/message.py`）

```python
@dataclass(frozen=True)
class Message:
    severity: str             # error_id から固定決定
    confidence: str
    business_summary: str     # Bedrock: 業務説明
    root_cause: str           # Bedrock: 原因の見立て（非技術者向け）
    technical_observation: str  # Bedrock: 発生状況（事実）
    technical_hypothesis: str   # Bedrock: 原因分析（仮説）
    actions: list[str]
    alarm_name: str
    ship_name: str
    timestamp: datetime
    error_id: str
```

### 4. Discord embed レイアウト（`src/channels/discord.py`）

上部（業務セクション）:
- title: `[severity_ja] business_summary`
- field: `原因の見立て` = root_cause

区切り + 下部（技術セクション）:
- field: `── 技術詳細 ──` (セパレータ)
- fields: `監視対象システム` / `検知アラーム` / `エラー種別` (inline)
- field: `発生状況` = technical_observation
- field: `原因分析（確度: X）` = technical_hypothesis
- field: `対応の提案` = suggested_actions

### 5. Email 構成（`src/channels/email.py`）

- Subject: `[severity_ja] business_summary`
- 本文上部: business_summary + 原因の見立て + 対象船舶 + 検知時刻
- 本文下部: `--- 技術詳細 ---` 区切り → エラー種別 + 発生状況 + 原因分析 + 対応の提案

### 6. fallback 通知の文言改善（`src/main.py`）

| 現在 | 変更後 |
|---|---|
| `AlarmName が per-ship 命名規約...` | `想定外のアラームを受信しました（対象外の監視設定の可能性あり）` |
| `config/alarm_log_groups.yml に...` | `このアラームの監視対象が未登録です（システム設定の追加が必要）` |
| `クライアントログ取得用 AssumeRole 失敗: {type}` | `ログ取得に必要な接続に失敗しました（権限設定の確認が必要: {type}）` |
| `CloudWatch Logs Insights 取得失敗: {status}` | `ログの検索に失敗しました（状態: {status}）` |
| `CloudWatch Logs Insights 取得がタイムアウトしました` | `ログの検索が時間内に完了しませんでした` |
| `LLM 分析失敗のためコア情報のみ通知: {type}` | `自動分析ができませんでした。基本情報のみお知らせします（{type}）` |

## 修正対象ファイル

| ファイル | 変更内容 |
|---|---|
| `src/utils/prompt.py` | スキーマ変更（severity/summary 削除、technical_observation/hypothesis 新設） |
| `src/channels/message.py` | dataclass フィールド更新 |
| `src/main.py` | severity 固定マッピング、_normalize_report 更新、extra_note 文言改善 |
| `src/channels/discord.py` | 業務/技術セクション分離レイアウト |
| `src/channels/email.py` | 業務/技術セクション分離構成 |
| `tests/` | 全テストファイルの make_message 更新 |
