# AWSAlarmReport — プロジェクトガイド

AWS CloudWatch アラームを受信し、Bedrock で原因解析して Discord に通知する Lambda。

## SDD スキル

このプロジェクトでは **仕様駆動開発（SDD）** を採用している。
新機能・改修の開発は必ず SPEC → DESIGN → TASK → TEST の順でドキュメントを作成してから実装する。

### スキルの場所

```
.github/skills/
├── sdd.md        — 全フロー統括（/sdd）
├── sdd-spec.md   — SPEC.md 作成（/sdd-spec）
├── sdd-design.md — DESIGN.md 作成（/sdd-design）
├── sdd-task.md   — TASK.md 作成（/sdd-task）
└── sdd-test.md   — TEST.md 作成（/sdd-test）
```

### いつスキルを使うか

| 状況 | 使うスキル |
|---|---|
| 新機能・改修の開発を開始するとき | `/sdd <feature-name>` |
| SPEC だけ先に作りたいとき | `/sdd-spec <feature-name>` |
| SPEC が承認されて設計に入るとき | `/sdd-design <feature-name>` |
| 実装タスクを定義するとき | `/sdd-task <feature-name>` |
| テスト設計を文書化するとき | `/sdd-test <feature-name>` |
| 既存ドキュメントを改訂するとき | 各スキルに `update` オプションを付けて呼ぶ |

### ドキュメント構造

```
specs/<feature-name>/
├── SPEC.md    — 要件（REQ）+ AC + 定義 + スコープ外 + 具体例
├── SPEC.yml   — 機械可読版
├── DESIGN.md  — 技術設計・アーキテクチャ・データ構造・実装ガイド
├── DESIGN.yml — 機械可読版
├── TASK.md    — 実装タスク（1タスク＝1検証基準）
├── TASK.yml   — 機械可読版
├── TEST.md    — テスト項目（TASKと1:1対応）
└── TEST.yml   — 機械可読版
```

### 変更伝播ルール

SPEC が変更されたとき、必ず DESIGN → TASK → TEST の順で影響箇所を更新する。
各ファイルの frontmatter にある `version` / `rev` をインクリメントして変更を追跡する。

## 作業方針

- 問題・懸念点（型の不整合、設計との乖離、破壊的変更の可能性など）は即座にユーザーに伝える
- 実装は慎重に進め、確認が取れたステップから順に着手する

## specs/ の既存フィーチャー

| ID | タイトル | ステータス |
|---|---|---|
| `bedrock-prompt-generalization` | Bedrock アラーム原因解析プロンプトの汎用化 | draft |
| `cross-account-architecture` | クロスアカウントアーキテクチャ | — |
| `production-operation-test-v2` | 本番運用テスト v2 | — |
| `test-zip-management` | テスト ZIP 管理 | — |
| `alarm-naming-convention` | アラーム命名規則 | — |
