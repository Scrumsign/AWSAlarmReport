---
id: production-operation-test-v2
version: 2.0.0
title: 本番運用試験 実施仕様 TEST
created_at: 2026-05-20
type: test
---

# 本番運用試験 実施仕様 TEST

- **Spec**: production-operation-test-v2@2.0.0
- **Plan rev**: 1
- **Rev**: 1
- **Created at**: 2026-05-20

## TC-001-1: シナリオ・カタログの 12 件網羅確認

- **対応 AC**: AC-001-1

docs/operations/test-scenarios.md を開き、表の TC-ID 列に
TC-A-1, TC-B-3, TC-B-5, TC-B-9, TC-B-10, TC-B-14,
TC-S-1, TC-X-1, TC-X-2, TC-X-3, TC-X-4, TC-X-5 の
12 件すべてが存在することを確認する。

## TC-001-2: シナリオ・カタログの誘発モード割当確認

- **対応 AC**: AC-001-2

docs/operations/test-scenarios.md の各シナリオ行に対し、
誘発モード列が A / B / C / D のいずれかで埋まっていることを確認する。
参考値: TC-A-1=D, TC-B-3=B, TC-B-5=B, TC-B-9=C, TC-B-10=C,
TC-B-14=C, TC-S-1=B, TC-X-1=C, TC-X-2=C, TC-X-3=C,
TC-X-4=A, TC-X-5=A。

## TC-001-3: シナリオ・カタログの期待挙動定義確認

- **対応 AC**: AC-001-3

docs/operations/test-scenarios.md の各シナリオ行に対し、
期待 Embed summary / 期待 root_cause_hypothesis /
期待 suggested_actions の 3 列がすべて空でないことを確認する。
各列に少なくとも 1 つのキーワードまたは内容文が記述されていること。

## TC-002-1: scripts/ops 各スクリプトの可逆性確認

- **対応 AC**: AC-002-1

次のいずれかの方法で、各スクリプトの snapshot → 変更 → restore の
往復で AWS リソース状態が元に戻ることを確認する:

(a) テストアカウント(profile: hdw-test)でリハーサル実施し、
snapshot 直前と restore 直後の状態を diff する。
(b) スクリプトのドライランモード(実装時に提供)で
restore 命令系列がスナップショット値と完全一致することを確認する。

対象スクリプト:

- scripts/ops/iam_policy_snapshot_revoke_restore.sh
- scripts/ops/lambda_config_snapshot_update_restore.sh
- scripts/ops/s3_object_move_restore.sh

## TC-002-2: scripts/ops 各スクリプトの restore 失敗手順記述確認

- **対応 AC**: AC-002-2

scripts/ops/ 配下の 3 スクリプトすべてに対し、ファイル冒頭コメント
または usage 出力に「restore が失敗した場合の手動復元手順」が
記述されていることを目視確認する。
手動復元に使う具体的な aws CLI コマンド例が含まれていること。

## TC-003-1: review テンプレの Slack 記録欄確認

- **対応 AC**: AC-003-1

docs/reviews/_template.md を開き、本文セクションに
「Slack 通信記録」または同等の欄が存在し、事前通知 /
抑止依頼 / 完了報告の送付時刻と Slack スレッドリンクを
記録する場所があることを確認する。

## TC-003-2: suppression-request テンプレの応答待ち明記確認

- **対応 AC**: AC-003-2

docs/operations/slack-templates/suppression-request.md を開き、
テンプレ本文中に「クライアントから完了応答を受領した後にのみ
次ステップへ進む」旨が明記されていることを確認する。
「完了応答」「次ステップ」「待機」相当のキーワードを含むこと。

## TC-004-1: review ファイル存在確認

- **対応 AC**: AC-004-1

本番運用試験を実施した各シナリオに対し、
docs/reviews/`<TC-ID>`-`<date>`.md が 1 件以上存在することを
ls または find で確認する。
例: docs/reviews/TC-A-1-2026-05-21.md

## TC-004-2: review テンプレの Embed 原文記録欄確認

- **対応 AC**: AC-004-2

docs/reviews/_template.md を開き、Discord Embed の
summary / root_cause_hypothesis / suggested_actions の
3 フィールドを原文で記録する欄が、それぞれ独立したブロックとして
存在することを確認する。

## TC-004-3: review テンプレ末尾ログ抽出ワンライナー確認

- **対応 AC**: AC-004-3

docs/reviews/_template.md の末尾付録に、
aws logs start-query → get-query-results →
scripts/mask_and_convert_fixture.py の流れを示す
ワンライナーまたはコマンド列が記述されていることを確認する。

## TC-005-1: review テンプレの AC 合否記録欄確認

- **対応 AC**: AC-005-1

docs/reviews/_template.md の本文セクションに、
シナリオの各 AC に対して pass / fail / 判定不能 を
記録する欄が存在することを確認する。
各 AC の合否を独立に記録できる構造であること。

## TC-005-2: review テンプレの再試験条件記録欄確認

- **対応 AC**: AC-005-2

docs/reviews/_template.md の本文セクションに、
判定不能の場合の再試験条件と次回実施予定を記録する欄が
存在することを確認する。
