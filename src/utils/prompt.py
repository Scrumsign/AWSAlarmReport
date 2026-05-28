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

# business_summary
- 100 文字以内。通知を受け取る非技術者が「業務上何が起きているか」を理解するための説明
- AWS 用語・技術用語（Lambda、Alarm、S3、CloudWatch 等）は使わない
- 「ファイル処理」「データ」「送信」など受信者が理解できる日本語で書く
- 「対応が必要かどうか」「業務にどう影響するか」が伝わるようにする
- 例: 「sakura のデータ処理中にエラーが発生しました。出力データが欠損している可能性があります。」

# root_cause_hypothesis
- 100 文字以内。原因を非技術者にも分かる言葉で説明する
- コード参照（ファイル名、行番号、関数名）やAWS用語は使わない
- 「何が原因で」「どうなったか」を業務の言葉で伝える
- 例: 「送信されたファイルの形式に問題があり、正しく処理できませんでした。」
- 例: 「ファイルが届いていないため、処理が開始されていません。」

# technical_observation
- 200 文字以内。ログから読み取れた技術的事実のみ
- 例外クラス名、発生箇所（file:line）、エラーメッセージを含める
- 仮説や推測は含めない。観測できた事実だけを書く
- 例: 「store.py:87 で KeyError('data') が発生。request_id=abc123 の実行で
  frontend_paths['data'][key] へのアクセス時に例外。」

# technical_hypothesis
- 200 文字以内。技術的な原因の仮説と対処の方向性
- もっともらしい順に複数仮説を並べてよい
- コード修正レベルの指摘を歓迎する
- ただし「断定的に "これを直せ"」ではなく、仮説性を残すこと
- 例: 「入力 ZIP 内のデータ構造が想定と異なる可能性が高い。
  store.py:87 の辞書アクセスを .get() に変更し KeyError 耐性を向上させることを推奨。」

# suggested_actions の制約
- 各項目 80 文字以内、最大 3 件
- 「即時対応」「調査手順」「恒久対策」の 3 段で並べる

# 出力スキーマ
{{
  "business_summary": "非技術者向け: 業務上何が起きているか (100 文字以内、技術用語禁止)",
  "root_cause_hypothesis": "非技術者向け: 原因の見立て (100 文字以内、技術用語禁止)",
  "confidence": "low" | "medium" | "high",
  "technical_observation": "技術者向け: ログから確認できた事実 (200 文字以内)",
  "technical_hypothesis": "技術者向け: 原因仮説と対処の方向性 (200 文字以内)",
  "suggested_actions": [
    "即時対応 (80 字以内)",
    "調査手順 (80 字以内)",
    "恒久対策 (80 字以内)"
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


def render_prompt_case_unknown() -> tuple[str, str]:
    """
    エラー種別不明（ログあり・status=error なし）用のケース名と追加指示文を返す。

    呼び出しトリガー: log_rows は存在するが status="error" のログが 1 件もない。
    """
    return (
        "エラー種別不明（ログあり・エラーなし）",
        "直近時間窓内に Lambda の実行ログは存在するが、status=\"error\" のログが確認できない。\n"
        "→ Lambda は起動しているが、成功・失敗いずれとも断定できない状態。\n"
        "  考えられる原因:\n"
        "    - 処理が完了したが success ログの出力がない（ロギング実装の漏れ）\n"
        "    - 処理が途中で中断されたが例外が補足されなかった\n"
        "    - Alarm の発火条件が実際のエラーと対応していない\n"
        "→ ログを精査して正常・異常のいずれに近いかを判断し、confidence は低めに設定する。\n"
        "suggested_actions は手動調査の手順を優先して提案してください。"
    )


def render_prompt_case_unknown_alarm() -> tuple[str, str]:
    """
    想定外アラーム（命名規約外）用のケース名と追加指示文を返す。

    呼び出しトリガー: AlarmName が hdw-<ship_name>[-test] 形式に一致しない。
    """
    return (
        "想定外アラーム（命名規約外）",
        "受信した AlarmName がシステムの命名規約（hdw-<ship_name>[-test]）に一致しない。\n"
        "→ このシステムが処理対象としていないアラームが誤って届いた可能性がある。\n"
        "  考えられる原因:\n"
        "    - アラーム設定の誤り（命名規約に合っていない）\n"
        "    - 別システムのアラームが同一 SNS トピックに紐付けられている\n"
        "→ ログとの対応が取れないため、提供できる分析は限定的。\n"
        "  severity は LOW、confidence は low として、アラーム設定の確認を促してください。"
    )


def build_system_prompt(error_id: str, error_description: str) -> str:
    """
    error_id に対応するケース関数を選択してシステムプロンプトを構築し、
    error-profiles.yml の description を末尾に注入して返す。
    """
    _CASE_MAP = {
        "s3_data_missing": render_prompt_case_no_logs,
        "lambda_failure":  render_prompt_case_lambda_failure,
        "unknown":         render_prompt_case_unknown,
        "unknown_alarm":   render_prompt_case_unknown_alarm,
    }
    case_fn = _CASE_MAP.get(error_id, render_prompt_case_lambda_failure)
    case_name, case_instructions = case_fn()
    system_prompt = render_prompt_system_base(case_name, case_instructions)
    if error_description:
        system_prompt += f"\n\n# エラープロファイル\n{error_description.strip()}"
    return system_prompt


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
