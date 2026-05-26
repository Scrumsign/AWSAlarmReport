---
id: llm-output-chaining
version: 0.1.0
title: LLM 出力チェーニング規約
created_at: 2026-05-25
type: spec
status: draft
---

# LLM 出力チェーニング規約

- **ID**: llm-output-chaining
- **Version**: 0.1.0
- **Created at**: 2026-05-25
- **Authors**: scrumsign-takuyakimura
- **Status**: draft

## 背景・目的

現在 Bedrock への各呼び出しは完全にステートレスであり、前回の解析結果は次回の LLM 呼び出しに引き継がれない。連続してアラームが発火した場合でも毎回ゼロから推論するため、診断精度・文脈継続性・アクション提案の質が低下する可能性がある。

本 spec は、LLM の出力を次回の LLM 呼び出しに再利用するための規約（フォーマット・内容・抽出・埋め込み・ライフサイクル）を定義する。

## 全体概要

LLM 出力に `chain_context` フィールドを追加し、次回 LLM 呼び出し時にそのフィールドをプロンプトに埋め込む。
出力フォーマットは JSON から YAML に変更し、人間・LLM 双方の可読性を高める。
`chain_context` は人間が読み飛ばせる補足セクションとして出力末尾に配置する。

## 主要 definitions

| 用語 | 説明 |
|---|---|
| chain_context | LLM to LLM 引き継ぎ専用の構造化フィールド。人間が読んでも意味があるが、主に次回 LLM のコンテキストとして使われる |
| pattern | アラームの事前判定結果。A（起動形跡なし）/ B（処理失敗） |
| key_technical_clues | 前回解析で特定された具体的な技術的手がかり（file:line、エラー型、AWS エラーコード等） |

## Requirements

### REQ-001: 出力フォーマット規約

LLM の出力フォーマットを JSON から YAML に変更し、人間・LLM 双方の可読性を確保する。
出力末尾に `chain_context` セクションを追加する。

**AC**:
- AC-001-1: LLM は `summary` / `severity` / `confidence` / `pattern` / `root_cause_hypothesis` / `suggested_actions` / `chain_context` の 7 フィールドを YAML 形式で出力する
- AC-001-2: `chain_context` はコメント行（`# LLM to LLM 引き継ぎ専用`）付きで出力末尾に配置される
- AC-001-3: システムプロンプトの出力スキーマ定義が YAML 形式に更新されている

### REQ-002: chain_context の内容規約

`chain_context` に含めるべき最小セット情報を定義する。

**AC**:
- AC-002-1: `chain_context` は `alarm_name` / `fired_at` / `pattern` / `root_cause_summary` / `key_technical_clues` / `severity` / `confidence` の 7 フィールドを含む
- AC-002-2: `root_cause_summary` は 50 文字以内
- AC-002-3: `key_technical_clues` は最大 3 件、各項目 80 文字以内
- AC-002-4: `pattern` は `"A"` または `"B"` の文字列

### REQ-003: 抽出規約

LLM レスポンスから `chain_context` を取得する方法を定義する。

**AC**:
- AC-003-1: YAML パースで `chain_context` フィールドを抽出できる
- AC-003-2: パース失敗・フィールド欠損の場合はコンテキストなし（`None`）として扱い、処理を継続する
- AC-003-3: 必須フィールド（`pattern` / `root_cause_summary` / `severity`）のいずれかが欠損している場合もコンテキストなし扱いとする

### REQ-004: 入力埋め込み規約

前回の `chain_context` を次回の LLM プロンプトに組み込む形式を定義する。

**AC**:
- AC-004-1: `chain_context` はシステムプロンプトの冒頭に「# 前回の解析結果」セクションとして埋め込まれる
- AC-004-2: `chain_context` が存在しない場合、該当セクションはプロンプトに含まれない
- AC-004-3: 埋め込みは YAML ブロックとしてそのまま挿入し、LLM が構造を読める形式とする

### REQ-005: ライフサイクル規約

`chain_context` の保持世代数・有効期限・リセット条件を定義する。

**AC**:
- AC-005-1: 引き継ぐのは直前の 1 世代のみ（累積しない）
- AC-005-2: TTL は 24 時間とする（前回アラーム発火時刻から起算）
- AC-005-3: TTL 超過の場合はコンテキストなし扱いとする

## スコープ外

- `chain_context` の永続化手段・ストレージ選定（別 spec で定義）
- 複数世代の累積・履歴管理
- `chain_context` を使った自動リトライ・エスカレーション判定
- LLM が YAML を出力しない場合のリトライ戦略

## 具体例・参考スキーマ

### LLM 出力例（YAML）

```yaml
summary: "[処理失敗] HDW_Backend_Processor_0001 が ZIP 処理中に KeyError で落ちた"
severity: HIGH
confidence: medium
pattern: B
root_cause_hypothesis: "store.py:87 の frontend_paths['data'][key] で KeyError が発生。入力 ZIP の構造不整合が最有力。"
suggested_actions:
  - "store.py:87 の .get() 切替を検討し KeyError 耐性を向上"
  - "CloudWatch で同一 ship_name の過去ログを確認し再現性を判断"
  - "入力 ZIP の構造バリデーションを main.py 冒頭に追加"

# LLM to LLM 引き継ぎ専用（人間は読み飛ばしてよい）
chain_context:
  alarm_name: HDW-BackendProcessor-Alarm
  fired_at: "2026-05-25T03:00:00Z"
  pattern: B
  root_cause_summary: "store.py:87 KeyError（入力データ異常の可能性）"
  key_technical_clues:
    - "store.py:87 frontend_paths['data'][key] KeyError"
    - "ship_name: sakura / ship_timestamp: 20260524T2200"
  severity: HIGH
  confidence: medium
```

### 次回 LLM へのシステムプロンプト埋め込み例

```
# 前回の解析結果
alarm_name: HDW-BackendProcessor-Alarm
fired_at: "2026-05-25T03:00:00Z"
pattern: B
root_cause_summary: "store.py:87 KeyError（入力データ異常の可能性）"
key_technical_clues:
  - "store.py:87 frontend_paths['data'][key] KeyError"
severity: HIGH
confidence: medium

あなたは AWS Lambda 障害分析の専門家で...（以下通常のシステムプロンプト）
```
