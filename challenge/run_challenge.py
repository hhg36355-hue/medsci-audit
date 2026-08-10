#!/usr/bin/env python3
# 本工作站原创（2026-07-30）；Python 3.13，纯标准库，确定性无随机性（无需 seed）。
"""medsci-audit 第三批移植检测器的植缺陷自检夹具（challenge harness）。

为什么存在：CLAUDE.md 那条「新写的门禁第一次就全绿 = 可疑；交付前必须先植入一个已知
缺陷确认门禁会开火」不能只在移植当天做一次——上游会更新，本地会改正则，任何一次改动都
可能把检测器改成"永远静默"。上游自己也承认 84 个检测器里只有 26 个带 challenge 夹具，
所以本地移植的这几个由本文件兜底：每次同步上游、或改动这四个脚本的正则之后，跑一遍。

验收标准是四格全过，缺一不可：
  1. 中文植缺陷 → 必须开火
  2. 中文干净稿 → 必须静默（防过报）
  3. 英文夹具   → 仍开火（防"为了适配中文把上游英文口径改坏"）
  4. --strict 退出码符合各检测器自身的严重度设计

用法（Windows 建议带 PYTHONUTF8=1）：
    python run_challenge.py [--python /path/to/python]
退出码：0 全过；1 有用例未达预期。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"

# (名称, 参数, 期望退出码 or None, 期望在 stdout 中出现/不出现的判据串)
CASES = [
    ("scope_coherence  中文·植缺陷",
     ["check_scope_coherence.py", "--manuscript", "zh_defect.md", "--strict"],
     1, "CROSS_SECTIONAL_PROGNOSTIC", True),
    ("scope_coherence  中文·干净",
     ["check_scope_coherence.py", "--manuscript", "zh_clean.md", "--strict"],
     0, "CROSS_SECTIONAL_PROGNOSTIC", False),
    ("scope_coherence  英文·回归",
     ["check_scope_coherence.py", "--manuscript", "en_defect.md", "--strict"],
     1, "CROSS_SECTIONAL_PROGNOSTIC", True),

    ("confounding      中文·植缺陷",
     ["check_confounding_completeness.py", "--table1", "table1_by_la.csv",
      "--adjusted-list", "年龄,性别,体质量指数,高血压,糖尿病", "--strict"],
     1, "空腹血糖", True),
    ("confounding      中文·干净",
     ["check_confounding_completeness.py", "--table1", "table1_by_la.csv",
      "--adjusted-list", "年龄,性别,体质量指数,高血压,糖尿病,空腹血糖,甘油三酯", "--strict"],
     0, "Major", False),
    ("confounding      英文·回归",
     ["check_confounding_completeness.py", "--table1", "table1_en.csv",
      "--adjusted-list", "age,sex,body mass index,hypertension,diabetes", "--strict"],
     1, "Fasting glucose", True),

    ("binning          植缺陷",
     ["check_binning_consistency.py", "--root", "code", "--strict"],
     1, "BINNING_DRIFT", True),
    ("binning          干净",
     ["check_binning_consistency.py", "--root", "code_clean", "--strict"],
     0, "BINNING_DRIFT", False),

    # rounded_delta 是 Minor-only：按设计 --strict 也永远退 0，故只判命中串
    ("rounded_delta    中文·植缺陷",
     ["check_rounded_delta.py", "--manuscript", "zh_defect.md"],
     None, "ROUNDED_DELTA_MISMATCH", True),
    ("rounded_delta    中文·干净",
     ["check_rounded_delta.py", "--manuscript", "zh_clean.md"],
     None, "ROUNDED_DELTA_MISMATCH", False),
    ("rounded_delta    英文·回归",
     ["check_rounded_delta.py", "--manuscript", "en_defect.md"],
     None, "ROUNDED_DELTA_MISMATCH", True),

    # ---- 2026-08-09 新增的四个原创检测器（统计表格类）----
    # 夹具数据全部来自当天实测的 12 篇真实论文，不是构造出来的假例子。
    ("regression_table 植缺陷·OR≠exp(β)",
     ["check_regression_table.py", "--manuscript", "zh_regression_defect.md", "--strict"],
     1, "OR_NOT_EXP_BETA", True),
    ("regression_table 植缺陷·定位错列",
     ["check_regression_table.py", "--manuscript", "zh_regression_defect.md"],
     None, "OR 列单独填错", True),
    ("regression_table 植缺陷·符号",
     ["check_regression_table.py", "--manuscript", "zh_regression_defect.md"],
     None, "OR_BETA_SIGN", True),
    ("regression_table 植缺陷·CI↔P",
     ["check_regression_table.py", "--manuscript", "zh_regression_defect.md"],
     None, "CI_P_MISMATCH", True),
    ("regression_table 干净·防过报",
     ["check_regression_table.py", "--manuscript", "zh_regression_clean.md", "--strict"],
     0, "Major", False),

    ("ratio_columns    植缺陷·均值之商",
     ["check_ratio_columns.py", "--manuscript", "zh_ratio_defect.md", "--strict"],
     1, "RATIO_IS_MEAN_OF_MEANS", True),
    ("ratio_columns    植缺陷·SD 下界",
     ["check_ratio_columns.py", "--manuscript", "zh_ratio_defect.md"],
     None, "RATIO_SD_BELOW_BOUND", True),
    ("ratio_columns    干净·防过报",
     ["check_ratio_columns.py", "--manuscript", "zh_ratio_clean.md", "--strict"],
     0, "Major", False),
    # 缩写名（NLR/MHR/NHR）不含斜杠，必须靠内置对照表识别；干净稿里 NHR 应被“认出来且不报”
    ("ratio_columns    干净·缩写名被识别",
     ["check_ratio_columns.py", "--manuscript", "zh_ratio_clean.md"],
     None, "识别为比值的行 2 行", True),

    ("diagnostic       植缺陷·比例不可达",
     ["check_diagnostic_metrics.py", "--manuscript", "zh_roc_defect.md",
      "--n1", "17", "--n0", "42", "--strict"],
     1, "RATE_UNREACHABLE", True),
    ("diagnostic       植缺陷·AUC↔SE↔CI",
     ["check_diagnostic_metrics.py", "--manuscript", "zh_roc_defect.md",
      "--n1", "17", "--n0", "42"],
     None, "AUC_CI_MISMATCH", True),
    ("diagnostic       干净·防过报",
     ["check_diagnostic_metrics.py", "--manuscript", "zh_roc_clean.md",
      "--n1", "42", "--n0", "84", "--strict"],
     0, "Major", False),

    ("correlation      植缺陷·r↔P 反推",
     ["check_correlation_table.py", "--manuscript", "zh_corr_defect.md",
      "--n", "60", "--strict"],
     1, "R_P_MISMATCH", True),
    ("correlation      植缺陷·单调性",
     ["check_correlation_table.py", "--manuscript", "zh_corr_defect.md", "--n", "60"],
     None, "R_P_NONMONOTONE", True),
    ("correlation      植缺陷·整列雷同",
     ["check_correlation_table.py", "--manuscript", "zh_corr_defect.md", "--n", "60"],
     None, "按列比", True),
    ("correlation      干净·防过报",
     ["check_correlation_table.py", "--manuscript", "zh_corr_clean.md",
      "--n", "126", "--strict"],
     0, "Major", False),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="medsci-audit 移植检测器植缺陷自检")
    ap.add_argument("--python", default=sys.executable, help="用哪个解释器跑被测脚本")
    args = ap.parse_args()

    failures = 0
    for name, argv, want_rc, needle, want_present in CASES:
        script = SCRIPTS / argv[0]
        if not script.is_file():
            print(f"FAIL  {name}  —— 脚本不存在：{script}")
            failures += 1
            continue
        proc = subprocess.run([args.python, str(script)] + argv[1:],
                              cwd=HERE, capture_output=True, text=True, encoding="utf-8")
        out = (proc.stdout or "") + (proc.stderr or "")
        problems = []
        if want_rc is not None and proc.returncode != want_rc:
            problems.append(f"退出码 {proc.returncode}（期望 {want_rc}）")
        hit = needle in out
        if hit != want_present:
            problems.append(f"{'未命中' if want_present else '误命中'} {needle}")
        if problems:
            failures += 1
            print(f"FAIL  {name}  —— " + "；".join(problems))
        else:
            print(f"pass  {name}")

    print()
    print("全部通过。" if not failures else f"{failures} 个用例未达预期——"
          "在把这几个检测器用于真实稿件之前先修好，否则它们的『全绿』不构成证据。")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
