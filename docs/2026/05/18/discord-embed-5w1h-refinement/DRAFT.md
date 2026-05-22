---
title: Discord 埋め込みの表示内容を 5W1H で洗練する
date: 2026-05-18
status: draft
type: information-design
scope: discord-embed
author: t.kimura@scrumsign.com
related:
  - ../../05/15/lambda-error-report-mvp/PLAN.md
  - ../../05/15/report-content-by-case/DRAFT.md
tags:
  - discord
  - embed
  - information-design
  - 5w1h
  - incident-response
  - observability
audience: 運用Lambda(hdw-ingest)の開発・運用担当者
purpose: >
  Discord 通知の Embed 表示内容を 5W1H（When/Where/Who/What/Why/How）で再設計するための
  たたき台。MVP 実装で固定した「title + summary + 原因仮説 + 推奨アクション + timestamp」
  の構成を、運用者が「次の30秒で判断する」観点で再評価し、各 W/H に何を載せるか／載せないかを
  議論で決め切る前段ドキュメント。
---

# Discord 埋め込みの表示内容を 5W1H で洗練する

## 0. このドキュメントの位置づけ

[lambda-error-report-mvp/PLAN.md](../../05/15/lambda-error-report-mvp/PLAN.md) で**配管**を、
[report-content-by-case/DRAFT.md](../../05/15/report-content-by-case/DRAFT.md) で**中身の方向性**を
それぞれ固めた。本ドラフトは **Embed の表示面**に絞り、5W1H フレームで現状を採点して
「何を足す／何を削る／何をどこに置く」を議論で決めるためのたたき台。

> **核心の問い**:
> 現在の Embed（title + 1行 summary + 原因仮説 + 推奨アクション + timestamp）で、
> 受信者は本当に **When / Where / Who / What / Why / How** を全部読み取れているか？
> 欠けているのはどれで、過剰なのはどれか？

このドラフトは結論を出さない。**前提を共有 → 5W1H で現状を採点 → 論点を列挙**までで止めて、
レビューを経て PLAN へ昇格させる。

---

## 1. 前提の共有

議論を空中戦にしないため、まず 3 つの前提を明文化する。これに合意してから 5W1H の検討に入る。

### 1.1 このリポジトリの基本的な目的

**HDW_Notify は「運用 Lambda（`HDW_Backend_Processor_0001` = hdw-ingest）の失敗を運用者へ即時通知し、
30 秒以内に次の一手を判断させる」ための Lambda 通知パイプライン。**

```
CloudWatch Alarm
   │ (Errors >= 1)
   ▼
Reporter Lambda (HDW_Lambda_Notifier_0001)
   │   ├─ Logs Insights でエラーログ取得
   │   ├─ Bedrock (Claude Sonnet 4.6 / Opus 4.7) で分析
   │   └─ Discord webhook へ Embed POST
   ▼
Discord チャネル（運用者が常駐）
```

- 通知は **「アラート」そのもの**であり、ダッシュボードの代替ではない。
- 「見れば対応判断できる」ことが価値の中心。詳細は CloudWatch にリンクで逃がす設計。
- Embed の情報量は Discord の制約（Embed 全体 6000 字 / field 1024 字 / field 数 25）に収める。

### 1.2 ユーザー

通知の**受信者**と**発信元**の双方を整理する。Embed の設計は受信者目線が主だが、
発信元の能力（何が取れて何が取れないか）が表現の上限になる。

| 区分 | 誰 | 通知に対する関心 |
|---|---|---|
| **一次受信者** | 運用 Lambda（hdw-ingest）の開発・運用担当者（社内、数名） | これは今すぐ自分が動くべきか／放置可か |
| **二次受信者** | 同チームの他メンバー、PM、後から見る人 | 過去にどんな障害があったか・トレンド |
| **発信元** | Reporter Lambda（機械抽出）＋ Bedrock LLM（自然言語化） | 機械が確証を持って言える事と、LLM の仮説の区別 |

> **暗黙の前提**:
> - 受信者は **AWS / hdw-ingest のコードベースを知っている**。一般的な Lambda 障害の知識もある。
> - 受信者は **Discord をモバイル/PC 両方で見る可能性**がある。狭幅でも崩れない設計が要る。
> - 通知は **チャネルに流れて埋もれる**前提。1 通の自己完結性が高いほど良い。

### 1.3 知りたいこと（受信者が 30 秒で答えを得たい問い）

[report-content-by-case/DRAFT.md §1](../../05/15/report-content-by-case/DRAFT.md) で定義した
3 判断を踏襲。これが Embed が答えるべき**目的関数**。

| # | 受信者の問い | 判断の出力 |
|---|---|---|
| ① | **今すぐ対応すべきか？** | "対応する" / "後でよい" / "放置" |
| ② | **何が起きているのか？** | 障害の一行要約（自分の言葉で誰かに説明できるレベル） |
| ③ | **どこを見れば深掘りできるか？** | CW Logs / Insights / Metrics のいずれかへの最短動線 |

Embed の全フィールドは、この 3 問いのどれか（または複数）に貢献するべき。
**どの問いにも貢献しない情報は載せない**を原則にする。

---

## 2. 5W1H フレームで現状の Embed を採点

現状の Embed を 5W1H に分解し、「何が表現されている／されていない」を率直に評価する。

### 2.1 現状の Embed 構造（再掲）

[src/main.py:166-187](../../../../src/main.py#L166-L187) より。

```
┌──────────────────────────────────────────┐
│ ⚠ <alarm_name>                  [color]  │  title (機械)
│ <summary>                                │  description (LLM 1行)
├──────────────────────────────────────────┤
│ 原因仮説                                  │  field (LLM)
│ <root_cause_hypothesis>                  │
├──────────────────────────────────────────┤
│ 推奨アクション                            │  field (LLM)
│ - <action 1>                              │
│ - <action 2>                              │
├──────────────────────────────────────────┤
│                       <timestamp, JST>   │  footer-ish (機械)
└──────────────────────────────────────────┘
```

- **機械由来**: title, color, timestamp の 3 つだけ。
- **LLM 由来**: description（summary）, 原因仮説, 推奨アクション の 3 つ。
- **欠けているもの**: 件数・影響範囲、deeplink、関数名（titleの alarm 名から推測する形）、
  request_id、ケース種別、confidence、Lambda 環境（dev/prod）等。

### 2.2 5W1H 採点表

各 W/H について「現状で表現できているか」「足りていないなら何が必要か」を整理。

| W/H | 受信者の問い | 現状の表現 | 評価 | 不足／改善余地 |
|---|---|---|---|---|
| **When** | いつ起きたか／いつから続いているか | `timestamp`（発火時刻のみ） | △ | 集計時間窓（start–end）、初回観測時刻、継続中か収束したか |
| **Where** | どの環境のどの Lambda／どのコード位置か | `alarm_name` に Lambda 名を含意 | △ | 環境タグ（dev/prod）、関数名の明示、stack trace の file:line、リージョン |
| **Who** | 誰の責務か／誰が動くべきか | 暗黙（チャネル受信者全員） | × | オーナー（ロールでも可）、エスカレーション先、無言の「全員放置」回避策 |
| **What** | 何が起きたか／何件か | `summary`（LLM 1行）| △ | エラー件数 / invocation 数 / 影響比率、エラー分類、代表エラーメッセージ、ケース種別 |
| **Why** | なぜ起きたか（仮説） | `root_cause_hypothesis`（LLM）| ○ | confidence、複数仮説の順位付け、「情報不足」の明示 |
| **How** | どう対処するか／どこを見るか | `suggested_actions`（LLM）| △ | 即時／調査／恒久 の段階分離、deeplink（Logs / Insights / Metrics）、代表 request_id |

> **総評**:
> - **Why と How（の方向性）は LLM が出している**が、それを裏打ちする**機械的事実（When 範囲・What 件数・Where 位置）が薄い**。
> - **Who が完全に欠落**。チャネル全員宛＝誰も動かないリスク。
> - **deeplink ゼロ**は痛い。Embed の自己完結性は高いが、深掘り動線がない。

### 2.3 5W1H 別・候補要素の洗い出し（議論の素材）

各 W/H に**載せ得る**要素を列挙する。全部載せる意味ではない。
§3 の論点で取捨選択を議論する。

#### When（いつ）
- `alarm_fired_at` — Alarm 発火時刻（既存）
- `window_start` / `window_end` — 集計時間窓（JST）
- `first_seen` — そのエラーパターンが最初に観測された時刻
- `is_ongoing` — まだ続いているか／既に収まったか
- `time_since_last_deploy` — 直近デプロイからの経過（ケース F の判定補助）

#### Where（どこで）
- `function_name` — Lambda 関数名（title から独立して field 化）
- `environment` — dev / staging / prod
- `region` — 例: ap-northeast-1
- `account_id` — 複数アカウント運用時
- `code_location` — stack trace 由来の `file:line in func`（ケース A）
- `event_source` — S3 key / SQS queue / EventBridge rule 等

#### Who（誰が）
- `owner` — 関数オーナー（人 or ロール）
- `escalation` — 1 次／2 次の連絡先
- `on_call` — 当番（運用してれば）
- `mention` — `<@user_id>` での Discord メンション

#### What（何が）
- `summary` — 1 行サマリ（既存）
- `case` — ケース種別（A: 例外 / B: timeout / C: memory / D: throttle / E: dependency / F: config / G: data）
- `error_count` / `invocation_count` / `error_rate` — 量的影響
- `error_class` + `error_message` — 代表エラー
- `representative_request_id` — 該当ログへの最短経路
- `affected_inputs` — S3 key 等の代表入力

#### Why（なぜ）
- `root_cause_hypothesis` — 原因仮説（既存）
- `confidence` — `low / medium / high`
- `alt_hypotheses` — 順位付き複数仮説
- `unknown_marker` — 情報不足を明示する固定文言

#### How（どう）
- `suggested_actions` — 推奨アクション（既存）
- `actions_immediate` / `actions_investigate` / `actions_long_term` — 3 段分離
- `deeplink_logs` — CloudWatch Logs（function group へ直リンク）
- `deeplink_insights` — Logs Insights（クエリ + 時間窓を埋め込んだ URL）
- `deeplink_metrics` — Errors / Throttles / Duration のメトリクス
- `deeplink_xray` — X-Ray（導入時）
- `runbook_url` — Runbook へのリンク（あれば）

---

## 3. 論点（議論で決めたいこと）

以下、合意が要る項目を列挙する。順序は重要度の主観。

### 3.1 Embed の "header" を機械由来で固める範囲

- 現状: title（alarm 名）+ description（LLM の summary）+ color
- 提案候補: title に「環境 + 関数名 + ケース」を機械で詰め、description は LLM summary を残す
- 例: `[prod] hdw-ingest · Timeout · 3件/120 (2.5%)`
- 論点: title の文字数（256 字）と可読性のバランス、emoji の扱い

### 3.2 Who をどう表現するか

- 「誰が動くべきか」を明示しないと **全員放置 → SLO 違反**になりがち
- 候補: ① 固定オーナーを env で持つ、② severity HIGH 時のみ `<@&role_id>` メンション、③ オンコール表参照
- 論点: メンション過剰でノイズになる閾値はどこか / dev と prod で挙動を変えるか

### 3.3 deeplink をどこまで載せるか

- 受信者の問い③「どこを見れば深掘りできるか」は現状未対応
- 候補: ① 専用 field 1 つに inline リンク 3〜4 個並べる、② Embed の `url` プロパティ（title をリンク化）に Insights URL を入れる、③ author 行を使う
- 論点: モバイル表示で崩れないか / URL 長制限（field 1024 字）に収まるか

### 3.4 件数・影響範囲をどう取るか

- 現状 LLM は summary 内に件数を書くこともあるが**機械保証なし**
- Logs Insights の stats / CW Metrics で取って機械 field 化すべき
- 論点: 計算コスト（追加クエリ 1 本分）と、欲しい指標（件数 / 比率 / 推移）の優先度

### 3.5 confidence の表示

- LLM 出力に `confidence` を必須化（[report-content-by-case §4.5](../../05/15/report-content-by-case/DRAFT.md)）した前提で、Embed にどう出すか
- 候補: ① 原因仮説 field の名前に併記（`原因仮説 [confidence: medium]`）、② color を confidence で控えめにする、③ footer に出す
- 論点: 「LLM 起源 / 機械起源」の区別を受信者が無意識に出来る UI か

### 3.6 ケース未実装時の degrade 戦略

- 現状ケース分類器は未実装（Generic 固定 — [src/main.py:146](../../../../src/main.py#L146)）
- ケース field を「未分類」にして出すか、ケース判定 PR まで field 自体を出さないか
- 論点: 段階導入の見せ方

### 3.7 fallback Embed の形

- LLM 失敗（JSON 逸脱・タイムアウト）時の最低限 Embed をどう作るか
- 5W1H のうち機械由来で埋められる When / Where / What（一部）/ How（deeplink のみ）だけで成立させる
- 論点: fallback と通常 Embed を**見た目で区別**するか（受信者に「LLM 分析欠落」を伝える）

### 3.8 Embed 字数制限とのトレードオフ

- Discord Embed 全体 6000 字 / field 1024 字 / field 数 25
- 全 W/H を埋めると 10 field 前後になる見込み
- 論点: モバイルでの可読性 / スクロール許容量 / 詰めすぎて読まれない問題

### 3.9 環境タグ（dev/prod）の扱い

- 現状 `env.environment` 由来の情報は Embed に出ていない
- prod での誤通知と dev でのノイズは扱いが違う
- 候補: color を環境で分ける / title に `[prod]` プレフィックス / footer に環境名

### 3.10 timestamp の見せ方

- 現状 `embed.set_timestamp(timestamp)` で Embed 標準の相対時刻（"1 minute ago" 等）が表示される
- 集計時間窓（start–end）も出すと「いつから・いつまで」が分かる
- 論点: Discord のローカル時刻表示と JST 明示のどちらを優先するか

---

## 4. 段階導入の素案（議論後に PLAN へ）

合意できた W/H から順に Embed へ追加していく前提で、ステップを置く。
**この節は §3 の議論の結果次第で書き換える前提**。

| Step | 内容 | 主に埋める W/H |
|---|---|---|
| 1 | deeplink（Logs / Insights / Metrics）を field 追加 | How |
| 2 | function_name / environment を title or field に分離 | Where |
| 3 | error_count / invocation_count / error_rate を機械抽出して field 追加 | What |
| 4 | confidence を LLM 出力 schema に追加し Embed に併記 | Why |
| 5 | ケース判定（A/B/E）と case field 表示 | What |
| 6 | owner / mention（severity HIGH 時のみ） | Who |
| 7 | window_start / window_end の明示 | When |
| 8 | fallback Embed パスの実装 | 全 W/H（縮約版） |

---

## 5. 次のアクション（このドラフトの使い方）

1. **§1 の前提**（目的・ユーザ・知りたいこと）に合意する。
2. **§2.2 の採点**が妥当か（評価が辛すぎる／甘すぎるところはないか）合意する。
3. **§3 の論点**を 1 つずつ潰す。決まったものは §4 のステップに反映。
4. 全論点の方針が決まったら、本ドラフトを **PLAN.md** に昇格し、コード変更タスクへ落とす。

---

## 6. オープンクエスチョン（今すぐ答えなくてよい）

- 同一 Alarm の連続発火時に **dedupe** をかけるか（本ドラフト範囲外だが Embed 設計に影響）。
- **過去の同種通知へのリンク**を載せる価値はあるか（履歴保存とセット）。
- **dev / prod で Embed テンプレート自体を分ける**か、同一テンプレートでフィールド出し分けか。
- **multilingual**（英語化）は将来必要か。現状は日本語固定。
- **AI 生成物の責任表示**（"これは LLM 生成の仮説です" の常時表記）を入れるか。
