# REPORT-001: Amazon SES 初期セットアップ

- **実施日**: 2026-05-26
- **実施者**: t.kimura@scrumsign.com
- **対象 AWS アカウント**: 088898720463 (t.kimura-scrumsign)
- **対象リージョン**: ap-northeast-1

---

## 実施内容

### 1. SES ドメイン Identity 登録

`scrumsign.com` を SES の送信元 Identity として登録した。
DKIM 署名方式は Easy DKIM（RSA 2048 bit）を選択。

**ステータス**: `NOT_STARTED`（CNAME 追加済み・DNS 伝播待ち）

---

### 2. DKIM レコード発行

SES が以下の3件の CNAME レコードを発行した。
**DNS への追加が完了するまで、ドメイン検証は有効にならない。**

| ホスト名 | 種別 | 値 |
|---|---|---|
| `j3ldawn4rjhlsvzybb3273ut23c2cyx4._domainkey.scrumsign.com` | CNAME | `j3ldawn4rjhlsvzybb3273ut23c2cyx4.dkim.amazonses.com` |
| `vtf767m3u6x4b7iw2urbd6tbiw6zrbh7._domainkey.scrumsign.com` | CNAME | `vtf767m3u6x4b7iw2urbd6tbiw6zrbh7.dkim.amazonses.com` |
| `s57fxgo3wtwvpxlkr3ezfmybin3cwirf._domainkey.scrumsign.com` | CNAME | `s57fxgo3wtwvpxlkr3ezfmybin3cwirf.dkim.amazonses.com` |

---

### 3. Sandbox 解除リクエスト送信

以下の内容で AWS に Production Access を申請した。

| 項目 | 値 |
|---|---|
| メール種別 | TRANSACTIONAL |
| 用途説明 | CloudWatch アラーム発火時に社内担当者へ自動通知メールを送信。送信先は社内アドレスのみ、送信件数は少ない |
| Webサイト | https://scrumsign.com |
| 連絡先 | t.kimura@scrumsign.com |
| **レビューステータス** | **PENDING（審査中）** |

審査完了まで数時間〜1営業日。承認後は任意のアドレスへの送信が可能になる。

---

## 残作業

| # | 作業 | 担当 | 状態 |
|---|---|---|---|
| 1 | お名前.com のコントロールパネルで DKIM CNAME レコード3件を DNS に追加 | 手動 | ✅ 完了（2026-05-27）DNS 伝播待ち |
| 2 | Sandbox 解除の審査通過を待つ | AWS | PENDING |
| 3 | Lambda 実行ロールに `ses:SendEmail` / `ses:SendRawEmail` 権限を追加 | 手動 | ✅ 完了（2026-05-26） |
| 4 | 送信元アドレス確定後、`SES_FROM_ADDRESS` を deploy.yml の環境変数に追加 | コード | 未実施 |
