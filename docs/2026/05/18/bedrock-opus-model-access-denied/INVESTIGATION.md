---
title: HDW_Lambda_Notifier_0001 が Bedrock Converse で AccessDenied を出し続ける件
date: 2026-05-18
status: investigation
type: incident-report
scope: test-env / reporter-lambda runtime
author: t.kimura@scrumsign.com
tags:
  - aws-lambda
  - bedrock
  - claude
  - access-denied
  - model-access
  - foundation-model-agreement
  - opus-4-7
  - incident
related:
  - ../../15/lambda-error-report-mvp/PLAN.md
  - ../../15/report-content-by-case/DRAFT.md
  - ../../../../operations.md
references:
  - https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html
  - https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-permissions.html
---

# HDW_Lambda_Notifier_0001 Bedrock Converse AccessDenied 調査

## 0. サマリ

test 環境 (`hdw-test` / `088898720463` / `ap-northeast-1`) の Reporter Lambda
`HDW_Lambda_Notifier_0001` が、CloudWatch Alarm 起動時に毎回 Bedrock
`Converse` 呼び出しで `AccessDeniedException` を返して落ちている。

**1次原因（確定）**: test アカウントで Claude Opus 4.7 の
**Foundation Model Agreement が未作成**（`agreementAvailability.status =
NOT_AVAILABLE`）。直近コミット `c43b714 test 環境の Bedrock モデルを Opus 4.7
に変更` でモデルを Sonnet 4.6 → Opus 4.7 に切り替えたが、Opus 4.7 のモデル
アグリーメント作成が追従していない（Sonnet 4.6 は過去にアグリーメント作成
済みだったため動いていた）。

Bedrock は本来「初回 invoke で AWS Marketplace サブスクリプションを auto
作成」する設計だが、これには**呼び出し IAM principal に Marketplace 権限**
が必要。Lambda 実行ロール `hdw-notify-execution-role` は Marketplace 権限を
持たないため auto-subscribe が走らず、結果としてアグリーメント未作成のまま
`AccessDeniedException` を返し続けている。

**当面の影響**: 全アラームが Discord 通知されない。Lambda は非同期 invocation
のデフォルトリトライ (`MaximumRetryAttempts = 2`) で計3回失敗する。

---

## 1. 観測

### 1.1 対象

| 項目 | 値 |
|---|---|
| Lambda | `HDW_Lambda_Notifier_0001` |
| アカウント / リージョン | `088898720463` (hdw-test) / `ap-northeast-1` |
| 関数 LastModified | 2026-05-15 08:51:01 UTC |
| 実行ロール | `hdw-notify-execution-role` |
| `BEDROCK_MODEL_ID` (env) | `jp.anthropic.claude-opus-4-7` |

### 1.2 ログパターン

最新2ストリームを確認、いずれも同パターン（各ストリーム内で同 RequestId が
3回繰り返される）:

```
START
INFO  alarm received
INFO  insights query started
INFO  insights query done   status=Complete  rows=0
[ERROR] AccessDeniedException (Converse)
END
REPORT  Duration ~1.5-2.0s  Memory 99-100 MB
```

3回繰り返しは **Lambda 非同期 invocation のデフォルトリトライ** と整合
（CloudWatch Alarm からの直接 Lambda invoke は非同期 invocation 扱い）。

### 1.3 エラー本文（全 invocation で同一）

```text
[ERROR] AccessDeniedException: An error occurred (AccessDeniedException)
when calling the Converse operation: Model access is denied due to IAM user
or service role is not authorized to perform the required AWS Marketplace
actions (aws-marketplace:ViewSubscriptions, aws-marketplace:Subscribe)
to enable access to this model. Refer to the Amazon Bedrock documentation
for further details. Your AWS Marketplace subscription for this model
cannot be completed at this time. If you recently fixed this issue,
try again after 2 minutes.

Traceback (most recent call last):
  File "/var/task/main.py", line 124, in main
    bedrock_response = boto3.client("bedrock-runtime").converse(...)
  ...
```

呼び出し箇所: [`src/main.py:125`](../../../../src/main.py#L125) の
`converse(...)`。

### 1.4 Foundation Model Availability 実測

```text
aws bedrock get-foundation-model-availability
  --model-id anthropic.claude-opus-4-7
→ {
    "agreementAvailability":  { "status": "NOT_AVAILABLE" },   ← ★ 未作成
    "authorizationStatus":    "AUTHORIZED",
    "entitlementAvailability": "AVAILABLE",
    "regionAvailability":      "AVAILABLE"
  }
```

`agreementAvailability` だけが `NOT_AVAILABLE`。他はすべて OK。
つまり「アカウントは Bedrock 認可済み・モデルは購入可能・リージョン提供あり」
だが「このアカウントでこのモデルのアグリーメントが作成されていない」状態。

---

## 2. 切り分け

### 2.1 IAM (許可済み)

`hdw-notify-execution-role` の inline policy `hdw-notify-permissions` 中の
`BedrockInvoke` ステートメント:

```json
{
  "Sid": "BedrockInvoke",
  "Effect": "Allow",
  "Action": "bedrock:InvokeModel",
  "Resource": [
    "arn:aws:bedrock:ap-northeast-1:088898720463:inference-profile/jp.anthropic.claude-sonnet-4-6",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-*",
    "arn:aws:bedrock:ap-northeast-1:088898720463:inference-profile/jp.anthropic.claude-opus-4-7",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-*"
  ]
}
```

→ inference profile / foundation-model 両 ARN を Opus 4.7 についても列挙済み。
`bedrock:InvokeModel` レベルでは**許可されている**。

### 2.2 モデル・Inference profile の存在 (両方 ACTIVE)

```text
aws bedrock list-foundation-models --by-provider anthropic
  → anthropic.claude-opus-4-7: ACTIVE

aws bedrock get-inference-profile
  --inference-profile-identifier jp.anthropic.claude-opus-4-7
  → status: ACTIVE
  → routes to ap-northeast-1 + ap-northeast-3 のモデル
```

### 2.3 Bedrock auto-subscribe の仕組み (公式仕様)

[公式ドキュメント](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)
より要約:

> When you invoke a third-party model for the first time in your account,
> Amazon Bedrock automatically initiates the subscription process in the
> background. ... If any prerequisites are missing, the subscription
> attempt fails and subsequent API calls will return `AccessDeniedException`.

つまり「初回 invoke 時に Bedrock が裏で Marketplace サブスクリプションを
作る」設計。これが成功するための前提:

| 前提 | 状態 |
|---|---|
| 呼び出し IAM principal が `aws-marketplace:Subscribe` / `Unsubscribe` / `ViewSubscriptions` を持つ | **Lambda 実行ロールには無い** → auto-subscribe 失敗 |
| Anthropic モデル: First Time Use (FTU) フォーム提出済み（org root または account 単位、1回限り） | Sonnet 4.6 が動いていた実績から **提出済み** と推定 |
| 有効な支払い方法 | 既存運用から **OK** と推定 |

「アカウント内の**誰か1人**が一度成功させれば、それ以降は全 principal が
`bedrock:InvokeModel` だけで呼べる」（同公式より）。これが Sonnet 4.6 が
動いていた理由でもある（=過去に誰かが GUI かAPI でアグリーメントを作った）。
**Opus 4.7 はそれが行われていない**。

### 2.4 副次観察: Insights クエリ結果が常に 0 行

`TestAlarm` は `HDW_Backend_Processor_0001` の `Invocations > 0` で発火する
設定（実 error 発生条件と切り離されている）。クエリ条件 `status = "error"`
に該当するレコードが時間窓に存在せず空配列が返る。**Notify 側ロジックの
不具合ではない**。ただし 0 行でも Bedrock を呼ぶ作りになっているため、
本件と独立した改善余地として記録する（§4 ③）。

---

## 3. 推定根本原因

| # | 仮説 | 評価 |
|---|---|---|
| ① | test アカウントで Opus 4.7 の **Foundation Model Agreement が未作成** | **確定**。§1.4 実測 `NOT_AVAILABLE` |
| ② | Lambda 実行ロールに Marketplace 権限が無く auto-subscribe が走らない（① を解消できない構造的理由） | **確定**。§2.1, §2.3 |
| ③ | IAM `bedrock:InvokeModel` 不足 | 否定（§2.1） |
| ④ | inference profile ARN 誤り / 非存在 | 否定（§2.2） |
| ⑤ | Bedrock 側の一時障害 | 否定（同症状が複数日・複数 invocation で再現） |

**重要**: Lambda 実行ロールに Marketplace 権限を付けて「invoke 時に
auto-subscribe させる」設計は推奨されない。Marketplace 操作はワークロード
ランタイムが毎回触る性質のものではなく、**人間の管理操作で1回作る**のが
正しい。

---

## 4. 対処

優先度順。

### ① 即時（本件解消）— アグリーメント作成

以下 A / B どちらか1つ。あなた本人 (t.kimura) が AWS console / CLI で
実行する。FTU は Sonnet 4.6 が動いていた実績から提出済みと推定（未提出
だった場合は手順内でフォーム提出を求められる）。

**A. コンソール手順（推奨。1分）**

1. AWS Console (test アカウント, `ap-northeast-1`) → Bedrock
2. 左メニュー **Model catalog**
3. Anthropic → **Claude Opus 4.7** を選択
4. **Request model access**（FTU 未提出ならフォームが出るので埋める）
5. 数十秒で反映

**B. CLI 手順（自動化したい場合）**

呼び出し principal に `bedrock:CreateFoundationModelAgreement` と
`aws-marketplace:Subscribe` が必要（`AmazonBedrockFullAccess` で十分）。

```powershell
$env:PYTHONUTF8 = '1'

# 1) offerToken 取得
$offer = aws bedrock list-foundation-model-agreement-offers `
  --profile hdw-test --region ap-northeast-1 `
  --model-id anthropic.claude-opus-4-7 `
  --offer-type PUBLIC | ConvertFrom-Json

# 2) アグリーメント作成
aws bedrock create-foundation-model-agreement `
  --profile hdw-test --region ap-northeast-1 `
  --model-id anthropic.claude-opus-4-7 `
  --offer-token $offer.offers[0].offerToken

# 3) 反映確認 (AVAILABLE になればOK、最大2分)
aws bedrock get-foundation-model-availability `
  --profile hdw-test --region ap-northeast-1 `
  --model-id anthropic.claude-opus-4-7
```

**反映確認後**: 次の Alarm 発火（または手動 invoke）で
`[ERROR] AccessDeniedException` が消え Discord に通知が出れば完了。

### ② production アカウントの確認

2026-05-18 時点の [`deploy/config-prod.yml`](../../../../deploy/config-prod.yml) は
`aws_bedrock_model_id: jp.anthropic.claude-sonnet-4-6` のままなので
**prod は本件の影響を受けていない**。将来 prod も Opus 4.7 へ切り替える
場合は、切替コミット前に prod アカウント (`hanshin / 920373030024`) で
同じアグリーメント作成手順 (§4.①) を実施しておく必要がある。

### ③ 設計フォロー: fallback embed

現状の [`src/main.py`](../../../../src/main.py) は Bedrock 失敗を try/except
で捕捉せず、例外がそのまま伝播する。`report-content-by-case` DRAFT §4.5 で
計画されている **「LLM 失敗時に機械抽出のコア6項目だけで Discord 通知」** の
fallback 経路が未実装のため、今回のように Bedrock 側で恒常的に失敗すると
**Discord 通知が完全に欠落** + **Lambda リトライで失敗ログだけが3倍に積もる**。

実装すれば:
- 通知ゼロを防げる（運用者は問題発生を Discord で把握できる）
- Lambda は成功終了するためリトライ嵐が止まる

### ④ コスト最適化: rows: 0 早期 return

`log_rows` が空のときは LLM 分析しても意味がない。`if not log_rows: return ...`
または機械抽出のみ Discord 通知する分岐で、無駄な Bedrock 呼び出しを抑止
できる。本件とは独立の改善。

### ⑤ ドキュメント整合

- [`docs/operations.md`](../../../../operations.md) のアーキ図が
  `Bedrock Converse (Claude Sonnet 4.6)` のままになっている。Opus 4.7 への
  切替後に追従していないので更新したい。
- 同ファイル「ハマりどころ」セクションに本件
  （**モデル切替時は新モデルの Foundation Model Agreement 作成が必要**）を
  追記すると、次回モデル変更時のチェックリストになる。

---

## 5. 最新ドキュメントに基づく訂正メモ

本調査の初版では「Bedrock コンソールの『Model access』ページから承認」と
書いていたが、最新ドキュメントを再確認したところ **commercial リージョン
では『Model access』ページは GovCloud 専用**で、commercial 側は「正しい
Marketplace 権限さえあれば全モデルがデフォルトで有効」という建付けに
変わっている。実際の作業フローは:

- 通常ユーザー: **Model catalog から目的モデルを開いて Request model access**
  → 裏で `CreateFoundationModelAgreement` + 必要なら FTU フォーム
- 自動化: 同じ操作を `bedrock:CreateFoundationModelAgreement` API で直接

本ドキュメントの §4 はこの仕様に合わせた手順を記載している。

---

## 6. 確認に使ったコマンド

参考用。`hdw-test` プロファイルで実行。`$env:PYTHONUTF8='1'` を事前にセット
しておかないと、CLI が日本語ログを CP932 で出そうとして途中エラーになる
ことがある。

```powershell
$env:PYTHONUTF8 = '1'

# ストリーム一覧
aws logs describe-log-streams `
  --profile hdw-test --region ap-northeast-1 `
  --log-group-name "/aws/lambda/HDW_Lambda_Notifier_0001" `
  --order-by LastEventTime --descending --max-items 10

# 個別ストリーム取得
aws logs get-log-events `
  --profile hdw-test --region ap-northeast-1 `
  --log-group-name "/aws/lambda/HDW_Lambda_Notifier_0001" `
  --log-stream-name "<stream-name>" --start-from-head

# Lambda 設定 / IAM
aws lambda get-function-configuration `
  --profile hdw-test --region ap-northeast-1 `
  --function-name HDW_Lambda_Notifier_0001
aws iam get-role-policy `
  --profile hdw-test --role-name hdw-notify-execution-role `
  --policy-name hdw-notify-permissions

# Bedrock モデル / Inference profile
aws bedrock list-foundation-models `
  --profile hdw-test --region ap-northeast-1 --by-provider anthropic
aws bedrock get-inference-profile `
  --profile hdw-test --region ap-northeast-1 `
  --inference-profile-identifier jp.anthropic.claude-opus-4-7

# Bedrock モデルアグリーメント状態（本件の核心）
aws bedrock get-foundation-model-availability `
  --profile hdw-test --region ap-northeast-1 `
  --model-id anthropic.claude-opus-4-7
aws bedrock list-foundation-model-agreement-offers `
  --profile hdw-test --region ap-northeast-1 `
  --model-id anthropic.claude-opus-4-7 --offer-type PUBLIC
```
