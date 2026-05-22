# FOLLOWUP — cross-account-architecture 移行後の確認事項

作成日: 2026-05-21
対象 SPEC: `specs/cross-account-architecture/` v3.3.0
作成者: 本セッションで TASK-001〜007 + TestAlarm 作成を実施した過程で発見した残課題の備忘録

## 背景

本セッションで cross-account-architecture (HDW_ML 監視を client account 経由で SNS → self Lambda → AssumeRole → Logs Insights → Bedrock → Discord に流す構成) の TASK-001〜007 を完了させた。

クリーンアップ段階で「dead permission」と判断していた以下が **実は active な旧運用** であることが判明し、誤削除を避けるため一旦 **現状維持 (案 b)** を選択。本ドキュメントは後日改めて判断するための材料を集めたもの。

## 主要な発見

1. self-account (088898720463) 側に **旧運用と思われる Alarm / SNS Topic / Log Group / Lambda permission が複数残存** している
2. 削除候補のリソースは互いに参照関係があり、削除順序を間違えると一時的な arn 不整合エラーを引き起こす可能性
3. orphan resource (subscribers 0 の SNS Topic 等) と active resource (使用中の Lambda permission) が混在している

---

## 確認すべきリソース一覧

### A. self-account CloudWatch Alarm: `TestAlarm`

```
AlarmArn:      arn:aws:cloudwatch:ap-northeast-1:088898720463:alarm:TestAlarm
StateValue:    INSUFFICIENT_DATA
AlarmActions:
  - arn:aws:lambda:ap-northeast-1:088898720463:function:HDW_Lambda_Notifier_0001
  - arn:aws:sns:ap-northeast-1:088898720463:scrumsign
Metric:        AWS/Lambda Invocations
Dimension:     FunctionName=MANUAL_TEST_PLACEHOLDER_DO_NOT_USE
LastUpdated:   2026-05-18T13:46
```

**確認すべきこと:**
- このアラームは誰が・いつ・何の目的で作ったか (`MANUAL_TEST_PLACEHOLDER_DO_NOT_USE` の命名から手動テスト用と推測)
- まだ使う予定があるか
- client 側に同名 `TestAlarm` (本セッションで作成) が存在するため運用上の名前衝突あり

**判断ガイド:**
- 使う予定が無い → 削除する (案 a)
- 用途不明だが残しておきたい → 改名を検討 (例: `BootstrapManualTestAlarm-DEPRECATED`)
- 確認待ち → そのまま放置 (現状)

**削除コマンド (案 a 採用時):**
```bash
aws cloudwatch delete-alarms --alarm-names TestAlarm \
  --profile hdw-test --region ap-northeast-1
```

---

### B. self-account CloudWatch Alarm: `HDW_Backend_Processor_0001-Errors`

```
AlarmArn:      arn:aws:cloudwatch:ap-northeast-1:088898720463:alarm:HDW_Backend_Processor_0001-Errors
StateValue:    OK (recentDatapoints が空 = メトリクスデータ届いていない)
AlarmActions:  arn:aws:lambda:ap-northeast-1:088898720463:function:HDW_Lambda_Notifier_0001
Metric:        AWS/Lambda Errors
Dimension:     FunctionName=HDW_Backend_Processor_0001
LastUpdated:   2026-05-18T13:46
```

**問題点:**
- Dimension が指す `HDW_Backend_Processor_0001` Lambda 関数は **self-account に存在しない** (client 920373030024 にある)
- self-account からはクライアントアカウントの Lambda メトリクスを直接見ることはできない (CloudWatch Cross-Account Observability 未設定)
- そのため datapoints が永久に空 → 永久に OK 状態 = 事実上 dead

**確認すべきこと:**
- これは migration 過程で取り残された残骸か? (推測: yes)
- new architecture (client alarm → SNS → self Lambda) が稼働すれば完全に重複機能になる
- client 側で本物の `hdw-backend-processor-0001-errors` Alarm を作ったら、self 側は廃止して問題ないはず

**判断ガイド:**
- new architecture が動作確認できる → 削除する (案 a 推奨)
- 念のため残す → ActionsEnabled=false で無効化のみ (案 c)

**削除コマンド (案 a 採用時):**
```bash
aws cloudwatch delete-alarms --alarm-names HDW_Backend_Processor_0001-Errors \
  --profile hdw-test --region ap-northeast-1
```

**無効化のみ (案 c 採用時):**
```bash
aws cloudwatch disable-alarm-actions --alarm-names HDW_Backend_Processor_0001-Errors \
  --profile hdw-test --region ap-northeast-1
```

---

### C. self-account SNS Topic: `scrumsign`

```
TopicArn:               arn:aws:sns:ap-northeast-1:088898720463:scrumsign
SubscriptionsConfirmed: 0
SubscriptionsPending:   0
Policy:                 default (__default_statement_ID のみ)
DisplayName:            (空)
```

**問題点:**
- subscribers が **0 件** — Publish しても誰も受け取らない (no-op)
- A の TestAlarm の AlarmAction として参照されているが、消費先が無いので無意味
- 過去の通知チャンネルの残骸の可能性

**確認すべきこと:**
- 過去にこの topic に publish していた仕組み (Lambda / Alarm) と、その受け取り先 (Email / SMS / 他 Lambda) があったか
- Slack 通知用に使われていた可能性 (`scrumsign` という organisation 名から)
- 今後使う予定があるか

**判断ガイド:**
- 使う予定無し & 過去の subscriber も存在しない → 削除 (案 a)
- 使うかも → 残す (案 b)

**削除コマンド (案 a 採用時):**
```bash
# A の TestAlarm の AlarmActions から scrumsign topic ARN を先に外す必要がある
# (TestAlarm 自体を削除するなら不要)
aws sns delete-topic --topic-arn arn:aws:sns:ap-northeast-1:088898720463:scrumsign \
  --profile hdw-test --region ap-northeast-1
```

---

### D. self-account CloudWatch Logs Log Group: `/aws/lambda/HDW_Backend_Processor_0001`

```
logGroupArn:        arn:aws:logs:ap-northeast-1:088898720463:log-group:/aws/lambda/HDW_Backend_Processor_0001
storedBytes:        144050  (144 KB のログデータあり)
metricFilterCount:  2       (Metric Filter 2 つ定義済)
creationTime:       1774580406145 (≒ 2026-03 頃)
```

**問題点:**
- self-account に **同名 Lambda 関数は存在しない** (本セッションで `aws lambda list-functions` で確認済)
- 過去に self-account で `HDW_Backend_Processor_0001` が動いていた残骸 (関数本体は client に移管 or 廃止) と推測
- 144 KB のログデータと 2 つの Metric Filter が残っている
- new architecture では client 側の同名 log group (`arn:aws:logs:ap-northeast-1:920373030024:log-group:/aws/lambda/HDW_Backend_Processor_0001`) を AssumeRole 経由でクエリする
- self 側 log group は不要

**確認すべきこと:**
- 144 KB のログを保管しておく必要があるか (過去のインシデント調査資料等)
- 2 つの Metric Filter が他のアラーム / ダッシュボードから参照されていないか
  ```bash
  aws logs describe-metric-filters \
    --log-group-name /aws/lambda/HDW_Backend_Processor_0001 \
    --profile hdw-test --region ap-northeast-1
  ```

**判断ガイド:**
- ログ保管不要 & Metric Filter 未使用 → 削除 (案 a)
- ログは残したいが Lambda 自体は廃止確定 → log group だけ残して関数依存リソースを削除
- 不明 → そのまま放置 (case 4)

**削除コマンド (案 a 採用時):**
```bash
# Metric Filter を先に削除 (もし他から参照されていたら CloudWatch Alarm が「データ無し」状態へ)
aws logs delete-metric-filter \
  --log-group-name /aws/lambda/HDW_Backend_Processor_0001 \
  --filter-name <metric_filter_name> \
  --profile hdw-test --region ap-northeast-1
aws logs delete-log-group \
  --log-group-name /aws/lambda/HDW_Backend_Processor_0001 \
  --profile hdw-test --region ap-northeast-1
```

---

### E. Lambda `HDW_Lambda_Notifier_0001` の Resource Policy: 旧 alarm 用 statement

```
Statement: AllowTestAlarmInvoke
  Principal:   lambda.alarms.cloudwatch.amazonaws.com
  Condition:   AWS:SourceArn = arn:aws:cloudwatch:ap-northeast-1:088898720463:alarm:TestAlarm

Statement: AllowBackendProcessorErrorsAlarmInvoke
  Principal:   lambda.alarms.cloudwatch.amazonaws.com
  Condition:   AWS:SourceArn = arn:aws:cloudwatch:ap-northeast-1:088898720463:alarm:HDW_Backend_Processor_0001-Errors
```

**位置づけ:**
- A (TestAlarm) と B (HDW_Backend_Processor_0001-Errors) の self-account Alarm が **存在し、AlarmActions が本 Lambda を直接 invoke する** ため、この 2 statement は現時点では active permission

**判断ガイド:**
- A / B の Alarm を削除する → この statement も同時に削除 (孤児になる)
- A / B の Alarm を残す → この statement も残す
- A / B の Alarm を無効化のみ (案 c) → statement は残しておいても無害

**削除コマンド (A / B Alarm 削除に合わせて):**
```bash
aws lambda remove-permission \
  --function-name HDW_Lambda_Notifier_0001 \
  --statement-id AllowTestAlarmInvoke \
  --profile hdw-test --region ap-northeast-1

aws lambda remove-permission \
  --function-name HDW_Lambda_Notifier_0001 \
  --statement-id AllowBackendProcessorErrorsAlarmInvoke \
  --profile hdw-test --region ap-northeast-1
```

---

### F. IAM Role `hdw-notify-execution-role` の inline policy `hdw-notify-permissions` の 2 Sid

```
Sid: InsightsStartQuery
  Action:   logs:StartQuery
  Resource: arn:aws:logs:ap-northeast-1:088898720463:log-group:/aws/lambda/HDW_Backend_Processor_0001:*

Sid: InsightsResults
  Action:   logs:GetQueryResults, logs:StopQuery
  Resource: *
```

**位置づけ:**
- new architecture では Logs Insights は **client 側 Role (`HDWNotifyLogReader`)** で実行される (TASK-002 / TASK-004 で配線済)
- self 側 Lambda は直接 logs:StartQuery を呼ばなくなった ([src/main.py](src/main.py) の AssumeRole 経路で確認済)
- D の log group `/aws/lambda/HDW_Backend_Processor_0001` を self 側で残すなら、`InsightsStartQuery` も残す意味がある (運用者が手動で投げる用)
- D を削除するなら `InsightsStartQuery` の Resource ARN は dangling reference になる (IAM 的にはエラーではないが、不要)

**判断ガイド:**
- D を削除する → F の `InsightsStartQuery` と `InsightsResults` も削除
- D を残す → F も残す (運用ツールとして使う可能性)

**削除手順 (D 削除に合わせて):**
```bash
# 現状の inline policy を取得
aws iam get-role-policy --role-name hdw-notify-execution-role \
  --policy-name hdw-notify-permissions \
  --profile hdw-test --region ap-northeast-1 > current-policy.json

# InsightsStartQuery / InsightsResults を除いた新 policy を作成
# (jq で Statement 配列から該当 Sid を除外):
jq '.PolicyDocument | .Statement |= map(select(.Sid != "InsightsStartQuery" and .Sid != "InsightsResults"))' \
  current-policy.json > new-policy.json

# 適用
aws iam put-role-policy --role-name hdw-notify-execution-role \
  --policy-name hdw-notify-permissions \
  --policy-document file://new-policy.json \
  --profile hdw-test --region ap-northeast-1
```

---

## 確認の進め方 (推奨)

new architecture が E2E で動作確認できた後 (REQ-006 充足後) に、以下の順で判断・削除を進めるのが安全:

1. **D (log group + metric filters)** から確認
   - Metric Filter が他から参照されていないことを `describe-metric-filters` で確認
   - 144 KB のログを保管する必要があるか担当者に確認
2. **C (scrumsign topic)** を確認
   - 過去の通知運用について担当者に確認 (Slack 連携の Lambda が無いか等)
3. **B (HDW_Backend_Processor_0001-Errors alarm)** を確認
   - new architecture が動いていれば確実に dead なので削除可
4. **A (TestAlarm)** を確認
   - 手動テスト用なので削除して構わない可能性が高い
5. **E と F** は上記 1〜4 の判断結果に追従させる
   - A / B 削除なら E の対応 statement も削除
   - D 削除なら F の対応 Sid も削除

逆順 (E や F から削除) はしないこと: active な alarm が permission を失い「invoke できない」状態になるため。

---

## 関連リソース (削除しない / new architecture で使用中)

以下は new architecture で使用するため絶対に削除しないこと:

| Resource | Account | 用途 |
|---|---|---|
| `arn:aws:iam::920373030024:role/HDWNotifyLogReader` | client | new アーキの assume 先 |
| `arn:aws:sns:ap-northeast-1:920373030024:hdw-ml-alarm-topic` | client | new アーキの Alarm 配信先 |
| `hdw-notify-execution-role` (Role 自体) | self | Lambda 実行 Role |
| `hdw-notify-permissions` の `OwnLogs` / `ECRImagePull` / `BedrockInvoke` Sid | self | Lambda 起動 / Bedrock 呼び出し |
| `hdw-notify-assume-cross-account` inline policy | self | new アーキの AssumeRole 権限 (本セッションで追加) |
| `HDW_Lambda_Notifier_0001` Lambda Resource Policy の `sns-hanshin-invoke` statement | self | new アーキの SNS invoke 許可 (本セッションで追加) |
| client 側 `TestAlarm` (本セッションで作成) | client | new アーキの配線スモークテスト用 |

---

## ローカルファイル (リポジトリ内) の状態

| ファイル | 状態 | 対応 |
|---|---|---|
| `deploy/.external-id-hanshin.txt` | gitignored | ExternalId 生値の控え。削除しないこと (Trust Policy 更新時の参照用) |
| `deploy/trust-policy-hdw-notify-log-reader.rendered.json` | gitignored | placeholder 置換版。今後の Trust Policy 編集時の参照用 |
| `deploy/policy-backup-hdw-notify-permissions-20260521.json` | gitignored | TASK-003 実施前の inline policy snapshot。ロールバック完了したら削除可 |
| `deploy/trust-policy-hdw-notify-log-reader.json` | untracked | placeholder 版。コミット候補 (source-of-truth として) |
| `deploy/permission-policy-hdw-notify-log-reader.json` | untracked | コミット候補 (source-of-truth として) |
| `deploy/policy-assume-cross-account.json` | untracked (本セッション作成) | コミット候補 (source-of-truth として) |
| `deploy/sns-topic-policy.json` | untracked | コミット候補 (誰かが先行作成。AWS 側に適用済) |

---

## このドキュメントを閉じるタイミング

- 上記 A〜F の判断と必要な削除が全て完了し、self-account に旧 architecture の残骸が無くなったら、本ドキュメント自体を削除して構わない
- それまでは migration 後の確認ガイドとして保持する
