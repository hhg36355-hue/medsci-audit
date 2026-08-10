#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 本工作站原创（2026-08-09）；Python 3.13，纯标准库，确定性无随机性（无需 seed）。
"""回归表六列恒等式自检（OR/HR 表的 β / SE / Wald / OR / 95%CI / P 必须互相反推）。

为什么存在：一张 Logistic / Cox 结果表里，六列不是六个独立的数，而是由 β 与 SE 两个
数完全决定的：

    OR = exp(β)            Wald = (β/SE)²            95%CI = exp(β ± 1.96·SE)

任何一列被单独填错，都能在不查原始数据的前提下被抓出来。这类错误在中文期刊里高发，
且**表面上非常整齐**——2026-08-09 实测的一批 12 篇中：

  · 某篇 17 行的表 Wald 列 17/17 全对、CI 列 12/17 对，**OR 列只有 3 行对**；
  · 另一篇模型 5 的 CI 上限表内印 2.548、正文印 3.548，复算为 3.549（表格错）；
  · 第三篇的 OR/CI 配套无误，**只有 P 值**与自己的 CI 对不上（CI 推出 0.033，印 0.008）。

**定位错列的关键判据**（本检测器的核心，其他工具没有）：算「报出 CI 的几何中点」
`sqrt(lo·hi)`。若它等于 exp(β) 而不等于该行印出的 OR，就说明 β/SE/CI 是一套自洽的
输出、**OR 列是单独填错的**；反之若它等于印出的 OR 而不等于 exp(β)，则是 β 列有问题。
没有这一步，只能报"这一行不自洽"，无法指出改哪一列。

与既有检测器的分工：`check_stat_recompute` 吃「统计量+自由度→p」，`check_reported_p_from_counts`
吃「四格表计数→p」，两者都**不看 β/SE/OR/CI 之间的关系**；本器专吃这一层，互补不重叠。

判据（Major 全部会让 --strict 退出 1）：
  OR_NOT_EXP_BETA    (Major) OR ≠ exp(β)。附「报出 CI 的几何中点」以定位是哪一列错。
  OR_BETA_SIGN       (Major) β 与 ln(OR) 异号（β>0 却报 OR<1，或反之）。最省事的一条。
  WALD_MISMATCH      (Major) Wald ≠ (β/SE)²。容差按 SE 的有效位数自动放宽。
  CI_NOT_FROM_SE     (Major) 95%CI ≠ exp(β ± 1.96·SE)。
  CI_P_MISMATCH      (Major) 由 CI 反推的 P 与报出的 P 差一个数量级以上。
  CI_ASYMMETRIC      (Minor) 无 β/SE 时的兜底：报出 CI 的几何中点明显偏离报出的 OR。

保守设计（防过报）：
  · SE 只给 2~3 位小数时，Wald 的容差按该精度能造成的最大偏差自动放宽（本批实测中
    β=0.016/SE=0.007 这类行不会误报）；
  · 一行至少要能取到 (β,SE) 或 (OR,CI) 之一的完整组合才参与判定，缺列的行只计入「跳过」；
  · 常数项 / 截距行照常参与（本批实测有一篇正是常数项的 P 印错）。

输入
  --manuscript PATH   .md/.txt（docx 请先转文本）
  --z FLOAT           构造 CI 用的正态分位数，默认 1.96
  --strict            有 Major 时退出 1
  --quiet / --json

用法：
  python scripts\\check_regression_table.py --manuscript 文稿\\论著.md --strict
  python scripts\\check_regression_table.py --manuscript 文稿\\论著.md --json
退出码：0 干净；--strict 下有 Major 为 1；输入/用法错为 2。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict, field

# ---------------------------------------------------------------- 数值与分布

def _norm_sf(z: float) -> float:
    """标准正态上尾概率 P(Z > z)，纯标准库。"""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def chi2_1df_sf(x: float) -> float:
    """自由度 1 的卡方上尾概率 P(X > x) = erfc(sqrt(x/2))。Wald 检验用。"""
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2.0))


def two_sided_p_from_z(z: float) -> float:
    return 2.0 * _norm_sf(abs(z))


# 全角 → 半角，并统一各种区间分隔符
_FULL = str.maketrans("０１２３４５６７８９．－（）～，％＜＞＝",
                      "0123456789.-()~,%<>=")
_SEPS = re.compile(r"\s*(?:~|～|—|–|-{1,2}|,|，|to|至)\s*")


def _clean(s: str) -> str:
    return s.translate(_FULL).replace("\u00a0", " ").strip()


_NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"


def _f(s: str):
    """把一个单元格解析成 float；取不到返回 None。"""
    if s is None:
        return None
    s = _clean(s)
    m = re.search(_NUM, s)
    return float(m.group(0)) if m else None


def _parse_ci(s: str):
    """从单元格里取 (lo, hi)。支持 '1.846~2.239'、'(1.846, 2.239)'、'2.033（1.846~2.239）'。"""
    if s is None:
        return None
    s = _clean(s)
    # 优先取括号内的内容（OR 与 CI 同格的情形）
    mb = re.search(r"\(([^)]*)\)", s)
    body = mb.group(1) if mb else s
    nums = re.findall(_NUM, body)
    if len(nums) >= 2:
        lo, hi = float(nums[-2]), float(nums[-1])
        if lo <= hi:
            return lo, hi
    return None


def _parse_p(s: str):
    """返回 (p_value, is_bound)。'<0.001' 记为 (0.001, True)。"""
    if s is None:
        return None, False
    s = _clean(s)
    if not re.search(r"\d", s):
        return None, False
    bound = ("<" in s) or (">" in s) or ("≤" in s) or ("≥" in s)
    v = _f(s)
    return v, bound


# ---------------------------------------------------------------- 表头识别

HDR = {
    "beta":  re.compile(r"^\s*(?:β|beta|b|回归系数|系数|偏回归系数|coef\w*)\s*(?:值)?\s*$", re.I),
    "se":    re.compile(r"^\s*(?:se|s\.?e\.?|标准误|标准误差|std\.?\s*err\w*)\s*(?:值)?\s*$", re.I),
    "wald":  re.compile(r"(?:wald)", re.I),
    "or":    re.compile(r"^\s*(?:or|hr|rr|比值比|风险比|优势比)\s*(?:值)?\s*$", re.I),
    "orci":  re.compile(r"(?:or|hr|rr).*(?:95\s*%?\s*(?:ci|可信区间|置信区间))", re.I),
    "ci":    re.compile(r"(?:95\s*%?\s*(?:ci|可信区间|置信区间))", re.I),
    "p":     re.compile(r"^\s*(?:p|p\s*值|p[-\s]?value|sig\.?)\s*$", re.I),
    "var":   re.compile(r"^\s*(?:变量|因素|指标|项目|自变量|影响因素|组别|variable|factor|predictor)\s*$", re.I),
}


def _col_kind(h: str):
    h = _clean(h).strip()
    if not h:
        return None
    if HDR["orci"].search(h):
        return "orci"
    if HDR["wald"].search(h):
        return "wald"
    if HDR["ci"].search(h):
        return "ci"
    for k in ("beta", "se", "or", "p", "var"):
        if HDR[k].match(h):
            return k
    return None


# ---------------------------------------------------------------- 表解析

@dataclass
class Row:
    table: int
    line: int
    name: str
    beta: float | None = None
    se: float | None = None
    wald: float | None = None
    orv: float | None = None
    lo: float | None = None
    hi: float | None = None
    p: float | None = None
    p_bound: bool = False


def parse_pipe_tables(text: str):
    """抽取 GFM 管道表里含回归列的行。"""
    rows: list[Row] = []
    lines = text.splitlines()
    i, tno = 0, 0
    while i < len(lines):
        if lines[i].count("|") < 2:
            i += 1
            continue
        # 找表头 + 分隔行
        head = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if i + 1 >= len(lines) or not re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i + 1]):
            i += 1
            continue
        kinds = [_col_kind(h) for h in head]
        if not (("beta" in kinds and "se" in kinds) or
                ("or" in kinds or "orci" in kinds)):
            i += 1
            continue
        tno += 1
        j = i + 2
        while j < len(lines) and lines[j].count("|") >= 2:
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            r = Row(table=tno, line=j + 1, name="")
            for k, cell in zip(kinds, cells):
                if k == "var" and not r.name:
                    r.name = _clean(cell)[:40]
                elif k == "beta":
                    r.beta = _f(cell)
                elif k == "se":
                    r.se = _f(cell)
                elif k == "wald":
                    r.wald = _f(cell)
                elif k == "or":
                    r.orv = _f(cell)
                elif k == "ci":
                    ci = _parse_ci(cell)
                    if ci:
                        r.lo, r.hi = ci
                elif k == "orci":
                    r.orv = _f(cell)
                    ci = _parse_ci(cell)
                    if ci:
                        r.lo, r.hi = ci
                elif k == "p":
                    r.p, r.p_bound = _parse_p(cell)
            if not r.name:
                r.name = _clean(cells[0])[:40] if cells else "?"
            if any(v is not None for v in (r.beta, r.se, r.orv, r.lo)):
                rows.append(r)
            j += 1
        i = j
    return rows


# ---------------------------------------------------------------- 判据

@dataclass
class Finding:
    verdict: str
    severity: str
    table: int
    line: int
    name: str
    detail: str


def _tol_from_precision(x: float) -> float:
    """由一个数的书面精度反推它代表的真值区间半宽（末位的一半）。"""
    s = f"{x!r}"
    if "." in s:
        dec = len(s.split(".")[1].rstrip("0")) or 1
    else:
        dec = 0
    return 0.5 * (10 ** (-dec))


def analyse(rows: list[Row], z: float) -> tuple[list[Finding], dict]:
    out: list[Finding] = []
    stat = {"rows": len(rows), "checked_or_beta": 0, "checked_wald": 0,
            "checked_ci": 0, "checked_ci_p": 0, "skipped": 0}

    for r in rows:
        did = False

        # --- OR = exp(β) ---
        if r.beta is not None and r.orv is not None and r.orv > 0:
            stat["checked_or_beta"] += 1
            did = True
            expb = math.exp(r.beta)
            # 容差：β 末位精度造成的 OR 波动 + 1% 相对
            tb = _tol_from_precision(r.beta)
            tol = max(abs(math.exp(r.beta + tb) - expb), 0.01 * r.orv)
            if abs(expb - r.orv) > tol:
                mid = math.sqrt(r.lo * r.hi) if (r.lo and r.hi and r.lo > 0) else None
                loc = ""
                if mid is not None:
                    if abs(mid - expb) <= max(0.01 * expb, 1e-6):
                        loc = f"；报出 CI 的几何中点 {mid:.4g} = exp(β)，故 **OR 列单独填错**"
                    elif abs(mid - r.orv) <= max(0.01 * r.orv, 1e-6):
                        loc = f"；报出 CI 的几何中点 {mid:.4g} = 报出的 OR，故 **β 列可疑**"
                    else:
                        loc = f"；报出 CI 的几何中点 {mid:.4g} 与两者都不等，整行可疑"
                out.append(Finding(
                    "OR_NOT_EXP_BETA", "Major", r.table, r.line, r.name,
                    f"β={r.beta} → exp(β)={expb:.4g}，而表中 OR={r.orv}{loc}"))

            # --- 符号一致性 ---
            if (r.beta > 0 and r.orv < 1) or (r.beta < 0 and r.orv > 1):
                out.append(Finding(
                    "OR_BETA_SIGN", "Major", r.table, r.line, r.name,
                    f"β={r.beta} 与 OR={r.orv} 异号（β>0 应 OR>1，β<0 应 OR<1）"))

        # --- Wald = (β/SE)² ---
        if r.beta is not None and r.se is not None and r.se > 0 and r.wald is not None:
            stat["checked_wald"] += 1
            did = True
            w = (r.beta / r.se) ** 2
            # 容差：β 与 SE 的书面精度都会放大 Wald，取两端最坏情况
            tb, ts = _tol_from_precision(r.beta), _tol_from_precision(r.se)
            hi_w = ((abs(r.beta) + tb) / max(r.se - ts, 1e-9)) ** 2
            lo_w = ((max(abs(r.beta) - tb, 0.0)) / (r.se + ts)) ** 2
            if not (lo_w - 1e-9 <= r.wald <= hi_w + 1e-9):
                out.append(Finding(
                    "WALD_MISMATCH", "Major", r.table, r.line, r.name,
                    f"(β/SE)²=({r.beta}/{r.se})²={w:.4g}，表中 Wald={r.wald}"
                    f"（按书面精度可接受区间 {lo_w:.4g}~{hi_w:.4g}）"))

        # --- CI = exp(β ± z·SE) ---
        if (r.beta is not None and r.se is not None and r.se > 0
                and r.lo is not None and r.hi is not None):
            stat["checked_ci"] += 1
            did = True
            clo, chi = math.exp(r.beta - z * r.se), math.exp(r.beta + z * r.se)
            tb, ts = _tol_from_precision(r.beta), _tol_from_precision(r.se)
            wlo = math.exp((r.beta - tb) - z * (r.se + ts))
            whi = math.exp((r.beta + tb) + z * (r.se + ts))
            nlo = math.exp((r.beta + tb) - z * max(r.se - ts, 0.0))
            nhi = math.exp((r.beta - tb) + z * max(r.se - ts, 0.0))
            ok_lo = min(wlo, nlo) - 1e-9 <= r.lo <= max(wlo, nlo) + 1e-9
            ok_hi = min(whi, nhi) - 1e-9 <= r.hi <= max(whi, nhi) + 1e-9
            if not (ok_lo and ok_hi):
                out.append(Finding(
                    "CI_NOT_FROM_SE", "Major", r.table, r.line, r.name,
                    f"exp(β±{z}·SE)=({clo:.4g}, {chi:.4g})，表中 95%CI=({r.lo}, {r.hi})"))

        # --- 由 CI 反推 P，与报出的 P 比 ---
        # 判据不用固定倍数阈值，而是把 OR / CI 两端的**书面精度**传播成一个 P 的可行区间，
        # 报出的 P 落在区间外才算不符。这样既能抓住 4 倍这种"倍数不大但精度上不可能"的差
        # （实测：CI 推出 0.033 而表中印 0.008），又不会被 3 位有效数字的舍入噪声带偏。
        if (r.lo is not None and r.hi is not None and r.lo > 0
                and r.orv is not None and r.orv > 0 and r.p is not None):
            t_or = _tol_from_precision(r.orv)
            t_lo = _tol_from_precision(r.lo)
            t_hi = _tol_from_precision(r.hi)
            se_lo = (math.log(max(r.hi - t_hi, 1e-9)) - math.log(r.lo + t_lo)) / (2 * z)
            se_hi = (math.log(r.hi + t_hi) - math.log(max(r.lo - t_lo, 1e-9))) / (2 * z)
            if se_lo > 0 and se_hi > 0:
                stat["checked_ci_p"] += 1
                did = True
                z_small = abs(math.log(max(r.orv - t_or, 1e-9))) / se_hi
                z_large = abs(math.log(r.orv + t_or)) / se_lo
                p_hi = two_sided_p_from_z(min(z_small, z_large))   # 可行 P 的上界
                p_lo = two_sided_p_from_z(max(z_small, z_large))   # 可行 P 的下界
                # 报在下限（P<0.001 之类）时，只要反推 P 不高于该下限即视为相容
                floor_ok = r.p_bound and p_lo <= r.p
                # 未标 < 但恰好印在常见下限值上，且反推更小 —— 同样视为相容（"<"常被漏印）
                floor_ok = floor_ok or (r.p in (0.001, 0.01, 0.0001) and p_hi <= r.p)

                # 报出的 P 自己也是舍入过的，必须按区间比区间，而不是拿点去比区间。
                # SLACK 是给"CI 未必由正态 Wald 法构造"（profile likelihood / 精确法等）
                # 留的余量：把反推区间上下各放宽 1.5 倍，两个区间**完全不相交**才报。
                # 这一步是防过报的关键——没有它，3 位有效数字的常规舍入就会满屏假阳性。
                SLACK = 1.5
                t_p = _tol_from_precision(r.p)
                rep_lo, rep_hi = max(r.p - t_p, 0.0), r.p + t_p
                env_lo, env_hi = p_lo / SLACK, p_hi * SLACK
                disjoint = (rep_hi < env_lo) or (rep_lo > env_hi)

                if not floor_ok and disjoint:
                    extra = ""
                    if (r.p < 0.05) != (p_lo < 0.05):
                        extra = "；**跨过 0.05，显著性结论会翻**"
                    out.append(Finding(
                        "CI_P_MISMATCH", "Major", r.table, r.line, r.name,
                        f"由 95%CI({r.lo}, {r.hi}) 与 OR={r.orv} 按书面精度反推 P∈"
                        f"[{p_lo:.3g}, {p_hi:.3g}]（放宽 {SLACK}× 后仍为 "
                        f"[{env_lo:.3g}, {env_hi:.3g}]），而表中 P={r.p}{extra}"))

        # --- 兜底：无 β/SE 时看 CI 的几何中点是否等于 OR ---
        if (r.beta is None and r.orv is not None and r.orv > 0
                and r.lo is not None and r.hi is not None and r.lo > 0):
            did = True
            mid = math.sqrt(r.lo * r.hi)
            if abs(mid - r.orv) > max(0.03 * r.orv, 0.02):
                out.append(Finding(
                    "CI_ASYMMETRIC", "Minor", r.table, r.line, r.name,
                    f"报出 CI({r.lo}, {r.hi}) 的几何中点 {mid:.4g} 偏离报出的 OR={r.orv}"
                    f"（对数尺度上 CI 应以 OR 为中心）"))

        if not did:
            stat["skipped"] += 1
    return out, stat


# ---------------------------------------------------------------- 主程序

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="回归表六列恒等式自检（OR=exp(β) / Wald=(β/SE)² / CI=exp(β±1.96SE) / CI↔P）")
    ap.add_argument("--manuscript", required=True)
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

    rows = parse_pipe_tables(text)
    findings, stat = analyse(rows, a.z)

    if a.json:
        print(json.dumps({"stat": stat, "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    elif not a.quiet:
        print(f"稿件：{a.manuscript}")
        print(f"识别到回归表行 {stat['rows']} 行；参与判定："
              f"OR↔β {stat['checked_or_beta']} 行、Wald {stat['checked_wald']} 行、"
              f"CI {stat['checked_ci']} 行、CI↔P {stat['checked_ci_p']} 行；"
              f"列不全跳过 {stat['skipped']} 行")
        if not findings:
            print("✓ 本清单内各判据均未发现不一致（不等于表格没有其他问题）")
        else:
            print(f"\n发现 {len(findings)} 处：")
            for f in findings:
                print(f"  [{f.severity}] {f.verdict}  表{f.table} 第{f.line}行  {f.name}")
                print(f"      {f.detail}")

    majors = sum(1 for f in findings if f.severity == "Major")
    if a.strict and majors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
