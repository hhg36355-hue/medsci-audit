#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 本工作站原创（2026-08-09）；Python 3.13，纯标准库，确定性无随机性（无需 seed）。
"""比值型指标行的两条硬判据（NLR / MHR / NHR / TyG / AIP / Cr-CysC 这一类）。

为什么存在：中文心血管论著里"两个常规检验值做成的比值"是最流行的一类指标，而它有
两个**只靠表格本身就能查出来**的典型错误，现有任何工具都不查：

**判据一 RATIO_IS_MEAN_OF_MEANS —— 比值恰好等于「分子均值÷分母均值」**

  这一条的方向和常规一致性检查**相反**：常规检查都是"两个数应该相等"，这一条是
  **"恰好相等反而说明算错了"**。原因是 Jensen 不等式：E[X/Y] ≠ E[X]/E[Y]。逐个病人
  算比值再求均值，几乎不可能恰好等于两个组均值之商；一旦连续多行精确吻合到小数点后
  两位，唯一的解释就是**这一列是拿两行均值相除填出来的，而不是逐人算的**。

  2026-08-09 实测：某篇 8 个组 × 2 个比值 = 16 行里，Cr/CysC 8/8 行、MHR 7/8 行精确
  等于均值之商。随之而来的是该文所有 Spearman 相关分析在逻辑上无法成立——个体层面的
  比值根本没被算出来过。

**判据二 RATIO_SD_BELOW_BOUND —— 比值的标准差低于数学下界**

  对 Z = X/Y，由 delta 法 CV(Z)² ≈ CV(X)² + CV(Y)² − 2ρ·CV(X)·CV(Y)。ρ=+1（分子分母
  完全正相关）时 CV(Z) 取到最小可能值 |CV(X) − CV(Y)|，故

      SD(Z) ≥ |CV(X) − CV(Y)| × Z

  这是**最宽松**的下界（分子分母若负相关，下界还会更大），低于它就是算错或编的。
  同一批实测：16 个比值里 9 个低于下界，表 3 的三行差到 4~5 倍。

判据（两条都是 Major）：
  RATIO_IS_MEAN_OF_MEANS (Major) 比值 ≈ 分子均值÷分母均值（默认容差 0.5%）。
  RATIO_SD_BELOW_BOUND   (Major) SD(比值) < |CV(分子)−CV(分母)| × 比值。

保守设计（防过报）：
  · 只处理 `均数±标准差` 形式的单元格；中位数(四分位) 形式的行直接跳过（下界不适用）；
  · 比值行必须能在**同一张表**里找到分子行与分母行才参与判定，找不到只计入「跳过」；
  · 判据一默认要求**同一张表里至少 2 个组都吻合**才报（单组吻合可能是巧合），
    可用 --min-hits 调整；
  · 判据二的下界已取最宽松形式，且再留 2% 余量。

比值行的识别：行名形如 `A/B`、`A／B`、`A与B比值`、`A/B比值`、`A/B ratio`，或用
`--ratio 名称=分子行名/分母行名` 显式指定（行名与表里一致即可，可多次给）。

输入
  --manuscript PATH   .md/.txt（docx 请先转文本）
  --tol FLOAT         判据一的相对容差，默认 0.005（0.5%）
  --min-hits INT      判据一至少几个组吻合才报，默认 2
  --ratio A=B/C       显式声明比值行与其分子分母行（可重复）
  --strict / --quiet / --json

用法：
  python scripts\\check_ratio_columns.py --manuscript 文稿\\论著.md --strict
  python scripts\\check_ratio_columns.py --manuscript 文稿\\论著.md --ratio "NLR=中性粒细胞/淋巴细胞"
退出码：0 干净；--strict 下有 Major 为 1；输入/用法错为 2。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict

_FULL = str.maketrans("０１２３４５６７８９．－（）±／，％",
                      "0123456789.-()±/,%")


def _clean(s: str) -> str:
    return s.translate(_FULL).replace("\u00a0", " ").strip()


_NUM = r"[-+]?\d*\.?\d+"
_MEANSD = re.compile(rf"({_NUM})\s*±\s*({_NUM})")
_MEDIAN = re.compile(rf"({_NUM})\s*[\(（]")


def parse_mean_sd(cell: str):
    """'65.49±9.01' → (65.49, 9.01)；中位数(IQR) 形式返回 None。"""
    c = _clean(cell)
    m = _MEANSD.search(c)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def _strip_unit(name: str) -> str:
    """去掉行名里的单位括注与空白：'Cr（μmol/L）' → 'Cr'。"""
    n = _clean(name)
    n = re.sub(r"[\(（\[][^)）\]]*[\)）\]]", "", n)
    return n.replace(" ", "").strip()


_RATIO_NAME = re.compile(r"^(.+?)\s*(?:/|／)\s*(.+?)(?:比值|比|ratio)?$", re.I)

# 常见血液学 / 代谢比值的缩写名 → (分子候选, 分母候选)。
# 这类名字里没有斜杠，靠字面拆不出来，但恰恰是中文心血管论著里最常用的一批
# （NLR / MHR / NHR / PLR 等），不列进来等于对主力指标失效。
# 每个位置给多个候选写法，`_find_row` 逐个试，命中唯一一行才采纳。
ACRONYM_RATIOS = {
    "nlr":  (["中性粒细胞", "中性粒细胞计数", "NEUT", "NEU", "N"],
             ["淋巴细胞", "淋巴细胞计数", "LYM", "LY", "L"]),
    "plr":  (["血小板", "血小板计数", "PLT"],
             ["淋巴细胞", "淋巴细胞计数", "LYM", "LY"]),
    "mlr":  (["单核细胞", "单核细胞计数", "MONO", "MON", "M"],
             ["淋巴细胞", "淋巴细胞计数", "LYM", "LY"]),
    "lmr":  (["淋巴细胞", "淋巴细胞计数", "LYM", "LY"],
             ["单核细胞", "单核细胞计数", "MONO", "MON"]),
    "mhr":  (["单核细胞", "单核细胞计数", "MONO", "MON"],
             ["HDL-C", "HDLC", "高密度脂蛋白胆固醇", "高密度脂蛋白"]),
    "nhr":  (["中性粒细胞", "中性粒细胞计数", "NEUT", "NEU"],
             ["HDL-C", "HDLC", "高密度脂蛋白胆固醇", "高密度脂蛋白"]),
    "lhr":  (["淋巴细胞", "淋巴细胞计数", "LYM"],
             ["HDL-C", "HDLC", "高密度脂蛋白胆固醇"]),
    "car":  (["CRP", "C反应蛋白", "超敏C反应蛋白", "hs-CRP"],
             ["白蛋白", "ALB"]),
    "whr":  (["白细胞", "白细胞计数", "WBC"],
             ["HDL-C", "HDLC", "高密度脂蛋白胆固醇"]),
}


def split_ratio_name(name: str):
    """'单核细胞/HDL-C比值' → ('单核细胞', 'HDL-C')。

    返回 (分子候选列表, 分母候选列表)；不像比值则返回 None。
    先按字面拆斜杠 / '与'，拆不出来再查 ACRONYM_RATIOS。
    """
    n = _strip_unit(name)
    n = re.sub(r"(?:比值|比率|ratio)$", "", n, flags=re.I)
    if "/" in n or "／" in n:
        m = _RATIO_NAME.match(n)
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            if a and b:
                return [a], [b]
    else:
        m2 = re.match(r"^(.+?)与(.+?)$", n)
        if m2 and m2.group(1) and m2.group(2):
            return [m2.group(1)], [m2.group(2)]
    key = re.sub(r"[^a-z]", "", n.lower())
    if key in ACRONYM_RATIOS:
        num, den = ACRONYM_RATIOS[key]
        return list(num), list(den)
    return None


@dataclass
class Table:
    idx: int
    line: int
    groups: list           # 列名（去掉第一列）
    rows: dict             # 去单位行名 -> [ (mean,sd) | None ] 按列
    raw_names: dict        # 去单位行名 -> 原始行名
    row_line: dict         # 去单位行名 -> 行号


def parse_tables(text: str) -> list[Table]:
    tabs, lines, i, tno = [], text.splitlines(), 0, 0
    while i < len(lines):
        if lines[i].count("|") < 2:
            i += 1
            continue
        if i + 1 >= len(lines) or not re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i + 1]):
            i += 1
            continue
        head = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        tno += 1
        t = Table(idx=tno, line=i + 1, groups=[_clean(h) for h in head[1:]],
                  rows={}, raw_names={}, row_line={})
        j = i + 2
        while j < len(lines) and lines[j].count("|") >= 2:
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            if cells:
                key = _strip_unit(cells[0])
                if key:
                    t.rows[key] = [parse_mean_sd(c) for c in cells[1:]]
                    t.raw_names[key] = _clean(cells[0])
                    t.row_line[key] = j + 1
            j += 1
        if t.rows:
            tabs.append(t)
        i = j
    return tabs


@dataclass
class Finding:
    verdict: str
    severity: str
    table: int
    line: int
    name: str
    detail: str


def _find_row(t: Table, wants):
    """在表里按去单位行名找一行；wants 是候选写法列表，逐个试，先精确后包含。"""
    if isinstance(wants, str):
        wants = [wants]
    cleaned = [w.replace(" ", "").lower() for w in wants if w and w.strip()]
    for w in cleaned:                       # 第一轮：精确
        for k in t.rows:
            if k.lower() == w:
                return k
    for w in cleaned:                       # 第二轮：唯一包含
        cands = [k for k in t.rows if w in k.lower() or k.lower() in w]
        # 只在唯一匹配时接受，避免 'HDL-C' 同时命中 'HDL-C' 与 'non-HDL-C'
        if len(cands) == 1:
            return cands[0]
    return None


def analyse(tabs: list[Table], tol: float, min_hits: int,
            explicit: dict) -> tuple[list[Finding], dict]:
    out: list[Finding] = []
    stat = {"tables": len(tabs), "ratio_rows": 0, "checked": 0, "skipped": 0}

    for t in tabs:
        for key in list(t.rows):
            parts = explicit.get(key) or split_ratio_name(t.raw_names[key])
            if not parts:
                continue
            stat["ratio_rows"] += 1
            num_k = _find_row(t, parts[0])
            den_k = _find_row(t, parts[1])
            if not num_k or not den_k or num_k == key or den_k == key:
                stat["skipped"] += 1
                continue
            stat["checked"] += 1

            hits, hit_detail = 0, []
            for gi, gname in enumerate(t.groups):
                z = t.rows[key][gi] if gi < len(t.rows[key]) else None
                x = t.rows[num_k][gi] if gi < len(t.rows[num_k]) else None
                y = t.rows[den_k][gi] if gi < len(t.rows[den_k]) else None
                if not (z and x and y) or y[0] == 0 or z[0] == 0:
                    continue

                # --- 判据一：比值 == 分子均值/分母均值 ---
                q = x[0] / y[0]
                if abs(q - z[0]) <= tol * abs(z[0]):
                    hits += 1
                    hit_detail.append(f"{gname}: {x[0]}/{y[0]}={q:.4g}≈表中{z[0]}")

                # --- 判据二：SD 下界 ---
                if x[0] != 0 and y[0] != 0 and z[1] > 0:
                    cvx, cvy = abs(x[1] / x[0]), abs(y[1] / y[0])
                    sd_min = abs(cvx - cvy) * abs(z[0])
                    if z[1] < sd_min * 0.98:      # 再留 2% 余量
                        out.append(Finding(
                            "RATIO_SD_BELOW_BOUND", "Major", t.idx, t.row_line[key],
                            f"{t.raw_names[key]}（{gname}）",
                            f"CV(分子 {t.raw_names[num_k]})={cvx*100:.1f}%、"
                            f"CV(分母 {t.raw_names[den_k]})={cvy*100:.1f}% → "
                            f"SD 下界 = |{cvx*100:.1f}%−{cvy*100:.1f}%| × {z[0]} = {sd_min:.4g}，"
                            f"而表中 SD={z[1]}（下界已按 ρ=+1 取最宽松，实际应更大）"))

            if hits >= min_hits:
                out.append(Finding(
                    "RATIO_IS_MEAN_OF_MEANS", "Major", t.idx, t.row_line[key],
                    t.raw_names[key],
                    f"该行在 {hits} 个组里都精确等于「{t.raw_names[num_k]}均值 ÷ "
                    f"{t.raw_names[den_k]}均值」（容差 {tol*100:g}%）："
                    + "；".join(hit_detail)
                    + "。E[X/Y]≠E[X]/E[Y]，逐人计算不可能连续吻合 → "
                      "该列疑为用两行均值相除填出，而非逐个病人算比值再求均值"))
    return out, stat


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="比值型指标行的两条硬判据（均值之商 / SD 下界）")
    ap.add_argument("--manuscript", required=True)
    ap.add_argument("--tol", type=float, default=0.005)
    ap.add_argument("--min-hits", type=int, default=2)
    ap.add_argument("--ratio", action="append", default=[],
                    help='显式声明，形如 "NLR=中性粒细胞/淋巴细胞"，可重复')
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    explicit = {}
    for spec in a.ratio:
        if "=" not in spec or "/" not in spec.split("=", 1)[1]:
            print(f"[错误] --ratio 格式应为 名称=分子/分母，收到：{spec}", file=sys.stderr)
            return 2
        nm, rest = spec.split("=", 1)
        num, den = rest.split("/", 1)
        explicit[_strip_unit(nm)] = ([num.strip()], [den.strip()])

    try:
        with open(a.manuscript, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        print(f"[错误] 读不到稿件：{e}", file=sys.stderr)
        return 2

    tabs = parse_tables(text)
    findings, stat = analyse(tabs, a.tol, a.min_hits, explicit)

    if a.json:
        print(json.dumps({"stat": stat, "findings": [asdict(f) for f in findings]},
                         ensure_ascii=False, indent=2))
    elif not a.quiet:
        print(f"稿件：{a.manuscript}")
        print(f"表 {stat['tables']} 张；识别为比值的行 {stat['ratio_rows']} 行，"
              f"其中能在同表找到分子与分母行的 {stat['checked']} 行，"
              f"找不到而跳过 {stat['skipped']} 行")
        if not findings:
            print("✓ 本清单内两条判据均未发现问题（不等于比值算法就是对的）")
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
