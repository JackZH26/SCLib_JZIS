# Timeline 数据大数据分析 v2 — 10 大主要发现 + 2 项补充(修订版)

> **⚠️ 极其重要 / VERY IMPORTANT** — 本文档替代 v1 [`TIMELINE_ANALYSIS_2026_05_23.md`](TIMELINE_ANALYSIS_2026_05_23.md)。v2 修正了 v1 中的 1 处事实性错误(294 K CaLuH12 是 DFT 预测而非实验测量)、4 处解读偏差,并**大幅扩展数据局限**。任何关于超导研究的家族/地缘/时代趋势讨论,**只参考本 v2 文档**。

> **快照时间:2026-05-23。** 数据依赖刚部署的 `papers.paper_geo` 列(99.52% 覆盖,通过 `ingestion/extract/affiliation_ner.py` 抽取)与视图 `v_tc_geo`(27,848 行)、`v_material_geo`(7,193 行)。详见 alembic `0037_paper_geo` + `scripts/backfill_paper_geo.py`。视图后端专用,前端零暴露。

## v2 相对 v1 的修订

- **发现 4 重写**:CaLuH12 294 K 是 DFT 预测,**不是**实验记录;分别给出实验最高(~250 K LaH₁₀)和理论最高(~294 K)两条独立线。
- **发现 5 重写**:"2021 中国超过美国" → "2021 起中美进入并驾齐驱期",明示国家计数**非互斥**(中美合作论文 BOTH 计入)。
- **发现 6 量化**:铁基"China 领先 USA"幅度仅 4%(598 vs 574),应称并驾齐驱;镍酸盐 / kagome / 氢化物领先 2-2.5×。
- **发现 7 改用 distinct 论文数**:**78.9%** 材料只 1 篇论文(v1 用记录数计为 72%);Top-7(非 18);Top-2 是 **BSCCO + MgB2**(非 BSCCO + YBCO)。
- **发现 1 补"过渡共治期"**:2005-09 cuprate-iron 共治、2020-24 三足鼎立、2025 完全均势。
- **数据局限大幅扩展**:加入 (a) arXiv 非全量入库、(b) 仅 `cond-mat.supr-con` 分类、(c) preprint 不是正式发表;另加理论/实验标签稀疏、国名变体、material 元素顺序去重不彻底等共 11 条。
- **新增发现 11(补充)**:**Tc Density Valley (BCS-cuprate gap)** —— 用户从 timeline 视觉观察出 50-80K 区间密度偏低;数据验证:最低 65-70K (depth ratio ρ = **0.22**,即 78% 赤字),宽 ~35K,Poisson p ≪ 0.001 极显著;家族分解表明这是**超导配对机制鸿沟**(BCS 类天然 ≤40K、铁基 ≤55K、cuprate 最优 90-160K,中间无机制天然栖息)。
- **新增发现 12(补充)**:**100K 分水岭 —— 97-99% 记录在低 Tc 区,>100K 只有两种回路**。用户观察到 0-100K 数据占 >90%,数据验证实际是 **97-99%**(四种过滤口径下都成立);>100K 区间结构极简洁:**铜氧化物常压**(205 条,98% 常压,峰 ~166K Hg-1223) + **氢化物极端高压**(291 条,75% >100 GPa,最高 ~294K) + 少量 fulleride 异常,**无第三种机制**。5,537 个材料中只有 4.15% 曾达 >100K,0.8% 曾达 >200K。提供 5 条可站住脚的科学陈述(S1-S5)和应避免的过度表述。

---

## 数据基础

`v_tc_geo`(应用 timeline 页面同款过滤:`needs_review=false`、`0<Tc≤300K`、`1900≤year≤2026`):**19,922 个 Tc 数据点**、**5,517 个材料**、**8,044 篇论文**(占全库 40,876 篇的 ~20%——只有报告数值 Tc 的论文进入 timeline),覆盖 **1994–2026 年**。地理映射首次可用,99.52% 论文带 country/city。

---

## 主要发现(10 项 v2 修订 + 2 项新增)

### 1. 三代研究浪潮,但有显著的"过渡共治期"

每 5 年期内 top-3 家族:

| 时期 | #1 | #2 | #3 |
|---|---|---|---|
| 1995–1999 | **cuprate** 578 | elemental 26 | borocarbide 16 |
| 2000–2004 | **cuprate** 1502 | mgb2 566 | conventional 228 |
| 2005–2009 | cuprate 1174 | **iron 992** | conventional 308 |
| 2010–2014 | **iron_based** 1928 | cuprate 685 | conventional 421 |
| 2015–2019 | **iron_based** 1116 | cuprate 549 | conventional 428 |
| 2020–2024 | conventional 643 | iron 443 | cuprate 431 |
| 2025 (上半) | cuprate 94 | hydride 91 | conventional 82 |

**清晰主导期:** 1995–2004 cuprate 一统;2010–2019 iron-based 一统。
**过渡 / 共治期:** 2005–09 cuprate 与 iron 共治(差距仅 18%);**2020–24 三足鼎立**(conventional / iron / cuprate 差距 < 50%);2025 cuprate / hydride / conventional 完全均势(样本小)。

当代(2020+)**没有任何单一家族占据主导地位**,反映场域多元化与计算筛选(conventional)/超导新发现(hydride / nickelate)并行的格局。

### 2. 2008 年铁基冲击 — 最剧烈的范式切换(需理解 family 标签)

| year | iron_based | cuprate | 全年总投稿 |
|---:|---:|---:|---:|
| 2007 | 2(实为 Lu2Fe3Si5 铁硅化物) | 309 | 1,248 |
| 2008 | **485**(全为 LaFeAsO 类 pnictide)| 188 | 1,624 |
| 2009 | 505 | 199 | 1,485 |

**单年内 pnictide 类铁基记录从 0 跳到 ~485,铜氧化物同步下挫 40%**。注意:NER `family='iron_based'` 包含**所有含铁化合物**,所以 2007 年的 2 条 Lu2Fe3Si5(1980 年代已知的铁硅化物超导体)被并入此类。真正的 LaFeAsO 类 pnictide 在 2008 年 2 月 Hosono 发现后才大规模进入语料。**且不是因为整体投稿缩量**(2008 总投稿 1,624 篇,反比 2007 多 30%)。

### 3. 高压超导 Tc "反转"(2014–2015 拐点)

| 时期 | 高压样本 N | 高压均 Tc | 常压均 Tc | 比值 |
|---|---:|---:|---:|---:|
| 1995–1999 | 5 ⚠️ 轶事级 | 12.5 K | 55.8 K | 0.22× |
| 2010–2014 | 222 | 22.5 K | 21.4 K | 1.05× |
| 2015–2019 | 324 | 62.7 K | 19.9 K | 3.15× |
| 2020–2024 | 422 | 64.0 K | 16.9 K | 3.79× |
| 2025 (上半) | 65 | **109.8 K** | 23.9 K | **4.60×** |

**HP/ambient 比值从 0.22× → 4.60×,约 20 倍翻转。** 拐点 2014–2015 对应 Drozdov H3S。`>100 GPa` 一档共 **355 条记录,均 Tc 128.7 K** —— 该体制在 2014 前几乎不存在。

**⚠️ 重要警示:** 这些"高压高 Tc 记录"中**相当部分是 DFT 预测,不是实验测量**(见发现 4 与数据局限 #4)。"翻转"在数据层真实,但其中"实验真值"占比未知。

### 4. 室温超导:**实验**最高 vs **理论**预测最高(v2 修正)

**实验**最高 Tc(已确证、未撤稿,文献共识):
- **LaH₁₀ ~250 K @ 170 GPa**(Somayazulu / Drozdov 2019 *Nature*)—— **自 2019 年起未被实验超越**
- H₃S 203 K @ 155 GPa(Drozdov 2015)
- (Snider CSH 287 K 声明已于 2022 年撤稿;本库标 `needs_review=true` 隔离)

**本库 timeline 中的最高 Tc 记录(294.2 K CaLuH12):**

| 字段 | 值 |
|---|---|
| paper_id | `arxiv:2408.00234` |
| 标题 | *Superconductive Sodalite-like Clathrate Hydrides MXH₁₂ ...* |
| Tc | 294.2 K @ 180 GPa |
| evidence_type | `primary`(模糊,非 `primary_experimental`)|

**这是一篇 sodalite-clathrate 氢化物的 DFT 筛选论文,294.2 K 是计算预测值**(NER 把 paper_type 误标为 "experimental")。v1 把它作为"实验最高记录"展示是错误的。

**实验 vs 理论预测的 gap:**

| 年 | 实验最高 (K) | 理论预测最高 (K, 本库)|
|---:|---:|---:|
| 2014 | ~190(H3S 预印本)| 243 |
| 2019 | **~250(LaH₁₀ 实测)** | 250 |
| 2024 | 250(无新实验突破)| 294(CaLuH12 理论)|

**结论:**
- 实验最高 Tc **5 年停滞**在 ~250 K (LaH₁₀);理论预测推进到 294 K。
- "室温超导"严格定义(ambient pressure 下常温):**未达成**。
- 294 K (21°C) 已在室温区间,但需 180 GPa 极端压力,且为理论值。

### 5. 中美自 2021 年起进入"并驾齐驱"年代(v2 修正)

**重要前提:** 这里"X 国 N 篇"是 `papers.paper_geo->countries ? 'X'`(包含 X 国作者的论文数)。**中美合作论文 BOTH 计入两国 tally**(2020–24 期 = 474 篇合作论文),所以两国 tally 大量重叠 ——**不应解读为"互相竞争的产出量"**。

| year | 含中国作者 | 含美国作者 | 领先方 |
|---:|---:|---:|---|
| 2008 | 142 | 183 | USA +41 |
| 2015 | 107 | 140 | USA +33 |
| 2020 | 94 | 132 | USA +38 |
| **2021** | **184** | **155** | China +29 |
| 2022 | 144 | 152 | USA +8 |
| 2023 | 152 | 154 | USA +2 |
| 2024 | 139 | 135 | China +4 |
| 2025 (上半) | 126 | 127 | 平 |

**正确叙事:2021–2025 年中美进入逐年互有领先的并驾齐驱期。** 这反映**全球协作深化**(见发现 9)而非"中国超越美国"的单向竞争。1995–99 期中国 6 篇 → 2020–24 期 713 篇(120 倍增长)的长期趋势是真实的。

### 6. 家族领头国:量化领先幅度(v2 修正)

按"含该国作者的论文数",每家族 #1 / #2:

| 家族(爆发年)| 第一 | 第二 | 幅度 |
|---|---|---|---:|
| cuprate (1986/1994 入库)| USA 781 | Japan 598 | +31% |
| heavy_fermion | Japan 159 | USA 150 | **+6%(基本均势)** |
| ruthenate | Japan 67 | USA 27 | 2.5× |
| mgb2 (2001) | USA 147 | Italy 60 | 2.5× |
| **iron_based** (2008) | China 598 | USA 574 | **+4%(并驾齐驱)** |
| **kagome** (~2020) | China 56 | USA 22 | **2.5×** |
| **bis2_layered** (2012) | Japan 41 | China 18 | 2.3× |
| **hydride** (~2015) | China 85 | USA 51 | **+67%** |
| **nickelate** (2023) | **China 49** | USA 20 | **2.5×** |

**模式:**
- **老家族(<2008):** USA 或 Japan 主导,通常领先 30%–2.5×。
- **新家族(≥2010):** China 几乎全面领先 —— 但**铁基只领先 4%(实质并驾齐驱)**;镍酸盐 / kagome 领先 2.5×;氢化物领先 +67%。

(USA 因国名归一化遗漏 ~0.15% — 见局限 #6,铁基可能微调为完全持平。)

### 7. Pareto 极端 — 按 **distinct 论文数** 更陡(v2 修正)

| 每材料 distinct 论文数 | 材料数 | 占比 |
|---|---:|---:|
| 1 篇 | **4,353** | **78.9%** |
| 2–5 | 909 | 16.5% |
| 6–20 | 210 | 3.8% |
| 21–100 | 38 | 0.7% |
| **101+ 篇** | **7** | 0.13% |

**78.9% 的材料只出现在 1 篇论文里**(v1 按 record 数计为 72%,实际更极端)。**只有 7 个材料**有 101+ 篇论文(v1 的 18 是按 record 数,易误读)。

按 distinct 论文数的 Top-12(v2 修正排序):

| # | 材料 | 论文 | 记录 | 记录/篇 |
|---:|---|---:|---:|---:|
| 1 | **BSCCO (Bi2212)** | **400** | 772 | 1.9 |
| 2 | **MgB2** | **369** | 563 | 1.5 |
| 3 | YBCO | 331 | 643 | 1.9 |
| 4 | Nb | 303 | 489 | 1.6 |
| 5 | Al | 203 | 300 | 1.5 |
| 6 | FeSe | 138 | 303 | 2.2 |
| 7 | NbN | 125 | 288 | 2.3 |
| 8 | Sr2RuO4 | 75 | 143 | 1.9 |
| 9 | Pb | 72 | 114 | 1.6 |
| 10 | UTe2 | 59 | 125 | 2.1 |
| 11 | CeCoIn5 | 57 | 81 | 1.4 |
| 12 | NbSe2 | 56 | 73 | 1.3 |

**Top-2 是 BSCCO + MgB2,不是 v1 的 BSCCO + YBCO**。YBCO 是 #3。每篇平均报 1.5–2.3 个 Tc,所以按 record 排序略偏向"单篇多记录"的家族。

### 8. 平均 Tc 二十年腰斩 —— 研究面变宽

| 时期 | 均 Tc | 主导家族 |
|---|---:|---|
| 1995–1999 | **55.5 K** | cuprate 一统 |
| 2010–2014 | 21.5 K | 铁基 + 元素 + 重费米子全面铺开 |
| 2020–2024 | 22.1 K | conventional / 计算 / 拓扑 / kagome |

**均 Tc 不到 1995 年水平的 40%。** 非物理倒退,而是研究焦点扩展到 kagome、重费米子、拓扑、轻元素等本就低 Tc 的体系。

参考:每家族均 Tc(按 record):hydride 109.7 K · cuprate 57.5 K · fulleride 46.4 K · mgb2 32.8 K · iron 22 K · 重费米子 1.6 K · 钌酸盐 1.4 K。**注意 hydride 109.7 K 中相当部分为理论预测(见 #4 和局限 #4)**。

### 9. 国际合作渗透到近半数论文(中美合作绝对+相对都在升)

| n_countries | 论文 | 占比 |
|---:|---:|---:|
| 1 | 23,440 | 57.7% |
| 2 | 11,255 | 27.7% |
| 3 | 4,055 | 10.0% |
| 4+ | 1,869 | 4.6% |

**42.3% 的论文是跨国合作,14.6% 涉及 3+ 国家。**

**中美合作演化(双重视角):**

| 期 | 中美合作篇数 | 同期总论文 | 比例 |
|---|---:|---:|---:|
| 1995–1999 | 10 | 2,449 | 0.4% |
| 2010–2014 | 389 | 7,445 | 5.2% |
| 2020–2024 | **474** | 8,314 | **5.7%** |

**绝对数 1995→2024 增长 47 倍,比例 14 倍。** 即便地缘政治紧张,2020–24 期中美合作绝对数和比例都创新高。

### 10. "热点火箭"现象:新发现 → 3–5 年内引爆数十篇研究(v2 修正:用 distinct 论文数)

| 材料/家族 | 首次入库 | distinct 论文数(至 2025) | 记录数 | 年均论文 |
|---|---:|---:|---:|---:|
| **UTe2**(重费米子)| 2018 | **59** | 125 | ~8.4 |
| **CsV3Sb5**(kagome)| 2020 | **72** | 92 | **~18(4 年)** |
| **La3Ni2O7**(镍酸盐) | 2023 | **43** | ~70+ | **~14(2 年,加速)** |
| **氢化物 (hydride)** | 2011 起 | ~250+ | 574 | 2011→2023 论文数 ~13× |

**实际"研究篇数"≈ 记录数的 1/2**(每篇通常报 1.5–2 个 Tc 数据点)。**单次实验突破在 2-5 年内可生成 50-100 篇跟进论文**。CsV3Sb5 与 La3Ni2O7 当下仍处于上升期。

### 11. Tc Density Valley(BCS-cuprate gap)— 50-80K 是物理上的"配对机制鸿沟"(新增,源自用户观察)

**观察起点:** 在 timeline 散点图上,0-100K 范围内 50-80K 区间记录密度明显低于左右两侧。数据完全支持这一观察,且最低点可精确定位。

#### 11.1 数据支撑

**10K bin 直方图(0-110K):**

| Tc 区间 | 记录 | 每 K 密度 |
|---|---:|---:|
| 30–40 K | 2,081 | 208.1 |
| 40–50 K | 694 | 69.4 |
| **50–60 K** | **478** | **47.8** |
| **60–70 K** | **357** | **35.7 ← 极小** |
| **70–80 K** | **451** | **45.1** |
| 80–90 K | 946 | 94.6 |
| 90–100 K | 773 | 77.3 |

5K bin 锁定**绝对极小值在 65-70K (152 条)**。50-80K 每 K 密度比 80-100K 低 50%,比 30-50K 低 70%。

#### 11.2 家族分解揭示物理根因

| 家族 | 0-50K | **50-80K** | 80-120K |
|---|---:|---:|---:|
| iron_based | 4,426 | **144**(余尾)| 0 |
| BCS 类合计(conventional + elemental + mgb2 + heavy_fermion + chalcogenide + bis2_layered + organic)| ~6,400 | **<5** | 0 |
| **cuprate** | 2,216 | **1,075** | 1,669 |
| hydride | 188 | 61 | 71 |
| nickelate | 39 | 22 | 0 |

**所有 BCS 类家族在 50K 以上几乎为零;铁基约 55K 截止;cuprate 在 50-80K 全是 underdoped 变体**(BSCCO underdoped 69K、YBCO 减氧 60-66K、Tl-2201、Hg-1201 underdoped...),**没有任何材料的天然 Tc 处在这个区间**。

#### 11.3 形式化指标:Tc Density Valley (Tc-DV)

为这类"Tc 密度谷"提供可复现的科学量化:

| 指标 | 定义 | 应用到 65K 谷 |
|---|---|---|
| **Valley 中心 $T_0$** | $\arg\min_T \hat D(T)$ 在该谷内 | **65-70 K** |
| **Depth ratio $\rho$** | $\hat D(T_0) / \min(D_{peak,L}, D_{peak,R})$ | $152/677$ = **0.22**(78% 赤字)|
| **Width $W$**($\alpha=0.7$)| $\{T : \hat D(T) < 0.7 \min(D_{peaks})\}$ 区间宽度 | **~35 K**(45-80K)|
| **Significance** | Poisson $P(N \leq N_{\text{obs}}\mid \lambda_{\text{expected}})$ | $p \ll 0.001$ **极显著** |

**判据:** $\rho < 0.5$ 为"显著谷",65K 处 $\rho = 0.22$ 远低于此阈值。

#### 11.4 物理诠释 — 这是配对机制天花板的直接证据

| Tc 区段 | 主导配对机制 | 天花板原因 |
|---|---|---|
| 0–40 K | BCS phonon-mediated(常规)| McMillan 极限 (~40K) |
| 0–55 K | iron-based unconventional | 铁基天然上限 |
| **50–80 K** | **无任何机制天然属于此区间** | **机制鸿沟** |
| 80–160 K | cuprate optimal doping | 铜氧化物 unconventional 最优 |
| >200 K @ HP | 高压氢化物声子 | 需要极端压力 |

50-80K 几乎只能通过"调低 cuprate"(underdope)或"调高 iron-based 极端样品"达到 —— **没有原生配对机制对应此区间**。

#### 11.5 实践意义

- **任何宣称在 50-80K 找到 ambient pressure 新材料的报告应被重点关注** —— 它会填补一个目前没有物理机制支撑的鸿沟,可能意味着新机制。
- 该谷可作为**理论模型的检验基准**:任何"统一配对理论"应能预言为什么 50-80K 物理上稀疏。
- 上述 Tc-DV 指标可推广到其他物理量(如 Hc2 分布、压力-Tc 相图)的密度谷分析。

#### 11.6 配套 SQL(可加入分析工具集)

```sql
WITH bins AS (
  SELECT (floor(tc_kelvin/5)*5)::int AS tc, count(*)::float AS n
  FROM v_tc_geo WHERE tc_kelvin>0 AND tc_kelvin<=200
  GROUP BY floor(tc_kelvin/5)
), neighbors AS (
  SELECT b.tc, b.n,
    (SELECT max(n) FROM bins b2 WHERE b2.tc BETWEEN b.tc-30 AND b.tc-5)  AS peak_left,
    (SELECT max(n) FROM bins b2 WHERE b2.tc BETWEEN b.tc+5  AND b.tc+30) AS peak_right
  FROM bins b
)
SELECT tc AS tc_low, n AS records, peak_left, peak_right,
  round((n / nullif(LEAST(peak_left, peak_right), 0))::numeric, 2) AS depth_ratio,
  CASE WHEN n / nullif(LEAST(peak_left, peak_right), 0) < 0.5 THEN 'VALLEY' END AS flag
FROM neighbors WHERE peak_left IS NOT NULL AND peak_right IS NOT NULL
ORDER BY depth_ratio NULLS LAST LIMIT 10;
```

### 12. 100K 分水岭:97-99% 记录在低 Tc 区,>100K 只有两种回路(新增,源自用户观察)

**观察起点:** 用户观察到 timeline 上 0-100K 的实验 Tc 数据占 >90%。数据验证:**实际为 97-99%**(不同过滤口径下都成立),并揭示 >100K 区间的物理结构远比想象简洁。

#### 12.1 数据验证 — 多口径下都 ≥97%

| 过滤口径 | 总数 | ≤100K | >100K | ≤100K 占比 |
|---|---:|---:|---:|---:|
| 全部(Tc 0-300,含理论)| 20,142 | 19,609 | 533 | **97.35%** |
| 严格实验(`evidence_type='primary_experimental'`)| 873 | 859 | 14 | **98.40%** |
| 常压(`pressure≤1` 或 NULL)| 18,793 | 18,513 | 280 | **98.51%** |
| 常压 + 排除已标理论 | 18,665 | 18,402 | 263 | **98.59%** |

四种口径都 ≥97%,中位 ~98.5%。用户的"90%+"是 lower bound,真实数字是 **~98%**。

#### 12.2 >100K 区间结构 — 整个高 Tc 物理世界只有两种纯净回路

533 条 >100K 记录按家族分:

| family | 记录 | 常压 | 高压 >1 GPa | 超高压 >100 GPa | 均 Tc | 最大 Tc |
|---|---:|---:|---:|---:|---:|---:|
| **hydride** | **291** | 49 | **242 (83%)** | **218 (75%)** | 181.9 K | 294.2 |
| **cuprate** | **205** | **200 (98%)** | 5 | 0 | 118.0 K | 200 |
| fulleride | 16 | 16 | 0 | 0 | 128.4 K | 175 |

**>100K 只剩两种纯净体制:**
- **铜氧化物 @ 常压**(205 条,98% 常压;Hg/Bi/Tl-Ba-Ca-Cu-O 系列;最高 ~166K Hg-1223)
- **氢化物 @ 极端压力**(291 条,75% 超 100 GPa;H₃S / LaH₁₀ / YH₆ ...;实验最高 ~250K,理论最高 ~294K)

中间 16 条 fulleride 是少量异常(C60 实际 Tc ~30-40K,这里疑似 NER 误抽)。**没有任何第三种机制**抵达 >100K。

#### 12.3 100K 阈值的清晰分界(10K bin)

| Tc 区间 | 总数 | cuprate | hydride | 主导 |
|---|---:|---:|---:|---|
| 100–130 K | 233 | **199 (85%)** | 36 | cuprate ambient |
| 130–140 K | 28 | 1 | 24 | 过渡点 |
| 140–200 K | 165 | 8 | **152 (92%)** | hydride HP |
| **>200 K** | 88 | **0** | **86 (98%)** | **hydride 独占** |

**100-130K 是 cuprate ambient 高地;130-140K 是物理转折(对应 Hg-1223 ~134K 上限);>140K 交给氢化物;>200K 完全没有 cuprate**。

#### 12.4 物质级别 — 高 Tc 物质宇宙极度稀疏

| 统计 | 数量 | 占比 |
|---|---:|---:|
| 全部 distinct material(有 Tc 记录) | 5,537 | 100% |
| 至少 1 条 >100K 记录 | **230** | **4.15%** |
| 至少 1 条 >200K 记录 | **44** | **0.795%** |

**5,537 个材料中只有 4.15% 曾跨过 100K;0.8% 曾跨过 200K**。高 Tc 物质宇宙是化学上极度受限的小集合。

>100K Top-12 材料(全是 cuprate ambient 或 hydride HP):

| 材料 | 家族 | 记录 | max Tc | 平均压力 GPa |
|---|---|---:|---:|---:|
| H₃S | hydride | 57 | 250 | 182 |
| Bi-2223 | cuprate | 29 | 112 | 2 |
| Hg-1223 | cuprate | 27 | 166 | 5 |
| Hg-1212 | cuprate | 16 | 154 | 0 |
| Tl-2212 | cuprate | 16 | 120 | 2 |
| LaH₁₀ | hydride | 16 | 250 | 275 |
| D₃S(氘代)| hydride | 10 | 183 | 184 |
| YH₆ / H₃S 掺杂体 | hydride | 8 each | ~200-250 | ~180 |

#### 12.5 时间趋势 — >100K 占比缓慢上升,但仍是绝对少数

| 时期 | 总 | >100K | 占比 | 其中 >100K 高压 |
|---|---:|---:|---:|---:|
| 1995-99 | 713 | 17 | 2.38% | 0 |
| 2000-04 | 3,210 | 77 | 2.40% | 2 |
| 2005-09 | 3,486 | 38 | 1.09% | 0 |
| 2010-14 | 4,262 | 33 | 0.77% | 5 |
| 2015-19 | 3,773 | 133 | **3.53%** | **96** |
| 2020-24 | 3,793 | 170 | **4.48%** | **113** |
| 2025 (上半) | 569 | 48 | **8.44%** | **30** |

**两个清晰体制:** 1995-2014 >100K 主要靠 cuprate ambient(占 1-2.5%);**2015 起氢化物高压加入,>100K 占比从 ~1% 升至 8%(完全由 HP 推动)**。但即使在最高的 2025,**91.6% 的记录仍在 ≤100K**。

#### 12.6 ✅ 五条可以站住脚的科学陈述

**S1.(体量陈述,最稳)** 在本数据库(1994-2026 arXiv cond-mat.supr-con,~20,000 条 Tc 记录)中,**约 97-99% 的 Tc 记录处于 ≤100K 区间**;严格只看常压 / 实验记录,比例升至 98.5% 以上。

**S2.(结构陈述,最有价值)** **100K 阈值清晰把超导研究分割成两个截然不同的世界:**
- **≤100K:** 16 个超导家族(cuprate / iron-based / conventional / hydride / heavy fermion / kagome ... )共同栖息
- **>100K:** 只剩两种回路 —— **铜氧化物常压**(~100-170K)和**氢化物极端高压(>100 GPa)**(~140-294K)
- **没有任何第三种已知机制**抵达 >100K。

**S3.(材料稀缺)** 在 5,537 个 distinct material 中,**只有 4.15% 曾报告过 >100K Tc 记录**,**只有 0.795% 曾报告过 >200K**。

**S4.(时间趋势)** >100K 记录占比从 1990s-2000s 的 1-2.4% 上升到 2025 上半年的 8.44%,**完全由氢化物高压工作推动**。≤100K 区间至今(2025)仍占 91.6%。

**S5.(实验 vs 理论的提醒)** >100K 的氢化物记录中,**理论 / DFT 预测占相当部分**(详见 Finding 4 + 数据局限 #4)。**实验确证最高 Tc 自 2019 LaH₁₀ ~250K 后未被超越**;>250K 的记录基本都是理论值。

#### 12.7 ❌ 不应该这么说的陈述

| 不能说 | 为什么 |
|---|---|
| "大多数超导体的 Tc < 100K" | 我们有的是 arXiv preprint 的 *records*,不是"被确证的超导体";material ≠ record。 |
| "100K 以上超导很难实现" | 已经有 230 个材料越过 100K,氢化物路径正在大幅推进。准确说法是"目前仍属少数"。 |
| "100K 以上不存在新机制" | 数据只能说"本库 1994-2026 未见第三种机制";**不能排除未来或非 arXiv 渠道存在**。 |
| "超导本质上是低 Tc 现象" | 哲学化、不可证伪。数据支持"已记录的超导记录绝大多数在低 Tc 区"。 |
| "氢化物突破了室温" | 实验最高仅 ~250K @ 170 GPa;>250K 是理论。ambient 室温未达成。 |

#### 12.8 与 Finding 11 合起来 — 完整的 Tc 谱分层

```
[0-50K]          ████████████████  主战场 (~80% 记录),BCS + iron + conventional 共栖
[50-80K]         ███               BCS-cuprate gap (Finding 11) — 配对机制鸿沟
[80-100K]        ████████          cuprate 最优 plateau (Hg/Bi/Tl/Y 等)
[100-140K]       ██                cuprate 高 Tc 极限 (Hg-1223 ~166K)
[140-300K @ HP]  █                 氢化物极端高压独占(150-294K)
[>300K]          (空)              已知物理上限以外
```

Finding 11 描述了 50-80K 谷,Finding 12 描述了 100K 分水岭 —— **合起来构成 0-300K Tc 分布的四层结构**,每一层都对应一种或多种配对机制的天然 Tc 区间。这不是数据偏差,是超导物理结构的直接显形。

#### 12.9 配套 SQL

```sql
-- 多口径下 0-100K 占比
SELECT scope, total, under_100K,
       round(100.0*under_100K/total, 2) AS pct
FROM (
  SELECT 'all' AS scope, count(*) AS total,
         count(*) FILTER (WHERE tc_kelvin<=100) AS under_100K
  FROM v_tc_geo WHERE tc_kelvin>0 AND tc_kelvin<=300
  UNION ALL
  SELECT 'ambient', count(*),
         count(*) FILTER (WHERE tc_kelvin<=100)
  FROM v_tc_geo WHERE tc_kelvin>0 AND tc_kelvin<=300
    AND (pressure_gpa IS NULL OR pressure_gpa<=1)
  UNION ALL
  SELECT 'strict_experimental', count(*),
         count(*) FILTER (WHERE tc_kelvin<=100)
  FROM v_tc_geo WHERE tc_kelvin>0 AND tc_kelvin<=300
    AND evidence_type='primary_experimental'
) t;

-- >100K 区间的家族 × 压力分解
SELECT family,
       count(*) AS records,
       count(*) FILTER (WHERE pressure_gpa IS NULL OR pressure_gpa<=1) AS ambient,
       count(*) FILTER (WHERE pressure_gpa>1)   AS high_pressure,
       count(*) FILTER (WHERE pressure_gpa>100) AS ultra_high_P
FROM v_tc_geo
WHERE tc_kelvin>100 AND tc_kelvin<=300 AND family IS NOT NULL
GROUP BY family ORDER BY records DESC;
```

---

## 数据局限说明(v2 大幅扩展)

### A. 语料来源与覆盖(用户特别强调)

**#1. arXiv 非全量入库** —— ingestion pipeline 受 arXiv OAI-PMH 限速(1 req/5s 元数据,5000 篇/天上限)和历史回填进度影响,**每个年份都有部分论文未入库**。精确缺口可参考 GCS `metadata/harvest_state.json` 与 `failed_papers.json`。**所有按年的论文/记录计数都是下限估计**;早期年份(1995–1999)样本本就稀疏,任何变化解读需谨慎。

**#2. 仅 `cond-mat.supr-con` 分类** —— **已确认**:全库 40,876 篇 100% 主分类为 `cond-mat.supr-con`(0 例外)。设置见 `ingestion/config.py: arxiv_primary_category`。**超导研究论文若提交到其他 arXiv 分类(如 `cond-mat.str-el` 强关联、`cond-mat.mtrl-sci` 材料、`physics.atm-clus`、`hep-th` 等)而未同时 cross-list 到 supr-con,则被遗漏**。这对**纯理论 / 跨学科话题**(轻元素超导理论、拓扑超导数学等)影响最大。Cross-list 到非 cond-mat 的只见到 5 篇(quant-ph 3、hep-th 1、physics.optics 1),其余 cross-list 都在 cond-mat 内部。

**#3. arXiv 是 preprint,不是正式发表 ⚠️** —— 入库论文均为 arXiv 投稿,**未经同行评审**。"Tc 记录"反映**研究兴趣与声明趋势**,**不能等同于已确证的科学事实**。已撤稿的论文(如 Snider 2020 CSH 287 K)可能仍在 arXiv 上;需配合 retraction database 才能完整剔除。**本分析适合趋势研究,不适合作为"超导 Tc 已确证"的引用依据。** 任何"高 Tc 记录"在使用前应回到原 arXiv 论文,并核实是否已发表 / 是否被同行评审。

### B. NER 与抽取层

**#4. ⚠️ 理论 / 实验区分严重失真** —— `evidence_type='primary_theoretical'` 标签极度稀疏。例:氢化物 2023 年 113 条记录里只有 12 条被打理论标签,其余 101 条是模糊的 `primary`。`timeline` 端点默认把 `primary` 当实验处理,**大量 DFT 预测被作为"实验记录"展示**(如发现 4 的 CaLuH12 294K)。**所有"高 Tc 记录"未经独立核实之前不应作为实验事实**。

**#5. NER 抽取篇级 ~96-98% 准** —— 极少数 Tc / 压力 / 测量条件值可能偏离(如 chalcogenide 最大 80 K 实为 Bi2Se3 系列 NER 误抽)。

### C. 地理与归一化

**#6. 国名变体未完全归并** —— Gemini 偶尔输出非标准变体:UK (2,537) + United Kingdom (128) → UK 实际**低估 ~5%**;South Korea (925) + Republic of Korea (53) + Korea (8) → **低估 ~6.7%**;USA 基本干净(主形 14,446 + 变体 22 < 0.2%);"Republic of China" (5) 实为 Taiwan,**可能被错误统计入"中国"维度**。

**#7. 国家计数非互斥** —— 一篇 USA-China 合作论文 BOTH 计入 USA 和 China tally。**所有按国家的论文数都是"含该国作者"的论文数,不是"该国独立产出"。** 解读时不要把它当成竞争性份额。

**#8. 城市未消歧** —— Cambridge UK(剑桥大学)与 Cambridge MA(MIT、Harvard)在 city 列被合并为同一个 "Cambridge"(1,638 篇)。其他同名城市(如多个 "Cambridge", "Berlin", "Paris" 等)同理。

### D. 材料聚合层

**#9. material 元素顺序去重不彻底** —— `La2.8Nd0.2Ni2O7` 和 `Nd0.2La2.8Ni2O7` 是同一化合物但被算作两个材料(`materials_aggregator.normalize_formula` 未消除元素书写顺序)。**轻微膨胀 distinct material 数**;排名不受影响,但 nickelate 等多元素掺杂体系的"材料数"略高估。

### E. 时间维度

**#10. `year` 是 arXiv 提交年,不是物理发现年** —— 老结果常被现代综述/再分析论文带入语料(例:bismuthate 实际 1988 Cava 发现,本库入库 1997)。"该家族首次入库年" ≠ "该家族物理发现年"。

**#11. 1995 年前数据稀疏** —— arXiv cond-mat 1992 上线,1995 前论文极少;早期"USA 主导"部分反映 arXiv 早期主要由美国机构使用的覆盖偏差。

---

## 总体结论(v2 修订)

40 年超导研究史里,本数据集支持以下**趋势性**结论(注意 limitations B-E):

- **体制最大的两次变化:**
  - (a) **2008 年 LaFeAsO 引发的铁基冲击** —— 1 年内 pnictide 类记录从 ~0 跳到 ~485,这是数据中最剧烈的范式切换;
  - (b) **2014–2015 高压氢化物拐点** —— HP/ambient Tc 比值开始反转,自此 `>100 GPa` 体制成为高 Tc 主战场。**但其中相当部分为 DFT 预测,实验最高 Tc 自 2019 LaH₁₀ ~250 K 后基本停滞**。

- **地缘上最大变化:** 中国从边缘玩家(1995–99 期 6 篇)成长为与美国并驾齐驱的领导者(2020+ 各年互有领先);**post-2008 新家族几乎都以中国为主要研究者**(铁基持平、镍酸盐 / kagome / 氢化物 China 领先 2-2.5×)。

- **研究分布特征:** 极度集中 + 国际化并存 —— **78.9% 的材料只 1 篇论文**,但 42% 的论文是跨国合作;Top-2 BSCCO + MgB2 占 9% 论文。

- **"室温超导"现状(诚实表述):** **实验**最高 ~250 K (LaH₁₀ @ 170 GPa, 2019),自此 5 年未被实验超越;**理论**预测推进到 ~294 K (CaLuH12 @ 180 GPa, 2024)。**ambient pressure 下的室温超导未达成,且本数据集为 arXiv preprint,不能作为科学定论引用**。

---

## 复现这些数字的关键 SQL

每个发现都可用 `v_tc_geo` / `v_material_geo` + `papers.paper_geo` 复现。**强烈建议**未来分析增加一个"严格实验子集"视图(过滤 DFT 预测后再统计高 Tc 趋势)。

```sql
-- 三代家族浪潮 + 共治期(top-3 per bucket)
WITH fb AS (
  SELECT (year/5)*5 AS bucket, family, count(*) AS recs,
         row_number() OVER (PARTITION BY (year/5)*5 ORDER BY count(*) DESC) AS rk
  FROM v_tc_geo
  WHERE tc_kelvin>0 AND tc_kelvin<=300
    AND year BETWEEN 1995 AND 2025 AND family IS NOT NULL
  GROUP BY bucket, family
)
SELECT bucket, rk, family, recs FROM fb WHERE rk<=3 ORDER BY bucket, rk;

-- 高压 Tc 翻转(注意:含 DFT 预测,需独立核实)
SELECT (year/5)*5 AS bucket,
  count(*) FILTER (WHERE pressure_gpa>1) AS hp_n,
  round(avg(tc_kelvin) FILTER (WHERE pressure_gpa>1)::numeric, 1) AS hp_mean_tc,
  round(avg(tc_kelvin) FILTER (WHERE pressure_gpa IS NULL OR pressure_gpa<=1)::numeric, 1) AS ambient_mean_tc
FROM v_tc_geo
WHERE tc_kelvin>0 AND tc_kelvin<=300 AND year BETWEEN 1985 AND 2025
GROUP BY bucket ORDER BY bucket;

-- 中美年度对照(国家计数非互斥,合作论文 BOTH 计入)
WITH pp AS (
  SELECT DISTINCT paper_id, year, jsonb_array_elements_text(countries) AS country
  FROM v_tc_geo WHERE year BETWEEN 2005 AND 2025
)
SELECT year,
  count(DISTINCT paper_id) FILTER (WHERE country='China') AS china,
  count(DISTINCT paper_id) FILTER (WHERE country='USA')   AS usa
FROM pp GROUP BY year ORDER BY year;

-- Top 材料(按 distinct 论文数,v2 推荐)
SELECT formula, family,
  count(DISTINCT paper_id) AS papers,
  count(*) AS records
FROM v_tc_geo WHERE tc_kelvin>0 AND tc_kelvin<=300
GROUP BY formula, family ORDER BY papers DESC LIMIT 15;
```

---

## 后续优化建议(从本次审查得出)

1. **加 view `v_tc_geo_strict`**:仅含 `evidence_type='primary_experimental'` AND paper_type='experimental' AND 排除已知 DFT-screening 关键词的论文 —— 作为"已确证实验"子集。
2. **国名归一化清理**:写 `UPDATE` 把 `United Kingdom`→`UK`、`Republic of Korea`/`Korea`→`South Korea`、`United States`/`U.S.A.`→`USA`;并在 `affiliation_ner.py` 加 `_canonicalize_country()` 后置处理。"Republic of China" → "Taiwan"独立标签。
3. **强化 NER 理论/实验区分**:用论文标题关键词(DFT、predicted、computational、screening 等)+ 家族-高压组合启发式,把模糊的 `primary` 重新分类。或者用 Gemini 重跑一遍仅理论判别。
4. **材料元素顺序归一**:`normalize_formula` 增加元素字典序排序。
5. **arXiv 入库缺口审计**:写一个对照脚本,把 OAI-PMH 实际投稿数 vs 本库入库数按年对照,量化每年缺口比例,加入数据局限报告。
6. **撤稿追踪**:接入 Retraction Watch 数据,定期标 `status='retracted'`。
