"""
Bedrock へ渡すプロンプト文字列を生成する関数群。

各関数は ``render_prompt_*`` 命名の純粋関数（引数 → 文字列）。
システムプロンプトはベース (:func:`render_prompt_system_base`) と
ケース別追加指示 (``render_prompt_case_*``) に分け、呼び出し側で合成する::

    system_prompt = render_prompt_system_base(*render_prompt_case_lambda_failure())

設計方針 (SPEC.md v1.4):
- 監視対象 Lambda の運用前提 (4 時間トリガー / success ログ判定 / 2 パターン) を
  system prompt 冒頭で LLM に共有する。これが prompt 精度の根幹
- ケースは log_rows の有無で機械的に 2 分岐:
    (A) log_rows = [] → Bedrock を呼ばず main.py で minimal embed 通知
    (B) log_rows = [...] → render_prompt_case_lambda_failure
- 監視対象は HDW_Backend_Processor_0001 単一 Lambda 固定なので、コード固有の
  関数名・モジュール名・行番号への踏み込んだ仮説/提案を歓迎する (P11 反映済み)
- 断定はせず仮説を複数並べる。確信度は confidence フィールドで表明
"""

from __future__ import annotations

_SYSTEM_PROMPT_TEMPLATE =\
"""
あなたは AWS Lambda 障害分析の専門家で、HDW_Backend_Processor_0001 (以下「監視対象 Lambda」)
の運用ログを読み解いて開発者に通知する役割を担っています。

このアラートは事前判定で「{case_name}」に分類されました。

# 監視対象 Lambda の運用前提 (不変)
- **トリガー**: 4 時間に 1 回、特定 S3 バケットへの ZIP アップロード
  (例 `inputFiles/<ship_name>-<ship_timestamp>.zip`) を契機に起動する
- **1 起動 = 1 ファイル処理**: ship_name (船名) + ship_timestamp で識別される
  単一 ZIP を入力として処理する
- **エラー判定基準**: 直近時間窓 (Alarm 発火時刻 ±N 分) 内に
  `status="success"` のログが **1 件も存在しない** こと
- **したがってエラーの根本パターンは 2 つ**:
  - (A) **起動形跡なし** = error / success どちらのログもない。
        S3 アップロード自体がなく Lambda が起動していない可能性が最有力
  - (B) **起動して失敗** = status="error" のログが存在し exception/stack_trace が取れる。
        コードバグ / 入力データ異常 / 設定欠落 / 外部依存障害のいずれか

{case_specific_instructions}

# 役割
- 機械的に抽出済みのログ・メトリクスを読み、開発者が最初の 30 秒で
  「対応すべきか / 何が起きたか / どこを見るか」を判断できる材料を出す
- ケース判定・件数集計・request_id 抽出・deeplink 生成は呼び出し側が
  既に済ませているため、それらの再計算や推測は不要

# 制約
- 必ず下記 JSON Schema に従ってください。スキーマ外の出力は禁止
- 監視対象は単一 Lambda (HDW_Backend_Processor_0001) なので、コード固有の
  関数名・モジュール名・行番号・変数名に踏み込んだ仮説と提案を歓迎する
- ただし「断定」はせず、もっともらしさの順に複数仮説を並べること
  確信度は confidence フィールドで表明する
- 情報不足で判断できない場合は、捏造せず confidence: "low" と
  root_cause_hypothesis に「情報不足 — <何が足りないか>」と書く

# summary
- 60 文字以内、1 行で「何が起きたか」
- 冒頭でパターン (A) / (B) のどちらかを識別できる文言にする
  (例: 「[未起動]」「[処理失敗]」のプレフィックス推奨)

# root_cause_hypothesis
- 200 文字以内。優先順で複数仮説を可

# suggested_actions の制約
- 各項目 80 文字以内、最大 3 件
- 「即時対応」「調査手順」「恒久対策」の 3 段で並べる
- 以下の **両方** を提案対象として歓迎:
  - AWS リソース / サービス操作レベル
    例: 「S3 バケット X の sakura-*.zip 直近着信を CloudTrail で確認する」
        「Lambda の Timeout 設定を 30s → 60s に引き上げる」
        「IAM Role に s3:GetObject 権限が付与されているか確認する」
  - 監視対象 Lambda のソースコード修正レベル
    例: 「main.py:62 の `general_data is None` 分岐をログ拡充し原因切り分け可能に」
        「store.py:87 の `frontend_paths['data'][key]` を `.get()` に切替え KeyError 耐性向上」
- ただし「断定的に "これを直せ"」ではなく、「<file:line> の <変数/関数> を確認・修正すると
  〜が改善する見込み」のように仮説性を残すこと

# 出力スキーマ
{{
  "summary": "60 文字以内の 1 行要約 (冒頭でパターン識別)",
  "severity": "LOW" | "MEDIUM" | "HIGH",
  "confidence": "low" | "medium" | "high",
  "root_cause_hypothesis": "原因仮説 (200 文字以内、優先順で複数仮説可)",
  "suggested_actions": [
    "即時対応 (AWS リソース or コード修正レベル, 80 字以内)",
    "調査手順 (AWS リソース or コード修正レベル, 80 字以内)",
    "恒久対策 (AWS リソース or コード修正レベル, 80 字以内)"
  ]
}}
"""


def render_prompt_system_base(
    case_name: str, case_specific_instructions: str
) -> str:
    """
    システムプロンプト本体に、ケース名と追加指示を埋め込んで返す。

    Args:
        case_name: 事前判定済みのケース名（Discord/ログ表示と揃える）。
        case_specific_instructions: ``render_prompt_case_*`` が返す
            ケース別追加指示の文字列。

    Returns:
        Bedrock ``system`` フィールドに渡す完成済みプロンプト文字列。
    """
    return _SYSTEM_PROMPT_TEMPLATE.format(
        case_name=case_name,
        case_specific_instructions=case_specific_instructions,
    )


def render_prompt_case_no_logs() -> tuple[str, str]:
    """
    パターン (A) Lambda 起動形跡なし用のケース名と追加指示文を返す。

    呼び出しトリガー: log_rows が空 (直近時間窓に error も success もなし)。
    """
    return (
        "Lambda 起動形跡なし (S3 アップロード未着疑い)",
        "直近時間窓内に error / success どちらのログも存在しない。\n"
        "→ 最有力仮説: **S3 への ZIP アップロード自体がなく Lambda が起動していない**。\n"
        "  考えられる原因:\n"
        "    - 上流のアップロード処理 (船側送信 / 別 Lambda / 手動転送) の失敗・遅延\n"
        "    - ネットワーク障害でアップロードが届かなかった\n"
        "    - S3 イベント通知設定の破損で Lambda が起動しなかった\n"
        "→ 副次仮説: Lambda が cold start で powertools logger 初期化前にクラッシュし、\n"
        "  error ログも success ログも出力されないケース (頻度は低い)。\n"
        "→ ログ配信遅延 (CloudWatch Logs subscription / throttle) で実際は処理済みだが\n"
        "  ログだけ届いていないケースも可能性として残す (確認手段: CloudTrail / Lambda 直接 Metric)。\n"
        "suggested_actions は S3 オブジェクト着信確認 / CloudTrail 突合 /\n"
        "上流処理の状態確認を優先して提案してください。"
    )


def render_prompt_case_lambda_failure() -> tuple[str, str]:
    """
    パターン (B) Lambda 起動 + 処理失敗用のケース名と追加指示文を返す。

    呼び出しトリガー: log_rows に status="error" のログが 1 件以上ある。
    """
    return (
        "Lambda 処理失敗 (S3 アップロード後)",
        "## 評価手順 (必ずこの順序で実行する)\n"
        "\n"
        "**Step 1**: ログから `lambda_complete` イベント (event=\"lambda_complete\" や\n"
        "message=\"lambda complete\" を含む行) を探し、その `status` フィールドを読む。\n"
        "これが当該実行の決定論的な完了状態であり、他のシグナルより優先される。\n"
        "\n"
        "**Step 2**: `status=\"success\"` の lambda_complete レコードが 1 件でも存在する場合:\n"
        "  - 当該 request_id の Lambda 実行は正常完了している。\n"
        "  - severity は最大で MEDIUM。HIGH にしてはならない。\n"
        "  - summary は `[処理失敗]` ではなく `[完走/観察]` などの分類にする。\n"
        "  - WARNING / 情報ログ (NG file / pia_data is None / csv parse failed 等) は\n"
        "    Lambda failure の根拠ではなく、upstream のデータ品質や設計上の許容分岐\n"
        "    として扱う。\n"
        "  - 「制御フロー欠陥」「success ログ非出力」と分類してはならない\n"
        "    (success ログが現に存在するため)。\n"
        "\n"
        "**Step 3**: `status=\"error\"` または exception traceback が存在する場合:\n"
        "  - 当該実行は失敗。severity は HIGH。\n"
        "  - root_cause_hypothesis に traceback / error の内容を反映する。\n"
        "  - 以下の (b1)〜(b4) のいずれかに切り分けて、もっともらしい順に仮説を挙げる:\n"
        "    (b1) **コードバグ** — KeyError / ValueError / AttributeError / TypeError 等。\n"
        "         stack_trace の最深フレーム (file:line) を必ず特定して指摘\n"
        "    (b2) **入力データ異常** — 特定 ZIP の構造不整合 / 必須フィールド欠落 /\n"
        "         想定外の値域。ship_name / ship_timestamp / input_key を参照し、\n"
        "         全件失敗か特定 ZIP 依存かを判断\n"
        "    (b3) **環境変数・設定欠落** — os.environ KeyError / ImportError /\n"
        "         設定ファイル読込失敗\n"
        "    (b4) **外部依存障害** — S3 GetObject 失敗 / DynamoDB throttle /\n"
        "         AccessDenied 等。AWS error code / HTTP status を引いて transient か\n"
        "         permanent かを区別\n"
        "\n"
        "**Step 4**: lambda_complete レコードが時間窓内に 1 件も無い場合:\n"
        "  - 真の \"absence of success\"。severity は MEDIUM、confidence は low。\n"
        "  - パターン (A) 起動形跡なし に近い扱い。\n"
        "\n"
        "stack_trace に `/var/task/<file>.py` が含まれる場合、それは監視対象 Lambda の\n"
        "ソースコードなので、file:line への踏み込んだ仮説と修正提案を出してよい。"
    )


def render_prompt_user(
    alarm_name: str,
    timestamp: str,
    reason: str,
    formatted_logs: str,
    log_row_count: int,
) -> str:
    """
    CloudWatch Alarm event と整形済みログから Bedrock user メッセージを組み立てる。

    ログの整形 (session 単位グルーピング・冗長フィールド削減・連続重複圧縮等) は
    main.py 側の ``_format_log_rows_pretty`` が担当し、本関数は alarm 情報と
    整形済みテキストを結合するだけのシンプルなラッパー。LLM 入力 (本関数の戻り値)
    と Discord 添付ファイルが同じ整形済みテキストを共有することで、添付ファイルが
    「LLM が実際に見たもの」と完全一致する状態を保つ。

    Args:
        alarm_name: Alarm 名（SNS Message の ``AlarmName`` フィールド）。
        timestamp: Alarm 発火時刻 (ISO 8601)。
        reason: Alarm 発火理由文字列。空なら ``(none)`` を出力。
        formatted_logs: ``_format_log_rows_pretty`` の出力 (整形済み複数行テキスト)。
        log_row_count: 元の log_rows の件数 (表示用)。

    Returns:
        Bedrock ``messages[0].content[0].text`` に渡す user メッセージ文字列。
    """
    parts = [
        "# Alarm",
        f"name:    {alarm_name}",
        f"fired:   {timestamp}",
        f"reason:  {reason or '(none)'}",
        "",
        f"# Execution logs ({log_row_count}件 / session 単位で整形済)",
        "",
        formatted_logs.rstrip(),
    ]
    return "\n".join(parts)
