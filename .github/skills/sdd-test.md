TEST.md を作成・更新する。TASK.md と 1:1 対応するテスト項目を、SPEC.md を参照しながら設計する。

## いつ使うか

- TASK.md が確定した後、テスト設計を文書化するとき
- 実装とテスト作成を分離して進めたいとき
- 既存 TEST.md にテストを追加・修正するとき（`/sdd-test <feature-name> update`）

## テスト設計の原則

### 1:1 の原則
**TASK と TEST は 1:1 対応**にする。TASK-001 に対して TC-001 が1つ存在する。
1タスクに複数テストが必要になった場合、タスクの粒度が粗すぎるサイン。

### 独立性の原則
**テストは SPEC から導く。実装コードを見て書かない。**
実装から書くと「実装を検証するテスト」になる。
SPEC の AC から書くと「仕様を検証するテスト」になる。

### 省略の原則
型システムや言語仕様が保証する自明な動作はテストしない:
- dataclass のフィールド名が宣言と一致する
- 関数が非 None を返す
- 恒等変換（`normalize("foo") == "foo"`）

代わりに「境界条件」「フォールバック保証」「横断的な不変条件」を重点的にテストする。

## 実行手順

### 1. 前提ドキュメントを読み込む

- `specs/<feature-name>/TASK.md` — 全タスクと完了基準
- `specs/<feature-name>/SPEC.md` — REQ と AC（テストの根拠）

### 2. ファイル作成

`specs/<feature-name>/TEST.md` を以下の構造で作成する:

```markdown
---
id: <feature-name>
spec_version: <参照 SPEC バージョン>
task_rev: <参照 TASK rev>
rev: 1
title: <タイトル> — テスト項目
created_at: <YYYY-MM-DD>
type: test
---

# <タイトル> — テスト項目

- **SPEC**: <feature-name>@<spec_version>
- **TASK rev**: <task_rev>
- **TEST rev**: 1

## 方針

<何を重点的にテストするか・何を省略するかを記述する>

省略するもの:
- <自明な動作>
- <型システムが保証する動作>

---

## TC-001: <テストタイトル>（TASK-001 対応）

- **TASK**: TASK-001
- **REQ**: REQ-NNN
- **type**: unit / integration / static / e2e
- **重要度**: 高 / 中 / 低

**なぜ重要**: <このテストが必要な理由>

```python
def test_<name>():
    # arrange
    ...
    # act
    result = ...
    # assert
    assert result == ...
```

## TC-002: <テストタイトル>（TASK-002 対応）

...

---

## テスト実行戦略

| フェーズ | 実行内容 | 頻度 |
|---|---|---|
| CI on PR | unit + static | PR 毎 |
| CI on merge | unit + static + integration | merge 毎 |
| 手動 | e2e（実環境） | デプロイ時 |
```

### 3. テスト種別の使い分け

| 種別 | 使いどころ |
|---|---|
| `unit` | 単一関数・クラスの境界条件・エラーケース |
| `integration` | 複数モジュール連携・フォールバック動作 |
| `static` | 削除確認（grep 0件）・禁則語チェック |
| `e2e` | 実 AWS / 外部サービスを含む統合動作 |

### 4. TEST.yml の作成

```yaml
id: <feature-name>
spec_version: <参照 SPEC バージョン>
task_rev: <参照 TASK rev>
rev: 1
test_cases:
  - id: TC-001
    task: TASK-001
    req: REQ-NNN
    type: unit
    importance: high
  - id: TC-002
    task: TASK-002
    req: REQ-NNN
    type: integration
    importance: high
```
