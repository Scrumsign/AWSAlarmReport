# SPEC: 本番運用テスト

## 概要

本リポジトリ (HDW_Notify) の Lambda は、監視対象 Lambda (HDW_Backend_Processor_0001 / HDW_ML 由来) の CloudWatch Logs を Bedrock に渡し、現状起きている状況を Discord に通知する。

本仕様は **HDW_ML への入力や周辺環境がどのような状態のときに、HDW_ML がどのようなログ・エラーを出し、Bedrock がどのような状況を推論できているべきか** を列挙する。各ケースは本番環境で発生 (能動誘発または自然発生) させ、Discord 通知の内容を人手目視で照合する。

各ケースは次の 4 要素で記述する:

- **入力条件**: HDW_ML への入力 / 周辺リソースの状態 (ground truth)
- **HDW_ML が出力する観測**: CloudWatch Logs に現れるログ・例外 (Bedrock が読む手がかり)
- **推論されるべき状況**: 入力条件を Bedrock がログから言い当てた結果として期待する記述
- **目視確認**: Discord 通知の内容が「推論されるべき状況」と一致しているかを判定する観点

## 前提 (本 SPEC が対象とする運用構成)

- 監視対象 Lambda (HDW_ML) と通知 Lambda (HDW_Notify) はいずれも **OCI image でデプロイ** されており、Lambda runtime / 依存ライブラリの実体はイメージに同梱されている
- 設定値は **Lambda 環境変数 (非機密ストア / 機密ストア) に直接配置** されている。SSM / Parameter Store / Secrets Manager 等の外部設定ストアは **利用しない**
  - 非機密値 (バケット名 / モデル ID / 時間窓設定 等) は config YAML → デプロイ時に Lambda 環境変数へ投入
  - 機密値 (Discord webhook URL 等) は GitHub Actions Secret → デプロイ時に Lambda 環境変数へ投入
- 参照リソース (shipInfo.json / fileFormat CSV / parameterFiles / 入出力 ZIP 等) は **S3 に配置** されており、Lambda は実行時に S3 API 経由で取得する
- LLM が「環境変数」関連の仮説を出す際は、SSM 等の外部ストアではなく **Lambda 環境変数 (機密/非機密ストア) と OCI image** を前提とすること

## 共通受理条件

すべての通知が以下を満たすこと:

- 出力が定義済み JSON スキーマ (`summary` / `severity` / `confidence` / `root_cause_hypothesis` / `suggested_actions`) を逸脱していない
- 監視対象に存在しない AWS サービス・架空の関数名・機密情報・差別表現・金銭請求への誘導を含まない
- 時刻表記が ISO 8601 / powertools 形式と矛盾していない
- HDW_ML のコード起因 (TC-B 系) と環境起因 (TC-X 系) の区別が `root_cause_hypothesis` から読み取れること
- 環境変数や設定値に関する仮説は **本リポジトリの構成 (Lambda 環境変数の機密/非機密ストア + OCI image)** を前提としており、SSM / Parameter Store / Secrets Manager 等を架空に言及しないこと

---

## ケース集

### TC-A-1: 上流アップロードが発生していない

**入力条件**: 直近時間窓 (Alarm 発火時刻の前 30 分) に S3 `inputFiles/` への ZIP アップロードが 1 件も発生していない。

**HDW_ML が出力する観測**: CloudWatch Logs に `lambda_handler invoked` も `lambda complete` も観測されない (HDW_ML 自体が起動していない)。

**推論されるべき状況**: S3 への ZIP アップロード自体がなく HDW_ML が起動していない。副次的に「cold start で powertools logger 初期化前に落ちた」「ログ配信遅延で実際は処理済み」も候補に残る。

**目視確認**: `summary` が未起動を示し、`root_cause_hypothesis` で「上流アップロード未着」が最有力仮説として提示され、副次仮説も並ぶこと。`suggested_actions` 冒頭が S3 着信確認や上流処理状態の確認を促していること。

---

### TC-B-1: ZIP に必須ファイル db02/General CSV が含まれない

**入力条件**: アップロードされた ZIP の `db02/<year>/<ship>/定時|任意/<timestamp>/` 配下に `General.csv` が存在しない (削除・改名・配置階層違い)。

**HDW_ML が出力する観測**: validation の `NG file` reason に該当ファイルパスのフォルダ構成違反やファイル名違反が含まれ、`ok_count > 0` だが db02 General が ok リストに入らないか、`ok_count = 0`。最終的に `lambda_handler failed` + `ValueError: general_data is None`。

**推論されるべき状況**: 入力 ZIP に db02/General CSV が含まれておらず、ML 推論前段で general_data 取得に失敗している。

**目視確認**: `root_cause_hypothesis` が「db02/General の欠落」または同等の状況を言い当てている。`suggested_actions` に該当 ZIP の内部構造確認 / 上流 ZIP 生成手順の点検が含まれている。

---

### TC-B-2: ZIP ファイル名が `<ship>-<timestamp>.zip` 規約を満たさない

**入力条件**: アップロードされた ZIP のファイル名に `-` が含まれない、または timestamp 部が 14 桁数字でない (例: `sakura20260427.zip`, `sakura-202604.zip`)。

**HDW_ML が出力する観測**: `input file identified` ログの直後、`name_part` を `rsplit('-', 1)` する箇所で `ValueError` (unpack 系)。`lambda_handler failed` で記録される。

**推論されるべき状況**: ZIP ファイル名が規約 `<shipname>-<timestamp>.zip` を満たさず、船名・時刻の分離処理で失敗している。

**目視確認**: `root_cause_hypothesis` がファイル名フォーマット違反を言い当てている。`suggested_actions` に該当 ZIP のファイル名確認 / 上流送信側の命名規則準拠点検が含まれている。

---

### TC-B-3: ZIP 内のフォルダ構成が全件想定外

**入力条件**: ZIP 展開後のディレクトリ階層が `db01|db02|db05em|db06em / <year> / <ship> / 定時|任意 / ...` 規約と一致しない (例: 古い階層、ルートフォルダ多重、サブフォルダ追加)。

**HDW_ML が出力する観測**: `validation complete` で `ok_count=0`, `ng_count>0`。各 `NG file` reason が「フォルダ構成が正しくないです」「ファイル名が正しくないです」「フォルダの深さが誤っています」系で占められる。最終的に `ValueError: general_data is None`。

**推論されるべき状況**: ZIP 内ディレクトリ構造が規約と乖離しており、全ファイルが validation で弾かれた。船側送信フォーマット変更 / アーカイブ手順崩れが疑われる。

**目視確認**: `root_cause_hypothesis` が ZIP 内ディレクトリ構造の規約違反を言い当てている。`suggested_actions` に ZIP 内構造の検査と上流アーカイブ処理の確認が含まれている。

---

### TC-B-4: アップロード元の船名が shipInfo.json に未登録

**入力条件**: ZIP ファイル名から抽出される shipname が S3 `shipInfo/shipInfo.json` の `shipName` リストに存在しない (新造船 / 改名 / 表記揺れ)。

**HDW_ML が出力する観測**: `validation complete` の各 `NG file` の reason に「船名がJSONファイルに登録されていません」が並ぶ。最終的に `ValueError: general_data is None`。

**推論されるべき状況**: shipInfo.json に該当船の登録がないため全ファイルが validation で弾かれている。

**目視確認**: `root_cause_hypothesis` が shipInfo.json への船名登録漏れを言い当てている。`suggested_actions` に shipInfo.json の確認 / 上流側船名表記の点検が含まれている。

---

### TC-B-5: CSV 内のデータが float に変換できない値を含む

**入力条件**: CSV の数値カラムに数値以外の文字 (FAULT, 異常, 破損文字, 空欄を超えた壊れ方) が混入している。

**HDW_ML が出力する観測**: db02 系では `csv parse failed phase=csv_read` warning と `NG file` reason「ファイルフォーマットが異常です。float型でないものが含まれています」。General では `NG file` reason「データ異常 : ◯◯のデータが異常です」(info レベル付随)。該当ファイルが ok リストから外れる。

**推論されるべき状況**: センサ出力 CSV の数値カラムに float 変換不能な値が混入しており、該当ファイルが NG リストへ。

**目視確認**: `root_cause_hypothesis` がセンサ出力データの値破損・型異常を言い当てている。`suggested_actions` に該当 CSV の中身抽出 / 船側センサ装置の出力状態確認が含まれている。

---

### TC-B-6: CSV の行数・列数が shipInfo の size 定義と一致しない

**入力条件**: CSV の shape (行数, 列数) が shipInfo.json で定義された該当センサの `size` と異なる (船側のセンサ追加・取得周期変更・ファームウェア更新)。

**HDW_ML が出力する観測**: `NG file` reason に「ファイルサイズが正しくないです。:(actual_shape):(expected_shape)」。該当ファイルが ok リストから外れる。

**推論されるべき状況**: shipInfo.json の size 定義と実 CSV 構造が乖離している。

**目視確認**: `root_cause_hypothesis` が shipInfo の size 定義と実 CSV の乖離を言い当てている。`suggested_actions` に shipInfo.json と実 CSV の突合 / 船側センサ仕様変更履歴の確認が含まれている。

---

### TC-B-7: fileFormat 定義 CSV が S3 から消えている

**入力条件**: S3 `shipInfo/fileFormat/<sensor>Format.csv` のいずれかが不在 (削除 / 配置先変更)。

**HDW_ML が出力する観測**: `NG file` reason に「センサ◯◯のフォーマット定義ファイルが存在しません」。該当センサのファイルが ok リストから外れる。

**推論されるべき状況**: 該当センサの fileFormat 定義ファイルが S3 上から欠落している。

**目視確認**: `root_cause_hypothesis` が fileFormat 定義ファイル欠落を言い当てている。`suggested_actions` に S3 `shipInfo/fileFormat/` の確認 / 最近の S3 操作履歴の点検が含まれている。

---

### TC-B-8: shipInfo.json 自体の読み込みに失敗

**入力条件**: S3 `shipInfo/shipInfo.json` が不在、または JSON が破損、または Lambda execution role に取得権限がない。

**HDW_ML が出力する観測**: `shipinfo load failed phase=shipinfo_load` の例外 (FileNotFoundError / JSONDecodeError / ClientError) → `lambda_handler failed`。

**推論されるべき状況**: shipInfo.json の S3 不在 / JSON 破損 / 権限欠落により、HDW_ML が起動初期で停止している。

**目視確認**: `root_cause_hypothesis` が shipInfo.json の取得失敗を言い当てている。`suggested_actions` に S3 オブジェクトの存在・権限確認 / CloudTrail での操作履歴確認が含まれている。

---

### TC-B-9: shipInfo / config / parameter フォルダの一括ダウンロード失敗

**入力条件**: S3 `shipInfo/`, `config/`, `parameterFiles/<ship>/` のいずれかへの `aws s3 cp --recursive` が AccessDenied / NoSuchBucket / ネットワーク経路問題で失敗する。

**HDW_ML が出力する観測**: `s3 download failed phase=s3_download` の例外 + `stderr` フィールドに aws CLI のエラー出力 → `lambda_handler failed`。

**推論されるべき状況**: 参照リソースの S3 一括取得が権限 / 経路 / 不在のいずれかで失敗している。

**目視確認**: `root_cause_hypothesis` が stderr の AWS エラーコードを踏まえた仮説 (権限欠落 / S3 prefix 不在 / VPC 経路) を提示している。`suggested_actions` に該当 S3 prefix と Lambda execution role policy の確認が含まれている。

---

### TC-B-10: 学習済みパラメータファイルが parameterFiles に存在しない

**入力条件**: S3 `parameterFiles/<ship>/` 配下に必須の `<db>_General.npz` / `glasso_precision.parquet` / `datapipeline.json` などのいずれかが不在 (新造船で学習未実施 / 配信失敗 / オブジェクト消失)。

**HDW_ML が出力する観測**: `Processing Bayesian Estimation for file: <ship>_<db>` または glasso 段階のログまで通過した後の `FileNotFoundError` → `lambda_handler failed`。

**推論されるべき状況**: ML 推論に必要な学習済みパラメータが S3 上に揃っていない。

**目視確認**: `root_cause_hypothesis` が学習済みパラメータの不在を言い当てている。`suggested_actions` に S3 `parameterFiles/<ship>/` の確認 / 学習バッチの最終実行時刻確認が含まれている。

---

### TC-B-11: SDS 計算で センサ数 × cylinder 数 が実 CSV 列数と一致しない

**入力条件**: shipInfo.json の `db02.<sensor>.size[1]` と `shipSpec.cylinder` の積が実 CSV の列数と一致しない (shipInfo の sensor 設定または cylinder 設定が古い)。

**HDW_ML が出力する観測**: `Bayesian Estimation finished` 通過後の SDS 計算中に `ValueError: データ数◯◯とあるべき1つのセンサのデータ数△△、センサ数▢▢が一致しません` → `lambda_handler failed`。

**推論されるべき状況**: shipInfo.json の sensor / cylinder 設定誤り、または fileFormat の更新漏れ。

**目視確認**: `root_cause_hypothesis` が shipInfo / fileFormat と実 CSV の列数整合性問題を言い当てている。`suggested_actions` に shipInfo の該当センサ size / cylinder 値と fileFormat CSV の突合が含まれている。

---

### TC-B-12: General CSV に主機負荷率カラムが含まれない

**入力条件**: General CSV の列構成または fileFormat 定義 (`GeneralFormat.csv`) に `2_主機負荷率` のマッピングが含まれず、`general_data['2_主機負荷率']` の参照が失敗する。

**HDW_ML が出力する観測**: `store complete` を通過した後の glasso / SDS 計算段階で KeyError 系の例外、または `2_主機負荷率` を参照する箇所での失敗。

**推論されるべき状況**: General の fileFormat 定義崩れ、または上流 CSV からの主機負荷率カラム消失。

**目視確認**: `root_cause_hypothesis` が主機負荷率カラム欠落 / fileFormat 定義崩れを言い当てている。`suggested_actions` に fileFormat CSV (`shipInfo/fileFormat/GeneralFormat.csv`) と実 General CSV の突合が含まれている。

---

### TC-B-13: ZIP 内に PIA データのみ含まれない (停泊中等の正常変則ケース)

**入力条件**: ZIP に db02/General CSV は含まれるが、db02/PIA CSV が含まれない (運用上の停泊中など)。

**HDW_ML が出力する観測**: `pia_data is None` の info ログ。エラーには至らず処理は継続 (SDS 計算は skip され、bayesian / glasso のみ実行)。最終的に `lambda complete status=success`。

**推論されるべき状況**: PIA データの不在は停泊中などで起こりうる **想定内** の状態であり、エラーではない。

**目視確認**: そもそも alarm が発火しない (status=success のため)。発火した場合は別の異常があるはずなので、その別異常を Bedrock が正しく推論しているか別ケースとして扱う。

---

### TC-B-14: S3 出力 (savedFiles / forFrontEnd) への書き込み失敗

**入力条件**: Lambda execution role に `s3:PutObject` 権限がない、または出力先 bucket / prefix が不在、または `/tmp/` 容量不足で中間 parquet 書き出しに失敗する。

**HDW_ML が出力する観測**: bayesian / glasso / SDS の各 finished ログまでは到達、`saved to s3` で `ClientError` (AccessDenied / NoSuchBucket) or parquet 書き出し時の `OSError` / `IOError` → `lambda_handler failed`。

**推論されるべき状況**: 計算結果の S3 出力経路で権限 / リソース / 容量の問題が生じている。

**目視確認**: `root_cause_hypothesis` が S3 出力経路の障害 (権限欠落 / bucket 不在 / 容量不足) を言い当てている。`suggested_actions` に出力先 bucket と IAM policy の確認、または Lambda の `/tmp` 容量設定確認が含まれている。

---

### TC-S-1: 運用上 skip すべき船 (alarm が出ないこと)

**入力条件**: ZIP ファイル名の shipname が HDW_ML の停止リスト (例: `shimakaji`) に含まれている。

**HDW_ML が出力する観測**: `skip suspended ship` + `lambda complete status=success` のみ。エラーは出ない。

**推論されるべき状況**: shipname が運用上の停止リストに含まれており、明示的に skip されて正常終了している。エラーではない。

**目視確認**: 該当時間窓に Discord 通知が **発火しない** こと。発火した場合は仕様違反として記録する。

---

## ケース集 (HDW_ML 外側起因)

HDW_ML のコード・入力 ZIP は健全だが、その外側 (Lambda runtime / デプロイ / AWS 依存) で発生し、CloudWatch Logs に痕跡が残るタイプの問題群。Bedrock が「HDW_ML のコード起因ではない」と切り分けて推論できているかを評価する。

### TC-X-1: Lambda Timeout

**入力条件**: HDW_ML Lambda 関数の `Timeout` 設定値が実際の処理時間に対して不足している (例: 通常 300 秒で完了する処理に対して Timeout 60 秒)。

**HDW_ML が出力する観測**: 途中フェーズのログ (例: `extract zip file complete`, `validation complete` 等) は出るが、その後 `lambda complete` に到達せず、Lambda runtime の標準ログに `Task timed out after Xs` が記録される。

**推論されるべき状況**: HDW_ML のコードバグではなく、Lambda 関数の Timeout 設定が処理時間予算に対して不足している。処理データ量増加や cold start 影響の可能性も含む。

**目視確認**: `root_cause_hypothesis` が「Lambda の Timeout 設定不足」を言い当てており、コード起因ではなく実行時間予算の問題として切り分けられている。`suggested_actions` に Lambda Timeout の引き上げや Init duration の確認が含まれている。

---

### TC-X-2: メモリ枯渇 (OOM)

**入力条件**: HDW_ML Lambda 関数の `MemorySize` 設定値が処理対象データのメモリ消費量に対して不足している (例: polars / numpy が大きな DataFrame を保持する瞬間に上限超過)。

**HDW_ML が出力する観測**: Lambda runtime の標準ログに `Runtime exited` または `Out of memory` のメッセージ。CloudWatch Metrics で Max memory used が MemorySize 値に張り付く。

**推論されるべき状況**: HDW_ML のコードロジック自体ではなく、Lambda メモリ設定が処理データ規模に対して不足している。データ規模拡大の傾向も疑う。

**目視確認**: `root_cause_hypothesis` が「Lambda メモリ設定不足」を言い当てている。`suggested_actions` に MemorySize の引き上げや Memory 使用傾向の Metrics 確認が含まれている。

---

### TC-X-3: /tmp 容量不足

**入力条件**: Lambda の Ephemeral Storage 設定値が、ZIP 展開 + 中間 parquet + parameter ファイル展開のサイズ合計を下回る。

**HDW_ML が出力する観測**: `OSError: [Errno 28] No space left on device` がいずれかのフェーズ (extract / save / parquet write) で発生 → `lambda_handler failed`。

**推論されるべき状況**: HDW_ML のコードバグではなく、Lambda の `/tmp` (Ephemeral Storage) 容量不足。処理対象データの増大や中間ファイルの累積が要因。

**目視確認**: `root_cause_hypothesis` が `/tmp` 容量不足を言い当てている。`suggested_actions` に Ephemeral Storage 設定値の引き上げや中間ファイルの clean up 経路の確認が含まれている。

---

### TC-X-4: 依存ライブラリ欠落 (デプロイ事故)

**入力条件**: デプロイされた Lambda の OCI image に、HDW_ML が import するライブラリの一部が含まれていない (requirements.txt 漏れ / image build 時の依存解決失敗 / image tag 取り違え)。

**HDW_ML が出力する観測**: Lambda 起動の init 段階で `ImportError: No module named 'X'` または `ModuleNotFoundError`。`lambda_handler invoked` ログにすら到達しない。

**推論されるべき状況**: HDW_ML のロジック起因ではなく、デプロイ済 OCI image の依存欠落。直近デプロイの差分が疑わしい。

**目視確認**: `root_cause_hypothesis` が依存ライブラリの欠落 / デプロイ事故を言い当てている。`suggested_actions` に直近デプロイの差分確認や OCI image tag の整合性チェックが含まれている。

---

### TC-X-5: SDK スロットリング / 一時的 5xx

**入力条件**: HDW_ML が呼び出す AWS サービス (S3 / Bedrock 等) が一時的に Throttling や 5xx を返している (リージョン側の transient な負荷状態)。

**HDW_ML が出力する観測**: boto3 の `ClientError` で error code が `SlowDown` / `RequestLimitExceeded` / `InternalError` / 5xx 系のいずれか。

**推論されるべき状況**: HDW_ML のコード問題でも入力データ問題でもなく、依存 AWS サービス側の一時的障害。再試行で回復する見込みがある transient な事象。

**目視確認**: `root_cause_hypothesis` が AWS 側の transient 障害を言い当てている。`suggested_actions` に AWS Service Health Dashboard の確認や再試行・指数バックオフ実装の検討が含まれている。

