---
title: 運用Lambda開発者目線で「各ケースに必要な情報」を設計する
date: 2026-05-15
status: draft
type: information-design
scope: report-content
author: t.kimura@scrumsign.com
related:
  - ../lambda-error-report-mvp/DRAFT.md
  - ../lambda-error-report-mvp/PLAN.md
tags:
  - aws-lambda
  - observability
  - incident-response
  - discord
  - llm-prompt-design
  - llm-capability-boundary
  - report-design
audience: 運用Lambda(hdw-ingest)の開発・運用担当者
purpose: >
  Discord通知を受け取った開発者が「次の一手」を即座に判断できる情報セットを、
  障害ケースごとに具体化する。あわせて LLM に任せる仕事と任せない仕事の境界を引き、
  Reporter Lambda の Logs Insights クエリ・Bedrock システムプロンプト・
  Discord Embed のフィールド設計に反映する。
---

# 運用Lambda開発者目線で「各ケースに必要な情報」を設計する

## 0. このドキュメントの位置づけ

[lambda-error-report-mvp](../lambda-error-report-mvp/DRAFT.md) で **配管**（Alarm → Lambda → Bedrock → Discord）は決めた。
本ドラフトは **中身**（通知に何を載せるか / LLMに何をさせるか）を運用者目線で固める。

> **核心の問い**:
> ① Discord通知を見た瞬間、開発者が「次の30秒で何をすべきか」を判断できる最小情報セットは何か？
> ② その情報生成のうち、LLMに任せる仕事はどこまでで、機械的に決める仕事はどこからか？

---

## 1. 運用Lambda開発者が通知に期待する3つの判断

通知を受け取った人が**最初の30秒**で下す判断は次の3つ。情報設計はここから逆算する。

| # | 判断 | 必要な情報 |
|---|---|---|
| ① | **これは今すぐ対応すべきか？** | severity / 影響範囲（件数, %）/ 既知の問題か |
| ② | **何が起きているのか？** | エラー分類 / 1行サマリ / 代表エラーメッセージ |
| ③ | **どこを見れば深掘りできるか？** | CW Logs deeplink / Insights deeplink / 関連request_id |

通知本文は**この3判断を最短で支援する**ことに集約する。詳細はリンク先に逃がしてよい。

---

## 2. 全ケース共通で必要な情報（コア6項目）

ケース別の前に、**どの障害でも必ず欲しい**コア情報を固める。Reporter Lambda はまずこれを抽出する。

| 項目 | 内容 | 取得元 |
|---|---|---|
| **alarm_name** | どのAlarmか | event.alarmArn |
| **function_name** | 対象Lambda | Alarm Dimensions |
| **window** | 集計時間窓 (start–end, JST) | alarmData.state.timestamp ± N |
| **error_count / invocation_count** | 件数と全体に対する比率 | Logs Insights + CW Metrics |
| **representative_request_id** | 代表的な1件のrequest_id | Logs Insights 最新ERROR |
| **deeplinks** | Logs / Insights / Metrics への直リンク | Reporter Lambda が組み立て |

> **設計指針**: 通知の **header領域**（Embed title/description + 上段fields）はこの6項目で固定する。LLMが何を出すかに依存させない。

---

## 3. ケース別に必要な情報

「Lambda失敗」は実際には複数のサブケースに分解できる。開発者は**ケースが特定された時点で対応手順がほぼ確定する**ため、ケース判定とそれに紐づく情報抽出が肝。

以下、優先度順（hdw-ingestで頻度が高そうなもの順）。

### 3.1 ケースA: コード例外（Unhandled Exception）

最も頻度が高い。Pythonランタイムでtracebackが残る典型ケース。

| 必須情報 | なぜ必要か |
|---|---|
| **error_class** (`KeyError`, `ClientError` 等) | 既知エラーか初見かの即判定 |
| **error_message** (1行) | 同一エラーパターンのグルーピング |
| **stack_trace** (関連行のみ) | コード位置の特定 — `file:line in func` 3〜5行で十分 |
| **request_id** | 該当ログへの最短経路 |
| **入力イベントの要約** (S3 key / event source) | 再現性のヒント / 特定データに依存するか |
| **同一error_classの頻度** | 単発か連発か |

**LLMに期待する分析**: error_class + message から原因仮説（コードバグ / 入力データ異常 / 環境変数欠落 など）の切り分け。

---

### 3.2 ケースB: タイムアウト（Task timed out after N seconds）

ログには `Task timed out after X.XX seconds` の1行しか出ないことが多い。**例外と違って情報が乏しい**ため抽出戦略が違う。

| 必須情報 | なぜ必要か |
|---|---|
| **configured_timeout** | 設定値の妥当性確認 (Lambda Config取得) |
| **last_log_line_before_timeout** (request_id内) | どの処理で止まったかの特定 |
| **REPORT行の Duration / Billed Duration** | 実行時間の実測値 |
| **同request_idの全ログ系列** | 処理がどこまで進んでいたか |
| **downstream service latency** (もしログに記録があれば) | 外部依存の遅延が原因か |

**LLMに期待する分析**: 「直前ログ」から処理ステップを推定し、**どの外部呼び出しで詰まったか**を特定。

> **Logs Insights クエリの変化**: 通常クエリ（ERROR/FATAL）では拾えない。`@message like "Task timed out"` で検出し、検出されたrequest_idで**再度クエリして同一request_idの全ログ**を集める2段構えが要る。

---

### 3.3 ケースC: メモリ不足（Memory Size Exceeded）

CloudWatchの `REPORT` 行に `Memory Size: XXX MB Max Memory Used: XXX MB` で出る。Lambdaは設定値を超えるとプロセス強制終了 → 例外スタックは残らない。

| 必須情報 | なぜ必要か |
|---|---|
| **memory_size (configured)** | 設定上限 |
| **max_memory_used** | 実測ピーク |
| **入力サイズ** (S3 object size 等) | 入力量と消費量の相関 |
| **直近の memory_used 推移** | 慢性的にギリギリか、特定入力で爆発したか |

**LLMに期待する分析**: 「設定値を増やせば直る案件」か「アルゴリズム/メモリリーク」か。

---

### 3.4 ケースD: スロットリング・並列度上限

`TooManyRequestsException` / `Rate Exceeded` / `ProvisionedConcurrencyConfigNotFoundException` 等。**Errorsメトリクスは立つがコードバグではない**ため、開発者の対応が大きく変わる。

| 必須情報 | なぜ必要か |
|---|---|
| **throttle件数** (CW Metrics: Throttles) | 真のスロットルか別の例外か |
| **同時実行数の推移** (ConcurrentExecutions) | 上限到達か |
| **アカウント / 関数の Concurrency Limit** | 設定値 |
| **発生元** (本Lambda起因 / downstream API起因) | 対処主体の特定 |
| **イベントソース** (S3 / SQS / EventBridge) | リトライ挙動・データロスリスクの判定 |

**LLMに期待する分析**: スロットルの**位置**を切り分ける（自Lambda / downstream AWS / 3rd-party API）。

---

### 3.5 ケースE: 外部依存の失敗

`ClientError` (`ThrottlingException`, `AccessDeniedException`, `ServiceUnavailable` 等) / `ConnectionError` / `ReadTimeout`。boto3 が多い。

| 必須情報 | なぜ必要か |
|---|---|
| **対象サービス・API** | DynamoDB? S3? Bedrock? |
| **HTTPステータス / AWS error code** | レート制限 / 権限 / 一時障害 の切り分け |
| **retry有無** (boto3 retry config / コード内retry) | 既にretry尽きたか、初回失敗か |
| **AWS Health状態** (該当時) | リージョン障害の有無 |
| **同期間中の他Lambdaの同種エラー有無** | 局所か全体障害か |

**LLMに期待する分析**: error code から **transient（再実行で直る）か permanent（修正必要）か** を判定。

---

### 3.6 ケースF: 設定・権限エラー

`AccessDeniedException` (IAM) / `ResourceNotFoundException` / 環境変数の `KeyError`。**デプロイ直後に出やすい**。

| 必須情報 | なぜ必要か |
|---|---|
| **対象リソースARN / 環境変数名** | 何が欠けているかの直指定 |
| **直近デプロイ時刻** (Lambda LastModified) | デプロイ起因の疑いを判定 |
| **IAM Policyの該当Statement** (可能なら) | 修正箇所の特定 |

**LLMに期待する分析**: 「直近のデプロイで何かが抜けた」ストーリーの仮説生成。

---

### 3.7 ケースG: 入力データ起因

S3トリガで「特定の壊れたファイル」だけが失敗する等。**コードは悪くない**が、データ修正・スキップ・後処理が必要。

| 必須情報 | なぜ必要か |
|---|---|
| **入力S3 key / event source識別子** | 該当データの特定 |
| **データの形式異常の所在** (parse errorのフィールド名) | 修正対象の絞り込み |
| **同種フォーマットの他データ成否** | データ単独異常か仕様変更か |
| **再処理可否** (idempotent性) | 復旧手順の判断 |

**LLMに期待する分析**: 「コード修正」「データ修正」「単純スキップ」のどれが妥当かの推奨。

---

## 4. LLMの役割と限界 — 任せる仕事と任せない仕事

ケース別の情報を揃えた次は、それを**誰が処理するか**の線引き。Reporter Lambda の心臓部である **LLM (Claude Sonnet 4.6) に何を任せ、何を任せないか** を明確化する。ここを曖昧にするとプロンプトが膨らみ、出力品質が安定せず、コストとレイテンシが膨張する。

### 4.1 LLMに「やってほしい」こと（得意領域）

開発者目線で見た時、LLMが価値を出せる領域は次の5つに絞れる。

| # | やってほしいこと | 具体例 |
|---|---|---|
| ① | **ノイズの圧縮** | 50件のERRORログ → 1行サマリ（30文字以内） |
| ② | **ストーリーの組み立て** | アラーム + ログ + ケース判定結果を読んで「何が起きたか」を文章化 |
| ③ | **原因仮説の優先順位付け** | 複数の候補を「もっともらしさ」順で出す（断定はしない） |
| ④ | **アクションの具体化** | 「即時対応」「調査手順」「恒久対策」の3段で行動を提示 |
| ⑤ | **重大度の推定** | severityを LOW/MEDIUM/HIGH で判定（影響範囲とエラー性質から） |

→ 共通点は **「曖昧な情報から意味を抽出し、人間が読める形にする」**。これはLLMの得意分野。

### 4.2 LLMに「させない」こと（不得意 or 過剰）

逆に、LLMに任せると品質が落ちる・コストが上がる・hallucinationリスクが出る領域。

| # | させない理由 | 代替手段 |
|---|---|---|
| ① | **ケースの初期判定** (`Task timed out` の検出など) | 正規表現で機械判定（§5） |
| ② | **数値の集計** (件数・割合・推移) | CW Metrics API / Logs Insights の stats |
| ③ | **構造化データの抽出** (request_id, error_class) | Insights クエリの fields で取得済み |
| ④ | **deeplinkの生成** | Reporter Lambda がテンプレートで組み立て |
| ⑤ | **コードベース固有の根本原因の断定** | LLMはhdw-ingestのコードを知らない → 仮説止まりにする |

→ 共通点は **「決定論的にできること」「外部情報が必要なこと」**。前者はコード、後者はRAG（将来）で。

### 4.3 LLMの構造的な限界 — プロンプトでは超えられない壁

理解しておくべきLLMの限界。プロンプト調整では本質的に解決しないので、**設計で回避する**。

| 限界 | 何が起きるか | 緩和策（設計レベル） |
|---|---|---|
| **コードベース未知** | 「`process_record`関数で...」と言われても何の関数か知らない → 一般論で止まる | コード抜粋を入力に同梱（将来）/ RAG |
| **時系列分析が弱い** | 「徐々に増えている」「特定時刻に集中」等の傾向把握は不正確 | 集計は Logs Insights stats で先に計算して数値で渡す |
| **過去事例の記憶なし** | 「先週も同じエラーが出た」を毎回ゼロから | レポート履歴を S3保存+検索（拡張パス） |
| **インフラ状態が見えない** | デプロイ履歴・AWS Health・他Lambdaの状況は知らない | 必要な状態をプロンプトに事実として同梱 |
| **hallucinationリスク** | 確信のない時もそれっぽい仮説を生成する | 出力JSONに `confidence` を要求 / 既知パターンと照合できなかった場合は明示させる |
| **入力長と精度のトレードオフ** | 1Mコンテキストでも、入力が長いほど重要情報が埋もれる | 重要度順にソート＋件数制限（既に `limit 50`） |
| **JSON逸脱** | 自由形式で書きたがる傾向（特に複雑な指示時） | `temperature: 0.2` / Schema厳格化 / バリデーション+リトライ |

### 4.4 役割分担の図

```
┌────────────────────────────────────────────────────────────────┐
│ Reporter Lambda の責務分担                                      │
├──────────────────────────┬─────────────────────────────────────┤
│ 機械(コード)がやる        │ LLMがやる                            │
├──────────────────────────┼─────────────────────────────────────┤
│ ・ケース判定 (regex)      │ ・1行サマリ生成                      │
│ ・ログ抽出 (Insights)     │ ・原因仮説 (順位付き)               │
│ ・件数・比率集計          │ ・推奨アクション (3段)              │
│ ・request_id追跡          │ ・severity 推定                      │
│ ・deeplink 生成           │ ・自然言語ストーリー化               │
│ ・JSON Schema 検証        │                                     │
│ ・fallback (LLM失敗時)    │                                     │
└──────────────────────────┴─────────────────────────────────────┘
                              │
                              ▼
                  LLMの入力 = 機械が整えた構造化データ
                  LLMの出力 = 機械が検証する構造化JSON
```

→ **LLMを「魔法の箱」として使わない**。「機械で前処理 → LLMが意味付け → 機械で後処理」の3段で安定させる。

### 4.5 LLM出力の信頼性確保 — 「もっともらしいデタラメ」対策

LLMが自信満々で誤った仮説を返した時の安全網を**仕組みで**用意しておく。

- **出力JSON Schemaを厳格定義**: Reporter Lambda でバリデーション。失敗時は raw text をそのままDiscordに出して**LLM分析欠如を明示**（黙って消さない）。
- **`confidence` フィールド必須**: `low/medium/high` を要求。`low` の時はEmbed側で「仮説」と明示・色も控えめに。
- **fallback embed**: LLM呼び出しが失敗・タイムアウト・JSON逸脱した場合、**機械抽出のコア6項目だけでDiscord通知**を成立させる（LLM分析なしでも価値ゼロにしない）。
- **暴走防止**: `maxTokens: 1024` / `temperature: 0.2` で出力を狭める。tool_use は MVP では無効（agentic化は拡張パスで）。
- **「分からない」を許容**: プロンプトで「情報不足の場合は `root_cause_hypothesis: "情報不足 — <何が足りないか>"` と返してよい」と明示。捏造より無回答を優先させる。

### 4.6 LLMの仕事を「採点」する観点（オフライン評価）

将来精度を測る時の指標。今は実装しないが、**何を評価すべきか**を先に決めておく。

| 指標 | 測り方 |
|---|---|
| **ケース判定の的中率** | 機械判定 vs 人手ラベルの一致率 |
| **summary の的確性** | 人手で「使える/使えない」の二値評価 |
| **原因仮説の含有率** | 「真の原因」が候補リストに含まれていた割合 |
| **アクションの実行可能性** | 提案アクションが具体的に着手可能か（人手スコア） |
| **JSON逸脱率** | バリデーション失敗・fallback発動の頻度 |
| **コスト効率** | 1通知あたりの Bedrock コスト (USD) |

→ MVP稼働後、過去ログで遡及評価することでチューニング指針が得られる。

---

## 5. ケース判定フロー（Reporter Lambdaの実装方針）

LLMに渡す前に Reporter Lambda が**機械的に**ケース判定する（§4.2 ①の具体化）。判定結果でLLM入力とプロンプトを切り替える。

```
1. Logs Insights で window 内の ERROR/FATAL を取得
2. 並行で REPORT 行を取得 (Duration / Memory / Init Duration)
3. パターンマッチでケース推定:
   - "Task timed out"          → ケースB (Timeout)
   - "Memory Size" >= "Max Used" 接近 → ケースC (Memory)
   - error_class == ClientError と botocore兆候 → ケースE (Dependency)
   - error_class in (KeyError, ImportError) かつ recent deploy → ケースF (Config)
   - Throttles メトリクス > 0    → ケースD (Throttling)
   - 上記いずれにも該当しない    → ケースA (Generic Exception)
4. ケースに応じた追加情報を収集 (例: ケースBなら同request_idの全ログ)
5. ケース別プロンプトテンプレートで Bedrock 呼び出し
```

> **設計上の利点**:
> - LLMに「全部の可能性」を考えさせるより**当たり**を絞った方が分析精度が上がる（§4.1の文脈に沿う）
> - ケース別にプロンプトを最適化できる
> - ケース判定の機械的部分は**LLMコスト・レイテンシ削減**にも効く

> **MVPでの妥協**: ケースA/B/E の3つだけ実装し、それ以外は「ケース不明」プロンプトでLLMに丸投げでも初期は許容。

---

## 6. Discord Embedへの落とし込み

ケース別の情報を**Embedのどこに置くか**を決める。Discord Embedは構造が決まっているため、情報設計と同時にUI設計になる。

```
┌─────────────────────────────────────────────────────────┐
│ ⚠ hdw-ingest-errors                          [color]    │  ← case-dependent color
│ <1行サマリ: 何が起きたか>                                │  ← description (LLM)
├─────────────────────────────────────────────────────────┤
│ 🔖 ケース       │ 📊 影響                                │  ← top row (機械)
│ Timeout         │ 3件 / 全120件中 (2.5%)                │
├─────────────────────────────────────────────────────────┤
│ 🧭 原因仮説  [confidence: medium]                       │  ← LLM output (full)
│ <root_cause_hypothesis>                                  │
├─────────────────────────────────────────────────────────┤
│ ✅ 推奨アクション                                        │  ← LLM output (full)
│ - <action 1>                                             │
│ - <action 2>                                             │
├─────────────────────────────────────────────────────────┤
│ 🔍 詳細リンク                                            │  ← deeplinks (機械)
│ [Logs Insights] [CW Logs] [Metrics] [X-Ray (該当時)]    │
├─────────────────────────────────────────────────────────┤
│ 🧪 サンプル request_id: abc123...                       │  ← footer (機械)
└─────────────────────────────────────────────────────────┘
```

**設計原則**:
- **上3行で「対応すべきか」が判断できる**（title + 1行サマリ + ケース・影響）
- **次の2フィールドでLLM分析を読む**（仮説・アクション、confidence併記）
- **深掘りは全部リンクで**（本文には貼らない、Embed 6000文字制限への配慮）
- **LLM起源 / 機械起源** がEmbed上で見分けられるとなお良い（confidence表示で間接的に実現）

---

## 7. Bedrockシステムプロンプトへの示唆

ケース判定をReporter Lambda側でやる前提（§5）と LLMの役割を絞る方針（§4）を反映。**ケースを伝えた上で分析させる** + **構造化出力を強制** + **「分からない」を許容**。

```python
SYSTEM_PROMPT_TEMPLATE = """\
あなたはAWS Lambda障害分析の専門家です。
このアラートは事前判定で「{case}」に分類されました。
{case_specific_instructions}

# 制約
- 必ず下記JSON Schemaに従ってください。スキーマ外の出力は禁止。
- コードベース固有の根本原因は知らない前提で、仮説として複数提示してください。
- 情報不足で判断できない場合は、捏造せず confidence: "low" と
  root_cause_hypothesis に「情報不足 — <何が足りないか>」と書いてください。

# 出力スキーマ
{
  "summary": "1行で何が起きたか（30文字以内）",
  "severity": "LOW" | "MEDIUM" | "HIGH",
  "confidence": "low" | "medium" | "high",
  "root_cause_hypothesis": "原因仮説（複数あれば優先順）",
  "suggested_actions": ["即時対応", "調査手順", "恒久対策"]
}
"""

CASE_INSTRUCTIONS = {
    "TIMEOUT": "直前ログから処理ステップを推定し、どの外部呼び出しで詰まったかを推測してください。",
    "MEMORY": "max_memory_used / memory_size の比から、設定変更で済むかコード起因かを判定してください。",
    "DEPENDENCY": "AWS error code から transient/permanent を判定し、retry戦略を推奨してください。",
    "GENERIC": "error_class と stack trace から原因仮説を複数挙げ、優先順位を付けてください。",
    ...
}
```

> 単一の汎用プロンプトより**ケース別の追加指示** + **「分からない」を許容する制約**を入れた方が、JSON逸脱率と hallucination が顕著に下がる（経験則 / §4.5 と整合）。

---

## 8. MVPで「やる」と「やらない」

このドラフトの提案を全部やると重い。MVPで実装する範囲を切る。

| 項目 | MVP | 後追い |
|---|---|---|
| コア6項目の抽出 | ✅ | — |
| ケースA/B/E の判定とケース別プロンプト | ✅ | — |
| ケースC/D/F/G の判定 | ❌ | 頻度が顕在化したら |
| LLM出力 JSON Schema バリデーション | ✅ | — |
| `confidence` フィールド対応 | ✅ | — |
| fallback embed（LLM失敗時の機械情報のみ通知） | ✅ | — |
| Embed の構造化（§6 のレイアウト） | ✅ | — |
| Deeplinks (Logs / Insights / Metrics) | ✅ | — |
| X-Ray traceリンク | ❌ | X-Ray導入時 |
| 同request_id全ログ取得（ケースB用2段クエリ） | ✅ | — |
| デプロイ時刻取得（ケースF用） | ❌ | ケースF対応時 |
| LLM出力のオフライン評価指標（§4.6） | ❌ | 稼働後チューニング段階で |

---

## 9. オープンな論点

- **ケース判定の信頼性**: パターンマッチで誤判定が出た時、LLMに上書き判断させるか、人が直すか。
- **情報量とDiscord文字数制限のトレードオフ**: Embed 1個6000文字 / fieldは1024文字。長いstack traceは切る or リンク化。
- **同一エラー連発時のレポート間引き**: 本ドラフト範囲外（dedupeはMVP外）だが、ケース別に間引き方を変える設計余地あり。
- **過去レポートとの相関**: 「先週も同じケースが出た」が分かると価値が上がる。S3+DDB保存とセット。
- **LLMモデルの選択肢**: Sonnet 4.6 で十分か。Haiku 4.5 でケース別プロンプト前提なら品質維持しつつコスト1/4も狙えるか（§4.6の評価指標で測れるようにしておく）。

---

## 10. 次のステップ

1. 本ドラフトをレビュー → PLAN化
2. ケース判定ロジックを `src/case_classifier.py` として実装
3. ケース別プロンプトテンプレートを `src/prompts/` に分離
4. LLM出力 JSON Schema を `src/schema.py` に定義しバリデーション組み込み
5. Discord Embed builder をケース別 + confidence対応に拡張
6. fallback embed パスを `src/main.py` のhandler内に実装（例外時の最終防衛）
7. 既存のhdw-ingestログを使ってオフライン精度評価（過去N件のエラーで判定精度・LLM出力品質を計測）
