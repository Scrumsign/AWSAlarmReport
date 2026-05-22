---
id: cross-account-architecture
version: 3.3.0
title: クロスアカウント Alarm 受信・ログ取得アーキテクチャ
created_at: 2026-05-20
type: spec
---

# クロスアカウント Alarm 受信・ログ取得アーキテクチャ

- **ID**: cross-account-architecture
- **Version**: 3.3.0
- **Created at**: 2026-05-20
- **Authors**: scrumsign-takuyakimura
- **Constitution**: main@1.0.0
- **Dependencies**: なし

## 全体概要

本仕様は HDW_Notify の中心動作である

> クライアント側 Alarm 起爆 → クライアント側 CloudWatch Logs 取得 (クロスアカウント) → Bedrock による LLM 分析 → Discord Webhook 通知

というフローを成立させるための **アカウント分離 + クロスアカウント権限受け渡し** の構成要件を定義する。具体的には以下 5 点:

1. HDW_Notify Lambda の配置を自社アカウントに限定する (REQ-001)
2. SNS Topic Policy による confused-deputy 防止と Subscribe 許可 (REQ-002)
3. STS AssumeRole + ExternalId によるクライアント側ログの読み出し (REQ-003)
4. `LOG_GROUP_MAP` の env var 化 (SSM / DynamoDB 不使用 / PRIN-001) (REQ-004)
5. Logs Insights 時間窓を Alarm 評価窓に合わせて拡張 (REQ-005)

REQ-006 は上記が組み合わさって Alarm 起爆 → Discord 着弾まで一気通貫で動くことを単一の E2E 検証シナリオとして担保する。REQ-007 は Lambda 経由の E2E を回す前に Logs Insights クロスアカウント取得の経路だけを単独で手動検証できることを担保する (E2E 失敗時の切り分けにも使う)。

関連: `constitution main@1.0.0` の PRIN-001 (env vars 一元管理) / PRIN-003 (Bedrock 失敗時の通知保証) / PRIN-004 (LLM 出力スキーマ準拠) の前提となるインフラ構成を本 SPEC で規定する。

## 構成図 (Alarm 起爆 → Discord 通知)

ステップ番号 `(1)`〜`(6)` は処理の発生順。各行は「主体 → 動作 → 対象」の形式。AssumeRole 後の boto3 呼び出しはすべて Reporter Lambda 上で完結する。

### クライアントアカウント (920373030024 / hanshin / ap-northeast-1)

```text
  HDW_Backend_Processor_0001  (監視対象 Lambda)
                          │ structured logs
                          ▼
  CloudWatch Logs         /aws/lambda/HDW_Backend_Processor_0001
                          │ Metric Filter { $.status = "error" }
                          ▼
  CloudWatch Alarm        hdw-backend-processor-0001-errors
                          │
                          │ (1) AlarmAction = SNS:Publish
                          ▼
  SNS Topic               hdw-ml-alarm-topic
                          Policy: aws:SourceArn (alarm:*) /
                                  aws:SourceAccount = 920373030024
```

### クロスアカウント境界  `920373030024` ─▶ `088898720463`

```text
  (2) SNS Topic  ── Subscribe + Invoke ─▶  HDW_Lambda_Notifier_0001 (Reporter)
```

### 自社アカウント (088898720463 / hdw-test / ap-northeast-1)

```text
  HDW_Lambda_Notifier_0001  (Reporter)
    env: EXTERNAL_ID / CROSS_ACCOUNT_ROLE_ARN / LOG_GROUP_MAP

  (3) Reporter  ── sts:AssumeRole + ExternalId ─▶  HDWNotifyLogReader
                                                   (クライアント側 IAM Role)
                                                   Trust:      sts:ExternalId 一致
                                                   Permission: logs:StartQuery /
                                                               logs:GetQueryResults /
                                                               logs:Describe*
      Reporter  ◀── tmp credentials (900s) ──  STS

  (4) Reporter  ── boto3("logs", tmp creds).start_query() ─▶  Logs Insights
                   logGroupName = LOG_GROUP_MAP[AlarmName]    (クライアント側ロググループ)
                   時間窓       = StateChangeTime -30m / +5m
      Reporter  ◀── rows ──  Logs Insights

  (5) Reporter  ── boto3("bedrock-runtime").converse() ─▶  Bedrock (Claude)
                                                           (自社アカウント内 / 同一リージョン)
      Reporter  ◀── 分析 JSON (summary / severity / confidence /
                               root_cause_hypothesis / suggested_actions) ──  Bedrock

  (6) Reporter  ── DiscordWebhook.execute() ─▶  Discord channel
                   HTTPS POST / 5W1H Embed (失敗時は fallback Embed)
```

### 各ステップが規定する REQ

- **(1) AlarmAction = SNS:Publish** … **REQ-002**
- **(2) SNS Topic Policy** (`cloudwatch.amazonaws.com` からの Publish を `aws:SourceArn` + `aws:SourceAccount` で confused-deputy 防止 / 自社アカウント root への Subscribe 許可) … **REQ-002**
- **(3) AssumeRole + ExternalId** (Trust に `sts:ExternalId` 一致条件 / `ExternalId` は GHA Secret 経由で env var 投入) … **REQ-003**
- **(4) LOG_GROUP_MAP の env var 化** (SSM / DynamoDB は使わない / PRIN-001) / Logs Insights 時間窓 = `StateChangeTime ±30 / +5 分` … **REQ-004**, **REQ-005**
- **(5) Bedrock** は自社アカウント内呼び出し (クロスアカウント不要)
- **(6) Discord Webhook** は失敗時も fallback Embed を必ず送出 … **PRIN-003**

## 用語集

### 自社アカウント

HDW_Notify Lambda が動作する AWS アカウント (088898720463 / hdw-test)。
bootstrap 段階では test 環境として用意されており、本仕様で本番運用ロールも
兼ねる構成として正式に稼働を開始する。
profile: hdw-test / region: ap-northeast-1

### クライアントアカウント

監視対象 HDW_ML が動作する AWS アカウント (920373030024 / hanshin)。
現時点で唯一のクライアント。SNS Topic と AssumeRole 対象 IAM Role を本仕様で
新規に提供してもらう (HDW_Notify Lambda 本体はこのアカウントには配置しない)。
profile: hanshin-t.kimura / region: ap-northeast-1

### ExternalId

AWS STS AssumeRole 時に Trust Policy 側で StringEquals 条件として要求される
識別子。Confused Deputy 問題を緩和するためクライアントごとに別値とする。

AWS 公式仕様 (IAM User Guide / id_roles_common-scenarios_third-party):

- ExternalId は **secret ではない** ("AWS does not treat the external ID as a secret.
  The external ID for a role can be seen by anyone with permission to view the role.")。
- 値は **role を引き受ける側 (= 自社 HDW_Notify) が生成**し、クライアントに通達する。
  クライアントは Trust Policy の `sts:ExternalId` 条件に同じ値を書く。
  (理由: 第三者ごとに ExternalId を一意にする責任は role-assuming 側にある。
  複数顧客で同じ値を使うと、ある顧客の信頼が別顧客の role 侵害につながる。)
- 推奨: 2-1224 文字、alphanumeric + `+=,.@:/-`。ランダム文字列推奨。

本プロジェクトでの運用: secret ではないものの、攻撃面縮小と git/log への
漏洩防止のため、GHA Secret (`EXTERNAL_ID_HANSHIN`) を経由して Lambda 環境変数
`EXTERNAL_ID` に投入する。SPEC / config YAML には生値を含めない。

### LOG_GROUP_MAP

AlarmName → CloudWatch Logs ロググループ名の対応表。
Lambda 環境変数として JSON 文字列で保持する
(例: `'{"hdw-backend-processor-0001-errors": "/aws/lambda/HDW_Backend_Processor_0001"}'`)。
PRIN-001 に従い、DynamoDB / SSM Parameter Store では管理しない。

### OAM (Observability Access Manager)

CloudWatch Cross-Account Observability の制御プレーン (2022 年導入)。
Sink (monitoring account 側) と Link (source account 側) を作ることで
AssumeRole 無しで Logs Insights をクロスアカウント実行できる。

本 SPEC v3.0.0 時点では採用しない。理由:

- クライアント数 1 では運用メリットが小さい。
- 同一 SPEC 内で 2 種類のクロスアカウント機構を併存させる複雑度を避ける。
- 初期構築段階で機構を選び切る必要は無く、AssumeRole で要件を満たす実績を
  まず作る。

将来クライアントが 3+ に増えたタイミングで、OAM ベースの新 SPEC を起こして
AssumeRole 経路からの段階的移行を検討すること (参照: `docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Unified-Cross-Account.html`)。

## REQ-001: HDW_Notify Lambda は自社アカウント側にのみ配置する

HDW_Notify Lambda は自社アカウント (088898720463) でのみ動作させ、
クライアントアカウント (920373030024) には配置しない。
現状 HDW_Notify Lambda は bootstrap 状態で自社アカウントに既に存在するが、
CloudWatch Alarm 配線が未着手のため本番運用に入っていない。本仕様は
この Lambda をクロスアカウント受信構成で本番運用に投入することを定義する。

### AC-001-1

`aws lambda get-function --function-name HDW_Lambda_Notifier_0001 --profile hdw-test`
が success を返し、同コマンドを `--profile hanshin-t.kimura` で実行すると
`ResourceNotFoundException` となること (クライアントアカウントには
HDW_Notify Lambda を作らない)。

### AC-001-2

ECR image と Lambda execution role が 088898720463 配下にのみ存在し、
920373030024 配下に HDW_Notify 用リソース (Lambda / ECR repository /
実行ロール) を作成しないこと。クライアント側に作るのは本 SPEC で
定義する SNS Topic と HDWNotifyLogReader IAM Role のみ。

## REQ-002: SNS 経由でクロスアカウント CloudWatch Alarm を受信する

クライアントアカウントの CloudWatch Alarm 発火を
SNS topic (`arn:aws:sns:ap-northeast-1:920373030024:hdw-ml-alarm-topic`) 経由で
自社 Lambda に届ける。Alarm Action は Lambda 直接 invoke から SNS Publish へ
差し替える。SNS topic と Lambda は同一リージョン (ap-northeast-1) であること。

SNS Topic Policy の confused-deputy 対策は公式推奨 (CloudWatch
`Notify_Users_Alarm_Changes` / `SNS_Confused_Deputy`) に従い、`aws:SourceArn`
(Alarm ARN ワイルドカード) と `aws:SourceAccount` を併用する。
`aws:SourceArn` が most effective な対策。

### AC-002-1

SNS Topic Policy の Publish 文が次の条件を満たすこと:

- `Principal.Service` = `cloudwatch.amazonaws.com`
- `Action` = `SNS:Publish`
- `Condition.ArnLike.aws:SourceArn` = `"arn:aws:cloudwatch:ap-northeast-1:920373030024:alarm:*"`
- `Condition.StringEquals.aws:SourceAccount` = `"920373030024"`

Subscribe 文が `arn:aws:iam::088898720463:root` の `SNS:Subscribe` / `SNS:Receive` を
許可していること。

### AC-002-2

自社 Lambda の入口で `event["Records"][0]["Sns"]["Message"]` (JSON 文字列) を
`json.loads` でパースし、`AlarmName` / `AWSAccountId` / `Region` / `StateChangeTime` /
`NewStateReason` を既存の Embed フィールド (`alarm_name` / `timestamp` / `reason` 等)
にマップできること。SNS Message の正規スキーマは CloudWatch 公式
(`Notify_Users_Alarm_Changes` / Schema when a metric alarm changes state) に準拠。

## REQ-003: AssumeRole によりクライアントアカウントのログを取得する

自社 Lambda は STS AssumeRole で
`arn:aws:iam::920373030024:role/HDWNotifyLogReader` を引き受け、
一時クレデンシャルで CloudWatch Logs Insights を実行する。
AssumeRole 要求には ExternalId を必須とする。

ExternalId の取り扱いは AWS 公式
(IAM User Guide / `id_roles_common-scenarios_third-party`) に準拠する:

- 値は自社 (role-assuming 側) がクライアントごとに一意に生成する。
- 公式上 secret ではないが、攻撃面縮小のため SPEC / config YAML / git ログには
  生値を含めず、GHA Secret 経由で Lambda 環境変数 `EXTERNAL_ID` に投入する。
- 長さ 2-1224、英数字 + `+=,.@:/-` が許容。ランダム文字列を推奨。

### AC-003-1

`assume_role` の `RoleArn` / `ExternalId` / `RoleSessionName` が
Lambda 実行ログに記録され、tmp credentials で `boto3.client("logs")` を
構築できること。実行ログには `assumed_role_arn` フィールドが含まれること。

### AC-003-2

ExternalId はクライアントごとに別値で自社が生成・配布したものを使用する。
SPEC・PLAN・YAML 設定・git 履歴のいずれにも生値を含めない (GHA Secret 経由で
Lambda 環境変数 `EXTERNAL_ID` に投入)。
これは AWS 公式上の secret 要件ではなく、攻撃面縮小のための運用衛生である。

### AC-003-3

AssumeRole が `ClientError` / `BotoCoreError` で失敗した場合、PRIN-003 に従い
fallback embed (アラーム名と発火時刻を含む) が Discord channel に届くこと。

## REQ-004: AlarmName → ロググループの対応を env var で管理する

AlarmName からクエリ対象のロググループ名を解決するマッピングは
Lambda 環境変数 `LOG_GROUP_MAP` (JSON 文字列) で管理する。
PRIN-001 に従い、SSM Parameter Store / Secrets Manager / DynamoDB は
使用しない。クライアント数が増えた段階で再検討するが、現スコープでは env var で十分。

### AC-004-1

`LOG_GROUP_MAP` に存在しない `AlarmName` が届いた場合、
`logger.warning` に `"no log group mapped"` が記録され、
PRIN-003 に従う fallback embed が Discord に届くこと
(Bedrock 呼び出しはスキップ)。

### AC-004-2

Lambda コード上で SSM / Secrets Manager / DynamoDB / S3 等の
外部設定ストアへの API 呼び出しが行われないこと (`os.environ` のみ)。

## REQ-005: Logs Insights 時間窓を Alarm 評価窓に合わせて拡張する

CloudWatch Alarm の評価窓は最大 30 分のため、Logs Insights クエリの
時間窓は `StateChangeTime - 30 分` ～ `StateChangeTime + 5 分` とする。
StateChangeTime のタイムゾーン情報を保持してパースする
(`datetime.fromisoformat()` を使用、文字列 slice によるタイムゾーン破棄禁止)。

### AC-005-1

`start_query` の `startTime` / `endTime` が
StateChangeTime UTC 換算で -30 分 / +5 分の Unix 秒であること。

### AC-005-2

StateChangeTime が `"2026-05-20T03:12:45.000+0000"` のような
タイムゾーン付き ISO 8601 形式で届いた場合、UTC 換算後の値が
元の絶対時刻と一致すること (TZ 情報を捨てない)。

## REQ-006: Alarm 発火から Discord 着弾までの E2E フローを満たすこと

本 SPEC のデプロイ目標は、Reporter Lambda が、クライアント側 Alarm 発火を
契機に、クライアントアカウントの運用 Lambda の CloudWatch Logs 直近 30 分を
cross-account で取得し、LLM 生成まで通せることを最小要件として検証することにある。

REQ-001〜005 は構成要件 (配置・SNS Policy・AssumeRole・LOG_GROUP_MAP・時間窓) を
個別に規定するが、本 REQ は「それらが組み合わさって一気通貫で動くこと」を
単一の検証シナリオとして担保する。

実装は REQ-001〜005 の実装で完結しており、本 REQ は追加実装を要求しない。
AC はデプロイ完了後の手動 E2E 試験で判定する。

### AC-006-1

クライアントアカウント (920373030024 / ap-northeast-1) でテスト用 Alarm を
`aws cloudwatch set-alarm-state` により ALARM 状態に手動遷移させると、
自社 Reporter Lambda (`HDW_Lambda_Notifier_0001`) が起動し、Discord channel に
Embed が 1 件着弾すること。

### AC-006-2

着弾する Embed が LLM 生成結果を含むこと (PRIN-003 で規定される fallback
embed の固定文言ではない)。Embed の description / summary 相当フィールドが
Bedrock Converse の出力に由来する内容であること。

### AC-006-3

Reporter Lambda の実行ログ (`/aws/lambda/HDW_Lambda_Notifier_0001`) に以下が
含まれること:

- `assumed_role_arn` = `"arn:aws:sts::920373030024:assumed-role/HDWNotifyLogReader/..."` (REQ-003 由来)
- Logs Insights の `status` = `"Complete"` かつ `rows > 0` (= クライアント側運用 Lambda の実ログが取得できている)
- Bedrock Converse が `ClientError` / `AccessDeniedException` を出さず正常終了

## REQ-007: クロスアカウント Logs Insights が単独で実行できることを手動で確認できる

Reporter Lambda 経由の E2E (REQ-006) を回す前に、構成要素のうち最も詰まりやすい
「クライアントアカウントの IAM Role を自社オペレータ端末から AssumeRole し、
クライアント側ロググループに対して Logs Insights クエリが完走する」経路だけを
単独で手動検証できることを要件化する。

この単独検証が通れば、以後の REQ-006 失敗時の切り分けにおいて
「Logs Insights 経路は健全」「問題は SNS 配線か Lambda コードか Bedrock 側」と
即時に判定できる。Lambda の改修・再デプロイを介さずに IAM / Trust Policy /
ExternalId / LOG_GROUP_MAP の値を独立に検査できることが本 REQ の趣旨。

本 REQ は構築フェーズおよび障害切り分けフェーズの両方で参照されることを想定し、
手順は AWS CLI のみで完結すること (Lambda 実行や追加のスクリプト不要)。

### AC-007-1

自社オペレータ端末 (profile: `hdw-test`) から `aws sts assume-role` を Lambda
実行ロールの代わりに直接実行することはできないため、Lambda 実行ロールを引き受ける
一時クレデンシャル相当として、自社アカウント内の信頼経路から HDWNotifyLogReader を
引き受ける手順が PLAN に記載されていること。具体的には以下のいずれかが PLAN に
手順として書かれていれば AC-007-1 を満たす:

- **(a)** `hdw-notify-execution-role` を一時的に自社オペレータ IAM User の AssumeRole 対象に追加し、二段 AssumeRole (User → execution-role → HDWNotifyLogReader) で tmp 認証を得る手順。
- **(b)** 自社オペレータ IAM User / Role を一時的に HDWNotifyLogReader の Trust Policy に直接加える手順 (検証完了後に除去すること)。

AC は手順の存在を担保し、選択肢自体の妥当性は PLAN/TEST で具体化する。

### AC-007-2

手動検証で得た一時クレデンシャルを環境変数に注入した上で
`aws logs start-query` および `aws logs get-query-results` を実行し、
LOG_GROUP_MAP に登録済みのロググループ
(例: `/aws/lambda/HDW_Backend_Processor_0001`) に対して
`status` = `"Complete"` が返り、`results` が JSON 配列として取得できること。
時間窓は直近 1 時間程度の任意区間で良く、`rows > 0` は AC-006-3 で担保するため
本 AC では `rows = 0` でも形式的成功 (Complete) を条件とする。

### AC-007-3

AC-007-2 で使用した一時クレデンシャルの `GetCallerIdentity` が
`arn:aws:sts::920373030024:assumed-role/HDWNotifyLogReader/...` を返すこと
(= 自社アカウントからクライアントアカウントへの Role 引き受けが
実際に成立している)。同コマンドの `Account` が `"920373030024"` であること。
