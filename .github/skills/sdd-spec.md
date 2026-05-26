SPEC.md を作成・更新する。要件・受け入れ基準・定義・スコープ外・具体例を構造化して記述する。

## いつ使うか

- 新機能の要件を仕様として文書化するとき
- GitHub Issue・会話上の要件を SPEC に変換するとき
- 既存 SPEC.md を改訂するとき（`/sdd-spec <feature-name> update`）

## 実行手順

### 1. 情報収集

作成前に以下を会話から収集する。不足があればユーザーに質問する:

- **背景・問題**: なぜこの機能が必要か
- **目的**: 何を達成したいか
- **制約**: 既存システムとの依存・触ってはいけない範囲
- **関連 Spec**: 依存する既存 spec の ID

### 2. ファイル作成

`specs/<feature-name>/SPEC.md` を以下の構造で作成する:

```markdown
---
id: <feature-name>
version: 0.1.0
title: <タイトル>
created_at: <YYYY-MM-DD>
type: spec
status: draft
---

# <タイトル>

- **ID**: <feature-name>
- **Version**: 0.1.0
- **Created at**: <YYYY-MM-DD>
- **Authors**: <git user>
- **Dependencies**: <依存する spec の id>（なければ省略）
- **Status**: draft

## 背景・目的

<なぜこの機能が必要か。解決する問題と達成したい状態を記述する>

## 全体概要

<機能の概要と主要な設計判断を記述する>

## 主要 definitions

| 用語 | 説明 |
|---|---|
| <用語> | <説明> |

## Requirements

### REQ-001: <要件タイトル>

<要件の説明。「何を」「どういう条件で」を記述する>

**AC**:
- AC-001-1: <検証可能な受け入れ基準>
- AC-001-2: <検証可能な受け入れ基準>

### REQ-002: <要件タイトル>

...

## スコープ外

- <明示的に対象外とするもの>
- <将来フェーズに先送りするもの>

## 具体例・参考スキーマ

<YAML・JSON・コード等の具体例をここに集める>
```

### 3. REQ 記述のルール

- **1 REQ = 1 つの責務**。複数の責務を混ぜない
- **AC は検証可能な形式**で書く（「grep 0 件」「200 を返す」等、合否が判定できる）
- **スコープ外セクションは必須**。AIが勝手に補完しないように境界を明示する
- **依存関係**: 他 REQ に依存する場合は本文中に「REQ-NNN を前提とする」と明記する

### 4. バージョン管理

- 初版: `version: 0.1.0`
- 要件追加: マイナーバージョンを上げる（0.1.0 → 0.2.0）
- 破壊的変更: メジャーバージョンを上げる（0.x.x → 1.0.0）
- status は `draft` → `review` → `approved` の順に遷移する

### 5. SPEC.yml の作成

SPEC.md と同ディレクトリに `SPEC.yml` を作成する。REQ の ID・タイトル・AC のみを抽出した機械可読版:

```yaml
id: <feature-name>
version: 0.1.0
status: draft
requirements:
  - id: REQ-001
    title: <タイトル>
    ac:
      - id: AC-001-1
        description: <受け入れ基準>
```
