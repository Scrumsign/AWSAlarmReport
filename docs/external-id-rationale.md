# 提案: cross-account AssumeRole から ExternalId を除去する

**Status: Proposal (未承認)**
**Author: t.kimura**
**Date: 2026-05-21**

本ドキュメントは HDW_Notify の cross-account AssumeRole に AWS STS の ExternalId を**今後採用しない**ことを提案する。判断のための材料を提示するもので、現時点では決定事項ではない。

レビュー後に合意が得られた場合、`specs/cross-account-architecture/SPEC.yml` を v3.4.0 に version up し、PLAN / TEST / 実装 / 既存環境を追従させる。

---

## 提案サマリ

| 項目 | 現状 (SPEC v3.3.0) | 提案 (SPEC v3.4.0 案) |
|---|---|---|
| hanshin 側 Trust Policy の `sts:ExternalId` 条件 | あり | 削除 |
| Lambda 環境変数 `EXTERNAL_ID` | あり | 削除 |
| GitHub Secret `EXTERNAL_ID_HANSHIN` | 登録予定 | 登録しない (既存があれば削除) |
| `assume_role()` の `ExternalId=` 引数 | あり | 削除 |
| `hdw-notify-execution-role` への Principal 完全限定 | あり | **維持** |

---

## なぜ提案するか — 一行で

> ExternalId は role-assuming 側で発生する confused deputy 攻撃を防ぐマーカーだが、HDW_Notify はその攻撃チェーンが構造的に成立しないアーキテクチャになっており、ExternalId が独立して守る層が空集合だから。

---

## ExternalId が本来守る攻撃チェーン

AWS 公式が ExternalId を要求するのは **「role を assume する側 (= ベンダ)」が confused deputy になる** 攻撃である。典型シナリオは以下:

1. ベンダ V が SaaS ポータルを公開し、複数顧客から RoleArn を入力させる
2. 顧客 A が正規に signup し、自分の RoleArn を V に登録 (Trust Policy で V を信頼)
3. 攻撃者 B も V の顧客として signup
4. B が **被害者 A の RoleArn** を V のポータル経由で submit
5. V のバックエンドが B のリクエストとして A の RoleArn で AssumeRole を実行
6. ExternalId 無しの場合: assume 成功 → V が A のリソースに B の指示で侵入
7. ExternalId 有りの場合: V は B の ExternalId を渡してしまい、A の Trust Policy の StringEquals 条件に一致せず失敗

**この攻撃が成立する前提**:
- ベンダの assume 対象 RoleArn が **外部入力 (顧客の submit) から決まる**
- ベンダが顧客ごとに異なる ExternalId を **正しく** 使い分けている

参考事例 (Praetorian 2020 監査): 調査対象ベンダの 37% で ExternalId 検証が不適切に実装され、上記攻撃が実際に成立した。

---

## HDW_Notify でこの攻撃が成立するか

成立しないと考えている。理由は以下の 4 点。

### (1) RoleArn は env var にハードコード

`src/main.py` の `assume_role()` に渡される RoleArn は Lambda 環境変数 `CROSS_ACCOUNT_ROLE_ARN` 由来で、GHA 経由でデプロイ時に注入される。

```
CROSS_ACCOUNT_ROLE_ARN = arn:aws:iam::920373030024:role/HDWNotifyLogReader
```

外部入力から RoleArn を組み立てる経路が存在しない。攻撃者が「別顧客の RoleArn」を持ち込む方法がない。

### (2) ポータル・顧客登録 UI が存在しない

HDW_Notify は SaaS ではなく自社運用ツール。顧客が動的に signup して RoleArn を登録する経路がない。

### (3) SNS Topic Policy で publisher を限定

`deploy/` に定義された SNS Topic Policy:

```json
"Condition": {
  "ArnLike":      { "aws:SourceArn":     "arn:aws:cloudwatch:ap-northeast-1:920373030024:alarm:*" },
  "StringEquals": { "aws:SourceAccount": "920373030024" }
}
```

そもそも Lambda を invoke できる発火源が hanshin アカウント内の CloudWatch Alarm に限定されている。

### (4) 顧客は 1 社 (Hanshin) のみ

multi-tenant にすらなっていないので、「顧客 A の RoleArn と顧客 B の RoleArn を取り違える」状況自体が物理的に発生しない。

### 反論の余地

もし上記 (1)〜(4) のいずれかが将来崩れる場合 — 特に「将来 multi-tenant 化する SPEC でこの 4 点の少なくとも 1 つが変わる」場合 — 本提案の前提は崩れる。下節 (多顧客化したら必要になるか) でこの条件を明示する。

---

## 真の security boundary はどこにあるか

HDW_Notify の cross-account AssumeRole を実際に守っているのは ExternalId ではなく、以下の 2 層であると整理した:

### Layer 1: hanshin 側 Trust Policy の Principal 限定

```json
{
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::088898720463:role/hdw-notify-execution-role"
  },
  "Action": "sts:AssumeRole"
}
```

`:root` ではなく **具体的な role ARN** を Principal に書いている。これにより 088898720463 アカウント内の任意 principal による引き受けではなく、`hdw-notify-execution-role` を引き受けた principal のみが assume できる。

### Layer 2: hdw-notify-execution-role の利用者限定

自社アカウント側で、`hdw-notify-execution-role` を引き受けられる principal を Lambda service (`lambda.amazonaws.com`) に限定している。つまりこの role を assume できるのは「HDW_Notify Lambda が起動された時の Lambda runtime」のみ。

### この 2 層と ExternalId の関係

| Layer | 性質 | 強度 |
|---|---|---|
| Trust Policy 編集権限 | 能動的・所有者の意思表示 | Security boundary そのもの |
| Trust Policy の Principal 指定 | 能動的・宛先限定 | Boundary を狭める強い制御 |
| Trust Policy の ExternalId 条件 | 受動的・呼出側に追加文字列を要求 | Confused deputy 用マーカー |
| Permission Policy | 能動的・許可範囲限定 | Blast radius 制御 |

ExternalId だけが「受動的マーカー」枠であり、他とは性質が異なる。Trust Policy の Principal 限定が機能している場合、ExternalId が独自に保護する層は **空集合** と考えられる。

---

## hanshin 側で操作可能な場合の防御は？

**ExternalId のスコープ外と整理。** hanshin 内部のオペレータが Trust Policy を編集できる場合:

- ExternalId 条件ごと削除可能
- Principal を任意の AWS アカウントに書き換え可能

これらに対する防御は ExternalId ではなく、hanshin 側 IAM 管理 (最小権限・MFA・CloudTrail 監視) で行うべき領域。HDW_Notify 側で何を設定しても防げない。

逆に hanshin オペレータが Trust Policy を「読む」だけの場合、ExternalId 値は Trust Policy 上に平文で見える (AWS 公式は ExternalId を "not a secret" と明記)。ExternalId は機密として機能しない。

---

## ExternalId の "secret 性" についての公式記述

AWS IAM User Guide (`id_roles_common-scenarios_third-party`):

> AWS does not treat the external ID as a secret.
> The external ID for a role can be seen by anyone with permission to view the role.

つまり ExternalId は:
- 認証要素ではない (推測困難であっても、知っていることが認可の根拠にならない)
- アクセス制御の主体ではない
- あくまで **role-assuming 側が複数顧客を取り違えないためのマーカー**

「ExternalId を knowing するか否か」を security の要にする設計は AWS 公式の意図に反する。

---

## 多顧客化したら ExternalId が必要になるか

**条件付きで不要のまま維持できる、と考えている。** 必要条件は 1 つだけ:

> **Routing key は SNS が付与するフィールド (`Sns.TopicArn` または `EventSubscriptionArn`) から取る。`Sns.Message` の中身からは取らない。**

### 危険な設計 (これをやると ExternalId が必要になる)

```python
msg = json.loads(event["Records"][0]["Sns"]["Message"])
role_arn = ACCOUNT_TO_ROLE_MAP[msg["AWSAccountId"]]  # ← 危険
```

`Sns.Message` の本体は publisher (CloudWatch / `sns:Publish` 権限を持つ任意の principal) が作る文字列。悪意ある顧客 B が自分の topic に「`AWSAccountId: "920373030024"`」と書いて publish すると、HDW_Notify は顧客 A の role を assume してしまう (= confused deputy 復活)。

### 安全な設計

```python
topic_arn = event["Records"][0]["Sns"]["TopicArn"]
role_arn  = TOPIC_TO_ROLE_MAP[topic_arn]
```

`Sns.TopicArn` は SNS サービスがメッセージ配送時に付与する metadata で、publisher が改竄不可能。これを routing key にすれば、辞書管理だけで confused deputy が起きない。

### 多顧客化を進める場合の SPEC 上の宿題

将来 multi-tenant 化する SPEC を起こす時に、以下を不変条件として明記することを併せて提案する:

- AssumeRole 対象 RoleArn は env var の辞書から SNS-controlled fields を key として lookup
- `Sns.Message` の本体は LLM prompt 用データとしてのみ扱い、AWS 認可判定の入力にしない
- 顧客ごとの Trust Policy は Principal を引き続き `hdw-notify-execution-role` に完全限定

これが守られる限り、ExternalId は永続的に不要と判断できる。

---

## 削除した場合のコスト削減

提案を受け入れた場合に除去される運用コスト:

- GitHub Secret `EXTERNAL_ID_HANSHIN` (test / production 両環境)
- Lambda 環境変数 `EXTERNAL_ID`
- hanshin 側 `HDWNotifyLogReader` Trust Policy の `StringEquals.sts:ExternalId` 条件
- `assume_role()` 呼出の `ExternalId=` 引数
- ExternalId 値のクライアント通達運用 (チャット / email 経由の手作業)
- 単独手動検証 (TC-007-1) における ExternalId Read-Host / 履歴非残存チェック
- SPEC / PLAN / TEST 内の ExternalId 関連記述

CONSTITUTION 相当の原則 PRIN-001 (Lambda 設定は env vars に集約、管理軸は最小化) の精神とも整合する。

---

## 反対意見として想定されるもの

レビュー時に出得る反論を予め列挙する。

### (a) 「業界慣行として ExternalId を入れておくべき」

→ 業界慣行は SaaS ベンダ前提で形成されている。HDW_Notify は SaaS ではなく自社運用ツール。慣行を文脈なく適用するのは ExternalId の本来目的 (= ベンダ側 confused deputy 防止) を理解していない実装になり、本提案の論旨と矛盾する。

### (b) 「将来 multi-tenant 化したときに既に仕組みがあると楽」

→ multi-tenant 化時には ExternalId の per-customer 管理 (辞書 + Trust Policy 配布) が新たに必要になる。**現時点で使われていない値を入れておく** ことが将来コストを下げる保証はなく、むしろ「すでにあるから流用する」判断が安全な routing 設計 (上節) を後退させるリスクがある。本提案では、多顧客化 SPEC を起こす際に「不変条件」を明示することで、ExternalId 無しでも安全を保つ方が筋が良いと考える。

### (c) 「Lambda credentials が盗まれたときの defense in depth」

→ ExternalId 値は Lambda env var に置かれるので、credentials を窃取できる攻撃者は env var も読める。defense in depth として機能しない。

### (d) 「hanshin の IAM チームが既に承認した Trust Policy を変更するのは手間」

→ これは正当な手続きコストの議論。以下の判断を提案する:
- hanshin 側 Trust Policy が **まだ投入前** なら、本提案を即時適用して投入する Trust Policy から ExternalId 条件を抜く
- **既に投入済** なら、次回 Trust Policy を編集する機会 (例: クライアント追加・権限見直し) に併せて除去する。除去のためだけに hanshin の IAM チームを動かさない

---

## 判断を求めたいポイント

1. 上記 (a)〜(d) の反論に対する整理に同意できるか
2. hanshin 側 Trust Policy は既に投入済か (片付け方針の分岐に必要)
3. 提案を採択する場合、SPEC を v3.4.0 として version up することに同意するか

---

## 参考

- [Access to AWS accounts owned by third parties — AWS IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_common-scenarios_third-party.html)
- [The confused deputy problem — AWS IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html)
- [How to Use External ID When Granting Access to Your AWS Resources — AWS Security Blog](https://aws.amazon.com/blogs/security/how-to-use-external-id-when-granting-access-to-your-aws-resources/)
- [AWS IAM Assume Role Vulnerabilities Found in Many Top Vendors — Praetorian](https://www.praetorian.com/blog/aws-iam-assume-role-vulnerabilities/)
