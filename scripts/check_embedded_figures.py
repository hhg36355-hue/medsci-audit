#!/usr/bin/env python3
"""Embedded-figure freshness gate: does the .docx actually carry the figures the
pipeline produced?

The failure this catches is silent and survives every text-level check. A revision
regenerates Fig 3 from the analysis pipeline, the reviewer is told "图3已按新调整集
重绘", the change log says so, every stale-value scan passes — and the .docx still
carries the *previous* rendering, because nobody re-embedded it. Prose and pixels
drift apart; no regex can see it, because the numbers that are wrong live inside a
PNG.

The same class of defect appears in two other shapes, both covered here:

  FIG_NOT_EMBEDDED    a pipeline figure has no byte-identical counterpart among the
                      images inside the document — it was regenerated but never
                      embedded (or an older copy is still in place).
  FIG_ORPHAN_MEDIA    an image part sits in the package that no longer matches any
                      pipeline output AND is not referenced by document.xml — a
                      leftover from deleted content, bloating the file and
                      recoverable by anyone who unzips it.
  FIG_UNREFERENCED    an image part exists and is referenced by nothing in
                      document.xml (r:embed) — it will not render, but ships.

Matching is by exact SHA-256 of the image bytes, so a figure that was re-exported
with identical content but different compression will be reported; that is
deliberate — "I re-ran the script and the bytes changed" is exactly the state the
author needs to resolve before claiming the figure is current.

Pure standard library (zipfile + hashlib + re). No rendering, no OCR: this gate
answers "is the embedded image the one the pipeline last wrote", not "are the
numbers printed inside it correct". Reading the numbers inside a figure remains a
human step.

Usage
    check_embedded_figures.py --docx MS.docx --figdir 论文图/
    check_embedded_figures.py --docx MS.docx --figdir out/ --strict
    check_embedded_figures.py --docx MS.docx --figdir out/ --out qc/figures.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".emf", ".wmf", ".gif", ".bmp"}
RASTER_PREFERRED = {".png", ".tif", ".tiff"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _media(zf: zipfile.ZipFile) -> dict[str, bytes]:
    out = {}
    for n in zf.namelist():
        if "/media/" in n and Path(n).suffix.lower() in IMG_EXT:
            data = zf.read(n)
            if data:
                out[n] = data
    return out


def _referenced_rids(zf: zipfile.ZipFile) -> set[str]:
    try:
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    except KeyError:
        return set()
    return set(re.findall(r'r:(?:embed|link)="([^"]+)"', xml))


def _rid_to_target(zf: zipfile.ZipFile) -> dict[str, str]:
    try:
        rels = zf.read("word/_rels/document.xml.rels").decode("utf-8", "replace")
    except KeyError:
        return {}
    out = {}
    for m in re.finditer(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels):
        out[m.group(1)] = "word/" + m.group(2).lstrip("/")
    return out


def analyze(docx: Path, figdir: Path, ignore: tuple[str, ...] = ()) -> dict:
    findings: list[dict] = []
    with zipfile.ZipFile(docx) as zf:
        media = _media(zf)
        rids = _referenced_rids(zf)
        rid_map = _rid_to_target(zf)
    used_targets = {rid_map[r] for r in rids if r in rid_map}

    embedded = {name: _sha(b) for name, b in media.items()}
    embedded_hashes = set(embedded.values())

    figs: dict[str, str] = {}
    skipped: list[str] = []
    for p in sorted(figdir.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in IMG_EXT):
            continue
        rel = str(p.relative_to(figdir))
        if "_旧版" in str(p) or "_old" in p.name.lower() or "backup" in str(p).lower():
            continue
        if any(tok and tok in rel for tok in ignore):
            skipped.append(rel)      # 稿件已按编辑意见删除该图，管线文件仍在，属预期
            continue
        figs[rel] = _sha(p.read_bytes())

    # 1. pipeline figure not embedded (raster masters only; vector/tif siblings of an
    #    embedded png are not independently required)
    png_stems = {Path(k).stem for k, v in figs.items()
                 if Path(k).suffix.lower() == ".png" and v in embedded_hashes}
    for rel, h in sorted(figs.items()):
        if h in embedded_hashes:
            continue
        suf = Path(rel).suffix.lower()
        if suf not in RASTER_PREFERRED:
            continue
        if suf in {".tif", ".tiff"} and Path(rel).stem in png_stems:
            continue  # png counterpart is embedded; tif is the print master
        findings.append({
            "code": "FIG_NOT_EMBEDDED", "severity": "Major", "figure": rel,
            "detail": f"管线图 {rel} 在文档中找不到字节一致的副本"
                      f"——可能重绘后未嵌入，或文档内仍是旧版本",
        })

    # 2/3. media parts that match nothing / are referenced by nothing
    for name, h in sorted(embedded.items()):
        referenced = name in used_targets
        matches_pipeline = h in set(figs.values())
        if not referenced and not matches_pipeline:
            findings.append({
                "code": "FIG_ORPHAN_MEDIA", "severity": "Minor", "figure": name,
                "detail": f"{name} 既未被 document.xml 引用，也不对应任何管线输出"
                          f"——疑为删除内容后残留的孤儿图片，应从包内剔除",
            })
        elif not referenced:
            findings.append({
                "code": "FIG_UNREFERENCED", "severity": "Minor", "figure": name,
                "detail": f"{name} 存在于包内但 document.xml 未引用，不会渲染",
            })

    return {
        "source": str(docx), "figdir": str(figdir),
        "n_embedded": len(media), "n_pipeline": len(figs),
        "n_referenced": len(used_targets),
        "ignored": skipped,
        "findings": findings,
        "matched": sorted(rel for rel, h in figs.items() if h in embedded_hashes),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Embedded-figure freshness gate (docx vs pipeline output).")
    ap.add_argument("--docx", required=True, help="built .docx")
    ap.add_argument("--figdir", required=True,
                    help="directory holding the pipeline's figure output")
    ap.add_argument("--ignore", default="", metavar="TOK[,TOK...]",
                    help="comma-separated substrings of pipeline figures that the "
                         "manuscript intentionally no longer carries (e.g. a figure "
                         "deleted per reviewer request); matched files are skipped")
    ap.add_argument("--out", help="write JSON artifact to this path")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any Major finding")
    ap.add_argument("--quiet", action="store_true", help="suppress stdout table")
    args = ap.parse_args()

    dp, fp = Path(args.docx), Path(args.figdir)
    if not dp.is_file():
        sys.stderr.write(f"ERROR: not a file: {dp}\n")
        return 2
    if not fp.is_dir():
        sys.stderr.write(f"ERROR: not a directory: {fp}\n")
        return 2

    ignore = tuple(t.strip() for t in args.ignore.split(",") if t.strip())
    res = analyze(dp, fp, ignore)
    majors = [f for f in res["findings"] if f["severity"] == "Major"]

    if not args.quiet:
        print("=" * 56)
        print(" Embedded Figure Freshness (docx vs pipeline)")
        print("=" * 56)
        print(f"  内嵌图片 {res['n_embedded']} 个｜管线图件 {res['n_pipeline']} 个"
              f"｜已引用 {res['n_referenced']} 个｜字节一致 {len(res['matched'])} 个"
              + (f"｜按 --ignore 跳过 {len(res['ignored'])} 个" if res['ignored'] else ""))
        print()
        print("| 检查 | 级别 | 说明 |")
        print("|---|---|---|")
        if res["findings"]:
            for f in res["findings"]:
                print(f"| {f['code']} | {f['severity']} | {f['detail']} |")
        else:
            print("| （无） | — | 所有管线图件均已字节一致地嵌入，无孤儿/未引用图片 |")
        print()
        if majors:
            print(f"MAJOR：{len(majors)} 个图件与管线输出不一致，须重新嵌入后再定稿。")
        elif res["findings"]:
            print("MINOR：存在孤儿或未引用图片，建议清理。")
        else:
            print("OK：内嵌图件与管线输出一致。")
        print()
        print("注：本闸门只核对『嵌入的是不是管线最后写出的那张图』，"
              "不读图内文字。图中印的人数/术语/P 值是否正确，仍须人工逐张打开核对。")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    return 1 if (args.strict and majors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
