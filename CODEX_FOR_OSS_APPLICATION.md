# Codex for Open Source: public application materials

Prepared on 2026-10-01 (America/Los_Angeles). This is an applicant-prepared summary for [OpenAI's Codex for Open Source program](https://developers.openai.com/community/codex-for-oss), not a selection notice or endorsement. The statements reflect evidence available when this file was prepared.

## Project and maintainer

- **GitHub username:** `hhg36355-hue`
- **Public repository:** https://github.com/hhg36355-hue/medsci-audit
- **Maintainer role to select:** Primary maintainer. The account owns the repository and authored its initial public commit.
- **License:** MIT, with upstream attribution in [NOTICE.md](NOTICE.md).
- **Purpose:** Deterministic, offline pre-submission checks for medical manuscripts, with Chinese-language journal support.

### Describe your role

I own medsci-audit and am its primary maintainer. I published the initial public release and am responsible for the repository's code, documentation, attribution, and future issue and release decisions. The public repository does not yet show post-release maintenance or PR review activity.

### Why does this repository qualify? (476 / 500 characters)

medsci-audit offers 20 offline, Python-standard-library checks for medical manuscripts, including Chinese-journal workflows. It checks reference order, statistical-table arithmetic, and stale values across files without uploading manuscripts. The MIT-licensed repo credits 12 checks ported from Aperivue/medsci-skills and identifies 8 original checks. I own the repo and published its initial release. This focused quality-control tool has no documented external adoption yet.

The project has a focused use case. The public record does not yet establish broad adoption or sustained post-release maintenance.

## Public evidence

1. [README.md](README.md) documents 20 standalone Python-standard-library checkers for reference order, reported statistics, and consistency across manuscript files. The scripts do not require network access.
2. [NOTICE.md](NOTICE.md) identifies 12 checkers ported from [Aperivue/medsci-skills](https://github.com/Aperivue/medsci-skills) and 8 described as original to this repository, with per-file provenance. This packet relies on that attribution; it does not independently certify each script's originality.
3. [challenge/README.md](challenge/README.md) documents 27 defect-injection cases covering 8 checkers. These repository-described cases were not re-run solely to prepare this packet.
4. The [initial public commit](https://github.com/hhg36355-hue/medsci-audit/commit/f2ee98f577144420b6b2f6a0adf90ab8db2c8c08) supports the publication role. Use the live [commits](https://github.com/hhg36355-hue/medsci-audit/commits/main), [issues](https://github.com/hhg36355-hue/medsci-audit/issues), [PRs](https://github.com/hhg36355-hue/medsci-audit/pulls), and [releases](https://github.com/hhg36355-hue/medsci-audit/releases) to assess subsequent maintenance.
5. No external users, downloads, or independent deployments were documented for this application at preparation. Upstream adoption and the repository's own tests are not external adoption evidence.

## Optional API credits request

This is a proposed use, not an existing deployment. API credits are an additional, discretionary benefit under the [program terms](https://learn.chatgpt.com/docs/codex-for-oss-terms).

### How will you use API credits for your project? (445 / 500 characters)

If awarded API credits, I would prototype optional, maintainer-reviewed PR workflows that explain findings from the deterministic checkers, help triage issues, and draft release notes. Checker output would remain the source of each finding, with human review before code changes or publication. This is a proposed workflow, not an existing deployment. I would begin with public test fixtures rather than confidential manuscripts or patient data.

## Private fields to enter directly in OpenAI's form

The [official application form](https://openai.com/form/codex-for-oss/) asks for the applicant's name, the email associated with their ChatGPT account, and an OpenAI Organization ID where applicable. These values are absent from this public repository. Review the current form before submitting; OpenAI decides whether to provide any benefit.

