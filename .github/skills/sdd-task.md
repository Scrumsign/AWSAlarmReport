TASK.md を作成・更新する。SPEC・DESIGN を読み込み、1タスク＝1検証基準の原子的な実装タスクに分解する。

## いつ使うか

- DESIGN.md が確定した後、実装タスクを定義するとき
- AIへの実装指示単位を明確にしたいとき
- 既存 TASK.md にタスクを追加・修正するとき（`/sdd-task <feature-name> update`）

## タスク設計の原則

### 原子性の原則
**1タスク＝1セッションで完了できる粒度**にする。
「バリデーションを実装する」は粗すぎる。「空文字列のバリデーションを実装する」が適切。

### 1:1 の原則
**1タスク＝1テスト項目**で検証可能な粒度にする。
1つのタスクに5つ以上のテストが必要になったら、タスクを分割するサイン。

### 検証可能性の原則
タスクの完了基準は**合否が判定できる形式**で書く:
- ✅ 「`pytest tests/test_config.py` が通る」
- ✅ 「`grep render_prompt_case src/` が 0 件」
- ❌ 「コードが整理されている」（主観的で判定不能）

## 実行手順

### 1. 前提ドキュメントを読み込む

- `specs/<feature-name>/SPEC.md` — 全 REQ と AC
- `specs/<feature-name>/DESIGN.md` — 実装ガイド・コード断片

### 2. ファイル作成

`specs/<feature-name>/TASK.md` を以下の構造で作成する:

```markdown
---
id: <feature-name>
spec_version: <参照 SPEC バージョン>
rev: 1
title: <タイトル> — 実装タスク
created_at: <YYYY-MM-DD>
type: task
---

# <タイトル> — 実装タスク

- **SPEC**: <feature-name>@<spec_version>
- **rev**: 1

## 実装順序（依存関係）

TASK-001 → TASK-002 → TASK-004
TASK-003 → TASK-004
TASK-005, TASK-006（TASK-004 完了後、並列可）

## タスク一覧

### TASK-001: <タスクタイトル>

- **REQ**: REQ-NNN
- **依存**: なし（または TASK-NNN）
- **完了基準**: <1文。テストコマンドや grep 結果等の客観的な基準>

<実装の説明。何を・どのファイルに・どう実装するか>

実装ガイド:
（DESIGN.md のコード断片をここに引用・補完する）

### TASK-002: <タスクタイトル>

...
```

### 3. タスク分解のルール

- **REQ との 1:1 は不要**。1 REQ が複数 TASK に分解されることは自然
- **粒度チェック**: 「このタスクの完了を確認するテストを1つ書けるか？」で判断する
- **依存関係を明示**する。依存なしのタスクは並列実行可能と示す
- **実装ガイドは DESIGN から引く**。TASK で新たな設計判断をしない

### 4. 完了後の確認

- 全 REQ が少なくとも1つの TASK に対応しているかトレーサビリティを確認する
- 依存関係に循環がないか確認する
- 各タスクの完了基準が TEST.md で1テストに対応できる粒度か確認する

### 5. TASK.yml の作成

TASK.md と同ディレクトリに `TASK.yml` を作成する:

```yaml
id: <feature-name>
spec_version: <参照 SPEC バージョン>
rev: 1
tasks:
  - id: TASK-001
    title: <タイトル>
    req: REQ-NNN
    depends_on: []
    done_criterion: <完了基準>
  - id: TASK-002
    title: <タイトル>
    req: REQ-NNN
    depends_on: [TASK-001]
    done_criterion: <完了基準>
```
