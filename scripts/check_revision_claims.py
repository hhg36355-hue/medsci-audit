# -*- coding: utf-8 -*-
# 可重复性信息:
#   Python 版本 : 3.11+（纯标准库）
#   关键包      : 无第三方依赖（docx 用标准库 zipfile 解）
#   随机种子    : 不涉及（确定性只读断言核验）
#
# check_revision_claims.py —— 中文返修「整改对照 / 逐点回复信」里每条"已改"断言的
# 双向核验器。是本工作站 verify_all_claims.py（SII+LVEF 项目，硬编码路径 + 硬编码
# 56 条 CLAIMS）的**通用版**：断言改由外部 claims 规格文件给出，可跨项目 / 跨轮次复用。
#
# 与英文 check_response_claims.py 的分工：那个从英文回复信里**自动抽取**"we added X"
# 断言，对中文回复信抽 0 条（空过），且中文信混用「已改为X」(应在)/「已删除X」(应无)
# 两种极性，通用自动抽取不可靠。本器改为**显式声明每条断言的极性**（in= 应出现 /
# out= 应消失），恰好吃下中文双极性——正是 CLAUDE.md「整改对照里每条'已改'都必须回稿子
# 里验过才能写」那条软约束的机器兜底。扫不到 = 报告失实，必须回去改稿或改说明。
#
# 用法：
#   python check_revision_claims.py --manuscript 清洁稿.docx --response 回复信.md --claims 断言.txt
#   python check_revision_claims.py --manuscript 终稿.md --claims 断言.json --strict --out qc.json
#
# claims 规格（两种格式，按扩展名判断；.json 走 JSON，其余走块格式）：
#   —— 块格式（推荐，中文友好、无需转义）——
#     # 注释行以 # 开头
#     [P1-4] 表4 中文题名已改          <- [标签] 可选描述，开一条新断言
#     where: body                      <- body(默认) | letter，指到正文还是回复信里查
#     in:  鉴别 AMI 与非 AMI 冠心病的表观效能   <- 应当出现的串（可写多行 in:）
#     out: 对 AMI 的诊断效能                     <- 应当消失的串（可写多行 out:）
#   —— JSON 格式 ——
#     [{"tag":"P1-4","where":"body","in":["A","B"],"out":"C","desc":"..."}]
#
# 退出码：0 全部成立；--strict 时有未成立断言退 1；输入/用法错误退 2。
from __future__ import annotations
import argparse
import json
import re
import sys
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ----------------------------------------------------------------- 读取文本

def _docx_text(path: Path):
    """用标准库 zipfile 读 .docx 正文文本（含表格单元格，它们同在 document.xml）。
    返回 (text, tracked)。tracked=True 表示是留痕稿——本器按"接受修订"视图读取
    （剔除 <w:del> 里的旧文字），但复杂嵌套可能不准，建议传清洁版。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "word/document.xml" not in names:
            raise ValueError("不是有效的 .docx（缺 word/document.xml）")
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    tracked = ("<w:ins " in xml) or ("<w:del " in xml) or ("<w:delText" in xml)
    # 接受修订视图：删掉被删除的内容（w:del 块 / w:delText），保留插入
    view = re.sub(r"<w:del\b[^>]*>.*?</w:del>", "", xml, flags=re.S)
    view = re.sub(r"<w:delText\b[^>]*>.*?</w:delText>", "", view, flags=re.S)
    # 段落边界补换行，去所有标签，反转义
    view = re.sub(r"</w:p>", "\n", view)
    view = re.sub(r"<[^>]+>", "", view)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&apos;", "'")):
        view = view.replace(a, b)
    return view, tracked


def read_text(path: Path):
    """返回 (text, tracked_warning_or_None)。"""
    ext = path.suffix.lower()
    if ext == ".docx":
        text, tracked = _docx_text(path)
        warn = ("留痕稿：已按'接受修订'视图读取（去 w:del），复杂嵌套修订可能不准，"
                "建议改传清洁版（已接受修订）" if tracked else None)
        return text, warn
    if ext in (".md", ".txt", ".markdown", ""):
        return path.read_text(encoding="utf-8", errors="ignore"), None
    raise ValueError("不支持的后缀 %s（支持 .docx/.md/.txt）" % ext)

# ----------------------------------------------------------------- 解析断言

def _norm_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [s for s in v if isinstance(s, str) and s.strip()]


def parse_claims(path: Path):
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        claims = []
        for i, obj in enumerate(data):
            claims.append({
                "tag": str(obj.get("tag", "C%d" % (i + 1))),
                "desc": str(obj.get("desc", "")),
                "where": str(obj.get("where", "body")).lower(),
                "ins": _norm_list(obj.get("in")),
                "outs": _norm_list(obj.get("out")),
            })
        return claims
    # 块格式
    claims, cur = [], None
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^\[([^\]]+)\]\s*(.*)$", s)
        if m:
            if cur:
                claims.append(cur)
            cur = {"tag": m.group(1).strip(), "desc": m.group(2).strip(),
                   "where": "body", "ins": [], "outs": []}
            continue
        if cur is None:
            continue
        m = re.match(r"^(where|in|out|desc)\s*[:：]\s*(.*)$", s, re.I)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "where":
                cur["where"] = val.lower()
            elif key == "in" and val:
                cur["ins"].append(val)
            elif key == "out" and val:
                cur["outs"].append(val)
            elif key == "desc":
                cur["desc"] = val
    if cur:
        claims.append(cur)
    return claims

# ----------------------------------------------------------------- 核验

@dataclass
class Finding:
    tag: str
    kind: str          # CLAIM_MISSING | CLAIM_STALE | CLAIM_TARGET_MISSING
    severity: str
    detail: str


@dataclass
class Report:
    manuscript: str
    response: str | None
    findings: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    n_claims: int = 0

    @property
    def n_flag(self):
        return sum(1 for f in self.findings if f.severity == "MAJOR")

    @property
    def verdict(self):
        return "CLAIMS UNMET" if self.n_flag else "OK"


def _ctx(text: str, needle: str, pad: int = 40):
    i = text.find(needle)
    if i < 0:
        return ""
    a, b = max(0, i - pad), min(len(text), i + len(needle) + pad)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def audit(body: str, letter: str | None, claims: list) -> list:
    findings = []
    for c in claims:
        where = c["where"]
        if where == "letter":
            if letter is None:
                findings.append(Finding(c["tag"], "CLAIM_TARGET_MISSING", "MAJOR",
                    "断言指向回复信(where: letter)，但未提供 --response"))
                continue
            target = letter
        else:
            target = body
        for s in c["ins"]:
            if s not in target:
                findings.append(Finding(c["tag"], "CLAIM_MISSING", "MAJOR",
                    "应出现但缺失[%s]：%s" % (where, s[:60])))
        for s in c["outs"]:
            if s in target:
                findings.append(Finding(c["tag"], "CLAIM_STALE", "MAJOR",
                    "应消失但残留[%s]：%s … 上下文：%s" % (where, s[:40], _ctx(target, s))))
    return findings

# ----------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(
        description="中文返修断言双向核验：整改对照/回复信里每条'已改'回终稿验 in=应出现 / out=应消失。")
    ap.add_argument("--manuscript", required=True, type=Path, help="终稿/清洁稿（.docx 建议清洁版 / .md / .txt）= body 目标")
    ap.add_argument("--response", type=Path, help="回复信（.md/.txt/.docx）= letter 目标；有 where: letter 的断言才需要")
    ap.add_argument("--claims", required=True, type=Path, help="断言规格文件（.txt 块格式 / .json）")
    ap.add_argument("--strict", action="store_true", help="有未成立断言时退出码 1")
    ap.add_argument("--quiet", action="store_true", help="只给退出码，不打印报告")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非文本报告")
    ap.add_argument("--out", type=Path, help="把 JSON 工件写到此路径")
    args = ap.parse_args()

    for p in (args.manuscript, args.claims) + ((args.response,) if args.response else ()):
        if not p.exists():
            print("ERROR 文件不存在：%s" % p, file=sys.stderr)
            sys.exit(2)

    try:
        body, body_warn = read_text(args.manuscript)
        letter, letter_warn = (read_text(args.response) if args.response else (None, None))
        claims = parse_claims(args.claims)
    except Exception as e:
        print("ERROR 读取失败：%s" % e, file=sys.stderr)
        sys.exit(2)

    rep = Report(manuscript=str(args.manuscript),
                 response=str(args.response) if args.response else None,
                 n_claims=len(claims))
    if body_warn:
        rep.warnings.append("manuscript " + body_warn)
    if letter_warn:
        rep.warnings.append("response " + letter_warn)
    rep.findings = audit(body, letter, claims)

    if args.out or args.json:
        payload = {
            "detector": "check_revision_claims",
            "manuscript": rep.manuscript, "response": rep.response,
            "n_claims": rep.n_claims, "verdict": rep.verdict,
            "n_flag": rep.n_flag,
            "warnings": rep.warnings,
            "findings": [asdict(f) for f in rep.findings],
        }
        js = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(js, encoding="utf-8")
        if args.json and not args.quiet:
            print(js)

    if not args.quiet and not args.json:
        print("== %s ==  %s" % (rep.verdict, args.manuscript))
        print("断言 %d 条，未成立 %d 条" % (rep.n_claims, rep.n_flag))
        for w in rep.warnings:
            print("  [warn] %s" % w)
        if rep.findings:
            for f in rep.findings:
                print("[%s] %-20s %s" % (f.severity, f.kind, ""))
                print("        (%s) %s" % (f.tag, f.detail))
        else:
            print("★ 全部 %d 条断言在终稿中核实成立（整改对照/回复信无失实陈述）" % rep.n_claims)

    sys.exit(1 if (args.strict and rep.n_flag) else 0)


if __name__ == "__main__":
    main()
