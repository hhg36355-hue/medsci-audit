#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GB/T 7714 顺序编码制：正文引用顺序 + 缺号 + 孤立文献 + md↔docx 同步核对。

面向中文医学论著（顺序编码制 / Vancouver 数字著录）。这是一个确定性、离线、
纯标准库的投稿前闸门，专门堵这套工作站 CLAUDE.md 记录过的真实翻车点：

  「增删文献后图省事接在列表末尾 → 正文编号从 [8] 直接跳到 [13] 断档跳号；
    且只改了 docx 未回写 md，两处不一致。」

检查项（正文 = 参考文献列表之前的部分）：
  ORDER_JUMP   (Major) 正文引用的"首次出现顺序"出现断档跳号——例如首次出现序列
                       是 …, 8, 13（9–12 从未在此前出现）。顺序编码制要求文献按正文
                       首次被引用的先后连续编号 1,2,3,…，跳号是最典型的增删事故。
  ORDER_INVERT (Major) 一个较小的编号在一个较大的编号之后才首次出现（如 [5] 在 [8]
                       之后才首次露面），说明编号未按首次出现顺序排。
  ORPHAN_LIST  (Major) 文末参考文献列表中的某条从未在正文被引用（孤立文献）。
  ORPHAN_TEXT  (Major) 正文引用了某编号，但文末列表没有对应条目（悬空引用）。
  COUNT_MISMATCH(Major) 正文出现的最大编号 与 参考文献列表条目数 不一致。
  SYNC_DIVERGE (Major) 提供 --compare 时，两个副本（典型是 md 与 docx）的
                       "被引编号集合"或"列表条目数"不一致——即"只改一处未同步"。

保守设计：只在能明确抽取到括号数字引用时才判定；抽不到不误报。中文/英文双语正文
均可（只认方括号数字引用 [n] / ［n］ 及区间 [n-m] / 逗号 [n,m]）。若正文用的是
上标数字而非方括号，docx 渲染后可能只剩纯数字、无法与页码等区分，此时本工具会
少报——请在 md 底稿（带方括号）上跑，这也是 CLAUDE.md 要求 md 为准的原因之一。

输入
  --manuscript PATH   主稿：.md/.txt 或 .docx（按扩展名自动识别；docx 用标准库
                      zipfile 解 word/document.xml，无需 python-docx）。
  --compare PATH      可选的第二副本，用于 md↔docx 同步核对。
  --out PATH          写出 JSON 工件。
  --strict            存在任一 Major 时退出码置 1（可用于 CI / hook 阻断）。
  --quiet             不打印表格。

退出码：0 干净（或仅提示）；1 有 Major 且 --strict；2 输入/用法错误。
仅用标准库（re / json / zipfile / argparse / pathlib）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

# Windows 控制台默认 GBK，中文输出会乱码/报错；尽量切到 UTF-8（失败则忽略）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 正文中的数字引用：以数字开头，内部只含数字与分隔符（逗号/顿号/连接号/波浪号）。
# 以数字开头可天然排除 [占位待核] / [图1] / [表2] 等非引用方括号。
CITE_RE = re.compile(
    r"[\[［]\s*([0-9]{1,3}(?:\s*[,，、\-–—~]\s*[0-9]{1,3})*)\s*[\]］](?!\()")
# 参考文献区标题
REF_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*\**\s*(参\s*考\s*文\s*献|references?|bibliography|works\s+cited)\s*\**\s*[:：]?\s*$",
    re.IGNORECASE)
# 列表条目起始编号：支持 "[1] …" / "1. …" / "1、…" / "1 …"
REF_ENTRY_RE = re.compile(r"^\s*[\[［]?\s*(\d{1,3})\s*[\]］]?\s*[\.\、．]?\s+\S")
# 其它一级章节标题（用于在到达下一个大标题时结束参考文献扫描）
OTHER_HEADING_RE = re.compile(r"^\s*#{1,3}\s+\S")


def _expand(numlist: str) -> list[int]:
    """把 '1,3-5' / '1，3–5' 展开成 [1,3,4,5]。"""
    nums: list[int] = []
    # 先按逗号/顿号切成 token
    for tok in re.split(r"[,，、]", numlist):
        tok = tok.strip()
        if not tok:
            continue
        rng = re.split(r"\s*[\-–—~]\s*", tok)
        if len(rng) == 2 and rng[0].isdigit() and rng[1].isdigit():
            a, b = int(rng[0]), int(rng[1])
            if a <= b and b - a < 200:  # 防御异常大区间
                nums.extend(range(a, b + 1))
            else:
                nums.append(a)
                nums.append(b)
        elif tok.isdigit():
            nums.append(int(tok))
    return nums


def _docx_text(path: Path) -> str:
    """用标准库读取 docx 的可见段落文本（换行连接）。"""
    try:
        with zipfile.ZipFile(path, "r") as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""
    paras = re.split(r"</w:p>", xml)
    out = []
    for p in paras:
        # 段落内保留 </w:t> 之间的文本，去掉所有标签
        txt = re.sub(r"<[^>]+>", "", p)
        txt = txt.replace(" ", " ").strip()
        out.append(txt)
    return "\n".join(out)


def _load_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return _docx_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


def _split_body_refs(text: str):
    """返回 (正文, 参考文献区行列表)。参考文献区 = 标题之后到下一大标题/结尾。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if REF_HEADING_RE.match(ln):
            start = i
            break
    if start is None:
        return text, []
    body = "\n".join(lines[:start])
    ref_lines = []
    for ln in lines[start + 1:]:
        if OTHER_HEADING_RE.match(ln) and not REF_HEADING_RE.match(ln):
            break
        ref_lines.append(ln)
    return body, ref_lines


def _first_appearance(body: str) -> list[int]:
    """返回正文中各编号"首次出现"的先后顺序（去重，按位置排序）。"""
    first_pos: dict[int, int] = {}
    for m in CITE_RE.finditer(body):
        for n in _expand(m.group(1)):
            if n not in first_pos:
                first_pos[n] = m.start()
    return [n for n, _ in sorted(first_pos.items(), key=lambda kv: kv[1])]


def _ref_entry_numbers(ref_lines: list[str]) -> list[int]:
    nums = []
    for ln in ref_lines:
        m = REF_ENTRY_RE.match(ln)
        if m:
            nums.append(int(m.group(1)))
    return nums


def analyze_one(text: str) -> dict:
    body, ref_lines = _split_body_refs(text)
    order = _first_appearance(body)            # 首次出现顺序
    cited = set(order)                          # 正文引用到的编号集合
    ref_nums = _ref_entry_numbers(ref_lines)   # 列表条目编号
    ref_set = set(ref_nums)

    claims: list[dict] = []

    # 1) 顺序检查：首次出现序列应为 1,2,3,…,max 且连续升序
    if len(order) >= 2:
        # 逐位比对理想序列
        expected = 1
        jump_at = None
        invert_at = None
        seen_max = 0
        for n in order:
            if n < seen_max and invert_at is None:
                invert_at = n
            seen_max = max(seen_max, n)
        # 断档：首次出现序列不等于 1..len 的连续（考虑正文可能只引用了部分？
        # 顺序编码制下正文应引用全部文献，故 order 理应是 1..N 的一个升序排列）
        ideal = list(range(1, len(order) + 1))
        if order == ideal:
            pass  # 完美
        else:
            # 找第一个偏离点
            for idx, n in enumerate(order):
                if n != idx + 1:
                    if n > idx + 1:
                        jump_at = (order[idx - 1] if idx else 0, n)
                    break
            pretty = ", ".join(str(n) for n in order[:20]) + ("…" if len(order) > 20 else "")
            if invert_at is not None:
                claims.append({
                    "verdict": "ORDER_INVERT", "severity": "Major",
                    "detail": (f"编号 [{invert_at}] 在更大的编号之后才首次出现——正文首次出现"
                               f"序列为 {pretty}；请按正文首次被引用的先后重新编号"),
                    "where": "正文引用顺序",
                })
            elif jump_at is not None:
                prev, cur = jump_at
                miss = ", ".join(str(k) for k in range(prev + 1, cur))
                claims.append({
                    "verdict": "ORDER_JUMP", "severity": "Major",
                    "detail": (f"正文引用编号从 [{prev}] 断档跳到 [{cur}]（{miss} 未在此前出现）"
                               f"——典型的「新增文献接在列表末尾」事故；请按首次出现顺序重排"),
                    "where": "正文引用顺序",
                })

    # 2) 孤立文献：列表有、正文无
    if ref_set:
        orphan_list = sorted(ref_set - cited)
        if orphan_list:
            claims.append({
                "verdict": "ORPHAN_LIST", "severity": "Major",
                "detail": (f"参考文献列表中 {len(orphan_list)} 条从未在正文被引用："
                           f"[{', '.join(str(n) for n in orphan_list)}]——删除或在正文补引"),
                "where": "参考文献列表",
            })

    # 3) 悬空引用：正文有、列表无（仅当列表被成功解析时才判）
    if ref_nums:
        orphan_text = sorted(cited - ref_set)
        if orphan_text:
            claims.append({
                "verdict": "ORPHAN_TEXT", "severity": "Major",
                "detail": (f"正文引用了 {len(orphan_text)} 个编号但列表无对应条目："
                           f"[{', '.join(str(n) for n in orphan_text)}]——补列表条目或改引用"),
                "where": "正文↔列表对应",
            })

    # 4) 计数一致性
    if order and ref_nums:
        max_cited = max(cited)
        if max_cited != len(ref_nums):
            claims.append({
                "verdict": "COUNT_MISMATCH", "severity": "Major",
                "detail": (f"正文最大编号为 [{max_cited}]，但参考文献列表有 {len(ref_nums)} 条"
                           f"——两者应相等"),
                "where": "计数",
            })

    n_major = sum(1 for c in claims if c["severity"] == "Major")
    return {
        "cited_numbers": sorted(cited),
        "first_appearance_order": order,
        "ref_entry_count": len(ref_nums),
        "claims": claims,
        "summary": {"n_claims": len(claims), "n_major": n_major,
                    "verdict": "MAJOR_CANDIDATE" if n_major else "OK"},
    }


def analyze_sync(a: dict, b: dict, name_a: str, name_b: str) -> list[dict]:
    claims = []
    set_a, set_b = set(a["cited_numbers"]), set(b["cited_numbers"])
    if set_a != set_b:
        only_a = sorted(set_a - set_b)
        only_b = sorted(set_b - set_a)
        parts = []
        if only_a:
            parts.append(f"仅 {name_a} 有 [{', '.join(map(str, only_a))}]")
        if only_b:
            parts.append(f"仅 {name_b} 有 [{', '.join(map(str, only_b))}]")
        claims.append({
            "verdict": "SYNC_DIVERGE", "severity": "Major",
            "detail": "两副本被引编号集合不一致：" + "；".join(parts) + "——只改了一处未同步",
            "where": f"{name_a} ↔ {name_b}",
        })
    if a["ref_entry_count"] != b["ref_entry_count"]:
        claims.append({
            "verdict": "SYNC_DIVERGE", "severity": "Major",
            "detail": (f"两副本参考文献条目数不一致：{name_a}={a['ref_entry_count']} 条，"
                       f"{name_b}={b['ref_entry_count']} 条——只改了一处未同步"),
            "where": f"{name_a} ↔ {name_b}",
        })
    return claims


def render(result: dict) -> str:
    lines = ["| 检查 | 级别 | 说明 |", "|---|---|---|"]
    for c in result["claims"]:
        lines.append(f"| {c['verdict']} | {c['severity']} | {c['detail']} |")
    if len(lines) == 2:
        lines.append("| （无） | — | 引用顺序/编号/同步均正常 |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="GB/T 7714 顺序编码制引用顺序 + 缺号 + 孤立文献 + md↔docx 同步核对")
    ap.add_argument("--manuscript", required=True, help="主稿 .md/.txt/.docx")
    ap.add_argument("--compare", help="第二副本（md↔docx 同步核对）")
    ap.add_argument("--out", help="写出 JSON 工件路径")
    ap.add_argument("--strict", action="store_true", help="有 Major 时退出码置 1")
    ap.add_argument("--quiet", action="store_true", help="不打印表格")
    args = ap.parse_args()

    p = Path(args.manuscript)
    if not p.is_file():
        sys.stderr.write(f"ERROR: 找不到主稿: {args.manuscript}\n")
        return 2
    result = analyze_one(_load_text(p))
    result["manuscript"] = str(p)

    if args.compare:
        q = Path(args.compare)
        if not q.is_file():
            sys.stderr.write(f"ERROR: 找不到对比副本: {args.compare}\n")
            return 2
        other = analyze_one(_load_text(q))
        sync_claims = analyze_sync(result, other, p.name, q.name)
        result["claims"].extend(sync_claims)
        result["compare"] = str(q)
        result["compare_summary"] = other["summary"]
        result["summary"]["n_major"] += sum(1 for c in sync_claims if c["severity"] == "Major")
        result["summary"]["n_claims"] = len(result["claims"])
        if result["summary"]["n_major"]:
            result["summary"]["verdict"] = "MAJOR_CANDIDATE"

    if not args.quiet:
        print("=" * 48)
        print(" GB/T 7714 引用顺序 / 同步核对")
        print("=" * 48)
        print(render(result))
        print()
        s = result["summary"]
        if s["n_major"]:
            print(f"MAJOR：发现 {s['n_major']} 处引用顺序/编号/同步问题，须修正后再定稿。")
        else:
            print("OK：正文首次出现顺序连续升序，无缺号/孤立/悬空，副本一致。")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        if not args.quiet:
            print(f"\nwrote {args.out}")

    return 1 if (args.strict and result["summary"]["n_major"]) else 0


if __name__ == "__main__":
    sys.exit(main())
