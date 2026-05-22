"""
ユーティリティモジュール群。

* :mod:`.prompt` — ``render_prompt_*`` 関数群（システムプロンプト + ケース別追加指示）

設定値・シークレットは Lambda 環境変数から :mod:`main` が ``os.environ`` で直接
取得する（``config`` / ``env`` モジュールは廃止）。
"""
