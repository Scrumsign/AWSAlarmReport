---
id: bedrock-prompt-generalization
version: 0.5.0
title: Bedrock アラーム原因解析プロンプトの汎用化 (health_signal 抽象化)
created_at: 2026-05-22
type: spec
status: draft
---

# Bedrock アラーム原因解析プロンプトの汎用化 (health_signal 抽象化)

- **ID**: bedrock-prompt-generalization
- **Version**: 0.5.0
- **Created at**: 2026-05-22
- **Authors**: scrumsign-takuyakimura
- **Constitution**: main@1.0.0
- **Dependencies**: cross-account-architecture (踏襲)
- **Status**: draft

> **NOTE**: spec.id / ディレクトリ名は仮称。残る命名スロット `<CONTEXT_PREFIX>` / `<PROFILE_FILE>` は O-6 で実名化する。

> **本仕様と原文 issue の関係**: 本仕様は原文 issue「[設計] Bedrock アラーム原因解析プロンプトの汎用化（health_signal 抽象化）」を実装計画として具体化したものである。原文と一致する部分・命名や構造を改めた部分・原文未規定で本仕様が新設した部分があり、各セクションに `> **原文対応**:` ブロックで明示する。

## 全体概要

Bedrock への入力を 2 層に分離し、システムプロンプトを監視対象非依存の「メタ手続き」へ昇格させ、運用 Lambda 固有情報を「リソースプロファイル」というデータに外出しする。

- **静的: システムプロンプト** (メタ手続きのみ、監視対象固有語彙ゼロ)
- **動的: 動的コンテキスト** (アラームごとに合成する user prompt)

> **原文対応**: 原文「概要 — この issue がやろうとしていること」「手順（変わらない）」「材料（毎回変わる）」と完全に一致する 2 層分離方針。原文「全体の処理フロー（概念図）」mermaid とも同じ。

### 構成上の主要な決定

| 軸 | 決定 | 原文との関係 |
|---|---|---|
| 設定の 2 分岐 | `configs/<正規化 alarm 名>.yaml` (AWS インフラ情報) + `profile.yaml` (観測ロジック) + `DISCORD_WEBHOOK_URLS` (webhook 配信先) | 原文「確認事項#1 (プロファイル格納先)」を「リポジトリ内 YAML (configs/) + 運用 Lambda S3 (profile)」で確定。AWS インフラ情報と観測ロジックの分離は本仕様の新設 |
| `-test` 正規化 | alarm 名で引かれる全対応表で正規化を経て同一キーとして扱う不変条件 | 本仕様の新設。原文には無いが、原文「概念図」の `hdw-sakura-test` の扱いを明確化 |
| signal の構造 | profile.signal_kind は配列、`type` (verdict/ignored) で discriminated union | 原文の `health_signals` 辞書 + `secondary_signals` リストを本仕様で統合・配列化・命名変更 |
| severity の所在 | profile.signal_kind[type=verdict] の必須フィールド (max_severity_on_success / severity_on_absence) | 原文「2. health_signal 抽象化」の severity 規約 + 原文「参考スキーマ」の severity フィールドを統合 |
| フォールバック 2 系統 | (a) profile 未登録/取得失敗 (b) signal_kind 解決失敗 → fallback_generic で続行 | 原文「実装タスク」のフォールバック処理項目 + 原文「4. 解決失敗時の扱い」と一致 |
| Phase A | profile YAML を運用 Lambda の既存 S3 に手動配置、運用 Lambda 側のコード/CI/CD は改修しない | 本仕様の新設。原文では格納先未決 |

## 処理フロー

```
SNS event → alarm_name 抽出
   ↓
load_config(alarm_name) → configs/<正規化名>.yaml を Config dataclass にロード
   ↓
STS AssumeRole(config.assume_role_arn)
   ↓
S3 GetObject(config.profile_location) → profile YAML
   ↓
resolve_signal_kind(alarm_name, profile)
   = profile.signal[] で alarm 名 → kind 名を引き、
     profile.signal_kind[] で実体取得 (見つからなければ fallback_generic)
   ↓
CloudWatch Logs Insights 取得 (config.log_group + profile.input_identifiers)
   ↓
render_dynamic_context(alarm 情報 + 解決済み signal_kind + ignored 系 +
                      input_identifiers + 調査時間窓 + 整形済みログ)
   ↓
Bedrock Converse (STATIC_SYSTEM_PROMPT + 動的コンテキスト)
   ↓
normalize_bedrock_response + apply_severity_policy
   ↓
render_report_embed (Title / Target / ResearchWindow / Alarm + Report + Action)
   ↓
resolve_webhook_url(alarm_name) → Discord 通知
```

> **原文対応**: 原文「処理フロー（呼び出し側オーケストレーター）」の擬似コードに以下を追加:
> - `load_config()` 経由の Config 取得 (原文では function_name 直接、本仕様では alarm_name 経由)
> - AssumeRole / S3 GetObject (原文では「レジストリから profile を引き当て」と抽象化されていた箇所の具体化)
> - severity 補正 (原文の severity 規約をコード側で実装)
> - webhook URL 解決 (本仕様で新設)
>
> その他の主要ステップ (signal_selector 解決、動的コンテキスト組み立て、Bedrock 呼び出し、レンダリング、通知) は原文と 1:1 対応。

## 主要 definitions

| 用語 | 説明 | 原文との関係 |
|---|---|---|
| **オーケストレーター** | アラーム受信〜通知までを担う Reporter Lambda 上の Python 実装。 | 原文用語集と一致 |
| **メタ手続き** | 「権威シグナルを読んで verdict 3 分岐」のアルゴリズム。 | 原文用語集と一致。本仕様で REQ-001 に取り込む |
| **システムプロンプト (静的)** | Bedrock system に渡す不変文字列。 | 原文用語集と一致 |
| **動的コンテキスト** | Bedrock messages に渡す user prompt。6 セクション合成。 | 原文用語集 + 原文「動的コンテキスト」テンプレと一致 |
| **リソースプロファイル (profile)** | 運用 Lambda 1 個分の観測契約 (YAML)。 | 原文用語集と一致。配置場所 (運用 Lambda S3) は本仕様の選択 |
| **signal_kind** | profile 内のフィールド。signal 種別の定義カタログ (配列)。 | 原文 `health_signals` (辞書) + `secondary_signals` (リスト) を統合・配列化・命名変更 |
| **signal (profile 内)** | profile 内のフィールド。正規化後 alarm 名 → signal_kind 名 のマッピング配列。 | 原文「4. signal_selector」の「alarm_name → selector のマッピング表」を採用し、profile 内に配置 |
| **verdict** | Bedrock の解析結論。healthy / failed / absent の 3 値。 | 原文用語集と一致 |
| **severity** | 緊急度 (HIGH/MEDIUM/LOW)。 | 原文「2. health_signal 抽象化」の severity 規約と一致 |
| **failure_taxonomy** | verdict=failed の原因分類 (b1〜b4)。 | 原文用語集と一致 |
| **pre_classification** | 動的コンテキスト内の補助フィールド。解決済み signal_kind.name そのまま。 | 原文用語集と「動的コンテキスト」テンプレに存在するが、原文では「signal_selector 解決の入力候補」として位置付け。本仕様では「Bedrock への補助ヒント (出力側)」に再定義 |
| **configs/ ディレクトリ** | リポジトリ内、1 alarm = 1 YAML。AWS インフラ情報のみ。 | 本仕様で新設。原文未記載 |
| **Config (dataclass)** | load_config の戻り値型 (frozen, slots)。9 フィールド。 | 本仕様で新設。configs/ YAML を型付きで扱うため |
| **load_config()** | alarm_name → 正規化 → configs/<...>.yaml を読み Config を返す関数。 | 本仕様で新設。原文の「レジストリから profile を引き当て」を 2 段構成 (Config → profile) に分割 |
| **normalize_alarm_name()** | alarm 名末尾 "-test" を除去する純関数。 | 本仕様で新設。-test 統合不変条件の単一実装点 |
| **DISCORD_WEBHOOK_URLS** | Lambda の唯一の env var。JSON 文字列で正規化後 alarm 名 → URL の辞書。 | 本仕様で新設。原文では通知配信先について未記載 |
| **fallback_generic** | REQ-008 のフォールバックで使う汎用 signal_kind 定数。 | 原文「実装タスク (a)(b) いずれも Errors メトリクス + traceback を既定 health_signal とする」を具体化 |
| **Phase A** | 初期実装フェーズ (profile を手動配置、運用 Lambda 側変更なし)。 | 本仕様で新設。所有権移譲の段階化は原文未記載 |

## "-test" 統合不変条件 (全域に効く)

alarm 名で引かれる全対応表は正規化後 alarm 名 (末尾 "-test" 除去後) をキーとする。適用対象:

- `configs/<正規化名>.yaml` のファイル名
- `DISCORD_WEBHOOK_URLS` の辞書キー
- `profile.signal[].name` のキー
- その他 alarm 名で引かれる全対応表

意図: test/prod の運用設定を二重管理しない。CloudWatch 上の alarm 名自体は別物 (`hdw-sakura-test`) として残るが、Reporter 側では同一として扱う。embed 表記で test/prod を区別する場合は alarm 名末尾から `derive_env_label()` で導出する。

> **原文対応**: 本仕様で新設の不変条件。原文には無いが、原文「概念図」で `hdw-sakura-test` が `signal_selector = completion_success` を引いていることと整合する。本仕様では設計全域に拡張した。

## Open Decisions

| ID | タイトル | 候補 | current_lean | 原文との関係 |
|---|---|---|---|---|
| O-4 | failure_taxonomy を profile で上書き可能にするか | システム固定 / 部分上書き可 | システム固定 | 原文「確認事項 #2」と一致 |
| O-5 | 同一 Lambda の同時発火時の通知粒度 | 独立通知 / 1 通集約 | 独立通知 | 原文「確認事項 #5」と一致 |
| O-6 | 命名スロットの実名 (`<CONTEXT_PREFIX>` / `<PROFILE_FILE>`) | — | 未確定 | 本仕様で新設 |

> **原文対応**: 原文「確認事項 / 未決事項」5 項目のうち #1 (格納先) / #3 (キー設計) / #4 (selector 解決方針) は本仕様 v0.4.0 以前で確定済 (definitions / REQ で反映)。#2 / #5 は未確定のまま継続。

## profile スキーマ完全形

profile YAML の構造を正規仕様としてまとめる。本セクションは REQ-002 の規範であり、具体的な値の例は PLAN.md「profile YAML 具体例」を参照。

### トップレベル構造

```yaml
function_name: <str>            # 必須
signal_kind:                    # 必須、空でない配列
  - <signal_kind entry>
  - ...
signal:                         # 必須、空でも可
  - <signal entry>
  - ...
input_identifiers:              # 必須、空でない配列
  - <str>
  - ...
```

### `signal_kind` エントリ (discriminated union by `type`)

#### 共通必須フィールド (全 type で共通)

| フィールド | 型 | 必須 | 説明・制約 |
|---|---|---|---|
| `name` | str | ✓ | signal_kind の識別子。signal_kind 配列内で一意 |
| `type` | enum | ✓ | `verdict` / `ignored` のいずれか (discriminator) |
| `mechanism` | enum | ✓ | `log_marker` / `metric` / `structured_result` のいずれか |
| `locator` | str | ✓ | どこを見るか (自然言語の指示) |

#### `type: verdict` 専用フィールド (全て必須)

| フィールド | 型 | 必須 | 説明・制約 |
|---|---|---|---|
| `success_condition` | str | ✓ | 成功と判定する条件 (Bedrock が読む) |
| `failure_condition` | str | ✓ | 失敗と判定する条件 (Bedrock が読む) |
| `absence_hypothesis` | str | ✓ | 不在時の仮説 (Bedrock が読む) |
| `max_severity_on_success` | enum | ✓ | `LOW` / `MEDIUM` / `HIGH` のいずれか。verdict=healthy 時の clamp 上限 |
| `severity_on_absence` | enum | ✓ | `LOW` / `MEDIUM` / `HIGH` のいずれか。verdict=absent 時の固定値 |

#### `type: ignored` 専用フィールド (必須)

| フィールド | 型 | 必須 | 説明・制約 |
|---|---|---|---|
| `description` | str | ✓ | なぜ障害根拠としないかの説明 (Bedrock が読む) |

> `type: ignored` には `success_condition` / `failure_condition` / `absence_hypothesis` / severity フィールドが**存在してはならない**。verdict 判定に使わないため意味を成さない。

### `signal` エントリ

| フィールド | 型 | 必須 | 説明・制約 |
|---|---|---|---|
| `name` | str | ✓ | 正規化後 alarm 名。`-test` 末尾を含まないこと。配列内で一意 |
| `kind` | str | ✓ | `signal_kind[].name` に存在する文字列。指す signal_kind は `type=verdict` でなければならない |

### `input_identifiers`

| 制約 | 内容 |
|---|---|
| 型 | list[str] |
| 空配列 | 不可 (スキーマ違反) |
| 要素の型 | str (空文字列不可) |

### 整合性制約 (検証関数で検査)

1. `signal_kind[].name` は配列内で重複なし
2. `signal[].name` は配列内で重複なし
3. `signal[].name` は `-test` 末尾を含まない (正規化済みのみ許容)
4. `signal[].kind` は `signal_kind[].name` のいずれかに存在
5. `signal[].kind` が指す `signal_kind` は `type=verdict` でなければならない (ignored を指してはならない)
6. `type=verdict` のエントリは `max_severity_on_success` / `severity_on_absence` を必須に持つ
7. `type=ignored` のエントリは `description` を必須に持つ

違反時の挙動: いずれも `ProfileSchemaError` (本仕様で定義する例外クラス) として扱い、main 側で REQ-008 (a) フォールバック (`fallback_generic`) に倒す。

### 「コード側で使う」と「Bedrock に渡すだけ」の区分

| 区分 | フィールド |
|---|---|
| コード側で if / 辞書引き / ループに使う | `function_name` / `signal_kind[].name` / `signal_kind[].type` / `signal_kind[].mechanism` / `signal[].name` / `signal[].kind` / `input_identifiers` / `max_severity_on_success` / `severity_on_absence` |
| Bedrock に文字列として渡すだけ | `signal_kind[].locator` / `success_condition` / `failure_condition` / `absence_hypothesis` / `description` |

> **原文対応**: 本セクションは REQ-002 の規範をまとめたもの。原文「3. リソースプロファイルのレジストリ化」+「参考スキーマ」を本仕様で再構成 (健康/非健康シグナルの統合、配列化、`type`/`mechanism` の命名変更、severity の signal_kind 内必須化) した結果を、スキーマ単体として独立記述した。具体的な値の例は PLAN.md「profile YAML 具体例」を参照。

## Requirements

### REQ-001: システムプロンプトと動的コンテキストを分離する

Bedrock 入力を 2 層に分け、システムプロンプト側に監視対象固有語彙を含めない。

**含めるもの**: メタ手続き / severity 既定規則 / failure_taxonomy b1〜b4 / 出力 JSON スキーマ + 字数制限 / secondary_signals 不使用指示。

**含めないもの**: 特定 Lambda 名、特定ログイベント名、特定エラーメッセージ、ship_name 等の運用識別子。

**動的コンテキストの 6 セクション** (順序固定):
1. アラーム情報 (alarm_name / alarm_description / fire_time / pre_classification)
2. 解決済み権威シグナル (signal_kind 1 個)
3. ignored 系シグナル列
4. input_identifiers
5. 調査時間窓
6. 抽出ログ

**AC**:
- AC-001-1: 禁則語が STATIC_SYSTEM_PROMPT に 0 件
- AC-001-2: 必須語が含まれる (b1〜b4 / severity 規約 / JSON スキーマ enum 値)
- AC-001-3: 動的コンテキストの 6 セクションヘッダが期待順に登場

> **原文対応**: 原文「概要 / 手順（変わらない）= システムプロンプト」「材料（毎回変わる）= 動的コンテキスト」+ 原文「実装タスク 1, 2」+ 原文「2. health_signal 抽象化」と一致。動的コンテキストの 6 セクション順序は原文「動的コンテキスト」テンプレに準拠 (ただし本仕様では `secondary_signals / input_identifiers` を 2 セクションに分離)。AC-001-2 の「b1〜b4 を含める」は原文「実装タスク」の「既定 failure_taxonomy（b1〜b4）を含む」を AC として担保。

### REQ-002: profile スキーマ

**トップレベル**: `function_name` / `signal_kind` (list) / `signal` (list) / `input_identifiers` (list[str])。

**signal_kind 各エントリ (共通必須)**: `name` / `type` (verdict|ignored) / `mechanism` (log_marker|metric|structured_result) / `locator`。

**type=verdict 追加 (必須)**: `success_condition` / `failure_condition` / `absence_hypothesis` / `max_severity_on_success` / `severity_on_absence`。

**type=ignored 追加 (必須)**: `description`。

**signal 各エントリ**: `name` (正規化後 alarm 名) / `kind` (signal_kind.name 参照)。

**整合性制約**:
- `signal[].kind` は `signal_kind[].name` に存在し、かつ `type=verdict` のもの
- `signal[].name` は `-test` 末尾を含まない
- 各配列内で name 重複なし

**AC**: フィールド欠落 / enum 違反 / 整合性違反 / `-test` 末尾混入 で個別に ProfileSchemaError。

> **原文対応**: 原文「3. リソースプロファイルのレジストリ化」+ 原文「参考スキーマ (HDW_Backend_Processor_0001 例)」を再構成。
> - `health_signals` (辞書) → `signal_kind` (配列) に変更。配列化で各エントリに `name` を持たせる
> - `secondary_signals` (フラット文字列リスト) → `signal_kind[type=ignored]` に統合 (構造化される)
> - `signal_selector` 解決のためのマッピング表 → `signal` フィールド (配列) として profile 内に同居
> - 原文の `type` (log_marker/metric/structured_result) → `mechanism` に改名 (verdict/ignored discriminator として `type` を使うため)
> - `max_severity_on_success` / `severity_on_absence` を必須化 (原文では参考スキーマで存在するが必須性は不明確)。詳細は REQ-009 参照
> - 構造変更の意図は本仕様の設計判断であり、原文の意図 (1 Lambda 多観点監視 + 1 alarm = 1 signal) を変えない

### REQ-003: profile を運用 Lambda の既存 S3 に配置する

profile YAML は運用 Lambda の既存 S3 バケットの `<CONTEXT_PREFIX>` 配下に配置。Phase A は Reporter 担当が手動 put。運用 Lambda 側の関数コード zip / image / 実行 IAM Role / CI/CD パイプライン定義に変更を加えない。

運用 Lambda チームへの依頼は、bucket policy / KMS CMK / lifecycle 確認に限る。

**AC**: AssumeRole 後の S3 client で GetObject 可能、運用 Lambda 側の差分ゼロ。

> **原文対応**: 原文「確認事項 #1 (プロファイル格納先: SSM Parameter Store / DynamoDB / リポジトリ内 JSON のどれにするか)」に対する本仕様の回答。3 候補のいずれでもなく「運用 Lambda の既存 S3」を選択している。理由は所有権分離 (運用 Lambda チームが profile の中身を所管) と既存の cross-account-architecture 経路の踏襲。

### REQ-004: alarm 名から Config を引き当てる (load_config + configs/*.yaml)

configs/<正規化 alarm 名>.yaml から `load_config()` で AWS インフラ情報を引き当てる。中央集権的なレジストリインデックスは持たない。

**configs/*.yaml の必須 9 フィールド** (Config dataclass と 1:1):

```
function_name                            (str)
account_id                               (str)
aws_region                               (str)
assume_role_arn                          (str)
log_group                                (str)
profile_location                         (str, S3 URI)
bedrock_model_id                         (str)
bedrock_max_tokens                       (int)
cloudwatch_logs_query_poll_interval_sec  (float)
```

configs/*.yaml には observation 系 (signal_kind 名等) を一切書かない。

既存の `config/alarm_log_groups.yml` は削除。

**AC**: 外部 I/O なしで Config を返す / `-test` 正規化動作 / 不在・スキーマ違反で明示例外 / Config に observation 系フィールドが無い (責務分離)。

> **原文対応**: 原文「確認事項 #3 (レジストリのキー設計を function_name 単位とし、アラーム差分は signal_selector で吸収する方針で確定してよいか)」に対する本仕様の回答。原文は function_name キーを提案したが、本仕様では alarm_name キー (configs/<正規化名>.yaml) を採用。理由:
> - 1 alarm = 1 ファイルで運用設定 (AWS インフラ情報) を独立管理したい
> - profile (function_name 単位) は別途存在し、配置先 (S3) も別なので機能的には等価
> - configs/ と profile の責務分離 (AWS インフラ ↔ 観測ロジック) を強化
>
> 原文の意図 (1 alarm = 1 signal_kind の対応、selector で吸収) は configs/<alarm>.yaml.profile_location + profile.signal[] のチェーンで実現。

### REQ-005: signal_kind を呼び出し側コードで決定論的に解決する

```
1. normalized = normalize_alarm_name(alarm_name)
2. signal_entry = profile.signal で name == normalized なものを探す
3. 見つからない → REQ-008 (b) フォールバック
4. kind_name = signal_entry.kind
5. signal_kind = profile.signal_kind で name == kind_name なものを探す
6. 見つからない / type != verdict → REQ-008 (b) フォールバック
7. 解決した signal_kind 1 個のみを動的コンテキストに埋め込む
```

ignored 系は別途 `profile.signal_kind` から `type=ignored` を全抽出し、動的コンテキストの「障害根拠としない情報」セクションに含める。

**AC**: 動的コンテキストの権威シグナルは常に 1 個 / 解決失敗 3 系統で REQ-008 (b) / 正規化前の生 alarm 名で引かない。

> **原文対応**: 原文「4. (リソース × アラーム) によるシグナル選択 — signal_selector」+ 原文「確認事項 #4 (signal_selector の解決を呼び出し側コードで行う方針（案A）で確定してよいか)」に対応。
> - 原文 #4 を採用 (案 A 確定)
> - 原文では `signal_selector` の値の出どころとして 3 候補 (CloudWatch アラームのタグ / alarm_name → selector のマッピング表 / pre_classification からの導出) が挙げられていた。本仕様では「alarm_name → selector のマッピング表」を採用し、その表を `profile.signal[]` として profile 内に配置
> - 原文「解決失敗時の扱い」(signal_selector 未設定 or キー不在) を本仕様 REQ-008 (b) で扱う
> - 「LLM には解決済みの health_signal を 1 個だけ渡し、どれを使うかの判断は LLM にさせない」を AC-005-1 で担保

### REQ-006: Insights クエリを input_identifiers から動的に生成する

- `fields` 句: 既定固定フィールド + input_identifiers を結合
- `filter` 句: input_identifiers の先頭フィールドを絞り込みキー

絞り込み値は v1 では「SNS event の AlarmName から正規表現で抽出した識別子値」(現状の ship_name 相当)。クエリ自体の設計・最適化はスコープ外。

**AC**: input_identifiers 差し替えでクエリ動的変化 (Python コード差分なし) / 空配列でスキーマ違反。

> **原文対応**: 原文「参考スキーマ」の `input_identifiers: [ship_name, ship_timestamp, input_key]` を「Bedrock に渡すだけ」ではなく「コード側でクエリ生成に使う」と明示。原文「スコープ外」の「CloudWatch Logs Insights のクエリ自体の設計・最適化（既存の抽出処理を流用）」を尊重しつつ、固定フィールド名のハードコードを撤去する範囲のみを対象とする。

### REQ-007: 出力 JSON スキーマと字数制限を統一する

```json
{
  "verdict":    "healthy" | "failed" | "absent",
  "severity":   "HIGH" | "MEDIUM" | "LOW",
  "confidence": "high" | "medium" | "low",
  "summary":    "string (<= 80 字。冒頭で verdict 識別)",
  "detail":     "string (<= 300 字)",
  "actions": [
    { "phase": "即時対応" | "調査手順" | "恒久対策",
      "text":  "string (<= 80 字)" }
  ]
}
```

旧 `root_cause_hypothesis` / `suggested_actions` は廃止 (REQ-012)。

字数制限はシステムプロンプト明記 + コード側 truncate で二重防御。

**AC**: キー集合が一致 / 字数 truncate / actions[].phase enum 違反スキップ。

> **原文対応**: 原文「5. 出力とレンダリングの分離」+ 原文「出力 JSON スキーマ」と完全一致。字数制限 (`<= 80字` / `<= 300字`) は原文どおり。AC-007-2 の truncate (コード側の二重防御) は本仕様で追加 (原文では字数制限を明記するのみ)。

### REQ-008: フォールバックを 2 系統で実装し、汎用 signal_kind で続行する

**(a) プロファイル未登録時**: configs 不在、configs スキーマ違反、profile S3 取得失敗、profile スキーマ違反。

**(b) signal_kind 解決失敗時**: signal[] にエントリ無し、kind 名が signal_kind[] に不在、指された kind の type != verdict。

**fallback_generic** (コード定数):

```yaml
name: fallback_generic
type: verdict
mechanism: metric
locator: 'CloudWatch メトリクス AWS/Lambda Errors'
success_condition: '時間窓内に Errors > 0 のサンプルが存在しない'
failure_condition: 'Errors > 0、または stack_trace/traceback が抽出ログに存在'
absence_hypothesis: 'Lambda invocation 自体が発生しておらず、メトリクスもログも生成されていない可能性'
max_severity_on_success: MEDIUM
severity_on_absence: MEDIUM
```

Discord embed footer に `fallback: profile_missing` / `fallback: signal_unresolved` の印を表示。

**AC**: (a) 4 ケースで通知欠落なし + 印 / (b) 3 ケースで通知欠落なし + 印が (a) と区別 / 既存の AssumeRole/Insights/Bedrock 失敗 fallback と非干渉。

> **原文対応**: 原文「実装タスク フォールバック処理の実装。次の2系統を区別する: (a) プロファイル未登録時 (b) signal_selector 解決失敗時（未設定 / キー不在）。いずれも Errors メトリクス + traceback を既定 health_signal とする」を具体化。
> - 2 系統の区別は原文どおり
> - 原文の「Errors メトリクス + traceback」を `fallback_generic` 定数として具体スキーマ化
> - 通知欠落させない方針は原文「4. 解決失敗時の扱い (アラームを解析不能で落とさない)」と一致
> - フォールバック印 (footer に "fallback: ..." 表示) は本仕様で追加

### REQ-009: severity を signal_kind のポリシーで補正する

- `verdict == "healthy"`: severity を `signal_kind.max_severity_on_success` で clamp
- `verdict == "absent"`: severity を `signal_kind.severity_on_absence` で上書き、confidence=low
- `verdict == "failed"`: 補正なし (HIGH のまま)

clamp ロジック: HIGH > MEDIUM > LOW の順序、ceiling より上を ceiling に丸める。

**AC**: healthy で HIGH→MEDIUM clamp / absent で severity 上書き + confidence=low / failed で不変。

> **原文対応**: 原文「2. health_signal 抽象化」の severity 規約 (verdict=healthy は最大 MEDIUM、failed は HIGH、absent は MEDIUM + confidence=low) と一致。
> - 「最大 MEDIUM」を `max_severity_on_success` フィールドで明示し、コード側で clamp
> - 「absent は MEDIUM」を `severity_on_absence` フィールドで明示
> - 原文の参考スキーマで `completion_success` 内に同フィールドが存在することと整合
> - 本仕様では signal_kind 単位で severity ポリシーを別個に持てる (latency なら max_severity_on_success=LOW など、kind 別に変えられる)。原文の意図 (kind ごとの severity 規約) を踏襲

### REQ-010: レポートヘッダーをコード側でレンダリングする

```
Title  (embed.title):  response.summary 昇格
Target (field):        config.function_name
ResearchWindow:        research_window_jst
Alarm:                 "{alarm_name} [{alarm_description}]"

Report(Summary):       response.summary
Report(Detail):        response.detail
Action (3 行):
  [即時対応] {actions[即時対応].text}
  [調査手順] {actions[調査手順].text}
  [恒久対策] {actions[恒久対策].text}
```

該当 phase の action が無い場合は `(なし)` を表示。

`embed.color` は severity 連動: HIGH=赤 / MEDIUM=黄 / LOW=緑。

`embed.footer` にフォールバック印 (REQ-008) を表示。

**AC**: Bedrock 応答が空でもヘッダー描画 / action 欠落 phase は `(なし)`。

> **原文対応**: 原文「5. 出力とレンダリングの分離」+ 原文「レポートレンダリングテンプレート（呼び出し側）」と一致。
> - Title / Target / ResearchWindow / Alarm を呼び出し側がレンダリング (原文どおり、ハルシネーション防止)
> - 原文の `{{title}}` は本仕様で「response.summary を昇格して使う」と決定 (原文では `{{title}}` の出どころ未指定)
> - `Action` セクションの 3 行構造 `[即時対応][調査手順][恒久対策]` は原文どおり
> - 該当 phase の action 欠落時の `(なし)` 表示は本仕様で追加
> - `embed.color` (severity 連動) と `embed.footer` (フォールバック印) は本仕様で追加

### REQ-011: 既存ケース分岐ロジックを廃止する

`render_prompt_case_no_logs` / `render_prompt_case_lambda_failure` / case_specific_instructions / `_SYSTEM_PROMPT_TEMPLATE` / `render_prompt_system_base` を完全削除。

空ログ早期 return も撤廃し、verdict=absent として Bedrock に判断させる。

**AC**: 5 つのキーワード grep 0 件 / 空ログ時に Bedrock 呼び出しが発生し verdict=absent。

> **原文対応**: 本仕様で新設 (原文には対応する記述なし)。原文の主目的「特定 Lambda 専用 → どの Lambda でも使い回せる形に」を達成するためには、現行コードのケース分岐 (HDW_Backend_Processor_0001 専用の 2 パターン分岐) を撤去する必要がある。原文「メタ手続き」概念に統一することで、ケース分岐の役割は Bedrock 側 (verdict 3 分岐) に吸収される。

### REQ-012: 後方互換ハック・移行用フォールバックを残さない

新旧の切替フラグ、コメントアウト残置、`// removed` コメントを置かない。

**AC**: `root_cause_hypothesis` / `suggested_actions` の src/ grep 0 件。

> **原文対応**: 本仕様で新設 (原文には対応する記述なし)。constitution PRIN-XXX (簡素優先) に準拠する運用方針。原文「将来拡張 (フェーズ2)」で出力 JSON が連携点となるため、旧スキーマ (root_cause_hypothesis / suggested_actions) を残すと Phase 2 の契約が不安定になる。本仕様で完全置換することで Phase 2 への入力スキーマを clean に保つ。

### REQ-013: Env dataclass を全廃止する

**configs/*.yaml に統合する設定** (9 フィールド): function_name / account_id / aws_region / assume_role_arn / log_group / profile_location / bedrock_model_id / bedrock_max_tokens / cloudwatch_logs_query_poll_interval_sec。

**残す env var**: `DISCORD_WEBHOOK_URLS` のみ。

**廃止する env var**: CROSS_ACCOUNT_ROLE_ARN / TARGET_FUNCTION_NAME / BEDROCK_MODEL_ID / BEDROCK_MAX_TOKENS / ENVIRONMENT_NAME / CLOUDWATCH_LOGS_QUERY_POLL_INTERVAL_SEC / DISCORD_WEBHOOK_URL (無印) / LOG_GROUP_MAP。

ENVIRONMENT_NAME は alarm 名末尾 `-test` から `derive_env_label()` で導出。

**AC**: Env クラス全削除 / 単独 DISCORD_WEBHOOK_URLS で解析成立 / GitHub Actions 配信削除 / ENVIRONMENT_NAME 参照削除。

> **原文対応**: 本仕様で新設 (原文には対応する記述なし)。現行 Reporter Lambda の `Env` dataclass はクライアント 1 / 監視対象 1 の前提で env var を保持しており、複数 Lambda を扱う本仕様では破綻する。本仕様の configs/*.yaml + profile + DISCORD_WEBHOOK_URLS の 3 階層に分配し、Env を全廃する。

### REQ-014: 新規アラーム追加時のデプロイ手順を確定する

**共通手順**:
1. `configs/<正規化 alarm 名>.yaml` を新規作成 + merge
2. (新クライアント時のみ) クライアント S3 に profile を手動 put
3. (新クライアント時のみ) AssumeRole Role に S3 GetObject / ListBucket / KMS Decrypt grant 追加
4. (新クライアント時のみ) クライアント側 SNS / CloudWatch Alarm 配線
5. `DISCORD_WEBHOOK_URLS` JSON に正規化後 alarm 名 → URL を追加
6. Reporter Lambda 再ビルド + 再デプロイ

既存クライアントの新アラーム時は手順 2〜4 をスキップ。

**AC**: PLAN に 2 ケース分岐記載 / 運用 Lambda 不変条件明示 / 自社↔クライアント側作業所在明示 / 手順 1/5 欠落時の失敗モード言及。

> **原文対応**: 本仕様で新設 (原文には対応する記述なし)。原文「概要」の「どの Lambda でも使い回せる形」を運用面で実現するために、新規 alarm 追加手順を明文化する。原文「3. リソースプロファイルのレジストリ化」の意図 (新しい監視対象が増えた際の変更箇所を最小化) を運用手順として具体化したもの。

### REQ-015: load_config() と Config dataclass を実装する

src/utils/config.py に Config (frozen/slots) / normalize_alarm_name / load_config / ConfigNotFoundError / ConfigSchemaError を実装。cold start 一括ロードはせず main 呼び出しごとに都度読む。

**AC**: prod/test 同一 Config / 9 フィールド型付き / ファイル不在 → ConfigNotFoundError / スキーマ違反 → ConfigSchemaError。

> **原文対応**: 本仕様で新設 (原文には対応する記述なし)。原文「処理フロー」の「レジストリから profile を引き当て」を本仕様では 2 段に分解 (configs/<alarm>.yaml → profile YAML)。その 1 段目を実装する責務を持つ。

### REQ-016: DISCORD_WEBHOOK_URLS の JSON 辞書スキーマと解決経路

- 値: JSON 文字列 (UTF-8)
- パース後: `dict[str, str]`
- キー: 正規化後 alarm 名
- 値: Discord webhook URL

cold start で `json.loads` → モジュールスコープ dict にキャッシュ。アラーム受信時に `dict[normalize_alarm_name(alarm_name)]` で引く。

キー不在は Lambda が例外で落ちず CloudWatch Logs warning 記録のみで正常終了 (Discord 通知欠落)。

**AC**: 不正 JSON で fail-fast / test/prod 同一エントリから同じ URL / キー不在で例外なし + warning / `-test` 末尾キー検出で warning。

> **原文対応**: 本仕様で新設 (原文には対応する記述なし)。原文は通知配信先について沈黙していたため、Lambda の env var として残す唯一のキーとして本仕様で設計。手動管理の容易さを優先 (`/loop` 等の自動化を当面採用せず、Lambda console / GitHub secrets で手動編集)。

### REQ-017: pre_classification を動的コンテキストに埋め込む

動的コンテキストの「アラーム情報」セクションに `pre_classification` フィールドを含める。値はコード側で決定論的に設定された `signal_kind.name`。

**値のパターン**:
- 通常解決: `signal_kind.name` (例: `completion_success` / `latency`)
- REQ-008 (a) / (b) フォールバック: `fallback_generic`

冗長だが Bedrock への補助ヒントとして許容 (権威シグナル本体に name は含まれる)。

**AC**: `pre_classification: {value}` 行が含まれる / 値が signal_kind.name と一致 / フォールバック時 `fallback_generic`。

> **原文対応**: 原文「用語集」の `pre_classification` (アラームに付いてくる、呼び出し前に機械的に付与した大分類のヒント) + 原文「動的コンテキスト」テンプレの `pre_classification: {{pre_classification}}` を採用するが、用途を本仕様で再定義。
> - 原文では「signal_selector の値の出どころ候補」として位置付け
> - 本仕様では signal_selector 解決は `profile.signal[]` で済むため、入力側用途は不要
> - 代わりに「Bedrock への補助ヒント (出力側)」として、解決済み signal_kind.name をそのまま埋め込む形に再定義
> - 「ヒントが冗長になる」コストを許容することで、原文用語を保持しつつ実用的な用途を与えた

### REQ-018: 1 アラーム = 1 signal_kind の前提を維持する

1 alarm に対し解決される signal_kind (type=verdict) は 1 個に限る。複合条件 (`Errors または高レイテンシ`) は v1 スコープ外、複数アラームに分割。

**AC**: signal[] で同一 name 重複でスキーマ違反 / 動的コンテキストに権威シグナル 2 個以上含まれない。

> **原文対応**: 原文「4. signal_selector」の末尾「1アラーム = 1シグナルを前提とする。『Errors または高レイテンシ』のような複合条件を1つのアラームで監視するケースは 1:1 が崩れるため v1 スコープ外とし、必要であれば複数アラームに分割する」を REQ として明示。原文では文中に書かれていたが、本仕様では制約として独立 REQ 化し、AC でスキーマ検証として担保。

## スコープ外

- 実行完了系以外のアラームクラス (コスト異常 / レイテンシ SLO バーンレート / GuardDuty 等)。verdict / failure_taxonomy の意味が変わるため別解析プロファイルで対応。
- CloudWatch Logs Insights のクエリ自体の設計・最適化 (既存抽出処理を流用)。
- ケース判定 / 件数集計 / request_id 抽出 / deeplink 生成 (呼び出し側で実施済み前提を継続)。
- 複数アラームの同時発火に対するクロス相関・集約 (1 アラーム = 1 Bedrock 呼び出し = 1 レポートで独立解析)。
- Phase B / C の所有権移譲 (運用 Lambda チームへの profile 管理移譲、CI/CD 連携)。

> **原文対応**: 上記 1〜4 番目は原文「スコープ外」と完全一致。5 番目 (Phase B/C の所有権移譲) は本仕様で追加。Phase A (手動配置) で運用 Lambda 側無変更を担保するが、その先の所有権移譲 (運用チームが自分で管理する形) は別途設計が必要。

## Phase 2 連携点

本仕様の出力 JSON (`verdict` / `severity` / `confidence` / `failure_taxonomy` 等) は将来拡張の連携点となる:

- 失敗かつコードバグ濃厚 (`verdict=failed` / `failure_taxonomy=b1`) で実ソースコード AI 深掘り解析
- 重大事象 (`severity=HIGH`) でクライアント向けメール文面生成 (人間承認を挟む)

別 issue「アラーム解析レポート後段パイプライン」で扱う。本 SPEC は出力 JSON のスキーマ安定性を Phase 2 への契約として保つ。

> **原文対応**: 原文「将来拡張（フェーズ2）」と一致。「出力 JSON（verdict / severity / confidence / failure_taxonomy 等）が、後段処理の連携点となる」「失敗かつコードバグ濃厚なケースでの、実ソースコードを用いた AI コード深掘り解析（file:line 単位の原因特定・修正案）」「クライアント影響のある重大事象での、クライアント向けメール文面の生成（送信は人間承認を挟む）」を本セクションに 1:1 で取り込み。

---

## 補足: 原文との差分マップ (一覧)

本仕様が原文 issue を出発点としつつ、以下の点で原文を**改めた / 拡張した / 新設した**。

### 命名の改めた箇所

| 原文の用語 | 本仕様の用語 | 改めた理由 |
|---|---|---|
| `health_signals` (辞書) | `signal_kind` (配列、各エントリに `name`) | 配列化で各エントリ自身が `name` を持つ。命名は「signals の種類カタログ」を表現 |
| `health_signal` (単数) | `signal_kind[].name=verdict ロール` | 「verdict 判定に使う signal_kind」を `type: verdict` で表現 |
| `secondary_signals` (リスト) | `signal_kind[].type=ignored` (構造化) | 「health vs non-health」の暗黙対立を解消し、ロールで discriminated にする |
| `signal_selector` (キー文字列) | `signal[].kind` (配列内の参照フィールド) | 独立概念としては不要。alarm → kind 名の対応表 (`signal` 配列) のフィールドに格下げ |
| `type` (log_marker/metric/...) | `mechanism` | 新しい `type` を verdict/ignored discriminator に使うため、メカニズム種別を `mechanism` に改名 |

### 構造を拡張した箇所

| 観点 | 原文 | 本仕様 |
|---|---|---|
| profile 配置 | 「格納先未決」(原文 確認事項#1) | 運用 Lambda の既存 S3 (REQ-003) |
| レジストリキー | function_name 単位を提案 (原文 確認事項#3) | alarm_name 単位 (configs/<alarm>.yaml) + 内部で function_name 単位 profile を参照 |
| signal_selector 解決 | 3 候補のいずれか (原文 4.) | profile.signal[] に格納 (案 「alarm_name → selector のマッピング表」採用) |
| severity ポリシー所在 | 参考スキーマ内、必須性不明確 | signal_kind[type=verdict] の必須フィールド (REQ-002 / REQ-009) |
| fallback signal_kind | 「Errors メトリクス + traceback」と概念のみ | `fallback_generic` 定数として具体化 (REQ-008) |
| レポートテンプレ Title | `{{title}}` プレースホルダ | `response.summary` を昇格 (REQ-010) |
| 字数制限 | 出力 JSON に明記 | システムプロンプト + コード側 truncate の二重防御 (REQ-007) |

### 本仕様で新設した箇所 (原文に対応記述なし)

- `configs/` ディレクトリ・`Config` dataclass・`load_config()` (REQ-004 / REQ-015)
- `DISCORD_WEBHOOK_URLS` 単一 env var による webhook 管理 (REQ-016)
- `Env` dataclass 全廃止と env var 整理 (REQ-013)
- `-test` 統合不変条件
- 既存ケース分岐 (`render_prompt_case_*`) の廃止 (REQ-011)
- 後方互換ハック禁止 (REQ-012)
- 新規アラーム追加デプロイ手順 (REQ-014)
- Phase A (手動配置) + Phase B/C 所有権移譲 (Phase B/C は本仕様スコープ外)

### 確定した原文 未決事項

| 原文の未決事項 | 本仕様の確定 |
|---|---|
| #1 プロファイル格納先 (SSM/DynamoDB/JSON) | 上記 3 候補のいずれでもなく、運用 Lambda 既存 S3 (REQ-003) + リポジトリ内 YAML (REQ-004) の 2 段構成 |
| #3 レジストリキーの function_name 単位 | alarm_name 単位を採用 (機能的に等価) |
| #4 signal_selector 解決の呼び出し側コード (案 A) | 確定 (REQ-005) |

### 残る原文 未決事項

| 原文の未決事項 | 本仕様での対応 |
|---|---|
| #2 failure_taxonomy 上書き可否 | O-4 として継続未決 (current_lean: システム固定) |
| #5 同時発火時の独立通知 vs 集約 | O-5 として継続未決 (current_lean: 独立通知) |
