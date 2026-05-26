# RESEARCH-002: DKIM・DNS・Amazon SES Easy DKIM の仕組み

- **作成日**: 2026-05-26
- **参照**: AWS 公式ドキュメント / EasyDMARC / RFC 6376

---

## 1. DKIM とは

**DomainKeys Identified Mail**。メール送信時に公開鍵暗号方式で署名を付与し、受信側がその署名を検証することで「正規のサーバーから送られたメールであること」を証明する仕組み。RFC 6376 で規定されている。

```
送信側（SES）                              受信側（さくら / Gmail 等）
  秘密鍵でメール本文に署名
  DKIM-Signature: v=1; a=rsa-sha256; ...
    ↓ 送信
                                            DNS から公開鍵を取得
                                            署名を検証
                                            合格 → 正規メールと判定
```

署名と検証は両端で完結し、DNS には公開鍵の在り処を示す情報だけを置く。

---

## 2. DNS レコードの構造

DKIM の公開鍵は DNS の **TXT レコード**として公開される。TXT レコードの中身は以下の形式：

```
v=DKIM1;       ← DKIM バージョン
k=rsa;         ← 鍵の種類（RSA）
p=MIGfMA0...   ← 公開鍵本体（Base64 エンコード済み RSA 公開鍵）
```

**CNAME レコード**はこの TXT レコードへのポインター（別名参照）であり、実体ではない。

---

## 3. Amazon SES Easy DKIM の構造

Easy DKIM では、公開鍵の実体（TXT レコード）を AWS 側（`dkim.amazonses.com`）が管理する。こちらの DNS には、その TXT レコードへの CNAME を置くだけでよい。

```
自分の DNS（さくら）                    AWS 管理の DNS
  <token>._domainkey.scrumsign.com
    CNAME ──────────────────────────→  <token>.dkim.amazonses.com
                                          TXT "v=DKIM1; k=rsa; p=<公開鍵>"
                                                               ↑
                                                       AWS が自動で差し替える
```

### 本プロジェクトの登録値（scrumsign.com）

| ホスト名（さくら DNS に追加） | 種別 | 参照先（AWS 管理） |
|---|---|---|
| `j3ldawn4rjhlsvzybb3273ut23c2cyx4._domainkey.scrumsign.com` | CNAME | `j3ldawn4rjhlsvzybb3273ut23c2cyx4.dkim.amazonses.com` |
| `vtf767m3u6x4b7iw2urbd6tbiw6zrbh7._domainkey.scrumsign.com` | CNAME | `vtf767m3u6x4b7iw2urbd6tbiw6zrbh7.dkim.amazonses.com` |
| `s57fxgo3wtwvpxlkr3ezfmybin3cwirf._domainkey.scrumsign.com` | CNAME | `s57fxgo3wtwvpxlkr3ezfmybin3cwirf.dkim.amazonses.com` |

3件の CNAME はポインターであり、公開情報として DNS に公開することが前提。機密情報ではない。秘密鍵は AWS 側のみが保持し、外部には一切公開されない。

---

## 4. なぜ CNAME が 3 件必要か

**キーローテーションのため**。AWS Easy DKIM は3つの鍵ペアを常時管理し、定期的に署名に使う鍵を切り替える。

```
鍵1 (j3ldawn4...)  ←── 現在署名に使用中
鍵2 (vtf767m3...)  ←── 待機中（次のローテーション候補）
鍵3 (s57fxgo3...)  ←── 待機中
```

ローテーション時に行われることは「CNAME が指す TXT の公開鍵（値）を AWS が差し替える」だけであり、さくら側の DNS 設定は変更不要。3件すべてが DNS に登録されていないと、ローテーション直後に受信側が公開鍵を参照できなくなり DKIM 検証が失敗する。

---

## 5. キーローテーションの頻度

| 鍵長 | 推奨ローテーション間隔 |
|---|---|
| 1024 bit | 3ヶ月ごと |
| 2048 bit | 6ヶ月ごと（本プロジェクト） |

本プロジェクトは RSA 2048 bit を選択済みのため、AWS が約6ヶ月ごとに自動でローテーションする。こちら側の作業は一切不要。

---

## 6. なぜさくら側で CNAME を設定しなければならないか

受信側のメールサーバーは DKIM 署名を検証するために、メールヘッダーのセレクタとドメインをもとに DNS を問い合わせる。

```
DKIM-Signature: v=1; s=j3ldawn4...; d=scrumsign.com; ...
                         ↑ セレクタ      ↑ ドメイン

→ 受信サーバーが引く DNS アドレス:
  j3ldawn4rjhlsvzybb3273ut23c2cyx4._domainkey.scrumsign.com
```

この `scrumsign.com` 配下のレコードは、`scrumsign.com` の **NS レコード（ネームサーバーレコード）** が指すサーバーだけが応答できる。NS レコードは「このドメインの DNS は誰が答えるか」を示すものであり、実際に確認すると：

```
$ nslookup -type=NS scrumsign.com

scrumsign.com   nameserver = 01.dnsv.jp
scrumsign.com   nameserver = 02.dnsv.jp
scrumsign.com   nameserver = 03.dnsv.jp
scrumsign.com   nameserver = 04.dnsv.jp
```

`dnsv.jp` はさくらインターネットのネームサーバーであり、`scrumsign.com` の DNS 権威はさくらにある。AWS はさくらの DNS に直接レコードを追加できないため、**ドメイン管理者がさくらのコントロールパネルで手動追加する**必要がある。

### CNAME を設定しない場合との比較

| | CNAME あり | CNAME なし |
|---|---|---|
| DNS 問い合わせ結果 | CNAME → 公開鍵（TXT）が見つかる | NXDOMAIN（レコードなし） |
| DKIM 検証 | 成功 | 失敗 |
| SES のドメイン検証状態 | `SUCCESS` | `NOT_STARTED` のまま |
| メールの到達性 | 正規メールとして届く | 迷惑メール扱いまたは拒否 |

CNAME の追加は、受信側に公開鍵の在り処を教えるための唯一の手段であり、省略するとメール送信自体が成立しない。

---

## 7. ドメイン単位検証の効果

`scrumsign.com` をドメイン単位で検証したことにより：

- `@scrumsign.com` の**任意のアドレス**（`alerts@`、`noreply@` 等）が送信元として使用可能
- サブドメイン（`mail.scrumsign.com` 等）にも DKIM 設定が継承される
- 送信元アドレスを変更しても SES 側の再設定は不要（`SES_FROM_ADDRESS` 環境変数を変えるだけ）

---

## 8. Easy DKIM vs BYODKIM

| | Easy DKIM（本プロジェクト） | BYODKIM |
|---|---|---|
| 鍵の生成 | AWS が自動生成 | 自前で生成 |
| 鍵の管理 | AWS が自動管理 | 自前で管理 |
| ローテーション | AWS が自動実施 | 手動 |
| DNS に登録するもの | CNAME 3件 | TXT 1件 |
| 推奨 | 一般用途 | 厳格な鍵管理が必要な場合 |

---

## 参考資料

- [Authenticating Email with DKIM in Amazon SES](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim.html)
- [Easy DKIM in Amazon SES](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim-easy.html)
- [Managing Easy DKIM and BYODKIM](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim-easy-managing.html)
- [What is DKIM Key Rotation? - EasyDMARC](https://easydmarc.com/blog/what-is-dkim-key-rotation/)
