# medsci-audit

医学稿件投稿前的确定性离线自检，对中文期刊为一等公民。

20 个独立检测器，纯 Python 标准库——不依赖 NumPy / SciPy / pandas，不联网。每个脚本都能单独跑，`--strict` 下有 Major 即退出码 1，可直接挂进 pre-commit 或 CI。

[English README](README.md)

---

## 它针对哪一类错误

有一类稿件错误在算术上完全可判，却几乎从来没人查——因为手工查太琐碎，而且每个人都默认上游已经查过了。它们能挺过多轮返修，恰恰是因为看上去已成定局：

- 回归表的 `OR` 列是手敲进去的，早已不等于 `exp(β)`。
- 比值型指标（NLR、MHR、PLR、AIP）的组均值是拿「分子均值 ÷ 分母均值」填的——个体层面的比值从未被算过，其后所有相关分析随之失效。
- 测试集只有 17 个事件却报灵敏度 72.00%：分母是整数，比例只能取 k/17，而 0.72×17 = 12.24 不是整数。
- 插入一条文献后没有整体重排，正文编号从 `[8]` 直接跳到 `[13]`。
- 某个数在摘要和讨论里改了，表格单元格和逐点回复信里还是旧值。

这些都不需要原始数据，光看稿件就能判定。

## 快速开始

```bash
git clone https://github.com/hhg36355-hue/medsci-audit.git
cd medsci-audit
python scripts/check_gbt7714_order.py --manuscript 论著.md --strict
```

无需安装、无需装包。Windows 建议先设 `PYTHONUTF8=1`，否则控制台中文会乱码。

所有脚本都支持 `--out FILE.json` 写工件、`--strict`（有 Major 退 1）、`--quiet`（仅一个例外，见下）。

## 检测器清单

### 文献与跨副本一致性

| 脚本 | 抓什么 |
|---|---|
| `check_gbt7714_order.py` | GB/T 7714 顺序编码制：`ORDER_JUMP`（断档跳号）、`ORDER_INVERT`（小编号后出现＝未按首次出现排序）、`ORPHAN_LIST`、`ORPHAN_TEXT`、`COUNT_MISMATCH`，以及 md↔docx 两副本的 `SYNC_DIVERGE`。docx 用标准库 `zipfile` 直接解，不需要 python-docx。 |
| `check_reference_duplication.py` | pandoc/citeproc 构建稿的参考文献重复列表（`[@key]` 渲染一份 + 手写一份）。偏英文。 |
| `check_citation_order.py` | 英文期刊的 Table/Figure 引用顺序——编辑部技术核查项，乱序会被退回。 |
| `check_cross_artifact_stale.py` | 旧值 / 旧措辞在正文与补充材料里的跨文件残留。把本轮**应当消失**的串用 `--old-value` / `--retired-term` 传进去。 |
| `check_placeholders.py` | `TODO` / `FIXME` / `TBD` / `XXX`、AI 披露模板 token、模板 URL，以及中文的 `占位待核`。 |
| `check_embedded_figures.py` | docx 里嵌的图，与绘图管线最后写出的那张是否字节一致（SHA-256）。堵"重绘了但没嵌入"。另报孤儿图片与未被引用的图片。 |

### 统计表格的内部恒等关系

这一层利用的事实是：结果表的各列不是几个独立的数，而是互相决定的。

| 脚本 | 抓什么 |
|---|---|
| `check_regression_table.py` | `OR=exp(β)`、`Wald=(β/SE)²`、`95%CI=exp(β±1.96·SE)`，以及 CI↔P 的自洽性。**它还能定位是哪一列错**：算报出 CI 的几何中点 `sqrt(lo·hi)`，若它等于 `exp(β)` 而不等于印出的 OR，就能断定 β/SE/CI 是一套自洽输出、OR 列单独填错；反之则 β 列可疑。 |
| `check_ratio_columns.py` | 比值型指标（NLR/PLR/MLR/LMR/MHR/NHR/LHR/CAR/WHR/AIP）被误用「分子均值÷分母均值」填表。**判据方向与直觉相反**：表里的比值恰好等于两组均值之商，才是失败信号——由 Jensen 不等式 E[X/Y] ≠ E[X]/E[Y]，逐人算比值再求均值不可能连续多行精确吻合。另查 SD 是否低于 delta 法下界。 |
| `check_diagnostic_metrics.py` | `RATE_UNREACHABLE`（给定整数分母下该比例根本取不到）、约登指数、准确率与灵敏度/特异度按两组人数的加权关系、AUC±1.96·SE 与印出 CI 的对照。容差按报告精度自动缩放。 |
| `check_correlation_table.py` | 同一样本量下 \|r\| 与 P 的单调性（数学必然，**连样本量都不用给**）、由 (r, n) 反算 P、以及**行与列两个方向**的整行/整列雷同。 |
| `check_stat_recompute.py` | 由「检验统计量 + 自由度」反算 p（statcheck 思路），t/F/χ²/正态 CDF 在文件内自实现。最该看的是 `P_DECISION`——反算 p 与报告 p 落在 α 两侧，显著性结论会翻。可选 GRIM（仅整数型变量有意义）。 |
| `check_reported_p_from_counts.py` | 由 2×2 计数用 Fisher / Pearson χ²(±Yates) 反算 P，先在能复现的行上校准全稿检验族。与上一个互补：吃的是中文基线表那种只写 `n(%)` 和 P、不写统计量的行。 |
| `check_table_percentages.py` | 三线表 `n (p%)` 单元格按列分母重算。分母按「`n = N` 表头 → Total 行 → 列内计数求和」三级恢复。 |
| `check_rounded_delta.py` | 声称的差值 ≠ 两个展示值相减。按设计只报 Minor，**永远不会**让 `--strict` 退 1。 |

### 设计与报告的自洽性

| 脚本 | 抓什么 |
|---|---|
| `check_cohort_arithmetic.py` | STROBE 排除级联（起始 − Σ排除 = 最终）、率的反算、分层 N 求和等于总计、以及记录数多于唯一受试者数却未声明分析单元。 |
| `check_confounding_completeness.py` | 数据驱动的残余混杂：一个变量既被测了、在暴露分组间又不平衡（P<0.05 或 SMD>0.1）、却不在调整集里。必须把 Table 1 与协变量清单 join 起来才看得见，纯读正文永远发现不了。`--exposure-defining-list` 豁免"属于暴露自身诊断标准"的变量——调它们是过度调整。*（这是唯一没有 `--quiet` 的脚本。）* |
| `check_binning_consistency.py` | 跨脚本的切点漂移：同一个派生分组（四分位、年龄段、eGFR 分期）在主分析和敏感性分析里各切一次且不一致。各表分层 N 悄悄不同，而总数仍然对得上，所以行和核对抓不到。认 R 的 `cut()` / `case_when` 与 Python 的 `pd.cut`。 |
| `check_scope_coherence.py` | 横断面设计却在讨论/结论里做预后、随访监测、"预测未来事件"一类纵向主张。**正确对冲过的句子不开火**。 |
| `check_revision_claims.py` | 返修信里每条"已改"断言回稿件的**双向核验**。每条断言显式声明极性：`in:`（应出现）/ `out:`（应消失）/ `where:`（正文或回复信）。报 `CLAIM_MISSING` 与 `CLAIM_STALE`。 |
| `check_response_claims.py` | 英文版对应物，自动抽取回复信里带锚点的 "we have added…" 类断言。语言限制见下。 |

## 设计原则

整个项目建立在一个立场上：**从未开过火的门禁，不构成证据。**

1. **任何检测器在被信任之前，必须先被看到会开火。** 新写或新移植的检测器如果第一次跑就全绿，一律视为可疑，直到植入一个已知缺陷并观察到它触发。从上游移植的一批里有 4 个正是因此被拒——它们在中文输入上永不开火，装进来就是"计数了却从不运行"的空检测器，还会虚增"已跑检查数"。

2. **检测器的扫描串不能取自被检查的那次修改。** 旧值扫描若复用改稿时的查找串，就继承了同一个盲区，等于自己验证自己。所以扫描器接收的是**退役值本身**，并对合法复用用显式白名单排除。

3. **反向验证。** 四个统计表格检测器的每一条核心判据，都被单独替换成永不成立的条件，确认对应用例会变红。这抓到一个真实的洞：`check_correlation_table` 的 `R_P_MISMATCH` 有两条产出路径，只打断一条，另一条照样开火、套件保持全绿；换成打断整个判据循环才变红。**植缺陷不够决定性时，"仍然全绿"是一条无信息的观察。**

4. **不做全称断言。** 通过只说明"我预想到的错误没发生"，不说明"稿件是对的"。输出用语按此写。

四个统计表格检测器的判据不是设想出来的，而是逐篇手工复算 12 篇已发表的中文心血管论文时**实际抓到的错误**——每一条判据都对应那批稿件里的一个真实错误。

## 测试

```bash
cd challenge
python run_challenge.py --python /path/to/python
```

27 个植缺陷用例：每个都断言「植入的缺陷会开火 / 干净对照保持静默 / `--strict` 退出码符合该检测器自身的严重度设计」。它们覆盖 20 个检测器中的 8 个——最近写的四个和最近移植的四个。其余 12 个已在真实稿件上用过，但尚未有夹具进这套 harness，欢迎补。

夹具正文取自真实发表的表格，不是构造出来的假例子。

## 适用范围与局限

明确写出来，因为一个说不清自己边界的检测器比没有更糟：

- **它不核实文献是否真实存在。** 按设计不联网。真伪、作者列表、刊名需要另外的联网工具。
- **它读不了图内文字。** `check_embedded_figures.py` 回答的是"嵌进去的是不是最新那张"，不是"图里印的数对不对"。渲染成像素的文字对任何文本门禁都不可见，只能逐张打开人工核。
- **语言覆盖不均，每个脚本都注明自己服务哪一侧。** `check_citation_order` 和 `check_reference_duplication` 偏英文；`check_response_claims` 只抽英文断言动词，对中文回复信抽 0 条——中文请用 `check_revision_claims`；`check_scope_coherence` 五条判据里只有一条补了中文口径。
- **`check_gbt7714_order` 需要方括号引用。** docx 渲染后的上标数字无法可靠识别，请在带方括号的 Markdown 底稿上跑。
- **`check_stat_recompute` 没有自由度就算不了。** 中文常见的 `t=2.34, P<0.05` 不写 df，它跳过而不猜——不抽取，也不误报。

## 来源与许可

MIT。20 个检测器里 12 个移植自 [Aperivue/medsci-skills](https://github.com/Aperivue/medsci-skills)（MIT，Copyright (c) 2026 Aperivue），8 个为本仓库原创。逐文件的来源、本地改动幅度、以及上游许可全文见 [NOTICE.md](NOTICE.md)。

`check_stat_recompute.py` 致敬 statcheck（Nuijten et al. 2020）与 GRIM（Brown & Heathers 2017）的方法思路，未复制任何一方的源码。
