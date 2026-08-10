#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计量↔p 值一致性反算（statcheck 思路）+ 可选 GRIM 均数可行性。

投稿前确定性、离线、纯标准库自检。灵感来自 statcheck（Nuijten 等）与 GRIM 检验
（Brown & Heathers），但为中文医学论著 + 英文 SCI 重写，且**不依赖 scipy**——t / F /
χ² 的分布函数由本文件用不完全 beta / gamma 函数（Numerical Recipes 算法）实现。

它抓的是 CLAUDE.md 陷阱清单 #42/#45/#46 那一类：**报告的 p 与其检验统计量+自由度对不上**
（复制粘贴错、转录错、或数字根本没指回真实运行）。

检查项：
  P_RECOMPUTE (Major)  报告的 p 与由统计量+自由度反算出的 p 不一致（超出报告精度的舍入）。
  P_DECISION  (Major)  更严重的一种：反算 p 与报告 p 落在显著性阈值（默认 0.05）两侧——
                       即"显著/不显著"的结论会翻。statcheck 称之为 decision error。
  P_ONE_TAILED(提示)   两尾对不上、但按单尾（p/2）能对上——可能作者用了单尾检验，核对声明。
  GRIM_IMPOSSIBLE(提示) 仅 --grim：给定整数样本量 N，报告的均数在数学上不可能由 N 个整数
                       值平均得到。**仅适用于整数型变量**（计数 / 整数评分 / 整岁），
                       连续测量（BMI、LVEF 等）不适用——故为提示级，需人工确认变量类型。

支持的统计量写法（大小写、全角括号/逗号、前导小数点 .03、P/p/P值 均可）：
  t(df)=v, p=...        F(df1,df2)=v, p=...      χ²(df)=v / chi2(df)=v, p=...
  r(df)=v, p=...        z=v, p=...（z 无需自由度）
比较符支持 = / < / > / ≤ / ≥（含全角）。**缺自由度**的写法（如中文常见 "t=2.34, P<0.05"
不写 df）无法反算，不被抽取、也不误报；输出里的"跳过"计数指"识别到统计量但邻近未找到 p"。

输入
  --manuscript PATH   .md/.txt（docx 请先转文本；本检测器针对可读文本）
  --alpha FLOAT       决策阈值，默认 0.05
  --grim              额外跑 GRIM（默认关闭；仅整数型变量有意义）
  --out PATH / --strict / --quiet   同本技能其它脚本

退出码：0 干净（或仅提示）；1 有 Major 且 --strict；2 输入/用法错误。
仅用标准库（math / re / json / argparse / statistics / pathlib）。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from statistics import NormalDist

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================ 特殊函数（纯标准库实现分布 CDF）====================

def _gammln(x: float) -> float:
    cof = [76.18009172947146, -86.50532032941677, 24.01409824083091,
           -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5]
    y = x
    tmp = x + 5.5
    tmp -= (x + 0.5) * math.log(tmp)
    ser = 1.000000000190015
    for c in cof:
        y += 1.0
        ser += c / y
    return -tmp + math.log(2.5066282746310005 * ser / x)


def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 300, 3.0e-14, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
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
    """正则化不完全 beta 函数 I_x(a,b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(_gammln(a + b) - _gammln(a) - _gammln(b)
                  + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _gser(a: float, x: float) -> float:
    EPS = 3.0e-14
    if x <= 0.0:
        return 0.0
    ap = a
    total = 1.0 / a
    dl = total
    for _ in range(500):
        ap += 1.0
        dl *= x / ap
        total += dl
        if abs(dl) < abs(total) * EPS:
            break
    return total * math.exp(-x + a * math.log(x) - _gammln(a))


def _gcf(a: float, x: float) -> float:
    FPMIN, EPS, MAXIT = 1.0e-300, 3.0e-14, 500
    b = x + 1.0 - a
    c = 1.0 / FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, MAXIT + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < FPMIN:
            d = FPMIN
        c = b + an / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return math.exp(-x + a * math.log(x) - _gammln(a)) * h


def _gammq(a: float, x: float) -> float:
    """上不完全 gamma Q(a,x)=1-P(a,x)。"""
    if x < 0.0 or a <= 0.0:
        return float("nan")
    if x < a + 1.0:
        return 1.0 - _gser(a, x)
    return _gcf(a, x)


# ------------------------------ 两尾 p 值 --------------------------------------

def p_from_t(t: float, df: float) -> float:
    if df <= 0:
        return float("nan")
    return _betai(df / 2.0, 0.5, df / (df + t * t))


def p_from_f(f: float, df1: float, df2: float) -> float:
    if df1 <= 0 or df2 <= 0 or f < 0:
        return float("nan")
    return _betai(df2 / 2.0, df1 / 2.0, df2 / (df2 + df1 * f))


def p_from_chisq(x2: float, df: float) -> float:
    if df <= 0 or x2 < 0:
        return float("nan")
    return _gammq(df / 2.0, x2 / 2.0)


def p_from_z(z: float) -> float:
    return 2.0 * (1.0 - NormalDist().cdf(abs(z)))


def p_from_r(r: float, df: float) -> float:
    if df <= 0 or abs(r) >= 1.0:
        return float("nan")
    t = abs(r) * math.sqrt(df / (1.0 - r * r))
    return p_from_t(t, df)


# ============================ 抽取（正则）======================================

NUM = r"[-+]?\d*\.?\d+"
# 比较符（含全角）→ 归一
CMP_MAP = {"＜": "<", "＞": ">", "≤": "<=", "≥": ">=", "⩽": "<=", "⩾": ">=",
           "<=": "<=", ">=": ">=", "=": "=", "<": "<", ">": ">", "：": "=", ":": "="}
CMP_ALT = r"(?:<=|>=|＜|＞|≤|≥|⩽|⩾|=|<|>)"

# p 值子句：p / P / P值 / p-value + 比较符 + 数字（允许 .001）
P_CLAUSE = re.compile(
    r"[pP]\s*(?:值|[- ]?value)?\s*(" + CMP_ALT + r")\s*(" + NUM + r")")

# 统计量锚点
T_RE = re.compile(r"\bt\s*[\(（]\s*(" + NUM + r")\s*[\)）]\s*=\s*(" + NUM + r")", re.I)
F_RE = re.compile(r"\bF\s*[\(（]\s*(" + NUM + r")\s*[,，]\s*(" + NUM + r")\s*[\)）]\s*=\s*(" + NUM + r")", re.I)
CHI_RE = re.compile(
    r"(?:χ\s*2|χ²|chi[-\s]?square|chisq|卡方)\s*[\(（]\s*(" + NUM + r")\s*[\)）]\s*=\s*(" + NUM + r")", re.I)
R_RE = re.compile(r"\br\s*[\(（]\s*(" + NUM + r")\s*[\)）]\s*=\s*(" + NUM + r")", re.I)
Z_RE = re.compile(r"\bz\s*=\s*(" + NUM + r")", re.I)

LOOKAHEAD = 60  # 统计量后多少字符内找 p


def _find_p_after(text: str, end: int):
    """在锚点之后 LOOKAHEAD 字符内找 p 子句，返回 (cmp, value, raw) 或 None。"""
    window = text[end:end + LOOKAHEAD]
    m = P_CLAUSE.search(window)
    if not m:
        return None
    cmp = CMP_MAP.get(m.group(1), m.group(1))
    try:
        val = float(m.group(2))
    except ValueError:
        return None
    return cmp, val, m.group(0)


def _reported_decimals(raw_num: str) -> int:
    if "." in raw_num:
        return len(raw_num.split(".", 1)[1])
    return 3


# ============================ 一致性判定 =======================================

def _consistent(computed: float, cmp: str, reported: float, dec: int) -> bool:
    """报告 p 与反算 p 是否一致（按报告精度）。"""
    if cmp == "=":
        return round(computed, dec) == round(reported, dec)
    tol = 0.5 * 10 ** (-dec)
    if cmp == "<":
        return computed < reported + tol
    if cmp == "<=":
        return computed <= reported + tol
    if cmp == ">":
        return computed > reported - tol
    if cmp == ">=":
        return computed >= reported - tol
    return True


def _straddle(computed: float, cmp: str, reported: float, alpha: float) -> bool:
    """反算与报告是否落在 alpha 两侧（结论会翻）。"""
    rep_sig = (reported < alpha) if cmp in ("=", "<", "<=") else (reported <= alpha)
    comp_sig = computed < alpha
    return rep_sig != comp_sig


def _evaluate(kind: str, stat: float, dfs, computed: float,
              cmp: str, reported: float, dec: float, alpha: float, where: str):
    if computed != computed:  # nan
        return None
    if _consistent(computed, cmp, reported, dec):
        return None
    # 单尾兜底：两尾对不上，单尾（半）能对上 → 提示而非报错
    if _consistent(computed / 2.0, cmp, reported, dec):
        return {
            "verdict": "P_ONE_TAILED", "severity": "提示",
            "detail": (f"{kind} 反算两尾 p≈{computed:.4g} 与报告 p{cmp}{reported:g} 对不上，"
                       f"但单尾 p≈{computed/2:.4g} 能对上——核对是否单尾检验并在方法中声明"),
            "where": where,
        }
    decision = _straddle(computed, cmp, reported, alpha)
    near = abs(computed - reported) <= 10 ** (-dec)  # 仅差最后一位（舍入方向不同）
    if decision:
        return {
            "verdict": "P_DECISION", "severity": "Major",
            "detail": (f"{kind} 反算 p≈{computed:.4g}，但报告 p{cmp}{reported:g}"
                       f"——且跨越显著性阈值 α={alpha:g}，'显著/不显著'的结论会翻"),
            "where": where,
        }
    if near:
        return {
            "verdict": "P_ROUNDING", "severity": "提示",
            "detail": (f"{kind} 反算 p≈{computed:.4g} 与报告 p{cmp}{reported:g} 仅差最后一位"
                       f"（舍入方向不同，结论不受影响）——统一舍入规则即可"),
            "where": where,
        }
    return {
        "verdict": "P_RECOMPUTE", "severity": "Major",
        "detail": (f"{kind} 反算 p≈{computed:.4g}，但报告 p{cmp}{reported:g}"
                   f"（差异超出报告精度，非单纯舍入）——核对统计量、自由度或 p 是否转录错"),
        "where": where,
    }


def check_pvalues(text: str, alpha: float):
    claims, n_checked, n_skipped = [], 0, 0

    def handle(anchor_end: int, kind: str, computed_fn, stat, dfs, snippet: str):
        nonlocal n_checked, n_skipped
        pinfo = _find_p_after(text, anchor_end)
        if not pinfo:
            n_skipped += 1
            return
        cmp, reported, praw = pinfo
        dec = _reported_decimals(re.search(NUM, praw.split(cmp)[-1]).group(0)
                                 if cmp in praw else praw)
        computed = computed_fn()
        n_checked += 1
        c = _evaluate(kind, stat, dfs, computed, cmp, reported, dec, alpha,
                      where=snippet.strip()[:80])
        if c:
            claims.append(c)

    for m in T_RE.finditer(text):
        df = float(m.group(1)); t = float(m.group(2))
        handle(m.end(), "t", lambda t=t, df=df: p_from_t(t, df), t, (df,), m.group(0))
    for m in F_RE.finditer(text):
        d1 = float(m.group(1)); d2 = float(m.group(2)); f = float(m.group(3))
        handle(m.end(), "F", lambda f=f, d1=d1, d2=d2: p_from_f(f, d1, d2), f, (d1, d2), m.group(0))
    for m in CHI_RE.finditer(text):
        df = float(m.group(1)); x2 = float(m.group(2))
        handle(m.end(), "χ²", lambda x2=x2, df=df: p_from_chisq(x2, df), x2, (df,), m.group(0))
    for m in R_RE.finditer(text):
        df = float(m.group(1)); r = float(m.group(2))
        handle(m.end(), "r", lambda r=r, df=df: p_from_r(r, df), r, (df,), m.group(0))
    for m in Z_RE.finditer(text):
        z = float(m.group(1))
        handle(m.end(), "z", lambda z=z: p_from_z(z), z, (), m.group(0))

    return claims, n_checked, n_skipped


# ============================ GRIM =============================================

MEAN_N_RE = re.compile(
    r"(?:均\s*数|均\s*值|平均|mean|M)\s*[=:：]?\s*(" + NUM + r")"
    r"[^\n。.;；]{0,60}?"
    r"(?:n|N|例数|样本量)\s*[=:：]?\s*(\d{1,6})", re.I)


def _grim_possible(mean: float, n: int, dec: int) -> bool:
    gran = 10 ** (-dec)
    target = round(mean * n)
    for s in (target - 1, target, target + 1):
        if abs(round(s / n, dec) - round(mean, dec)) < gran / 2:
            return True
    return False


def check_grim(text: str):
    claims = []
    for m in MEAN_N_RE.finditer(text):
        mraw = re.search(NUM, m.group(1)).group(0)
        if "." not in mraw:
            continue  # 整数均数无判别力
        mean = float(mraw); n = int(m.group(2))
        dec = _reported_decimals(mraw)
        if n >= 10 ** dec or n <= 0:
            continue  # N 太大时 GRIM 无判别力
        if not _grim_possible(mean, n, dec):
            claims.append({
                "verdict": "GRIM_IMPOSSIBLE", "severity": "提示",
                "detail": (f"均数 {mean} 在 n={n} 下不可能由整数值平均得到（GRIM）——"
                           f"若该变量为整数型（计数/评分/整岁）则为报告错误；连续变量请忽略"),
                "where": m.group(0).strip()[:80],
            })
    return claims


# ============================ 驱动 =============================================

def analyze(manuscript: str, alpha: float, grim: bool) -> dict:
    p = Path(manuscript)
    if not p.is_file():
        sys.stderr.write(f"ERROR: 找不到稿件: {manuscript}\n")
        sys.exit(2)
    text = p.read_text(encoding="utf-8", errors="replace")
    claims, n_checked, n_skipped = check_pvalues(text, alpha)
    if grim:
        claims += check_grim(text)
    n_major = sum(1 for c in claims if c["severity"] == "Major")
    return {
        "manuscript": str(p),
        "alpha": alpha,
        "n_pvalues_checked": n_checked,
        "n_pvalues_skipped_no_df": n_skipped,
        "claims": claims,
        "summary": {"n_claims": len(claims), "n_major": n_major,
                    "verdict": "MAJOR_CANDIDATE" if n_major else "OK"},
    }


def render(result: dict) -> str:
    lines = ["| 检查 | 级别 | 说明 |", "|---|---|---|"]
    for c in result["claims"]:
        lines.append(f"| {c['verdict']} | {c['severity']} | {c['detail']} |")
    if len(lines) == 2:
        lines.append("| （无） | — | 所抽取的统计量与 p 值一致 |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="统计量↔p 值一致性反算（statcheck 思路）+ 可选 GRIM")
    ap.add_argument("--manuscript", required=True, help="稿件 .md/.txt")
    ap.add_argument("--alpha", type=float, default=0.05, help="决策阈值（默认 0.05）")
    ap.add_argument("--grim", action="store_true", help="额外跑 GRIM 均数可行性（仅整数型变量有意义）")
    ap.add_argument("--out", help="写出 JSON 工件路径")
    ap.add_argument("--strict", action="store_true", help="有 Major 时退出码置 1")
    ap.add_argument("--quiet", action="store_true", help="不打印表格")
    args = ap.parse_args()

    result = analyze(args.manuscript, args.alpha, args.grim)

    if not args.quiet:
        print("=" * 52)
        print(" 统计量 ↔ p 值一致性（statcheck 思路）")
        print("=" * 52)
        print(render(result))
        print()
        s = result["summary"]
        print(f"抽取核对 {result['n_pvalues_checked']} 处；"
              f"缺自由度跳过 {result['n_pvalues_skipped_no_df']} 处。")
        if s["n_major"]:
            print(f"MAJOR：{s['n_major']} 处 p 值与统计量对不上，须逐一核对（多为复制粘贴/转录错）。")
        else:
            print("OK：所抽取的统计量与 p 值一致（缺自由度者未检，见上）。")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        if not args.quiet:
            print(f"\nwrote {args.out}")

    return 1 if (args.strict and result["summary"]["n_major"]) else 0


if __name__ == "__main__":
    sys.exit(main())
