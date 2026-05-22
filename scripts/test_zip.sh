#!/bin/bash
# test_zip.sh — test-zip-management SPEC の E2E 動作確認スクリプト。
#
# spec: test-zip-management@2.0.0
#
# 動作:
#   Phase 1  クリーンアップ + make_test_zip.py で TC-B-3 / TC-B-5 / TC-S-1
#            の 3 種を生成
#   Phase 2  verify_test_zip.py で 4 種の positive 検証
#            (base / TC-B-3 / TC-B-5 / TC-S-1、すべて --base 比較込み)
#   Phase 3  verify_test_zip.py --expect-fail で 6 種の negative 検証
#            (TC-005-1 〜 TC-005-6)
#
# 前提:
#   tmp/test-zips/base/ に有効な HDW_ML 入力 ZIP が 1 件存在すること。
#   ベース ZIP のファイル名はワイルドカードで自動検出する。
#
# 終了コード:
#   0  全 phase 完走 (positive は exit 0 / negative は --expect-fail で exit 0)
#   非0 いずれかのステップで予期しない失敗

set -u  # 未定義変数で停止
set +e  # 個別コマンドの失敗で停止しない (失敗は明示的に判定)

# ベース ZIP を自動検出 (1 件目)
BASE=$(ls tmp/test-zips/base/*.zip 2>/dev/null | head -1)
if [ -z "$BASE" ]; then
  echo "ERROR: tmp/test-zips/base/ にベース ZIP が見つかりません" >&2
  exit 2
fi

TS=$(date +%Y%m%d%H%M%S)
SHIP=sakura

TCB3=tmp/test-zips/TC-B-3/${SHIP}-${TS}.zip
TCB5=tmp/test-zips/TC-B-5/${SHIP}-${TS}.zip
TCS1=tmp/test-zips/TC-S-1/shimakaji-${TS}.zip

fail=0
section() { echo ""; echo "=============================================================="; echo "$1"; echo "=============================================================="; }
step()    { echo "--- $1 ---"; }
check()   {
  local name=$1
  local rc=$2
  if [ "$rc" -eq 0 ]; then
    echo "  [OK]  $name (exit=$rc)"
  else
    echo "  [NG]  $name (exit=$rc)"
    fail=$((fail + 1))
  fi
}

section "Phase 1: 生成 (make_test_zip.py)"
step "BASE: $BASE"
step "TC-B-3"
python scripts/make_test_zip.py TC-B-3 "$BASE" -o "$TCB3"
check "TC-B-3 generation" $?
step "TC-B-5"
python scripts/make_test_zip.py TC-B-5 "$BASE" -o "$TCB5"
check "TC-B-5 generation" $?
step "TC-S-1"
python scripts/make_test_zip.py TC-S-1 "$BASE" -o "$TCS1"
check "TC-S-1 generation" $?

section "Phase 2: positive verify (合致 mode で pass)"
step "TC-001-2: base"
python scripts/verify_test_zip.py base "$BASE"
check "TC-001-2" $?
step "TC-002-1,002-2: TC-B-3 --base"
python scripts/verify_test_zip.py TC-B-3 "$TCB3" --base "$BASE"
check "TC-002-* " $?
step "TC-003-1,003-2: TC-B-5 --base"
python scripts/verify_test_zip.py TC-B-5 "$TCB5" --base "$BASE"
check "TC-003-* " $?
step "TC-004-1,004-2: TC-S-1 --base"
python scripts/verify_test_zip.py TC-S-1 "$TCS1" --base "$BASE"
check "TC-004-* " $?

section "Phase 3: negative verify (不一致 mode + --expect-fail で fail 検出)"
# (case_id, mode, zip)
declare -a cases=(
  "TC-005-1|TC-B-5|$TCB3"
  "TC-005-2|TC-S-1|$TCB3"
  "TC-005-3|TC-B-3|$TCB5"
  "TC-005-4|TC-S-1|$TCB5"
  "TC-005-5|TC-B-3|$TCS1"
  "TC-005-6|TC-B-5|$TCS1"
)
for c in "${cases[@]}"; do
  id="${c%%|*}"; rest="${c#*|}"; mode="${rest%|*}"; zip="${rest#*|}"
  step "$id: $mode on $(basename "$zip")"
  python scripts/verify_test_zip.py "$mode" "$zip" --expect-fail
  check "$id" $?
done

section "SUMMARY"
if [ "$fail" -eq 0 ]; then
  echo "ALL PASS"
  exit 0
else
  echo "FAILED: $fail step(s)"
  exit 1
fi
