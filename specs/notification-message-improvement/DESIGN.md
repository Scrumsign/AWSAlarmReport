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
  "business_action": "業務担当者が次に取るべき行動 (100文字以内、技術用語禁止)",
  "confidence": "low | medium | high",
  "technical_observation": "ログから確認できた技術的事実 (250文字以内、簡潔に)",
  "technical_hypothesis": "技術的な原因仮説と対処の方向性 (250文字以内、簡潔に)",
  "technical_actions": ["技術担当者向けの対処 最大3件、各80字以内"]
}
```

**削除フィールド:**
- `severity` → error_id から固定で決定するため Bedrock に判断させない
- `summary` → `technical_observation` に役割を統合

**変更フィールド:**
- `root_cause_hypothesis` → 非技術者向けに制約変更（技術用語禁止、100文字以内）
- `suggested_actions` → `technical_actions` にリネーム（技術者向けに役割を明確化）

**新設フィールド:**
- `business_action` — 業務担当者が次に取るべき行動（確認事項 + 技術担当へのエスカレーション）。非技術者向け
- `technical_observation` — ログから読み取れた技術的事実（例外クラス、発生箇所、エラーメッセージ）
- `technical_hypothesis` — 技術的な原因仮説と対処の方向性（仮説、コード修正提案）

**フィールドと受信者の対応:**

| 区分 | フィールド | 通知での表示 |
|---|---|---|
| 業務（上部） | business_summary | embed タイトル / メール件名 |
| 業務（上部） | root_cause_hypothesis | 原因の見立て |
| 業務（上部） | business_action | ご対応のお願い |
| 技術（下部） | technical_observation | 発生状況 |
| 技術（下部） | technical_hypothesis | 原因分析（確度: X） |
| 技術（下部） | technical_actions | 対応の提案（技術） |

### プロンプト指示

```
# business_summary
- 100 文字以内。非技術者向け
- AWS 用語・技術用語（Lambda、Alarm、S3、CloudWatch 等）は使わない
- 「ファイル処理」「データ」「送信」など受信者が理解できる日本語で書く
- 「何が起きたか」と「業務にどう影響するか」を伝える（具体的な行動は business_action へ）
- 例: 「sakura のデータ処理中にエラーが発生しました。出力データが欠損している可能性があります。」

# root_cause_hypothesis
- 100 文字以内。原因を非技術者にも分かる言葉で説明する
- コード参照（ファイル名、行番号、関数名）やAWS用語は使わない
- 「何が原因で」「どうなったか」を業務の言葉で伝える
- 例: 「送信されたファイルの形式に問題があり、正しく処理できませんでした。」
- 例: 「ファイルが届いていないため、処理が開始されていません。」

# business_action
- 100 文字以内。業務担当者が「次に何をすべきか」を示す
- AWS 用語・技術用語・コード参照は使わない
- 「業務側で確認できること」と「技術担当へ共有・相談すべきか」を伝える
- 放置でよいのか確認が要るのかを明確にし、受信者が迷わないようにする
- 例: 「最新の処理結果が届いているかご確認ください。問題があれば技術担当へ共有してください。」

# confidence
- low / medium / high

# technical_observation
- 250 文字以内、できるだけ簡潔に。ログから読み取れた技術的事実のみ
- 例外クラス名、発生箇所（file:line）、エラーメッセージを含める
- 仮説や推測は含めない。観測できた事実だけを書く。文を途中で切らない
- 例: 「store.py:87 で KeyError('data') が発生。request_id=abc123 の実行で
  frontend_paths['data'][key] へのアクセス時に例外。」

# technical_hypothesis
- 250 文字以内、できるだけ簡潔に。技術的な原因の仮説と対処の方向性
- もっともらしい順に複数仮説を並べてよい。文を途中で切らない
- コード修正レベルの指摘を歓迎する
- 例: 「入力 ZIP 内のデータ構造が想定と異なる可能性が高い。
  store.py:87 の辞書アクセスを .get() に変更し KeyError 耐性を向上させることを推奨。」

# technical_actions の制約
- 技術担当者向けの具体的な対処。各項目 80 文字以内、最大 3 件
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
  "business_action": "ファイルが送信済みかご確認ください。送信済みであれば技術担当へお知らせください。",
  "confidence": "medium",
  "technical_observation": "直近 5h30m の時間窓に Lambda 実行ログが 0 件。error / success いずれのステータスも記録されていない。",
  "technical_hypothesis": "最有力: 上流からの ZIP アップロードが未到着。副次: S3 イベント通知設定の破損により Lambda が起動しなかった可能性。",
  "technical_actions": [
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
│ ご対応のお願い                                    │
│ ファイルが送信済みかご確認ください。送信済みで     │
│ あれば技術担当へお知らせください。                 │
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
│ 対応の提案（技術）                                │
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
  "business_action": "sakura の最新の処理結果が届いているかご確認のうえ、技術担当へ共有してください。",
  "confidence": "high",
  "technical_observation": "store.py:87 で KeyError('data') が発生。request_id=abc123 の実行で frontend_paths['data'][key] へのアクセス時に例外。",
  "technical_hypothesis": "入力 ZIP 内のデータ構造が想定と異なる可能性が高い。特定 ZIP 依存の問題と推定。store.py:87 の辞書アクセスを .get() に変更し KeyError 耐性を向上させることを推奨。",
  "technical_actions": [
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
│ ご対応のお願い                                    │
│ sakura の最新の処理結果が届いているかご確認の      │
│ うえ、技術担当へ共有してください。                 │
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
│ 対応の提案（技術）                                │
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

本番ログ（sakura, 2026-05-27）での実 Bedrock 出力例:

```json
{
  "business_summary": "sakura のデータ処理は最後まで完了しているように見えますが、完了確認の記録がないため監視側で異常と判定されました。",
  "root_cause_hypothesis": "処理は正常終了しているものの、完了を示す合図が監視側に届かず、エラー扱いになった可能性があります。",
  "business_action": "出力データが届いているかをご確認ください。届いていれば業務影響はありません。念のため技術担当へ共有してください。",
  "confidence": "medium",
  "technical_observation": "23:02 セッション(request_id=abc123)は extraction→validation→store→Bayesian→Glasso→SD Score→saved to s3→lambda complete まで到達。エラーログ・例外は無し。ただし success ステータス出力が欠落しており、Alarm の閾値判定 (success<1) を下回った。",
  "technical_hypothesis": "処理本体は正常完了しているが、success ログ (status=\"success\") の出力がスキップまたは欠落している可能性が高い。lambda complete 直前のロギング処理に条件分岐や例外抑制があり、メトリクス用の success 出力に到達していない疑い。Alarm 判定ロジックと実装の整合性確認が必要。",
  "technical_actions": [
    "出力 S3 オブジェクトの実体と更新時刻を確認し処理完了の事実を裏付ける",
    "lambda_handler 終端の success ログ出力箇所を確認し条件分岐や例外握り潰しを精査",
    "success ログ出力を lambda complete と同階層で無条件に行うよう恒久修正"
  ]
}
```

#### Discord embed

```
┌────────────────────────────────────────────────────────┐
│ HDW Notify · prod                                  [黄] │
├────────────────────────────────────────────────────────┤
│ [注意] sakura のデータ処理は最後まで完了しているように  │
│ 見えますが、完了確認の記録がないため監視側で異常と       │
│ 判定されました。                                         │
├────────────────────────────────────────────────────────┤
│ 原因の見立て                                            │
│ 処理は正常終了しているものの、完了を示す合図が監視側に   │
│ 届かず、エラー扱いになった可能性があります。             │
├────────────────────────────────────────────────────────┤
│ ご対応のお願い                                          │
│ 出力データが届いているかをご確認ください。届いていれば   │
│ 業務影響はありません。念のため技術担当へ共有してください。│
├────────────────────────────────────────────────────────┤
│ ── 技術詳細 ──                                          │
├──────────────────┬───────────────┬─────────────────────┤
│ 監視対象システム  │ 検知アラーム   │ エラー種別           │
│ HDW_Backend_     │ hdw-sakura    │ unknown             │
│ Processor_0001   │               │                     │
├──────────────────┴───────────────┴─────────────────────┤
│ 発生状況                                                │
│ 23:02 セッション(request_id=abc123)は extraction→     │
│ validation→store→...→lambda complete まで到達。         │
│ エラーログ・例外は無し。ただし success ステータス出力が  │
│ 欠落しており、Alarm の閾値判定 (success<1) を下回った。  │
├────────────────────────────────────────────────────────┤
│ 原因分析（確度: 中）                                    │
│ 処理本体は正常完了しているが、success ログの出力が       │
│ スキップまたは欠落している可能性が高い。...              │
├────────────────────────────────────────────────────────┤
│ 対応の提案（技術）                                      │
│ - 出力 S3 オブジェクトの実体と更新時刻を確認し...        │
│ - lambda_handler 終端の success ログ出力箇所を確認し...  │
│ - success ログ出力を lambda complete と同階層で...       │
├────────────────────────────────────────────────────────┤
│                                  2026-05-27 23:02:30 UTC │
└────────────────────────────────────────────────────────┘
```

#### Email（プレーンテキスト）

```
[注意] sakura のデータ処理は最後まで完了しているように見えますが、完了確認の記録がないため監視側で異常と判定されました。
対象船舶: sakura
検知時刻: 2026-05-28 08:02 JST

原因の見立て:
処理は正常終了しているものの、完了を示す合図が監視側に届かず、エラー扱いになった可能性があります。

ご対応のお願い:
出力データが届いているかをご確認ください。届いていれば業務影響はありません。念のため技術担当へ共有してください。

--- 技術詳細 ---
エラー種別: unknown
発生状況: 23:02 セッション(request_id=abc123)は extraction→...→lambda complete まで到達。エラーログ・例外は無し。ただし success ステータス出力が欠落しており、Alarm の閾値判定 (success<1) を下回った。
原因分析（確度: 中）: 処理本体は正常完了しているが、success ログの出力がスキップまたは欠落している可能性が高い。...
対応の提案（技術）:
- 出力 S3 オブジェクトの実体と更新時刻を確認し処理完了の事実を裏付ける
- lambda_handler 終端の success ログ出力箇所を確認し条件分岐や例外握り潰しを精査
- success ログ出力を lambda complete と同階層で無条件に行うよう恒久修正
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
- `business_action` / `technical_observation` / `technical_hypothesis` を新設
- `suggested_actions` を `technical_actions` にリネーム
- `root_cause_hypothesis` の制約を非技術者向けに変更

### 3. Message dataclass 更新（`src/channels/message.py`）

```python
@dataclass(frozen=True)
class Message:
    severity: str                # error_id から固定決定
    confidence: str
    business_summary: str        # Bedrock: 業務説明
    root_cause: str              # Bedrock: 原因の見立て（非技術者向け）
    business_action: str         # Bedrock: 業務担当者が取るべき行動
    technical_observation: str   # Bedrock: 発生状況（事実）
    technical_hypothesis: str    # Bedrock: 原因分析（仮説）
    technical_actions: list[str]  # Bedrock: 技術的な対処（最大3件）
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
