# APS 论文入库流程与框架设计方案

> **创建日期：2026-05-31**
> 状态：已与 Jack 确认设计决策，待开发（从阶段 1 Schema 迁移开始）
> 适用范围：在现有 SCLib 框架下**新增** APS（American Physical Society）论文入库链路；**不替换、不影响**现有 arXiv 链路。
> 授权背景：已获 APS 论文入库许可及 IP 授权（https://harvest.aps.org/），按已通过 APS 认可的 TDM 工作流执行。

---

## 0. APS 授权的 TDM 工作流（合规基线）

1. **通过 APS Harvest API 获取**：文章 JSON 元数据 + abstract；BagIt ZIP 包（含全文 XML、PDF、OCR）用于 TDM 处理。
2. **临时处理**：将 BagIt 解压到受控的、有访问限制的临时目录；对全文 XML 跑 NER 抽取超导结构化参数（材料组分、临界温度、压力、方法等）。
3. **SCLib 永久存储仅保留**：文章元数据 + abstract（Appendix A 授权范围）；抽取出的结构化数据（TDM 输出）；处理审计日志（DOI、时间戳、删除确认）。
4. **立即删除 Licensed Materials**：所有原始授权内容（ZIP、PDF、全文 XML、OCR）在抽取后立即从服务器永久删除；不建立、不维护任何 APS 授权内容的中央仓库。
5. **公开页面展示**：元数据 + abstract（授权范围）；抽取出的结构化事实（如 "Tc = X K for material Y"）；回链原文 APS 文章的 DOI；不复现任何超出授权元数据/abstract 的 APS 文章正文。

> 合规核心：APS 全文内容视为**瞬时工作数据**，仅用于 TDM 抽取；持久输出只有 (a) 授权的元数据/abstract 与 (b) 抽取出的结构化数据。

---

## 1. 现有 arXiv 流程（理解基线）

**入库主链路** `ingestion/ingestion/pipeline.py` `process_paper()`：

```
OAI-PMH 元数据 (collect/arxiv_oai.py)
  → 下载 .tar.gz LaTeX 源 → 永久存 GCS (gs://bucket/src/{yymm}/{id}.tar.gz)
  → LaTeX 解析成 sections (parse/latex_parser.py)
  → 分块 chunk (chunk/chunker.py, 512/64 token)
  → 嵌入 text-embedding-005 (embed/embedder.py)
  → 写 Postgres papers+chunks (index/indexer.py upsert_paper_with_chunks)
  → Vertex VS 上传 chunk 向量 (upsert_chunks_to_vector_search)
  → 材料 NER (extract/material_ner.py extract_materials) → papers.materials_extracted
  → 作者地理 NER (extract/affiliation_ner.py) → papers.paper_geo
```

**关键事实（对 APS 设计重要）：**

1. **arXiv NER 本来就跑全文**。`extract_materials(parsed)` 吃的是 `ParsedPaper.sections`（整篇 LaTeX 正文），不只是 abstract。→ APS 全文 NER **复用同一函数**，只换文本来源，配合"精简 schema"决策几乎零改造。
2. **Aggregator** `extract/materials_aggregator.py` `aggregate_from_papers()`：把每篇 `papers.materials_extracted` (JSONB) 汇总进 `materials` 表；幂等；受 `manual_overrides` / `refuted_claims` / `pipeline_state` 版本互锁约束。`scripts/rener.py` 可对指定论文重跑 NER。
3. **source 区分机制（现状）**：
   - `papers.source` 列（`"arxiv"` / `"nims"`），`api/models/db.py:271`。
   - `materials` 表**无 source 列** —— 材料是跨论文聚合的规范实体；provenance 落在 `materials.records` (JSONB) 与 论文←→材料 关联里。
   - NIMS 隔离 = `materials.review_reason='provenance_quarantine_nims'`，在 `routers/materials.py`、`bookmarks.py`、`admin.py`、`services/stats_refresh.py` 中**无条件过滤**。
4. **arXiv 原始内容永久存 GCS** —— 这正是 APS **绝对不能照搬**之处。

---

## 2. APS 与 arXiv 的核心差异 / 合规红线

| 维度 | arXiv | APS（必须） |
|---|---|---|
| 原始全文 | 永久存 GCS | **只进临时目录，NER 后立即删，绝不入 GCS / `chunks.text`** |
| 向量内容 | 全文分块 | **abstract（授权）+ NER 结构化事实句（派生）**；**无全文 embedding** |
| 审计 | 无 | **TDM 删除审计表**（DOI、时间戳、删除确认） |
| 标识 | `arxiv:{id}` | `source='aps'` + 规范化 `external_id`(=DOI) + `doi` 唯一 |
| 取数 | OAI-PMH | APS Harvest API（JSON 元数据 + BagIt ZIP） |
| 期刊 | 一般无 | 记录具体期刊（PRB/PRL/PRX…）+ 卷/期/article-id |

---

## 3. 已确认的设计决策

### ① arXiv↔APS 去重 —— 但"不同 Tc 视为新值"
分两层，绝不丢数据：
- **论文层**：按 DOI 检测重叠，两行都保留，加 `papers.related_paper_id`（自引用 FK）互相 link，标记为"同一 work"。
- **数据层（材料/Tc）**：APS 全文**独立跑 NER**。聚合时只折叠 link 论文之间**完全相同**的记录（同 formula + 同 Tc + 同条件 → 算一次，避免重复计数）；**只要 Tc 或条件不同，就当作新记录保留**（正式发表版改了 Tc = 新值）。
- **计数**：`materials.total_papers` 按 "work-group" 去重计数，而非按行 —— 同一 work 的 arXiv+APS 两行只算 1 篇。

### ② abstract 也入向量
APS 向量单元 = abstract chunk（授权可显示）+ 结构化事实句（授权派生）；**均不含全文**。提升 Ask/RAG 语义质量。

### ③ records 打 source 标签
`materials.records[]` 每条记录加 `source`(`'aps'`/`'arxiv'`) + `doi`（纯 JSONB，无需改列）；材料详情页可显示"本条数据来自 APS / arXiv"。

### ④ 期刊标识（PRB / PRL 等）—— 新增结构化字段
现有 `papers.journal String(300)` 存全名（"Physical Review B"）。新增：
- `papers.journal_abbrev String(30)` —— "PRB"/"PRL"/"PRX"…（建索引，可筛选）
- `papers.publication_ref JSONB` —— `{volume, issue, article_id, page, published_date}`
- 复用现有 `date_published` 作正式发表日期。

### ⑤ arXiv 流程完全保留 —— APS 是新增不是替换
- 所有 APS 代码为新文件（`aps_*.py`），不动 `pipeline.py` 的 arXiv 主链路。
- 对共享代码的唯一改动：迁移 0038 给 `papers` 加列后，arXiv 的 `upsert_paper_with_chunks` 顺带补 `external_id=arxiv_id, id_scheme='arxiv'`（一行 values，不改逻辑）。arXiv 的 OAI-PMH、GCS 永久存储、cron 全部照旧持续更新。
- `aggregate_from_papers()` 增强去重逻辑后，对纯 arXiv 数据（无 link）行为不变。

---

## 4. 数据库改动

### 迁移 0038 — 标识 + 期刊 + 关联（一次性加列，arXiv 兼容）
```
papers 新增:
  external_id     String(200)    -- arXiv: arxiv_id; APS: doi
  id_scheme       String(20)     -- 'arxiv' / 'nims' / 'doi'
  journal_abbrev  String(30)     -- 'PRB' 等, 建索引
  publication_ref JSONB          -- 卷/期/article-id/页/发表日
  related_paper_id String(100)   -- 自引用 FK, arXiv↔APS link
约束:
  UNIQUE(source, external_id)              -- 跨源去重锚点
  partial UNIQUE(doi) WHERE source='aps'   -- APS 按 DOI 唯一
回填:
  现有 arXiv/NIMS 行的 external_id / id_scheme
```

### 迁移 0039 — TDM 删除审计表（合规强制）
```
tdm_audit_log(
  id, source='aps', doi, paper_id,
  harvested_at, processed_at,
  bagit_bytes, files_processed(jsonb),   -- 处理过哪些 XML/PDF/OCR
  ner_record_count,
  deleted_at, deletion_confirmed(bool),  -- 删除证明
  temp_path, status, error )
```

同步更新：`api/models/db.py` ORM 与 `ingestion/ingestion/index/indexer.py` 的 Table 镜像。
`materials.records[]` 的 `source`/`doi` 走 JSONB，无需改列。
（可选）Vertex VS 增加 `source` restrict namespace，便于按源筛选检索。

---

## 5. 新增模块（全部新增，零破坏）
```
ingestion/ingestion/
  collect/aps_harvest.py     # APS Harvest API: JSON 元数据 + BagIt ZIP (鉴权+限速)
  parse/aps_xml.py           # BagIt 解压 → JATS 全文 XML → ParsedPaper(sections)
  aps_storage.py             # 临时目录(tmpfs,0700) + 安全删除 + 审计写入
  extract/fact_sentences.py  # materials_extracted → 事实句; abstract 也嵌入 → VS
  aps_pipeline.py            # 编排: 临时处理→NER→即删→写审计 (不碰 GCS)
复用: extract_materials(NER)、aggregate_from_papers、embedder、indexer DB upsert
```

### APS per-paper 流程（带强制清理）
```
Harvest JSON + abstract + 期刊信息 [持久]
  → BagIt ZIP 下载到 /tmp/aps/{doi}/ (tmpfs,0700) [临时]
  → 解析 JATS XML → sections [临时,内存]
  → extract_materials(parsed) → materials_extracted (打 source='aps') [持久]
  → abstract + 事实句 嵌入 → Vertex VS (无全文) [持久,授权派生]
  → DOI 重叠检测 → 写 related_paper_id link
  → upsert papers(source='aps', journal_abbrev, publication_ref) + chunks
  → ★ 安全删除 /tmp/aps/{doi}/ (try/finally 强制)
  → 写 tdm_audit_log(deleted_at, confirmed=true)
```

---

## 6. 补充 / 优化建议

- **临时目录强隔离**：tmpfs（内存盘）+ 容器内 `127.0.0.1` + 0700 权限；`try/finally` 保证清理；再加**清道夫 cron**（删除 >N 分钟残留并记日志），双保险防进程崩溃留残。
- **删除可验证**：删除后 `os.path.exists` 复查，写 `deletion_confirmed`；审计表可随时向 APS 出具合规证明。
- **独立 cron**：新增 `scripts/cron_aps_ingest.sh`，与 arXiv 的 `cron_daily_ingest.sh` 分开，遵守 APS Harvest 速率限制。
- **前端区分**：论文卡片/详情加 "APS 正式发表" badge + 期刊 badge + DOI 回链；材料详情按 `records[].source` 显示证据来源。呼应"preprint 不是正式发表"的数据局限 —— APS 首次提供"已发表"信号，可单独标注。
- **失败池复用** arXiv 的 `failed_papers.json` 模式，但 APS 失败后同样要保证临时文件已删。

---

## 7. 开发阶段（细粒度提交）

| 阶段 | 内容 | 关键交付 |
|---|---|---|
| **1. Schema** | 迁移 0038 + 0039 + ORM/Table 镜像 | arXiv 回填验证不破坏 |
| **2. Harvest** | `aps_harvest.py`：API 客户端、鉴权、限速、抓 JSON+BagIt+期刊字段 | 单篇拉取烟雾测试 |
| **3. Parse+临时存储** | `aps_xml.py` + `aps_storage.py`：JATS 解析 + tmpfs + 安全删除 + 审计 | 删除可验证 |
| **4. Pipeline** | `aps_pipeline.py` 串联 + finally 清理 + 审计写入 | 3~5 篇端到端 |
| **5. 向量** | `fact_sentences.py`：abstract + 事实句嵌入（VS 加 source restrict） | |
| **6. 去重+聚合** | DOI 重叠 link + work-group 计数 + "不同 Tc 视为新值" 逻辑；records 打标签 | arXiv 行为回归测试 |
| **7. API/前端** | source/journal badge、DOI 回链、按源/按期刊筛选 | |
| **8. Ops** | `cron_aps_ingest.sh`（独立）+ 临时目录清道夫 cron + 合规审计导出 | |

**贯穿不变量**：arXiv 的 OAI-PMH→GCS→VS 链路与 cron 全程保留、持续更新；APS 原文永不落 GCS、永不入 `chunks.text`。

---

## 8. 待办 / 后续确认
- APS Harvest API 的鉴权方式与速率限制细节（API key / IP 白名单）—— 开发阶段 2 落地时确认。
- BagIt 内全文 XML 的具体 schema（JATS 版本）—— 开发阶段 3 取真实样例后确认。
- `journal_abbrev` 取值表（PRB/PRL/PRX/PRApplied/PRMaterials/RMP…）—— 从 Harvest 元数据枚举。
