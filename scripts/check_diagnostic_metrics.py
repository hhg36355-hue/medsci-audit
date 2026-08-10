#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 本工作站原创（2026-08-09）；Python 3.13，纯标准库，确定性无随机性（无需 seed）。
"""诊断效能表自检：灵敏度/特异度的**可达性**、约登指数、准确率、AUC↔SE↔95%CI。

为什么存在：ROC 表是投稿稿件里最容易被整表照抄、又最少被复核的一张。它有四条只靠
表格自身就能验的关系，任何一条不成立都说明数字不是从这批数据里跑出来的：

**判据一 RATE_UNREACHABLE —— 比例 × 分母必须是整数**

  分母是整数、分子也是整数，所以灵敏度只能取 k/n₁ 这有限的一组值。2026-08-09 实测：
  某篇测试集只有 17 个事件，却报灵敏度 **72.00%**——0.72×17 = 12.24 例，而 17 例能
  取到的最近值是 12/17=70.59% 与 13/17=76.47%，**72.00% 根本取不到**。同篇的特异度
  84.90%（分母 42）同样取不到。这是一条 5 秒钟、零假设、零领域知识的检查。

  注意精度：只给 2 位有效数字（"72%"）时容差要放宽到该精度能覆盖的范围，否则会满屏
  假阳性；本器按报告精度自动定容差（见 `_tol_from_precision`）。

**判据二 YOUDEN_MISMATCH —— 约登指数 = 灵敏度 + 特异度 − 1**

**判据三 ACCURACY_INCONSISTENT —— 准确率 = 灵敏度×n₁/N + 特异度×n₀/N**

  实测：某篇训练集报灵敏度 80.00%、特异度 78.40%、准确率 **82.50%**，而由前两者与
  两组人数（35/102）算出来是 **78.81%**。

**判据四 AUC_CI_MISMATCH —— AUC ± 1.96·SE 必须等于印出的 95%CI**

  再加一条提示级的 AUC_CI_TOO_NARROW：用 Hanley-McNeil 公式由 AUC 与两组人数反推
  SE 的量级，若印出的 CI 宽度明显窄于它，说明 CI 不是按这个样本量算的。实测：某篇
  测试集只有 17 个事件，AUC 的 CI 宽度却与 35 个事件的训练集相当。

判据：
  RATE_UNREACHABLE     (Major) 比例 × 分母不是整数（按报告精度放宽后仍不可达）。
  YOUDEN_MISMATCH      (Major) 约登指数 ≠ 灵敏度 + 特异度 − 1。
  ACCURACY_INCONSISTENT(Major) 准确率与灵敏度/特异度/两组人数不相容。
  AUC_CI_MISMATCH      (Major) AUC ± z·SE ≠ 印出的 95%CI。
  AUC_CI_TOO_NARROW    (提示) CI 宽度远窄于 Hanley-McNeil 量级（仅在给了 --n1/--n0 时）。

保守设计（防过报）：
  · 判据一、三、四需要两组人数，用 --n1（阳性/事件组）与 --n0（阴性组）给；没给就
    只跑判据二，并在统计里说明跳过了哪些；
  · 所有比较都按**报告精度**定容差（"72%" 与 "72.00%" 的容差差两个数量级）；
  · 判据四的提示级下界留 0.75 倍余量，只抓量级差异。

输入
  --manuscript PATH   .md/.txt
  --n1 INT --n0 INT   阳性组 / 阴性组人数（判据一三四需要）
  --z FLOAT           默认 1.96
  --strict / --quiet / --json

用法：
  python scripts\\check_diagnostic_metrics.py --manuscript 文稿\\论著.md --n1 42 --n0 84 --strict
退出码：0 干净；--strict 下有 Major 为 1；输入/用法错为 2。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict

_FULL = str.maketrans("０１２３４５６７８９．－（）～，％",
                      "0123456789.-()~,%")


def _clean(s: str) -> str:
    return s.translate(_FULL).replace("\u00a0", " ").strip()


_NUM = r"[-+]?\d*\.?\d+"


def _f(s):
    if s is None:
        return None
    m = re.search(_NUM, _clean(s))
    return float(m.group(0)) if m else None


def _tol_from_precision(x: float) -> float:
    """由书面精度反推末位的一半。72 → 0.5；72.00 → 0.005。"""
    s = repr(float(x))
    if "." in s:
        frac = s.split(".")[1].rstrip("0")
        dec = len(frac)
    else:
        dec = 0
    return 0.5 * (10 ** (-dec))


def _tol_from_text(txt: str) -> float:
    """直接看原始文本的小数位（repr 会把 72.00 变成 72.0，必须看原串）。"""
    m = re.search(r"\d+\.(\d+)", _clean(txt))
    return 0.5 * (10 ** (-len(m.group(1)))) if m else 0.5


def _parse_ci(s):
    if s is None:
        return None
    body = _clean(s)
    mb = re.search(r"\(([^)]*)\)", body)
    if mb:
        body = mb.group(1)
    nums = re.findall(_NUM, body)
    if len(nums) >= 2:
        lo, hi = float(nums[-2]), float(nums[-1])
        if lo <= hi:
            return lo, hi
    return None


def hanley_mcneil_se(auc: float, n1: int, n0: int) -> float:
    q1 = auc / (2 - auc)
    q2 = 2 * auc * auc / (1 + auc)
    v = (auc * (1 - auc) + (n1 - 1) * (q1 - auc * auc)
         + (n0 - 1) * (q2 - auc * auc)) / (n1 * n0)
    return math.sqrt(max(v, 0.0))


HDR = {
    "auc":   re.compile(r"^\s*auc\s*$|曲线下面积", re.I),
    "ci":    re.compile(r"95\s*%?\s*(?:ci|可信区间|置信区间)", re.I),
    "se":    re.compile(r"^\s*(?:se|标准误)\s*$", re.I),
    "sens":  re.compile(r"灵敏度|敏感度|敏感性|sensitivity", re.I),
    "spec":  re.compile(r"特异度|特异性|specificity", re.I),
    "acc":   re.compile(r"准确率|准确度|accuracy", re.I),
    "youden": re.compile(r"约登|youden", re.I),
    "name":  re.compile(r"指标|因素|变量|项目|模型|test|index", re.I),
}


def _kind(h: str):
    h = _clean(h)
    if not h:
        return None
    if HDR["ci"].search(h):
        return "ci"
    for k in ("youden", "sens", "spec", "acc", "auc", "se"):
        if HDR[k].search(h):
            return k
    if HDR["name"].search(h):
        return "name"
    return None


@dataclass
class Row:
    table: int
    line: int
    name: str
    auc: float | None = None
    se: float | None = None
    lo: float | None = None
    hi: float | None = None
    sens: float | None = None
    sens_txt: str = ""
    spec: float | None = None
    spec_txt: str = ""
    acc: float | None = None
    acc_txt: str = ""
    youden: float | None = None
    youden_txt: str = ""


def parse(text: str) -> list[Row]:
    rows, lines, i, tno = [], text.splitlines(), 0, 0
    while i < len(lines):
        if lines[i].count("|") < 2 or i + 1 >= len(lines) \
                or not re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i + 1]):
            i += 1
            continue
        head = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        kinds = [_kind(h) for h in head]
        if not any(k in ("auc", "sens", "spec") for k in kinds):
            i += 1
            continue
        tno += 1
        j = i + 2
        while j < len(lines) and lines[j].count("|") >= 2:
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            r = Row(table=tno, line=j + 1, name=_clean(cells[0]) if cells else "?")
            for k, c in zip(kinds, cells):
                if k == "auc":
                    r.auc = _f(c)
                elif k == "se":
                    r.se = _f(c)
                elif k == "ci":
                    ci = _parse_ci(c)
                    if ci:
                        r.lo, r.hi = ci
                elif k == "sens":
                    r.sens, r.sens_txt = _f(c), c
                elif k == "spec":
                    r.spec, r.spec_txt = _f(c), c
                elif k == "acc":
                    r.acc, r.acc_txt = _f(c), c
                elif k == "youden":
                    r.youden, r.youden_txt = _f(c), c
            if any(v is not None for v in (r.auc, r.sens, r.spec)):
                rows.append(r)
            j += 1
        i = j
    return rows


@dataclass
class Finding:
    verdict: str
    severity: str
    table: int
    line: int
    name: str
    detail: str


def _as_frac(v):
    """把 76.19 或 0.7619 统一成 0~1 的比例。"""
    if v is None:
        return None
    return v / 100.0 if v > 1.0 else v


def analyse(rows, n1, n0, z):
    out, stat = [], {"rows": len(rows), "reach": 0, "youden": 0, "acc": 0, "auc_ci": 0}
    for r in rows:
        # --- 判据一：可达性 ---
        if n1 or n0:
            for val, txt, n, lbl in ((r.sens, r.sens_txt, n1, "灵敏度"),
                                     (r.spec, r.spec_txt, n0, "特异度")):
                if val is None or not n:
                    continue
                stat["reach"] += 1
                p = _as_frac(val)
                tol = _tol_from_text(txt) / (100.0 if val > 1.0 else 1.0)
                k = p * n
                # 报告精度允许的比例区间内，是否存在某个整数 k
                lo_k, hi_k = (p - tol) * n, (p + tol) * n
                if math.floor(hi_k + 1e-9) < math.ceil(lo_k - 1e-9):
                    near_lo, near_hi = math.floor(k), math.ceil(k)
                    out.append(Finding(
                        "RATE_UNREACHABLE", "Major", r.table, r.line, r.name,
                        f"{lbl} 报 {txt.strip()}，分母 n={n} → {k:.2f} 例，非整数；"
                        f"该分母能取到的最近值只有 {near_lo}/{n}={near_lo/n*100:.2f}% "
                        f"与 {near_hi}/{n}={near_hi/n*100:.2f}%"))

        # --- 判据二：约登指数 ---
        if r.sens is not None and r.spec is not None and r.youden is not None:
            stat["youden"] += 1
            calc = _as_frac(r.sens) + _as_frac(r.spec) - 1.0
            rep = _as_frac(r.youden) if r.youden > 1.0 else r.youden
            tol = (_tol_from_text(r.sens_txt) + _tol_from_text(r.spec_txt)) / \
                  (100.0 if r.sens > 1.0 else 1.0) + _tol_from_text(r.youden_txt)
            if abs(calc - rep) > tol + 1e-12:
                out.append(Finding(
                    "YOUDEN_MISMATCH", "Major", r.table, r.line, r.name,
                    f"灵敏度+特异度−1 = {calc:.4f}，而表中约登指数 = {rep}"))

        # --- 判据三：准确率 ---
        if r.sens is not None and r.spec is not None and r.acc is not None and n1 and n0:
            stat["acc"] += 1
            calc = (_as_frac(r.sens) * n1 + _as_frac(r.spec) * n0) / (n1 + n0)
            rep = _as_frac(r.acc)
            tol = (_tol_from_text(r.sens_txt) + _tol_from_text(r.spec_txt) +
                   _tol_from_text(r.acc_txt)) / (100.0 if r.acc > 1.0 else 1.0)
            if abs(calc - rep) > tol + 1e-12:
                out.append(Finding(
                    "ACCURACY_INCONSISTENT", "Major", r.table, r.line, r.name,
                    f"由灵敏度 {r.sens_txt.strip()}、特异度 {r.spec_txt.strip()} 与 "
                    f"n₁={n1}、n₀={n0} 算得准确率 = {calc*100:.2f}%，"
                    f"而表中 = {r.acc_txt.strip()}"))

        # --- 判据四：AUC ± z·SE == CI ---
        if r.auc is not None and r.se is not None and r.lo is not None:
            stat["auc_ci"] += 1
            clo, chi = r.auc - z * r.se, r.auc + z * r.se
            if abs(clo - r.lo) > 0.004 or abs(chi - r.hi) > 0.004:
                out.append(Finding(
                    "AUC_CI_MISMATCH", "Major", r.table, r.line, r.name,
                    f"AUC {r.auc} ± {z}×SE {r.se} = ({clo:.3f}, {chi:.3f})，"
                    f"而表中 95%CI = ({r.lo}, {r.hi})"))

        # --- 提示：CI 宽度与样本量是否相称 ---
        if r.auc is not None and r.lo is not None and n1 and n0 and 0 < r.auc < 1:
            hm = hanley_mcneil_se(r.auc, n1, n0)
            width_rep, width_hm = r.hi - r.lo, 2 * z * hm
            if width_rep < 0.75 * width_hm:
                out.append(Finding(
                    "AUC_CI_TOO_NARROW", "提示", r.table, r.line, r.name,
                    f"印出的 95%CI 宽度 {width_rep:.3f}，而按 Hanley-McNeil 由 "
                    f"AUC={r.auc}、n₁={n1}、n₀={n0} 反推的宽度约 {width_hm:.3f}"
                    f"（两法有出入，仅作量级判断）"))
    return out, stat


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="诊断效能表自检（可达性 / 约登 / 准确率 / AUC↔CI）")
    ap.add_argument("--manuscript", required=True)
    ap.add_argument("--n1", type=int, default=0, help="阳性（事件）组人数")
    ap.add_argument("--n0", type=int, default=0, help="阴性组人数")
    ap.add_argument("--z", type=float, default=1.96)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    try:
        with open(a.manuscript, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        print(f"[错误] 读不到稿件：{e}", file=sys.stderr)
        return 2

    rows = parse(text)
    findings, stat = analyse(rows, a.n1, a.n0, a.z)

    if a.json:
        print(json.dumps({"stat": stat, "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    elif not a.quiet:
        print(f"稿件：{a.manuscript}")
        print(f"识别到诊断效能行 {stat['rows']} 行；参与判定：可达性 {stat['reach']} 项、"
              f"约登 {stat['youden']} 行、准确率 {stat['acc']} 行、AUC↔CI {stat['auc_ci']} 行")
        if not (a.n1 and a.n0):
            print("  注：未给 --n1/--n0，可达性与准确率判据已跳过（约登与 AUC↔CI 不受影响）")
        if not findings:
            print("✓ 本清单内各判据均未发现不一致")
        else:
            print(f"\n发现 {len(findings)} 处：")
            for f in findings:
                print(f"  [{f.severity}] {f.verdict}  第{f.table}张表 第{f.line}行  {f.name}")
                print(f"      {f.detail}")

    if a.strict and any(f.severity == "Major" for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
