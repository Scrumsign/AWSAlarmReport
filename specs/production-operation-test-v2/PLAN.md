---
id: production-operation-test-v2
version: 2.0.0
title: 本番運用試験 実施仕様 PLAN
created_at: 2026-05-20
type: plan
---

# 本番運用試験 実施仕様 PLAN

- **Spec**: production-operation-test-v2@2.0.0
- **Rev**: 1
- **Created at**: 2026-05-20

## TASK-001: 試験対象シナリオ・カタログの作成

- **対応要件**: REQ-001

docs/operations/test-scenarios.md を作成する。
12 シナリオ(TC-A-1, TC-B-3, TC-B-5, TC-B-9, TC-B-10, TC-B-14,
TC-S-1, TC-X-1, TC-X-2, TC-X-3, TC-X-4, TC-X-5)を 1 表に集約する。

表の列:

- TC-ID
- 誘発モード(A/B/C/D)
- 誘発操作の概要(どのスクリプト/テンプレ/コマンドを使うか)
- 期待 Discord Embed summary(出現すべきキーワード)
- 期待 root_cause_hypothesis(最有力仮説と副次仮説)
- 期待 suggested_actions(冒頭アクション)
- 対応する旧 v1 REQ(参考)

旧 SPEC v1.0.0 の REQ-001〜REQ-012 の description および
acceptance_criteria 本文をベースに、各シナリオの期待挙動を転写する。

## TASK-002: Slack 事前通知テンプレ作成

- **対応要件**: REQ-003

docs/operations/slack-templates/pre-notification.md を作成する。
Mode B/C シナリオの事前通知用テンプレ。

プレースホルダ: `<TC-ID>` / `<対象船>` / `<対象時刻>` / `<誘発操作概要>` /
`<期待される動作>` / `<影響範囲>` / `<復旧時刻見込み>`

構成: 件名 / 挨拶 / テスト ID / 実施内容 / 期待動作 / 影響範囲 /
想定復旧時刻 / 完了時の連絡フロー。

## TASK-003: Slack 抑止依頼テンプレ作成

- **対応要件**: REQ-003

docs/operations/slack-templates/suppression-request.md を作成する。
Mode D(TC-A-1)専用。クライアントへの通常 cron アップロード
1 回スキップ依頼。

プレースホルダ: `<対象船>` / `<対象時刻>` / `<返答形式サンプル>`

重要要件: テンプレ本文に「クライアントから完了応答を受領した後にのみ
次ステップ(CloudWatch Alarm 発火待機)へ進む」旨を明記する
(SPEC AC-003-2 対応)。

雛形ベース: 旧 specs/2026/05/19/production-operation-test/PLAN.md §2.5
(git commit d4fc59f に保管)。

## TASK-004: Slack 完了報告テンプレ作成

- **対応要件**: REQ-003

docs/operations/slack-templates/completion.md を作成する。
試験完了時の関係者向け報告用テンプレ。

プレースホルダ: `<TC-ID>` / `<実施時刻>` / `<観測結果概要>` /
`<review ファイルへの相対パス>`

構成: 件名 / 実施完了報告 / 観測結果サマリ / review ファイルリンク /
次アクション。

## TASK-005: review ファイルテンプレート作成

- **対応要件**: REQ-004, REQ-005

docs/reviews/_template.md を作成する。

frontmatter:

```yaml
tc_id: <TC-ID>
scenario: <シナリオ名>
mode: <A|B|C|D>
executor: <実施者>
started_at: <ISO8601>
completed_at: <ISO8601>
related_req: <旧 v1 REQ-XXX 参考>
```

本文セクション:

1. 実施手順実績(チェックリスト形式、test-scenarios.md の手順順)
2. Slack 通信記録(事前通知 / 抑止依頼 / 完了報告の送付時刻・
   スレッドリンク・要旨) — SPEC AC-003-1 対応
3. Discord Embed 原文記録(summary / root_cause_hypothesis /
   suggested_actions の 3 フィールドそれぞれを別ブロックで記録)
   — SPEC AC-004-2 対応
4. Discord スクリーンショット(tmp/reviews-raw/ への相対パス)
5. CloudWatch Logs マスキング済み抜粋
6. AC 判定(シナリオの各 AC に対し pass / fail / 判定不能 を
   記録) — SPEC AC-005-1 対応
7. 判定不能時の再試験条件と次回実施予定 — SPEC AC-005-2 対応
8. 特記事項

付録(テンプレ末尾) — SPEC AC-004-3 対応:

CloudWatch Logs 抽出 + マスキングのワンライナー:

```
aws logs start-query --log-group-name <LOG_GROUP> \
  --start-time <epoch> --end-time <epoch> \
  --query-string 'fields @timestamp, @message | sort @timestamp asc' \
  --profile hanshin-t.kimura --region ap-northeast-1
aws logs get-query-results --query-id <ID> ... > tmp/logs/<TC>.json
python scripts/mask_and_convert_fixture.py tmp/logs/<TC>.json \
  --output - >> docs/reviews/<TC-ID>-<date>.md
```

## TASK-006: IAM policy 一時剥奪/復元スクリプト作成

- **対応要件**: REQ-002

scripts/ops/iam_policy_snapshot_revoke_restore.sh を作成する。

サブコマンド:

- `snapshot` — aws iam get-role-policy で現在の policy を取得し
  tmp/snapshots/iam-`<role>`-`<policy>`-`<timestamp>`.json に保存
- `revoke` — 指定 action(例: s3:GetObject)を Deny ステートメントとして
  既存 policy に付加し aws iam put-role-policy で適用
- `restore` — 最新スナップショットを読み aws iam put-role-policy で
  元の policy を復元

共通引数:

- `--role <HDW_ML_ROLE>`
- `--policy <POLICY_NAME>`
- `--profile hanshin-t.kimura`
- `--region ap-northeast-1`

revoke 専用引数:

- `--action <iam-action>` 例: `s3:GetObject` / `s3:PutObject`

スクリプト冒頭コメントに、restore 失敗時の手動復元手順
(aws iam put-role-policy にスナップショット JSON を渡す具体的なコマンド例)を
記述する。— SPEC AC-002-2 対応

## TASK-007: Lambda config 一時変更/復元スクリプト作成

- **対応要件**: REQ-002

scripts/ops/lambda_config_snapshot_update_restore.sh を作成する。

サブコマンド:

- `snapshot` — aws lambda get-function-configuration で
  Timeout / MemorySize / EphemeralStorage.Size を取得し
  tmp/snapshots/lambda-`<function>`-`<timestamp>`.json に保存
- `update` — 引数で指定された設定値で
  aws lambda update-function-configuration を呼ぶ
- `restore` — 最新スナップショットの値で
  aws lambda update-function-configuration を呼ぶ

共通引数:

- `--function HDW_Backend_Processor_0001`
- `--profile hanshin-t.kimura`
- `--region ap-northeast-1`

update 専用引数(いずれか 1 つ以上):

- `--timeout <seconds>`
- `--memory-size <mb>`
- `--ephemeral-storage <mb>`

スクリプト冒頭コメントに restore 失敗時の手動復元手順を記述。

## TASK-008: S3 オブジェクト一時移動/復元スクリプト作成

- **対応要件**: REQ-002

scripts/ops/s3_object_move_restore.sh を作成する。

サブコマンド:

- `move <src-s3-uri> <dst-s3-uri>` — aws s3 mv で `<src>` を `<dst>` へ移動し、
  元/先 path のペアを tmp/snapshots/s3-mv-`<timestamp>`.json に追記記録
- `restore` — 最新スナップショットを読み、各ペアについて
  `aws s3 mv <dst> <src>` で逆方向移動して復元

共通引数:

- `--profile hanshin-t.kimura`
- `--region ap-northeast-1`

想定ユースケース:

- TC-B-10: `s3://<BUCKET>/parameterFiles/<ship>/<file>` を
  `s3://<BUCKET>/tmp-backup/TC-B-10/<file>` へ移動

スクリプト冒頭コメントに restore 失敗時の手動復元手順を記述。
