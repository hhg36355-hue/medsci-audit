# Third-party sources and licensing

## Ported detectors

The following detectors are **ported from**
[Aperivue/medsci-skills](https://github.com/Aperivue/medsci-skills)
(MIT License, Copyright (c) 2026 Aperivue), preserving the upstream file
headers and logic:

| File in this repo | Upstream location | Local changes |
|---|---|---|
| `scripts/check_cohort_arithmetic.py` | `skills/self-review/scripts/check_cohort_arithmetic.py` | none |
| `scripts/check_reference_duplication.py` | `skills/manage-refs/scripts/check_reference_duplication.py` | none |
| `scripts/check_placeholders.py` | `skills/write-paper/scripts/check_placeholders.py` | added Chinese placeholder token and Chinese "参考文献" heading detection |
| `scripts/check_citation_order.py` | `skills/self-review/scripts/check_citation_order.py` | none |
| `scripts/check_table_percentages.py` | `skills/self-review/scripts/check_table_percentages.py` | none |
| `scripts/check_reported_p_from_counts.py` | `skills/self-review/scripts/check_reported_p_from_counts.py` | none |
| `scripts/check_cross_artifact_stale.py` | `skills/sync-submission/scripts/check_cross_artifact_stale.py` | none |
| `scripts/check_response_claims.py` | `skills/revise/scripts/check_response_claims.py` | none |
| `scripts/check_binning_consistency.py` | `skills/self-review/scripts/check_binning_consistency.py` | byte-identical apart from two provenance comment lines |
| `scripts/check_confounding_completeness.py` | `skills/self-review/scripts/check_confounding_completeness.py` | 11 lines: `_norm()` now preserves CJK code points and drops full-width parenthetical units |
| `scripts/check_scope_coherence.py` | `skills/self-review/scripts/check_scope_coherence.py` | 28 lines: Chinese wording added for the `CROSS_SECTIONAL_PROGNOSTIC` rule only |
| `scripts/check_rounded_delta.py` | `skills/self-review/scripts/check_rounded_delta.py` | 16 lines: Chinese comparison words / delta labels / full-width punctuation |

Upstream license text is reproduced below.

## Original detectors

The following are original to this repository, not ported:

`check_gbt7714_order.py`, `check_stat_recompute.py`, `check_revision_claims.py`,
`check_embedded_figures.py`, `check_regression_table.py`, `check_ratio_columns.py`,
`check_diagnostic_metrics.py`, `check_correlation_table.py`

`check_stat_recompute.py` acknowledges two published methods as **conceptual**
influences (no source code was copied from either):

- statcheck — Nuijten et al., *Research Synthesis Methods* 2020;
  R package `MicheleNuijten/statcheck` — recomputing p from test statistic + df.
- GRIM — Brown & Heathers 2017 — whether a reported mean is arithmetically
  possible given an integer sample size.

The t / F / chi-square CDFs used by `check_stat_recompute.py`,
`check_correlation_table.py` and `check_diagnostic_metrics.py` are implemented
in-file via incomplete beta / gamma functions (standard Numerical Recipes
algorithms, public domain methods), so that the package has no SciPy or NumPy
dependency.

---

## Upstream license (Aperivue/medsci-skills)

MIT License

Copyright (c) 2026 Aperivue (https://aperivue.com)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
