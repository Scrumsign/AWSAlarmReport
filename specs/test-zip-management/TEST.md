---
id: test-zip-management
version: 2.0.0
title: テスト用 ZIP 生成・管理 TEST
created_at: 2026-05-20
type: test
---

# テスト用 ZIP 生成・管理 TEST

- **Spec**: test-zip-management@2.0.0
- **Plan rev**: 3
- **Rev**: 5
- **Created at**: 2026-05-20

## TC-001-1: ベース ZIP 保管領域の git 除外確認

- **対応 AC**: AC-001-1

次のシェル一行で確認する:

```
test -d tmp/test-zips/base && \
  grep -qE '^tmp/' .gitignore && \
  git check-ignore -q tmp/test-zips/base/dummy.txt 2>/dev/null || \
  git status --porcelain tmp/ | grep -q '^??'
```

合格条件:

- `tmp/test-zips/base/` が存在する
- `.gitignore` に `tmp/` を含む行がある
- `git status` で `tmp/` 配下が追跡されていない

## TC-001-2: ベース ZIP のフォルダ規約準拠確認

- **対応 AC**: AC-001-2

`scripts/verify_test_zip.py` に `verify_base(zip_path)` 関数を実装する。

前提ヘルパー `_real_filename(info)`:

`make_test_zip.py` PLAN rev 3 と同一実装を verify 側にも置く。
UTF-8 フラグの有無に依存せず常時 cp437→cp932 ラウンドトリップを試み、
`UnicodeError` 時は原文 fallback:

```python
def _real_filename(info):
    try:
        return info.filename.encode("cp437").decode("cp932")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename
```

実装内容:

```python
import re, zipfile
PAT_ENTRY = re.compile(
    r'^(db01|db02|db05em|db06em)/\d{4}/[^/]+/(定時|任意)/.+$'
)
PAT_DB02_GEN = re.compile(
    r'^db02/\d{4}/[^/]+/(定時|任意)/\d{14}/General\.csv$'
)
PAT_DB02_SENSOR = re.compile(
    r'^db02/\d{4}/[^/]+/(定時|任意)/\d{14}/(?!General)[^/]+\.csv$'
)

def verify_base(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        real_names = [_real_filename(i) for i in z.infolist()]
        bad = [n for n in real_names
               if not n.endswith("/") and not PAT_ENTRY.match(n)]
        assert not bad, f"規約違反エントリ: {bad[:3]}"
        assert any(PAT_DB02_GEN.match(n) for n in real_names), \
            "db02 配下に General.csv が見つかりません"
        assert any(PAT_DB02_SENSOR.match(n) for n in real_names), \
            "db02 配下に sensor CSV が見つかりません"
```

実行方法:

```
python scripts/verify_test_zip.py base tmp/test-zips/base/<base>.zip
```

合格条件: 終了コード 0、stdout に `OK: base`

## TC-002-1: TC-B-3 ZIP の tampered/ プレフィックス確認

- **対応 AC**: AC-002-1

`scripts/verify_test_zip.py` に `verify_tcb3(zip_path)` 関数を実装する。

実装内容:

```python
def verify_tcb3(zip_path, base_path=None):
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        bad = [n for n in names if not n.startswith("tampered/")]
        assert not bad, f"tampered/ で始まらないエントリ: {bad[:3]}"
        assert names, "ZIP が空"
```

実行方法:

```
python scripts/verify_test_zip.py TC-B-3 \
  tmp/test-zips/TC-B-3/<ship>-<ts>.zip
```

合格条件: 終了コード 0、stdout に `OK: TC-B-3 N エントリすべて tampered/ 配下`

## TC-002-2: TC-B-3 ZIP のエントリ数一致確認

- **対応 AC**: AC-002-2

`verify_tcb3` に `--base <base-zip>` オプションを追加し、
ベース ZIP とのエントリ数比較を行う:

```python
def verify_tcb3(zip_path, base_path=None):
    ...  # 既存の tampered/ チェック
    if base_path:
        with zipfile.ZipFile(base_path) as zb:
            base_count = len(zb.namelist())
        assert len(names) == base_count, \
            f"エントリ数不一致: 生成={len(names)} base={base_count}"
```

実行方法:

```
python scripts/verify_test_zip.py TC-B-3 \
  tmp/test-zips/TC-B-3/<ship>-<ts>.zip \
  --base tmp/test-zips/base/<base>.zip
```

合格条件: 終了コード 0、stdout に `OK: エントリ数一致 N=N`

## TC-003-1: TC-B-5 ZIP の対象 CSV 値破損確認

- **対応 AC**: AC-003-1

`scripts/verify_test_zip.py` に `verify_tcb5(zip_path)` 関数を実装する。

実装内容:

```python
import re
PAT_TARGET = re.compile(
    r'(^|.*?/)db02/\d{4}/[^/]+/(定時|任意)/\d{14}/(?!General)[^/]+\.csv$'
)

def verify_tcb5(zip_path, base_path=None):
    with zipfile.ZipFile(zip_path) as z:
        targets = [n for n in z.namelist() if PAT_TARGET.match(n)]
        assert targets, "対象 CSV が見つかりません"
        # ベース ZIP と並べたとき最初に見つかった 1 件が改造対象
        text = z.read(targets[0]).decode("cp932", errors="replace")
        lines = text.splitlines()
        assert len(lines) >= 2, f"行数不足: {targets[0]}"
        cells = lines[1].split(",")
        assert cells[0] == "BROKEN", \
            f"2行目1列目: {cells[0]!r} (BROKEN を期待)"
```

実行方法:

```
python scripts/verify_test_zip.py TC-B-5 \
  tmp/test-zips/TC-B-5/<ship>-<ts>.zip
```

合格条件: 終了コード 0、stdout に `OK: TC-B-5 <target> の 2行目1列目 = BROKEN`

## TC-003-2: TC-B-5 ZIP の対象 CSV 以外のエントリ同一性確認

- **対応 AC**: AC-003-2

`verify_tcb5` に `--base <base-zip>` オプションを追加し、
対象 CSV 以外のエントリのバイト列が一致することを確認する:

```python
def verify_tcb5(zip_path, base_path=None):
    ...  # 既存の BROKEN チェック
    if base_path:
        with zipfile.ZipFile(zip_path) as z, \
             zipfile.ZipFile(base_path) as zb:
            target = targets[0]
            for name in zb.namelist():
                if name == target:
                    continue
                assert z.read(name) == zb.read(name), \
                    f"バイト列差分: {name}"
```

実行方法:

```
python scripts/verify_test_zip.py TC-B-5 \
  tmp/test-zips/TC-B-5/<ship>-<ts>.zip \
  --base tmp/test-zips/base/<base>.zip
```

合格条件: 終了コード 0、stdout に `OK: 対象 CSV 以外 N-1 エントリのバイト列一致`

## TC-004-1: TC-S-1 ZIP のファイル名形式確認

- **対応 AC**: AC-004-1

`scripts/verify_test_zip.py` に `verify_tcs1(zip_path)` 関数を実装する。

実装内容:

```python
import re
from pathlib import Path
PAT_FILENAME = re.compile(r'^shimakaji-\d{14}\.zip$')

def verify_tcs1(zip_path, base_path=None):
    name = Path(zip_path).name
    assert PAT_FILENAME.match(name), \
        f"ファイル名: {name} (shimakaji-<14digits>.zip を期待)"
```

実行方法:

```
python scripts/verify_test_zip.py TC-S-1 \
  tmp/test-zips/TC-S-1/shimakaji-<ts>.zip
```

合格条件: 終了コード 0、stdout に `OK: TC-S-1 ファイル名 <name>`

## TC-004-2: TC-S-1 ZIP のエントリ一覧・バイト列完全一致確認

- **対応 AC**: AC-004-2

`verify_tcs1` に `--base <base-zip>` オプションを追加し、
エントリ一覧と各エントリのバイト列が完全一致することを確認する:

```python
def verify_tcs1(zip_path, base_path=None):
    ...  # 既存のファイル名チェック
    if base_path:
        with zipfile.ZipFile(zip_path) as z, \
             zipfile.ZipFile(base_path) as zb:
            names_z = sorted(z.namelist())
            names_b = sorted(zb.namelist())
            assert names_z == names_b, \
                f"エントリ一覧差分: {set(names_z) ^ set(names_b)}"
            for name in names_z:
                assert z.read(name) == zb.read(name), \
                    f"バイト列差分: {name}"
```

実行方法:

```
python scripts/verify_test_zip.py TC-S-1 \
  tmp/test-zips/TC-S-1/shimakaji-<ts>.zip \
  --base tmp/test-zips/base/<base>.zip
```

合格条件: 終了コード 0、stdout に `OK: TC-S-1 N エントリすべて base と一致`

## TC-005-1: negative: TC-B-3 ZIP を TC-B-5 mode で検証 → fail 検出

- **対応 AC**: AC-003-1

TC-B-3 ZIP（中身無改造、`tampered/` プレフィックスのみ）を TC-B-5 mode で
検証すると、対象 CSV の 2 行目 1 列目が元データ（例: float 値）のままで
BROKEN ではないため fail することを確認する。`verify_tcb5` の BROKEN 検知
ロジックが非自明な感度を持つことの証明。

`verify_test_zip.py` の `--expect-fail` オプションを使用する:

- 検証が fail（`AssertionError` / 他例外）した場合 exit 0
- 検証が pass した場合は UNEXPECTED PASS として exit 1

実行方法:

```
python scripts/verify_test_zip.py TC-B-5 \
  tmp/test-zips/TC-B-3/<ship>-<ts>.zip --expect-fail
```

合格条件: 終了コード 0、stdout に `[EXPECTED FAIL] TC-B-5 on ...`

## TC-005-2: negative: TC-B-3 ZIP を TC-S-1 mode で検証 → fail 検出

- **対応 AC**: AC-004-1

TC-B-3 ZIP（ファイル名 `sakura-...`）を TC-S-1 mode で検証すると、
ファイル名が `shimakaji-<14digits>.zip` 形式に一致せず fail することを
確認する。`verify_tcs1` のファイル名チェックの感度を証明。

実行方法:

```
python scripts/verify_test_zip.py TC-S-1 \
  tmp/test-zips/TC-B-3/<ship>-<ts>.zip --expect-fail
```

合格条件: 終了コード 0、stdout に `[EXPECTED FAIL] TC-S-1 on ...`

## TC-005-3: negative: TC-B-5 ZIP を TC-B-3 mode で検証 → fail 検出

- **対応 AC**: AC-002-1

TC-B-5 ZIP（中身改造あり、`tampered/` プレフィックス無し）を TC-B-3 mode で
検証すると、全エントリが `db01/db02/...` 配下で `tampered/` プレフィックスを
持たないため fail することを確認する。`verify_tcb3` の `tampered/` チェックの
感度を証明。

実行方法:

```
python scripts/verify_test_zip.py TC-B-3 \
  tmp/test-zips/TC-B-5/<ship>-<ts>.zip --expect-fail
```

合格条件: 終了コード 0、stdout に `[EXPECTED FAIL] TC-B-3 on ...`

## TC-005-4: negative: TC-B-5 ZIP を TC-S-1 mode で検証 → fail 検出

- **対応 AC**: AC-004-1

TC-B-5 ZIP（ファイル名 `sakura-...`）を TC-S-1 mode で検証すると、
ファイル名が `shimakaji-<14digits>.zip` 形式に一致せず fail することを
確認する。TC-005-2 と並ぶ `verify_tcs1` ファイル名チェック感度確認。

実行方法:

```
python scripts/verify_test_zip.py TC-S-1 \
  tmp/test-zips/TC-B-5/<ship>-<ts>.zip --expect-fail
```

合格条件: 終了コード 0、stdout に `[EXPECTED FAIL] TC-S-1 on ...`

## TC-005-5: negative: TC-S-1 ZIP を TC-B-3 mode で検証 → fail 検出

- **対応 AC**: AC-002-1

TC-S-1 ZIP（中身無改造、ベース ZIP と同一）を TC-B-3 mode で検証すると、
全エントリが `db01/db02/...` 配下で `tampered/` プレフィックスを持たないため
fail することを確認する。TC-005-3 と並ぶ `verify_tcb3` 感度確認。

実行方法:

```
python scripts/verify_test_zip.py TC-B-3 \
  tmp/test-zips/TC-S-1/shimakaji-<ts>.zip --expect-fail
```

合格条件: 終了コード 0、stdout に `[EXPECTED FAIL] TC-B-3 on ...`

## TC-005-6: negative: TC-S-1 ZIP を TC-B-5 mode で検証 → fail 検出

- **対応 AC**: AC-003-1

TC-S-1 ZIP（中身無改造、ベース ZIP と同一）を TC-B-5 mode で検証すると、
対象 CSV の 2 行目 1 列目が元データ（float 値）のまま BROKEN ではないため
fail することを確認する。TC-005-1 と並ぶ `verify_tcb5` 感度確認。

実行方法:

```
python scripts/verify_test_zip.py TC-B-5 \
  tmp/test-zips/TC-S-1/shimakaji-<ts>.zip --expect-fail
```

合格条件: 終了コード 0、stdout に `[EXPECTED FAIL] TC-B-5 on ...`

## TC-VERIFY-CLI: scripts/verify_test_zip.py の CLI 全体構造

- **対応 AC**: AC-002-1, AC-003-1, AC-004-1

`scripts/verify_test_zip.py` の CLI を以下の構造で実装する。
各 TC 検証関数を統合する dispatcher。

CLI 仕様:

```
python scripts/verify_test_zip.py <MODE> <zip-path> [--base <base-zip>]

<MODE>       : base / TC-B-3 / TC-B-5 / TC-S-1
<zip-path>   : 検証対象 ZIP のパス
--base <p>   : ベース ZIP のパス（オプション、AC-002-2/003-2/004-2 用）
```

実装構造:

```python
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("mode",
    choices=["base", "TC-B-3", "TC-B-5", "TC-S-1"])
parser.add_argument("zip_path")
parser.add_argument("--base", dest="base_path", default=None)
args = parser.parse_args()

dispatcher = {
    "base":   lambda: verify_base(args.zip_path),
    "TC-B-3": lambda: verify_tcb3(args.zip_path, args.base_path),
    "TC-B-5": lambda: verify_tcb5(args.zip_path, args.base_path),
    "TC-S-1": lambda: verify_tcs1(args.zip_path, args.base_path),
}
dispatcher[args.mode]()
print(f"OK: {args.mode}")
```

`AssertionError` は `SystemExit(1)` に変換し、エラーメッセージを stderr へ出力する。

合格条件:

```
python scripts/verify_test_zip.py --help
```

が exit 0 で usage を表示する。
