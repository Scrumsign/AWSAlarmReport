---
id: cross-account-architecture
version: 3.3.0
title: クロスアカウント Alarm 受信・ログ取得アーキテクチャ TEST
created_at: 2026-05-20
type: test
---

# クロスアカウント Alarm 受信・ログ取得アーキテクチャ TEST

- **Spec**: cross-account-architecture@3.3.0
- **Plan rev**: 5
- **Rev**: 5
- **Created at**: 2026-05-20

## TC-001-1: 自社アカウントにのみ HDW_Notify Lambda が存在することを確認する

- **対応 AC**: AC-001-1

TASK-001〜007 完了後 (AWS リソース新規作成と Lambda コードデプロイの完了後)
に確認する。

確認コマンド:

```
aws lambda get-function --function-name HDW_Lambda_Notifier_0001 \
  --profile hdw-test --region ap-northeast-1
aws lambda get-function --function-name HDW_Lambda_Notifier_0001 \
  --profile hanshin-t.kimura --region ap-northeast-1
```

合格条件:

- 1 つ目のコマンドが exit 0 で関数 ARN を返す
  (自社アカウントに HDW_Notify Lambda が存在する)。
- 2 つ目のコマンドが `ResourceNotFoundException` で exit 非ゼロ
  (クライアントアカウントには HDW_Notify Lambda を**作らない**という
  REQ-001 の不変条件が守られている。本 SPEC は初期構築仕様であり、
  クライアント側に Lambda が存在したことは過去にも無い)。

## TC-001-2: ECR image / 実行ロールが自社アカウント配下のみであることを確認する

- **対応 AC**: AC-001-2

確認手順:

```
aws ecr describe-repositories \
  --repository-names hdw-notify \
  --profile hdw-test --region ap-northeast-1
aws iam get-role --role-name hdw-notify-execution-role \
  --profile hdw-test --region ap-northeast-1

aws ecr describe-repositories --profile hanshin-t.kimura --region ap-northeast-1 \
  | jq '.repositories[].repositoryName' | grep -i notify || echo "no notify repo (OK)"
aws iam list-roles --profile hanshin-t.kimura \
  | jq -r '.Roles[].RoleName' | grep -i hdw-notify || echo "no hdw-notify role (OK)"
```

合格条件:

- 自社アカウント側に `hdw-notify` repo と `hdw-notify-execution-role` が存在する。
- クライアントアカウント側に `hdw-notify` 関連の ECR repo と IAM role が
  存在しないこと (`HDWNotifyLogReader` は AssumeRole 対象として残るが、
  これは「クライアント側に提供される Role」であり HDW_Notify 専用ロールではない)。

## TC-002-1: SNS Topic Policy が CloudWatch Publish と自社 Subscribe を許可していること

- **対応 AC**: AC-002-1

確認コマンド:

```
aws sns get-topic-attributes \
  --topic-arn arn:aws:sns:ap-northeast-1:920373030024:hdw-ml-alarm-topic \
  --profile hanshin-t.kimura --region ap-northeast-1 \
  | jq -r '.Attributes.Policy' | jq .
```

合格条件 (Statement 配列に以下が含まれる):

- Sid `"AllowCloudWatchPublish"`:
  - `Principal.Service` = `"cloudwatch.amazonaws.com"`
  - `Action` = `"SNS:Publish"`
  - `Condition.ArnLike."aws:SourceArn"` = `"arn:aws:cloudwatch:ap-northeast-1:920373030024:alarm:*"`
  - `Condition.StringEquals."aws:SourceAccount"` = `"920373030024"`

- Sid `"AllowCrossAccountSubscribe"`:
  - `Principal.AWS` = `"arn:aws:iam::088898720463:root"`
  - `Action` = `["SNS:Subscribe", "SNS:Receive"]`

## TC-002-2: SNS Message から AlarmName 等のフィールドが正しくパースされること

- **対応 AC**: AC-002-2

手動 `set-alarm-state` でアラームを発火させ、Discord Embed の各 field を確認する。

発火コマンド (クライアントアカウント側):

```
aws cloudwatch set-alarm-state \
  --alarm-name hdw-backend-processor-0001-errors \
  --state-value ALARM \
  --state-reason "TC-002-2 test invocation" \
  --profile hanshin-t.kimura --region ap-northeast-1
```

合格条件:

- 1〜2 分以内に Discord channel に Embed が届く。
- Embed title に `hdw-backend-processor-0001-errors` が含まれる。
- Embed の「Alarm reason」または summary に
  `"TC-002-2 test invocation"` 相当の reason が表示される。
- CloudWatch Logs (自社アカウント) で Lambda の実行ログを確認し、
  `alarm_name` / `timestamp` / `region` がそれぞれ
  正しい値で記録されていること。

## TC-003-1: AssumeRole が成功し、assumed_role_arn が実行ログに記録されること

- **対応 AC**: AC-003-1

TC-002-2 と同じ手動発火を行い、自社アカウントの Lambda 実行ログを確認する。

ログ確認:

```
aws logs filter-log-events \
  --log-group-name /aws/lambda/HDW_Lambda_Notifier_0001 \
  --filter-pattern '"assumed cross-account role"' \
  --start-time $(node -e "console.log(Date.now()-300000)") \
  --profile hdw-test --region ap-northeast-1
```

合格条件:

- 該当行が 1 件以上見つかる。
- 行の structured fields に `assumed_role_arn` が含まれ、
  値が `arn:aws:sts::920373030024:assumed-role/HDWNotifyLogReader/...`
  であること。
- Discord Embed に Logs Insights 結果由来のフィールド
  (件数 / 原因仮説 など) が表示されていること
  (= AssumeRole 後の logs API 呼び出しが成功している)。

## TC-003-3: ExternalId 生値が SPEC / config YAML / git 履歴に含まれていないこと

- **対応 AC**: AC-003-2

AWS 公式上 ExternalId は secret ではないが、攻撃面縮小のため運用衛生として
生値が repository にコミットされていないことを検査する。

静的検査 (PowerShell):

```
# GHA Secret 経由のものだけが許容。生値が deploy/ や specs/ に
# 含まれていないか確認。EXTERNAL_ID_HANSHIN という Secret 名 (placeholder) は許容。
Select-String -Path specs\**\*, deploy\**\*, src\**\* `
  -Pattern '(?i)external[_-]?id\s*[:=]\s*["'']?[A-Za-z0-9_+=,.@:/\-]{16,}'
```

git 履歴検査:

```
git log -p --all -S 'EXTERNAL_ID' -- deploy/ specs/ src/ | `
  Select-String 'EXTERNAL_ID\s*[:=]\s*[A-Za-z0-9]{16,}'
```

合格条件:

- 静的検査の結果 0 件 (Secret 名 / env var キー名のみで生値の埋め込みなし)
- git 履歴検査の結果 0 件

## TC-003-2: AssumeRole 失敗時に fallback embed が届くこと

- **対応 AC**: AC-003-3

意図的に `EXTERNAL_ID` を誤値に変更してから発火させる。

手順:

1. 現在の `EXTERNAL_ID` を退避:

   ```
   aws lambda get-function-configuration \
     --function-name HDW_Lambda_Notifier_0001 \
     --query 'Environment.Variables.EXTERNAL_ID' --output text \
     --profile hdw-test --region ap-northeast-1 > tmp/external_id_backup.txt
   ```

2. `EXTERNAL_ID` を誤値に上書き:

   ```
   aws lambda update-function-configuration \
     --function-name HDW_Lambda_Notifier_0001 \
     --environment "Variables={EXTERNAL_ID=BROKEN_VALUE,<その他は維持>}" \
     --profile hdw-test --region ap-northeast-1
   ```

   (実運用上は他キーを毀損しないよう `get-function-configuration` の出力を
   ベースに jq で 1 キーだけ書き換える)

3. アラームを `set-alarm-state` で発火。
4. Discord に fallback embed (黄/赤の minimal embed) が届くこと。
5. `EXTERNAL_ID` を退避値で復元 (`tmp/external_id_backup.txt` を反映)。

合格条件:

- Discord channel に fallback embed が届く (Bedrock 分析は含まない最小通知)。
- Embed の説明に `"AssumeRole 失敗"` 相当の文字列が含まれる。
- 自社 Lambda の実行ログに ERROR level で `"assume_role failed"` が記録される。
- 復元後の再発火で TC-003-1 が再度 Pass する。

## TC-004-1: LOG_GROUP_MAP に未登録の AlarmName で fallback embed が届くこと

- **対応 AC**: AC-004-1

`LOG_GROUP_MAP` に存在しない `AlarmName` を持つ test alarm を一時作成し発火させる。

手順:

1. test alarm を 1 つ作成 (例: `hdw-notify-unmapped-test`):

   ```
   aws cloudwatch put-metric-alarm \
     --alarm-name hdw-notify-unmapped-test \
     --metric-name Errors --namespace AWS/Lambda \
     --statistic Sum --period 60 --evaluation-periods 1 \
     --threshold 0 --comparison-operator GreaterThanThreshold \
     --dimensions Name=FunctionName,Value=NonExistentFn \
     --alarm-actions arn:aws:sns:ap-northeast-1:920373030024:hdw-ml-alarm-topic \
     --profile hanshin-t.kimura --region ap-northeast-1
   ```

2. `set-alarm-state` で ALARM に遷移。
3. Discord に fallback embed が届くことを確認。
4. 自社 Lambda 実行ログに `"no log group mapped"` warning が記録されることを確認。
5. テスト後は `delete-alarms` で削除。

合格条件:

- Discord に fallback embed が届く。
- Embed の説明に `"LOG_GROUP_MAP に該当アラームの登録がありません"` 相当が含まれる。
- 自社 Lambda が Bedrock を呼び出していないこと
  (Bedrock 呼び出し回数 Metric で当該時間窓に増分がないこと)。

## TC-004-2: Lambda コードが SSM / Secrets Manager / DynamoDB を呼び出していないこと

- **対応 AC**: AC-004-2

静的検査と実行ログの両方で確認する。

静的検査:

```
Select-String -Path src/**/* -Pattern 'boto3.client\("(ssm|secretsmanager|dynamodb)"\)|client\(.s3.\)' -SimpleMatch:$false
```

(HDW_Notify では S3 も使用しない。logs / sts / bedrock-runtime のみ許容)

実行ログ検査 (CloudTrail 経由):

直近 1 時間の Lambda 実行から発生した CloudTrail event を確認し、
`eventSource` が `ssm` / `secretsmanager` / `dynamodb` の event が無いこと:

```
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=ssm.amazonaws.com \
  --start-time <1h ago> --profile hdw-test --region ap-northeast-1
```

合格条件:

- 静的検査の結果が 0 件。
- CloudTrail の lookup 結果に該当 event が 0 件。

## TC-005-1: Logs Insights クエリの startTime / endTime が ±30/+5 分であること

- **対応 AC**: AC-005-1

TC-002-2 と同じ手動発火後、自社 Lambda の実行ログから `start_query` パラメータを確認する。

ログ確認:

```
aws logs filter-log-events \
  --log-group-name /aws/lambda/HDW_Lambda_Notifier_0001 \
  --filter-pattern '"insights query started"' \
  --start-time $(node -e "console.log(Date.now()-300000)") \
  --profile hdw-test --region ap-northeast-1
```

合格条件:

- `start_query` 呼び出し前の `logger.info` に `startTime` / `endTime` が記録されている
  (実装で `extra={"start_time": start_ts, "end_time": end_ts}` を追加する場合)。
- または、Lambda の structured log を Logs Insights で
  `stats avg(end_time - start_time)` として集計し、
  値が 2100 (=35 分) に近いこと。

## TC-005-2: StateChangeTime のタイムゾーン情報が破棄されていないこと

- **対応 AC**: AC-005-2

fixture を用いた単体ロジック検証 (Lambda invocation は不要)。

手順:

- `tests/` または `scripts/` に小さなチェックスクリプトを置き、
  `"2026-05-20T03:12:45.000+0000"` を入力として
  `datetime.fromisoformat(...).timestamp()` の結果を計算する。
- 同じ絶対時刻を表す `"2026-05-20T12:12:45.000+0900"` を入力にしても
  `timestamp()` の戻り値が一致することを確認する。

```python
import datetime as dt
a = dt.datetime.fromisoformat("2026-05-20T03:12:45.000+00:00").timestamp()
b = dt.datetime.fromisoformat("2026-05-20T12:12:45.000+09:00").timestamp()
assert a == b, (a, b)
```

合格条件:

- 上記 `assert` が通る。
- `src/main.py` 中に timestamp 文字列の slice (`[:19]`) や、TZ を捨てる
  手作りパースが残っていないこと
  (grep で確認、既存の `_format_jst` の `.replace("Z", "+00:00")` は許容)。

## TC-006-1: テスト Alarm 手動発火で Discord に Embed が 1 件着弾すること

- **対応 AC**: AC-006-1

TASK-001〜009 完了後に実施する。

発火コマンド (クライアントアカウント側 PowerShell):

```powershell
$env:PYTHONUTF8 = '1'
aws cloudwatch set-alarm-state `
  --alarm-name hdw-backend-processor-0001-errors `
  --state-value ALARM `
  --state-reason "TC-006-1 E2E verification" `
  --profile hanshin-t.kimura --region ap-northeast-1
```

合格条件:

- 1〜2 分以内に Discord channel に Embed が 1 件着弾する。
- Embed が fallback (最小) embed ではなく、5W1H 構造を持つ通常 embed であること (= REQ-006 の正常系を通過している)。
- 同時間帯に他の手動発火が無い前提で、Embed は 1 件のみ (= Lambda 非同期 invocation のリトライが発生せず成功終了している)。

## TC-006-2: 着弾 Embed の生成内容が fallback 固定文言ではないこと

- **対応 AC**: AC-006-2

TC-006-1 で受信した Embed を目視確認する。

合格条件:

- Embed の description / summary 相当フィールドが、PRIN-003 で規定される fallback embed の固定文言 (例: "クライアントログ取得用 AssumeRole 失敗"、"LOG_GROUP_MAP に該当アラームの登録がありません" 等) と一致しないこと。
- 内容が Bedrock Converse の生成出力 (Lambda のログから抽出された 5W1H に基づく自然言語要約) であること。
- 生成内容に AlarmName / StateChangeTime / NewStateReason のいずれかに言及する記述が含まれること (= prompt 経路と Bedrock 呼び出しが正しく繋がっている証跡)。

## TC-006-3: Lambda 実行ログにクロスアカウントログ取得と Bedrock 正常完了が記録されること

- **対応 AC**: AC-006-3

TC-006-1 と同時刻の Lambda 実行ログを確認する。

ログ確認コマンド (自社アカウント側 PowerShell):

```powershell
$env:PYTHONUTF8 = '1'
aws logs tail /aws/lambda/HDW_Lambda_Notifier_0001 `
  --profile hdw-test --region ap-northeast-1 `
  --since 5m --format short
```

合格条件 (同一 invocation の中で以下すべて):

- `"assumed cross-account role"` 相当の INFO ログがあり、structured field `assumed_role_arn` に `"arn:aws:sts::920373030024:assumed-role/HDWNotifyLogReader/..."` が記録されている。
- `"insights query done"` 相当の INFO ログに `status = "Complete"` かつ `rows > 0` が記録されている (= クライアント側運用 Lambda の実ログが取れている)。
- Bedrock Converse 呼び出しが `ClientError` / `BotoCoreError` / `AccessDeniedException` を出していないこと (= 例外 traceback がログに含まれない)。
- `main()` が return value で skipped / fallback ではない通常成功 (例: `{"ok": True, "alarm": ...}`) を返している。

## TC-007-1: クロスアカウント Logs Insights が単独で実行できることを手動で検証する

- **対応 AC**: AC-007-1 / AC-007-2 / AC-007-3

TASK-010 の手順を実機で実行し、Lambda を介さずに自社端末から
HDWNotifyLogReader を引き受けて Logs Insights クエリが完走することを確認する。
実施タイミング: TASK-001〜007 完了後 (= Trust Policy / IAM Role / SNS Topic 等が
構築済み)、TASK-009 の E2E 検証より前。E2E 失敗時の切り分けでも本 TC を再実行する。

### 前提

- HDWNotifyLogReader が作成済み (TASK-002)。
- `EXTERNAL_ID` 値が GHA Secret `EXTERNAL_ID_HANSHIN` に登録済み、かつ検証実施者がその値を取り出せる権限を持つ。
- `LOG_GROUP_MAP` の value 側ロググループ (例: `/aws/lambda/HDW_Backend_Processor_0001`) がクライアントアカウントに実在する。

### 手順 (PowerShell)

```powershell
# 1. Trust Policy を一時拡張 (TASK-010 ステップ 1 を実施)
#    自社オペレータ ARN を Principal.AWS に追加した JSON を適用済みとする。

# 2. ExternalId をセッション変数化
$EXTERNAL_ID = Read-Host "ExternalId" -AsSecureString | `
  ConvertFrom-SecureString -AsPlainText

# 3. AssumeRole
$resp = aws sts assume-role `
  --role-arn "arn:aws:iam::920373030024:role/HDWNotifyLogReader" `
  --role-session-name "hdw-notify-manual-verify" `
  --external-id $EXTERNAL_ID `
  --duration-seconds 900 `
  --profile hdw-test --region ap-northeast-1 | ConvertFrom-Json
$env:AWS_ACCESS_KEY_ID     = $resp.Credentials.AccessKeyId
$env:AWS_SECRET_ACCESS_KEY = $resp.Credentials.SecretAccessKey
$env:AWS_SESSION_TOKEN     = $resp.Credentials.SessionToken
$env:AWS_REGION            = "ap-northeast-1"

# 4. GetCallerIdentity で引き受けを確認
$ident = aws sts get-caller-identity | ConvertFrom-Json
$ident.Account   # 期待: "920373030024"
$ident.Arn       # 期待: "arn:aws:sts::920373030024:assumed-role/HDWNotifyLogReader/hdw-notify-manual-verify"

# 5. Logs Insights クエリ
$end   = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$start = $end - 3600
$qid = aws logs start-query `
  --log-group-name "/aws/lambda/HDW_Backend_Processor_0001" `
  --start-time $start --end-time $end `
  --query-string "fields @timestamp, @message | sort @timestamp desc | limit 20" `
  --query 'queryId' --output text

do {
  Start-Sleep -Seconds 2
  $r = aws logs get-query-results --query-id $qid | ConvertFrom-Json
} while ($r.status -in @("Running","Scheduled"))

$r.status   # 期待: "Complete"
($r.results | Measure-Object).Count   # 0 でも可 (E2E で rows>0 を別途担保)

# 6. 片付け (TASK-010 ステップ 6 を実施)
Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN
# Trust Policy を元に戻す。
```

### 合格条件 (すべて満たすこと)

- 手順 4 の `GetCallerIdentity` が `Account = "920373030024"` かつ `Arn` が `"arn:aws:sts::920373030024:assumed-role/HDWNotifyLogReader/..."` を返す (**AC-007-3**)。
- 手順 5 の `$r.status` が `"Complete"` を返す (**AC-007-2**)。`$r.results` が JSON 配列として取得できる (空配列でも可)。
- 手順 6 の片付け後に下記コマンドを実行すると `AccessDenied` になること (= 検証用に追加した Trust が確実に剥がせている):

  ```powershell
  aws sts assume-role --role-arn "arn:aws:iam::920373030024:role/HDWNotifyLogReader" `
    --role-session-name cleanup-check --external-id $EXTERNAL_ID `
    --profile hdw-test
  ```

- 検証中・終了後ともに、`ExternalId` 生値が PowerShell コマンド履歴 (PSReadLine) / シェルスクリプト / git diff のいずれにも残っていないこと (手順 2 を `Read-Host -AsSecureString` 経由で実施した結果として)。確認コマンド例:

  ```powershell
  Get-Content (Get-PSReadLineOption).HistorySavePath -Tail 200 | `
    Select-String -Pattern $EXTERNAL_ID
  # ↑ 該当 0 件であること。
  ```
