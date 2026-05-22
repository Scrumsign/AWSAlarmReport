---
id: production-operation-test-v2
version: 2.0.0
title: 本番運用試験 実施仕様
created_at: 2026-05-20
type: spec
---

# 本番運用試験 実施仕様

- **ID**: production-operation-test-v2
- **Version**: 2.0.0
- **Created at**: 2026-05-20
- **Authors**: Reck Developer
- **Constitution**: main@1.0.0
- **Dependencies**: test-zip-management@2.0.0

## 用語集

### 試験対象シナリオ

HDW_Notify の本番運用挙動を検証する 12 件の単位。
TC-A-1 / TC-B-3 / TC-B-5 / TC-B-9 / TC-B-10 / TC-B-14 /
TC-S-1 / TC-X-1 / TC-X-2 / TC-X-3 / TC-X-4 / TC-X-5 の 12 件。
各シナリオは誘発モード（CONSTITUTION 定義: A/B/C/D）に分類される。

### review ファイル

シナリオ実施後に作成する記録ファイル。
Discord Embed の原文・スクリーンショット・CloudWatch Logs 抽出結果・
各 AC への合否判定を含む Markdown ファイル。
格納先: docs/reviews/<TC-ID>-<date>.md

### test-scenarios.md

12 シナリオの誘発操作・期待 Discord Embed 内容を 1 表に集約した
運用カタログ。docs/operations/test-scenarios.md として保管する。
本 SPEC は実体ではなくカタログ構造に対する要件を持つ。

## REQ-001: 試験対象シナリオの網羅と分類

本番運用試験は 12 件の試験対象シナリオを網羅する。
各シナリオは誘発モード（A/B/C/D）のいずれかに分類され、
対応する HDW_Notify の期待挙動（Discord Embed の summary /
root_cause_hypothesis / suggested_actions の内容）が定義される。
実体は docs/operations/test-scenarios.md として保管される。

### AC-001-1

docs/operations/test-scenarios.md に
TC-A-1, TC-B-3, TC-B-5, TC-B-9, TC-B-10, TC-B-14,
TC-S-1, TC-X-1, TC-X-2, TC-X-3, TC-X-4, TC-X-5 の
12 件が列挙されている。

### AC-001-2

12 シナリオすべてに対し、誘発モード A/B/C/D のいずれかが
割り当てて記述されている。

### AC-001-3

12 シナリオすべてに対し、対応する HDW_Notify の期待挙動として
Discord Embed の summary / root_cause_hypothesis /
suggested_actions に現れるべきキーワードまたは内容が記述されている。

## REQ-002: Mode C 誘発操作の可逆性

Mode C による AWS リソース一時変更（IAM policy / Lambda 設定 /
S3 オブジェクト配置）は、観測完了後に試験開始前の状態へ
確実に復元される。スナップショット取得・変更・復元は
単一スクリプトで完結し、復元失敗時の代替手順が明示される。

### AC-002-1

scripts/ops/ 配下の各スクリプトを snapshot → 変更 → restore の
順に実行した結果、対象 AWS リソースの状態（IAM policy JSON /
Lambda Timeout・MemorySize・EphemeralStorage / S3 オブジェクト位置）が
snapshot 取得時点と一致する。

### AC-002-2

scripts/ops/ 配下の各スクリプトの usage またはコメントに、
restore が失敗した場合の手動復元手順または参照先が記述されている。

## REQ-003: クライアント協調手続き

本番運用に影響を与え得る操作（Mode B/C/D）の実施前に、
Slack による事前通知が行われる。Mode D シナリオ（TC-A-1）は
クライアントからの完了応答受領後にのみ次ステップへ進む。
通知文面は事前通知テンプレ・抑止依頼テンプレ・完了報告テンプレの
3 種を docs/operations/slack-templates/ に整備して標準化する。

### AC-003-1

Mode B/C/D の各シナリオ実施後の review ファイルに、
事前通知の Slack 送付時刻と内容(または Slack スレッドへのリンク)が
記録される欄が存在する。

### AC-003-2

docs/operations/slack-templates/suppression-request.md に、
「クライアントから完了応答を受領した後にのみ次ステップ
(CloudWatch Alarm 発火待機)へ進む」旨が明記されている。

## REQ-004: 観測物の到達と記録

各シナリオの実施結果は、Discord Embed のスクリーンショットと
CloudWatch Logs の抽出結果を証跡として、review ファイル
(docs/reviews/<TC-ID>-<date>.md)に保管される。
CloudWatch Logs はマスキング処理を経た上で記録される。

### AC-004-1

実施されたシナリオごとに docs/reviews/<TC-ID>-<date>.md が
1 件以上存在する。

### AC-004-2

review ファイルテンプレート docs/reviews/_template.md に、
Discord Embed の summary / root_cause_hypothesis /
suggested_actions を原文で記録する欄が存在する。

### AC-004-3

review ファイルテンプレート末尾の付録に、
CloudWatch Logs の抽出と scripts/mask_and_convert_fixture.py による
マスキングを行うワンライナーが記述されている。

## REQ-005: AC 判定の記録

各シナリオは、対応する HDW_Notify 期待挙動を AC として持ち、
review ファイルにその合否判定が記録される。
証跡不足等により判定不能の場合は再試験条件が記録される。

### AC-005-1

review ファイルテンプレート docs/reviews/_template.md に、
シナリオの各 AC に対する合否(pass / fail / 判定不能)を
記録する欄が存在する。

### AC-005-2

review ファイルテンプレートに、判定不能の場合の
再試験条件と次回実施予定を記録する欄が存在する。
