#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 本工作站原创（2026-08-09）；Python 3.13，纯标准库（自带不完全 beta，不依赖 scipy）。
# 确定性无随机性（无需 seed）。
"""相关系数表自检：|r| 与 P 的单调关系、由 (r, n) 反算 P、以及整行雷同。

为什么存在：相关分析表在中文论著里几乎不被复核，而它有一条**不需要任何原始数据、
甚至不需要知道样本量**就能验的铁律：

**判据一 R_P_NONMONOTONE —— 同一样本量下，|r| 越大 P 必然越小**

  这是数学关系（t = r√(n−2)/√(1−r²) 对 |r| 严格单调），不是经验规律。2026-08-09
  实测：某篇表 3 里 r=0.368 被赋 P<0.001，而 r=−0.687 反而被赋 P=0.002 —— **整张表的
  P 值顺序是反的**。这一条连样本量都不用给，是投稿前最省事的一次扫描。

**判据二 R_P_MISMATCH —— 给了 n 就能把 P 直接算出来**

  t = r√(n−2)/√(1−r²)，df = n−2。同篇实测 r=−0.687、n=60 → P < 0.0000001，而表中印 0.002。

**判据三 R_ROW_NEAR_DUPLICATE —— 不同自变量与同一批因变量的相关，不该整行雷同**

  同篇的 IMT / 狭窄程度 / Crouse 积分三行，14 个相关系数逐格差 ≤ 0.112，其中 5 格
  **完全相同**。三个测量内容不同的变量，与同一批结局的相关系数逐一重合，统计上极不
  可能，是整行复制的强信号。

判据：
  R_P_NONMONOTONE    (Major) 同表内 |r| 更大的那对却被赋了更大的 P。
  R_P_MISMATCH       (Major) 由 (r, n) 反算的 P 与报出的 P 不相容（需 --n）。
  R_ROW_NEAR_DUPLICATE (提示) 两行的 r 向量近乎逐格相同。

保守设计（防过报）：
  · 判据一要求 |r| 至少相差 --r-margin（默认 0.05）且 P 相差 1.5 倍以上才报，
    并且**假定同表各行样本量相同**——这一点写在输出里，由人确认；
  · "P<0.001" 一类按上界处理，不当成点值；
  · 判据二按报告精度定容差，且 P 报在下限时只要反算值不高于下限即视为相容；
  · 判据三要求两行至少 6 个可比格子、且逐格差都 ≤ --dup-tol（默认 0.02）才提示。

输入
  --manuscript PATH   .md/.txt
  --n INT             相关分析的样本量（判据二需要；不给则跳过）
  --r-margin FLOAT    默认 0.05
  --dup-tol FLOAT     默认 0.02
  --strict / --quiet / --json

用法：
  python scripts\\check_correlation_table.py --manuscript 文稿\\论著.md --n 60 --strict
退出码：0 干净；--strict 下有 Major 为 1；输入/用法错为 2。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict

# --------------------------------------------------- 纯标准库的 t 分布尾概率

def _betacf(a: float, b: float, x: float) -> float:
    """不完全 beta 的连分式（Numerical Recipes 6.4）。"""
    MAXIT, EPS, FPMIN = 200, 3.0e-12, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 beta I_x(a,b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1.0 - x))
    bt = math.exp(lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: int) -> float:
    """双侧 t 检验 p 值，纯标准库。"""
    if df <= 0:
        return float("nan")
    return _betai(0.5 * df, 0.5, df / (df + t * t))


def p_from_r(r: float, n: int) -> float:
    """由 Pearson/Spearman 的 r 与 n 反算双侧 P。"""
    if n <= 2 or abs(r) >= 1.0:
        return float("nan")
    t = abs(r) * math.sqrt(n - 2) / math.sqrt(1.0 - r * r)
    return t_two_sided_p(t, n - 2)


# --------------------------------------------------- 解析

_FULL = str.maketrans("０１２３４５６７８９．－（）＜＞≤≥，％",
                      "0123456789.-()<>≤≥,%")


def _clean(s: str) -> str:
    return s.translate(_FULL).replace("\u00a0", " ").strip()


_NUM = r"[-+]?\d*\.?\d+"

R_HDR = re.compile(r"^\s*(?:r\s*值?|rs\s*值?|相关系数|r)\s*$", re.I)
P_HDR = re.compile(r"^\s*(?:p\s*值?|p[-\s]?value|sig\.?)\s*$", re.I)
# 复合表头："IMT r值" / "狭窄程度 P值"
R_HDR2 = re.compile(r"(?:^|\s)(?:r\s*值|rs\s*值|相关系数)\s*$", re.I)
P_HDR2 = re.compile(r"(?:^|\s)(?:p\s*值)\s*$", re.I)


def _f(s):
    m = re.search(_NUM, _clean(s))
    return float(m.group(0)) if m else None


def _parse_p(s):
    c = _clean(s)
    if not re.search(r"\d", c):
        return None, False
    return _f(c), bool(re.search(r"[<>≤≥]", c))


@dataclass
class Pair:
    table: int
    line: int
    row: str
    col: str
    r: float
    p: float | None
    p_bound: bool


@dataclass
class Finding:
    verdict: str
    severity: str
    table: int
    line: int
    name: str
    detail: str


def parse(text: str):
    """返回 (pairs, rowvecs)：rowvecs[table][rowname] = [r,...] 供查重。"""
    pairs, rowvecs = [], {}
    lines, i, tno = text.splitlines(), 0, 0
    while i < len(lines):
        if lines[i].count("|") < 2 or i + 1 >= len(lines) \
                or not re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i + 1]):
            i += 1
            continue
        head = [_clean(c) for c in lines[i].strip().strip("|").split("|")]
        kinds = []
        for h in head:
            if R_HDR.match(h) or R_HDR2.search(h):
                kinds.append("r")
            elif P_HDR.match(h) or P_HDR2.search(h):
                kinds.append("p")
            else:
                kinds.append(None)
        if "r" not in kinds:
            i += 1
            continue
        tno += 1
        rowvecs.setdefault(tno, {})
        j = i + 2
        while j < len(lines) and lines[j].count("|") >= 2:
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            rname = _clean(cells[0]) if cells else "?"
            vec = []
            for ci, (k, c) in enumerate(zip(kinds, cells)):
                if k != "r":
                    continue
                rv = _f(c)
                if rv is None or abs(rv) > 1.0:
                    continue
                vec.append(rv)
                pv, pb = (None, False)
                # 就近取右侧第一个 p 列
                for cj in range(ci + 1, len(cells)):
                    if kinds[cj] == "p":
                        pv, pb = _parse_p(cells[cj])
                        break
                    if kinds[cj] == "r":
                        break
                pairs.append(Pair(tno, j + 1, rname, head[ci], rv, pv, pb))
            if vec:
                rowvecs[tno][rname] = vec
            j += 1
        i = j
    return pairs, rowvecs


def _tol_from_text_p(p: float) -> float:
    s = repr(float(p))
    dec = len(s.split(".")[1].rstrip("0")) if "." in s else 0
    return 0.5 * (10 ** (-dec))


def analyse(pairs, rowvecs, n, r_margin, dup_tol):
    out, stat = [], {"pairs": len(pairs), "with_p": 0, "checked_recompute": 0,
                     "mono_compared": 0, "dup_compared": 0}

    # --- 判据二：由 (r, n) 反算 P ---
    if n:
        for pr in pairs:
            if pr.p is None:
                continue
            stat["checked_recompute"] += 1
            calc = p_from_r(pr.r, n)
            if math.isnan(calc):
                continue
            if pr.p_bound:
                if calc <= pr.p + 1e-12:
                    continue
                out.append(Finding(
                    "R_P_MISMATCH", "Major", pr.table, pr.line, f"{pr.row} × {pr.col}",
                    f"r={pr.r}、n={n} → 反算 P={calc:.3g}，而表中报 <{pr.p}（反算值更大，不相容）"))
            else:
                tol = _tol_from_text_p(pr.p)
                if not (pr.p - tol - 1e-12 <= calc <= pr.p + tol + 1e-12):
                    extra = "；**跨过 0.05，显著性结论会翻**" if (calc < 0.05) != (pr.p < 0.05) else ""
                    out.append(Finding(
                        "R_P_MISMATCH", "Major", pr.table, pr.line, f"{pr.row} × {pr.col}",
                        f"r={pr.r}、n={n} → t={abs(pr.r)*math.sqrt(n-2)/math.sqrt(1-pr.r**2):.3f}、"
                        f"反算 P={calc:.3g}，而表中 P={pr.p}{extra}"))

    # --- 判据一：|r| 与 P 的单调性（同表内，假定同 n）---
    bytab = {}
    for pr in pairs:
        if pr.p is not None:
            bytab.setdefault(pr.table, []).append(pr)
            stat["with_p"] += 1
    for tno, lst in bytab.items():
        for i in range(len(lst)):
            for j in range(len(lst)):
                if i == j:
                    continue
                A, B = lst[i], lst[j]
                if abs(A.r) <= abs(B.r) + r_margin:
                    continue
                stat["mono_compared"] += 1
                # A 的 |r| 明显更大 → A 的 P 应当更小
                pa = A.p          # A 为界值时取其上界，仍可比
                pb = B.p
                if pa > pb * 1.5 and not (A.p_bound and pa <= pb):
                    out.append(Finding(
                        "R_P_NONMONOTONE", "Major", tno, A.line,
                        f"{A.row} × {A.col}  vs  {B.row} × {B.col}",
                        f"|r|={abs(A.r)} > |r|={abs(B.r)}，但 P={'<' if A.p_bound else ''}{pa}"
                        f" > P={'<' if B.p_bound else ''}{pb}。同一样本量下 |r| 越大 P 必然越小"
                        f"（若两者样本量不同，请在表注中写明）"))
        # 每张表只报最严重的一条，避免 O(n²) 刷屏
        keep, seen = [], set()
        for f in out:
            if f.verdict == "R_P_NONMONOTONE" and f.table == tno:
                if tno in seen:
                    continue
                seen.add(tno)
            keep.append(f)
        out = keep

    # --- 判据三：整行 / 整列雷同 ---
    # 两个方向都要查：自变量既可能排成行（每行一个自变量 × 多个结局），
    # 也可能排成列（每列一个自变量，行是结局）。实测那张表正是后者，
    # 只查行方向会完全漏掉。
    def _dup_scan(tno, vecs, axis_label):
        names = list(vecs)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = vecs[names[i]], vecs[names[j]]
                m = min(len(a), len(b))
                if m < 6:
                    continue
                stat["dup_compared"] += 1
                diffs = [abs(x - y) for x, y in zip(a[:m], b[:m])]
                if max(diffs) <= dup_tol:
                    exact = sum(1 for d in diffs if d == 0)
                    out.append(Finding(
                        "R_ROW_NEAR_DUPLICATE", "提示", tno, 0,
                        f"{names[i]} 与 {names[j]}（按{axis_label}比）",
                        f"两{axis_label} {m} 个相关系数逐格最大差仅 {max(diffs):.3f}"
                        f"（其中 {exact} 格完全相同）。不同自变量与同一批结局的相关"
                        f"逐一重合，是整{axis_label}复制的信号，建议回原始输出核对"))

    for tno, rows in rowvecs.items():
        _dup_scan(tno, rows, "行")
        # 转置成列向量再查一遍
        cols: dict = {}
        for pr in pairs:
            if pr.table == tno:
                cols.setdefault(pr.col, []).append(pr.r)
        _dup_scan(tno, cols, "列")
    return out, stat


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="相关系数表自检（|r|↔P 单调性 / r,n→P / 整行雷同）")
    ap.add_argument("--manuscript", required=True)
    ap.add_argument("--n", type=int, default=0, help="相关分析的样本量")
    ap.add_argument("--r-margin", type=float, default=0.05)
    ap.add_argument("--dup-tol", type=float, default=0.02)
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

    pairs, rowvecs = parse(text)
    findings, stat = analyse(pairs, rowvecs, a.n, a.r_margin, a.dup_tol)

    if a.json:
        print(json.dumps({"stat": stat, "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    elif not a.quiet:
        print(f"稿件：{a.manuscript}")
        print(f"识别到相关系数 {stat['pairs']} 个（其中带 P 值 {stat['with_p']} 个）；"
              f"反算 P {stat['checked_recompute']} 个、单调性比较 {stat['mono_compared']} 对、"
              f"整行查重 {stat['dup_compared']} 对")
        if not a.n:
            print("  注：未给 --n，由 (r,n) 反算 P 的判据已跳过（单调性与查重不受影响）")
        if not findings:
            print("✓ 本清单内各判据均未发现不一致")
        else:
            print(f"\n发现 {len(findings)} 处：")
            for f in findings:
                loc = f"第{f.line}行" if f.line else "整表"
                print(f"  [{f.severity}] {f.verdict}  第{f.table}张表 {loc}  {f.name}")
                print(f"      {f.detail}")

    if a.strict and any(f.severity == "Major" for f in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
