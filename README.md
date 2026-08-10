# medsci-audit

Deterministic, offline, dependency-free pre-submission checks for medical manuscripts — with first-class support for Chinese-language journals.

20 standalone checkers. Pure Python standard library: no NumPy, no SciPy, no pandas, no network access. Each script runs on its own and exits non-zero under `--strict`, so any of them can drop into a pre-commit hook or CI job.

[中文说明见 README.zh-CN.md](README.zh-CN.md)

---

## The problem this addresses

A class of manuscript errors is arithmetically checkable but almost never checked, because checking them by hand is tedious and reviewers assume someone upstream already did it. These errors survive multiple revision rounds precisely because they look settled:

- A regression table where the `OR` column was retyped by hand and no longer equals `exp(β)`.
- A ratio biomarker (NLR, MHR, PLR, AIP) whose group mean was filled in as *mean of numerator ÷ mean of denominator* — so the per-patient ratio was never actually computed, and every downstream correlation is void.
- A sensitivity of 72.00% reported on a test set with 17 events — but with an integer denominator only `k/17` is reachable, and 0.72 × 17 = 12.24 is not an integer.
- A reference list renumbered after inserting a citation, leaving the in-text numbering to jump from `[8]` to `[13]`.
- A value updated in the abstract and discussion but left stale in a table cell or in the point-by-point response letter.

None of these require the underlying data. All of them are decidable from the manuscript alone.

## Quick start

```bash
git clone https://github.com/hhg36355-hue/medsci-audit.git
cd medsci-audit
python scripts/check_gbt7714_order.py --manuscript paper.md --strict
```

No installation step and no dependencies. On Windows, set `PYTHONUTF8=1` so Chinese output renders correctly.

Every script accepts `--out FILE.json` to write a machine-readable artifact, `--strict` to exit 1 when a Major finding is present, and `--quiet` (one exception, noted below).

## Checkers

### Reference and cross-artifact integrity

| Script | What it catches |
|---|---|
| `check_gbt7714_order.py` | GB/T 7714 sequential numbering: `ORDER_JUMP`, `ORDER_INVERT` (a lower number appearing after a higher one — i.e. not ordered by first mention), `ORPHAN_LIST`, `ORPHAN_TEXT`, `COUNT_MISMATCH`, and `SYNC_DIVERGE` between a `.md` draft and its `.docx` twin. Reads `.docx` through `zipfile`, no `python-docx` needed. |
| `check_reference_duplication.py` | Duplicated reference lists in pandoc/citeproc builds (a `[@key]` bibliography plus a hand-written one). English-oriented. |
| `check_citation_order.py` | Table/Figure citation order for English journals — a routine technical-check rejection reason. |
| `check_cross_artifact_stale.py` | Retired values and retired wording surviving anywhere across manuscript + supplements. You pass the strings that *should be gone* via `--old-value` / `--retired-term`. |
| `check_placeholders.py` | `TODO` / `FIXME` / `TBD` / `XXX`, AI-disclosure template tokens, template URLs, and the Chinese `占位待核` marker. |
| `check_embedded_figures.py` | Whether the figure embedded in the `.docx` is byte-identical (SHA-256) to what the plotting pipeline last wrote. Catches "redrew the figure, forgot to re-embed". Also flags orphan and unreferenced media. |

### Statistical table consistency

These exploit the fact that the columns of a results table are not independent numbers — they are determined by one another.

| Script | What it catches |
|---|---|
| `check_regression_table.py` | `OR = exp(β)`, `Wald = (β/SE)²`, `95%CI = exp(β ± 1.96·SE)`, and CI↔P coherence. Notably it **localizes** the error: by computing the geometric midpoint `sqrt(lo·hi)` of the printed CI, it can tell whether β/SE/CI form a self-consistent set and the `OR` column alone was mistyped, or the reverse. |
| `check_ratio_columns.py` | Ratio biomarkers (NLR, PLR, MLR, LMR, MHR, NHR, LHR, CAR, WHR, AIP) filled in as a quotient of group means. The criterion runs **opposite to intuition**: an exact match between the tabulated ratio and mean(X)/mean(Y) is the *failure* signal, since by Jensen's inequality E[X/Y] ≠ E[X]/E[Y]. Also checks SD against the delta-method lower bound. |
| `check_diagnostic_metrics.py` | `RATE_UNREACHABLE` (a proportion not expressible as k/n for the stated integer denominator), Youden index, accuracy vs. sensitivity/specificity reweighted by group sizes, and AUC ± 1.96·SE against the printed CI. Tolerances scale to the reported precision. |
| `check_correlation_table.py` | Monotonicity of \|r\| against P (a mathematical necessity at fixed n — and it needs no sample size to check), recomputation of P from (r, n), and near-duplicate rows **and** columns. |
| `check_stat_recompute.py` | p recomputed from test statistic + df (statcheck-style), with t/F/χ²/normal CDFs implemented in-file. `P_DECISION` — where the recomputed and reported p straddle α, flipping the significance claim — is the finding that matters most. Optional GRIM check for integer-valued measures. |
| `check_reported_p_from_counts.py` | p recomputed from 2×2 counts via Fisher / Pearson χ² (±Yates), after calibrating which test family the manuscript used. Complements the above: it handles baseline-table rows that report only `n(%)` and P. |
| `check_table_percentages.py` | `n (p%)` cells recomputed against the column denominator, recovered from an `n = N` header, a Total row, or the column sum. |
| `check_rounded_delta.py` | A stated difference that does not equal the difference of the two displayed values. Minor-only by design — never fails `--strict`. |

### Design and reporting coherence

| Script | What it catches |
|---|---|
| `check_cohort_arithmetic.py` | STROBE exclusion cascades (start − Σexclusions = final), rate back-calculation, stratum partitions summing to the total, and undisclosed analysis units when records outnumber unique subjects. |
| `check_confounding_completeness.py` | Data-driven residual confounding: a variable that was measured, is imbalanced across exposure groups (P<0.05 or SMD>0.1), and is nevertheless absent from the adjustment set. Requires joining Table 1 against the covariate list — invisible to any prose-only read. `--exposure-defining-list` exempts variables that constitute the exposure definition itself, where adjustment would be overadjustment. *(This is the one script without `--quiet`.)* |
| `check_binning_consistency.py` | Cut-point drift across analysis scripts — the same derived grouping (quartiles, age bands, eGFR stages) cut differently in the primary and sensitivity scripts. Strata counts diverge silently while the total still reconciles. Parses R `cut()` / `case_when` and Python `pd.cut`. |
| `check_scope_coherence.py` | Longitudinal claims (prognosis, surveillance, "predicts future events") in a cross-sectional design. Hedged sentences are correctly left alone. |
| `check_revision_claims.py` | Bidirectional verification of "we changed X" assertions in a revision letter, back against the revised manuscript. Each claim declares its polarity explicitly — `in:` (must appear) / `out:` (must be gone) / `where:` (body or letter). Reports `CLAIM_MISSING` and `CLAIM_STALE`. |
| `check_response_claims.py` | The English-language counterpart: extracts anchored "we have added…" assertions from a response letter automatically. See the language note below. |

## Design principles

The project takes one position that shapes everything else: **a gate that has never fired is not evidence.**

1. **Every checker must be shown to fire before it is trusted.** A newly written or newly ported checker that passes on the first run is treated as suspect until a known defect has been injected and observed to trigger it. Four checkers ported from upstream were rejected on exactly this basis — they never fired on Chinese-language input, which would have made them silent no-ops that still increased the apparent count of checks being run.

2. **A checker's search strings must not come from the edit that is being checked.** If a stale-value scan reuses the find-strings from the revision itself, it inherits the same blind spot and validates itself. So the scanners take the *retired values* as input and scan for those, with an explicit allowlist for legitimate reuse.

3. **Reverse-validation.** For the four statistical-table checkers, each core criterion was individually replaced with a never-true condition to confirm the corresponding test case turns red. This caught a real gap: `check_correlation_table` has two code paths producing `R_P_MISMATCH`, so breaking one left the other still firing, and the suite stayed green. Breaking the enclosing loop was required to make it fail. An indecisive defect injection produces a green run that carries no information.

4. **No universal claims.** Passing means "the errors I anticipated did not occur", not "the manuscript is correct". The output wording reflects that.

The criteria in the four statistical-table checkers were not designed from first principles. They were derived by hand-recomputing 12 published Chinese cardiology papers; every rule corresponds to an error actually found in that set.

## Tests

```bash
cd challenge
python run_challenge.py --python /path/to/python
```

27 defect-injection cases: each asserts that a seeded defect fires, that a clean control stays silent, and that the `--strict` exit code matches each checker's severity design. They cover 8 of the 20 checkers — the four most recently written and the four most recently ported. The remaining 12 have been exercised on real manuscripts but do not yet have fixtures in this harness. Contributions there are welcome.

Fixture content is drawn from real published tables, not synthesized examples.

## Scope and limitations

Stated plainly, because a checker whose limits are unclear is worse than none:

- **This does not verify that references exist.** No network access, by design. Authenticity, author lists, and journal names need a separate online tool.
- **It does not read text inside figures.** `check_embedded_figures.py` answers "is the embedded image the latest one", not "are the numbers printed in it right". Text rendered into pixels is invisible to every text-based gate; those must be checked by opening each figure.
- **Language coverage is uneven, and each script says which case it serves.** `check_citation_order` and `check_reference_duplication` are English-oriented. `check_response_claims` extracts English claim verbs only and will find nothing in a Chinese letter — use `check_revision_claims` there. `check_scope_coherence` has Chinese wording for one of its five rules.
- **`check_gbt7714_order` needs bracketed citations.** Superscript numerals in a rendered `.docx` cannot be reliably distinguished; run it on the bracketed Markdown draft.
- **`check_stat_recompute` cannot work without degrees of freedom.** The common Chinese style `t=2.34, P<0.05` is skipped rather than guessed at — no extraction, no false alarm.

## Attribution and license

MIT. 12 of the 20 checkers are ported from [Aperivue/medsci-skills](https://github.com/Aperivue/medsci-skills) (MIT, Copyright (c) 2026 Aperivue); 8 are original to this repository. Per-file provenance, the extent of local modification, and the upstream license text are in [NOTICE.md](NOTICE.md).

`check_stat_recompute.py` acknowledges statcheck (Nuijten et al. 2020) and GRIM (Brown & Heathers 2017) as methodological influences; no source code was copied from either.
