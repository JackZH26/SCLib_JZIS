# Timeline 数据大数据分析 — 10 大主要发现

> **🚫 已被 v2 取代 / SUPERSEDED BY v2** — 请参考 [`TIMELINE_ANALYSIS_2026_05_23_v2.md`](TIMELINE_ANALYSIS_2026_05_23_v2.md)。
>
> v1 含 **1 处事实性错误**(294 K CaLuH12 实为 DFT 预测而非实验测量)+ **4 处解读偏差**(中美关系叙事、家族领先幅度、Top 材料排序、Pareto 计数),已在 v2 修正。v2 同时**大幅扩展了数据局限**说明(arXiv 非全量入库、仅 cond-mat.supr-con 分类、preprint 不是正式发表等共 11 条)。
>
> **v1 仅保留作历史记录与对比,不再作为权威分析。**

> **(v1 原"极其重要"标记 — 已失效)** — 本文档曾是 2026-05-23 全库快照的统计分析,作为 timeline 数据 + 新补全地理(`paper_geo`)首次联合分析的基线。

> **快照时间:2026-05-23。** 本次分析依赖刚部署的 `papers.paper_geo` 列(99.52% 覆盖,通过 `ingestion/extract/affiliation_ner.py` 抽取)与视图 `v_tc_geo`(27,848 行)、`v_material_geo`(7,193 行)。详见 alembic `0037_paper_geo` + `scripts/backfill_paper_geo.py`。视图后端专用,前端零暴露。

## 数据基础

分析对象:`v_tc_geo` 视图(应用 timeline 页面的同款过滤:`needs_review=false`、`0<Tc≤300K`、`1900≤year≤2026`)。共 **19,922 个 Tc 数据点**,**5,517 个材料**,**8,044 篇论文**(占全库 40,870 篇的 ~20% —— 只有报告了数值 Tc 的论文才进入 timeline),覆盖 **1994–2026 年**。地理映射首次可用,99.52% 的论文带 country/city。

---

## 🔟 主要发现

### 1. 三代研究浪潮 — 每代由单一材料家族主导
每 5 年期内"最大产出家族"在三代之间清晰更替:

| 时期 | 主导家族 | 该家族产出条数 |
|---|---|---:|
| 1990–2009 | cuprate(铜氧化物) | 1995–2004 合计 2,080 |
| 2010–2019 | **iron_based** | 2010–2014: **1,928** |
| 2020–2024 | conventional(BCS 类,多与第一性原理筛选有关) | 643 |

每一代切换都伴随着前一代研究量的明显衰减。

### 2. 2008 年铁基冲击 — 数据中最剧烈的范式切换
| year | iron_based | cuprate |
|---:|---:|---:|
| 2007 | **2** | 309 |
| 2008 | **485** | 188 |
| 2009 | 505 | 199 |

**一年内铁基记录暴增 240 倍,铜氧化物同步下挫 40%**。对应 2008 年 Hosono 团队 LaFeAsO 的发现 —— 文献焦点在数月内完成转向。

### 3. 高压超导 Tc 反转(2014 前后的体制变化)
| 时期 | 高压记录均 Tc | 常压均 Tc | 比值 |
|---|---:|---:|---:|
| 1995–1999 | 12.5 K | **55.8 K** | 0.22× |
| 2010–2014 | 22.5 K | 21.4 K | 1.05× |
| 2015–2019 | 62.7 K | 19.9 K | 3.15× |
| 2020–2024 | 64.0 K | 16.9 K | 3.79× |
| 2025 (上半) | **109.8 K** | 23.9 K | **4.60×** |

**高压由"低 Tc 利基"翻转为"高 Tc 前沿",拐点 ~2014–2015**(对应 Drozdov H3S)。`>100 GPa` 这一档共 **355 条记录,均 Tc 128.7 K** —— 这个体制在 2014 前的语料里基本不存在。

### 4. 294 K — 距离室温只剩 4 开尔文
全库最高 Tc 记录:**CaLuH12,294.2 K,180 GPa,2024,中国**。氢化物年最高 Tc 的攀升轨迹:

```
2013→243K  2015→250K  2020→288K  2023→293K  2024→294.2K
```

**过去十年室温距离收窄了 50+ K**(1995–99 全库最高 133K → 2020–24 最高 294K)。25°C(298K)就在视野之内。

### 5. 中国 2021 年在年产出上首次超过美国
| year | China | USA | Japan |
|---:|---:|---:|---:|
| 2008 | 142 | 183 | 130 |
| 2015 | 107 | 140 | 81 |
| 2020 | 94 | 132 | 106 |
| **2021** | **184** | **155** | 115 |
| 2023 | 152 | 154 | 90 |
| 2024 | 139 | 135 | 76 |
| 2025 | 126 | 127 | 80 |

**中国论文计数 25 年增长 ~120 倍**(1995–99 合计 6 篇 → 2020–24 合计 713 篇),并在 **2021 年首次超过美国**,此后基本势均力敌。

### 6. 家族领头国与"年代地图"强相关
| 家族(首次出现年份) | 领头国 | 第一名 : 第二名 |
|---|---|---:|
| cuprate (1994) | USA | 781 : Japan 598 |
| heavy_fermion (1996) | Japan | 159 : USA 150 |
| ruthenate (1997) | Japan | 67 : USA 27 |
| mgb2 (2001) | USA | 147 : Italy 60 |
| **iron_based (2008 真正爆发)** | **China** | **598 : USA 574** |
| **kagome (2011)** | **China** | **56 : USA 22** |
| **bis2_layered (2012)** | Japan | 41 : China 18 |
| **hydride** (爆发 2015) | **China** | **85 : USA 51** |
| **nickelate** (爆发 2023) | **China** | **49 : USA 20 (2.5×)** |

**家族越新,中国领先越明显;老家族仍由美/日主导**。这是全数据集里最干净的国别-时代相关性。

### 7. Pareto 极端 — 18 个材料撑起整个语料
| 每材料论文数 | 材料数 | 占比 |
|---|---:|---:|
| 1 篇 | 3,973 | 72.0% |
| 2–5 篇 | 2,530 | 45.8% |
| 6–20 篇 | 550 | 10.0% |
| 21–100 篇 | 122 | 2.2% |
| **101+ 篇** | **18** | 0.33% |

**72% 的材料只出现在 1 篇论文里**;Top-2 材料 BSCCO (772 条) + YBCO (643 条) = 1,415 条 = **占总 Tc 记录的 7.1%**。前 18 个材料的研究密度比中位材料高 100+ 倍。

### 8. 平均 Tc 二十年腰斩 —— 不是物理倒退,是研究面变宽
| 时期 | 均 Tc | 主导家族 |
|---|---:|---|
| 1995–1999 | **55.5 K** | cuprate 一统天下 |
| 2010–2014 | 21.5 K | 铁基 + 元素 + 重费米子全面铺开 |
| 2020–2024 | 22.1 K | conventional / 计算 / 拓扑 / kagome 等 |

**均 Tc 不到 1995 年水平的 40%。** 这并非超导退步,而是研究焦点从"追高 Tc"扩展到 kagome、重费米子、拓扑材料等本就低 Tc 的奇异体系(重费米子均 Tc **1.6 K**,钌酸盐 1.4 K)。

### 9. 国际合作是常态 — 中美合作 GROWS through 2020–2024
| n_countries | 论文 | 占比 |
|---:|---:|---:|
| 1 | 23,440 | 57.7% |
| 2 | 11,255 | 27.7% |
| 3 | 4,055 | 10.0% |
| **4+** | **1,869** | 4.6% |

**42.3% 的论文是跨国合作**,14.6% 涉及 3+ 国家。多国占比 1995–2019 从 34% 升至 46%。**中美合作论文数(`paper_geo @> '{"countries":["USA","China"]}'`)在 2020–24 期 = 474 篇,创历史新高** —— 即便地缘政治紧张,中美超导合作不降反升。

### 10. "热点火箭"现象 — 新发现 → 3-5 年内引爆百篇级研究
| 材料/家族 | 首次入库 | 至 2025 总记录 | 年均 |
|---|---:|---:|---:|
| **UTe2**(重费米子)| 2018 | **125** | ~18/yr |
| **CsV3Sb5**(kagome)| 2020 | **92** | ~23/yr(4 年) |
| **氢化物 (hydride)** | 2011 起 | 574 | 2011→2023:**13×** |
| **La3Ni2O7** 系列 | 2023+ | 数十条(增长中) | — |

**单次实验突破在 3-5 年内可生成 50-100 篇跟进论文**。氢化物年记录数 2011→2023 增长 13 倍,且仍在加速(2024 上半 78,2025 上半 91)。

---

## 数据局限说明
- `year` 是 arXiv 提交年,不一定等于物理发现年(很多老结果是后来论文引用入库)。
- NER 抽取篇级 ~96–98% 准,极少数 Tc 值可能偏离(如表里 chalcogenide 最大 80K 实为 NER 误抽 Bi2Se3 体系)。
- 1995 年前数据稀疏,因 arXiv cond-mat 1992 才上线;早期"USA 主导"部分反映 arXiv 覆盖偏差。
- 城市维度里 Cambridge UK 与 Cambridge MA 未消歧(geo NER 已知短板)。

## 总体结论

40 年超导研究史里:

- **体制最大的两次变化**:(a) 2008 铁基冲击,(b) 2014–2015 高压氢化物体制翻转
- **地缘上最大变化**:中国从边缘玩家变成与美国并列的领头者(**2021 年完成超越**)
- **研究分布特征**:极度集中(72% 材料只 1 篇,18 个材料占 7% 数据)同时国际合作渗透到近一半论文

## 复现这些数字的关键 SQL

每个发现都可用 `v_tc_geo` / `v_material_geo` + `papers.paper_geo` 复现。3 条最有代表性的查询:

```sql
-- 三代家族浪潮
WITH fb AS (
  SELECT (year/5)*5 AS bucket, family, count(*) AS recs,
         row_number() OVER (PARTITION BY (year/5)*5 ORDER BY count(*) DESC) AS rk
  FROM v_tc_geo
  WHERE tc_kelvin>0 AND tc_kelvin<=300
    AND year BETWEEN 1985 AND 2025 AND family IS NOT NULL
  GROUP BY bucket, family
)
SELECT bucket, family AS top_family, recs FROM fb WHERE rk=1 ORDER BY bucket;

-- 高压 Tc 翻转
SELECT (year/5)*5 AS bucket,
  round(avg(tc_kelvin) FILTER (WHERE pressure_gpa>1)::numeric, 1) AS hp_mean_tc,
  round(avg(tc_kelvin) FILTER (WHERE pressure_gpa IS NULL OR pressure_gpa<=1)::numeric, 1) AS ambient_mean_tc
FROM v_tc_geo
WHERE tc_kelvin>0 AND tc_kelvin<=300 AND year BETWEEN 1985 AND 2025
GROUP BY bucket ORDER BY bucket;

-- 中美年度并驾齐驱
WITH pp AS (
  SELECT DISTINCT paper_id, year, jsonb_array_elements_text(countries) AS country
  FROM v_tc_geo WHERE year BETWEEN 2005 AND 2025
)
SELECT year,
  count(DISTINCT paper_id) FILTER (WHERE country='China') AS china,
  count(DISTINCT paper_id) FILTER (WHERE country='USA')   AS usa
FROM pp GROUP BY year ORDER BY year;
```
