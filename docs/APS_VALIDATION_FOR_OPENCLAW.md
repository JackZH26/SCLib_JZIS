# APS 入库 — VPS2 部署与验证说明（给 openclaw）

> 创建日期：2026-05-31
> 执行环境：VPS2（72.62.251.29，已在 APS Harvest IP 白名单内）
> 目标读者：openclaw（在 VPS2 上执行部署与验证的 agent）
> 关联文档：`docs/APS_INGESTION_PLAN.md`（设计方案）、记忆 `project_aps_ingestion`

---

## 0. 背景（必读，30 秒）

SCLib 新增了 **APS（American Physical Society）论文入库管线**，作为 arXiv 之外的**新增数据源**（不替换 arXiv）。代码（Phase 1–5）已 push 到 `origin/main`，最新 commit 应为 `1efd6b9`。

**合规红线（APS TDM 协议，最重要）：**
- APS 全文（BagIt ZIP / 全文 XML / PDF / OCR）是**瞬时工作数据**，只用于 NER 抽取，**抽取后必须立即删除**。
- 永久保留的只有：(a) 授权的元数据 + abstract，(b) 抽取出的结构化数据（Tc/材料等），(c) 删除审计日志。
- APS 全文**绝不能**进入 GCS，**绝不能**写入 `chunks.text`。
- 本验证的一个核心目的就是**确认全文确实被删除了**（`tdm_audit_log.deletion_confirmed = true`）。

**endpoint 路径状态（2026-06-03）：** metadata 路径 `/v2/journals/articles/{doi}`（Accept json）VPS2 实测 200 已确认；全文路径**已据 APS IT 反馈修正**为同一个 base 路径（Accept zip），不再用废弃的 `/accepted_fulltext` 子路径。先按 **§4.0 直连冒烟**确认两条都 200，再跑管线。若仍失败，按 §6 收集信息回报，不要自行猜测改代码。

---

## 1. 第一步：确认代码是否已部署（务必先做）

⚠️ **重要：本仓库的 GitHub Actions 自动部署（deploy.yml）已知是静默失效的** —— 它报成功但实际不在 VPS2 上执行。所以 `git push` **不等于**已部署。必须手动核对。

```bash
cd /opt/sclib
git rev-parse --short HEAD
```

- 如果输出 **`1efd6b9`** → 代码已是最新，**跳到 §3（应用迁移）**。
- 如果输出**其它值** → 代码未部署，**执行 §2 部署**。

---

## 2. 部署到 VPS2（仅当 §1 显示 HEAD ≠ 1efd6b9 时执行）

### 2.1 拉取最新代码
```bash
cd /opt/sclib
git fetch origin
git log --oneline -1 origin/main          # 应显示 1efd6b9 test(ingestion): fact-sentence ...
git status --porcelain                     # 确认无未提交改动会被覆盖；若有，先停下报告 Jack
git pull --ff-only origin main
git rev-parse --short HEAD                  # 必须 == 1efd6b9
```

### 2.2 重建受影响的容器镜像
本次改动涉及 **ingestion**（新增 APS 模块）与 **api**（ORM 新增列/模型）。frontend 本次无改动。
```bash
cd /opt/sclib
export GIT_SHA=$(git rev-parse --short HEAD)
docker compose build api ingestion
```

### 2.3 重启 api（让新 ORM 生效）
```bash
docker compose up -d api
docker compose ps                          # 确认 sclib-api 为 healthy
```
> 注意：**不要** `docker compose up` 整个栈做无谓重启；只重启 api 即可。frontend / postgres / redis 不动，避免影响现有 jzis.org / asrp.jzis.org。

---

## 3. 应用数据库迁移（alembic 0038 + 0039）

新增两个迁移：
- `0038_aps_source_identity` — papers 表加 `external_id`/`id_scheme`/`journal_abbrev`/`publication_ref`/`related_paper_id` + 约束 + 回填现有 arXiv/NIMS 行。
- `0039_tdm_audit_log` — 新建 TDM 删除审计表。

```bash
cd /opt/sclib
# 先备份（迁移会改 papers 表 + 回填，务必先备份）
docker compose exec postgres pg_dump -U sclib -d sclib -Fc -f /tmp/pre_aps_0038.dump
docker compose exec postgres ls -la /tmp/pre_aps_0038.dump

# 查看当前迁移版本（应为 0037_paper_geo）
docker compose exec api alembic current

# 应用到最新
docker compose exec api alembic upgrade head

# 确认到达 0039
docker compose exec api alembic current     # 应显示 0039_tdm_audit_log (head)
```

### 3.1 迁移成功校验（SQL）
```bash
docker compose exec postgres psql -U sclib -d sclib -c "
SELECT column_name FROM information_schema.columns
WHERE table_name='papers'
  AND column_name IN ('external_id','id_scheme','journal_abbrev','publication_ref','related_paper_id')
ORDER BY column_name;"
```
**预期：** 返回 5 行（5 个新列都存在）。

```bash
docker compose exec postgres psql -U sclib -d sclib -c "
SELECT to_regclass('public.tdm_audit_log') AS tdm_table;"
```
**预期：** 返回 `tdm_audit_log`（非空，即表已创建）。

```bash
docker compose exec postgres psql -U sclib -d sclib -c "
SELECT count(*) AS arxiv_backfilled
FROM papers WHERE source='arxiv' AND external_id IS NOT NULL;"
```
**预期：** 非零（现有 arXiv 行的 `external_id` 已被回填）。

### 3.2 回归校验：现有 arXiv 数据未受损
```bash
docker compose exec postgres psql -U sclib -d sclib -c "
SELECT source, count(*) FROM papers GROUP BY source ORDER BY source;"
```
**预期：** arXiv 行数与迁移前一致（迁移只加列/回填，不删行）。

---

## 4. 验证（核心）：用指定 DOI 跑入库管线

**目标 DOI：`10.1103/PhysRevB.104.014501`**（Physical Review B，期刊缩写应识别为 `PRB`）

ingestion 是一次性容器（`profiles: ["tools"]`），用 `docker compose run --rm` 调用。

### 4.0 步骤 0 —— 出口 IP 核验 + APS 直连冒烟（在跑管线前务必先做）

**背景（2026-06-03 更新，重要）：** 之前全文 401 的根因**不是** TDM 授权未批，而是我们把全文路径打成了 `/v2/journals/articles/{doi}/accepted_fulltext`（一个不存在的子路由，返回通用 `401 Unauthorized`）。APS IT 已确认：**全文 ZIP = 与 metadata 同一个 base 路径 `/v2/journals/articles/{doi}`，只把 `Accept` 头换成 `application/zip`，且不需要 key**。代码已修正（`aps_bagit_path` 现指向 base 路径）。

**(a) 先确认 VPS2 实际出口 IP 是 APS 白名单之一**（白名单：`72.62.251.29`、`76.13.191.130`）。注意要测**容器内**的出口 IP（管线在 ingestion 容器里跑，若有出站 NAT，容器看到的出口可能与宿主入站 IP 不同）：
```bash
# 宿主出口
curl -s https://api.ipify.org; echo
# 容器内出口（这才是 APS 调用时真正的来源 IP）
cd /opt/sclib && docker compose run --rm ingestion \
  python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org',timeout=10).read().decode())"
```
**预期：** 两者都应是 `72.62.251.29` 或 `76.13.191.130`。**若容器出口是第三个 IP，立即报告 Jack** —— 需要把那个 IP 也加进 APS 白名单。

**(b) 用 APS IT 自己的可用示例直连冒烟**（在 VPS2 宿主上跑，用白名单 DOI `10.1103/hbdj-2hgf`）：
```bash
# metadata（json）—— 期望 200 + JSON
curl -s -H "accept: application/json" -o /tmp/aps_meta.json \
  -w "meta  http=%{http_code} ctype=%{content_type} size=%{size_download}\n" \
  "https://harvest.aps.org/v2/journals/articles/10.1103/hbdj-2hgf"
# 全文（zip）—— 期望 200 + application/zip，size 数 KB～MB，文件头是 PK\x03\x04
curl -s -H "accept: application/zip" -o /tmp/aps_full.zip \
  -w "full  http=%{http_code} ctype=%{content_type} size=%{size_download}\n" \
  "https://harvest.aps.org/v2/journals/articles/10.1103/hbdj-2hgf"
file /tmp/aps_full.zip; head -c 4 /tmp/aps_full.zip | xxd
```
**判读：**
- 两条都 `200` → IP 白名单生效，全文路径正确 → 继续 §4.1。**这是跑通的前提。**
- `401 {"...not authorized"}`（**点名 DOI**）→ 该来源 IP 不在白名单（回到 (a) 查容器出口 IP）。
- `401 {"Unauthorized"}`（**泛化、不点名**）→ 路径打错了（命中了无效子路由）；确认已部署含本次修正的代码（HEAD 应 ≥ 本次 commit）。
- 若全文 `200` 但 `file` 显示**不是 ZIP**（如裸 XML）→ 停下报告 Jack：需要给 `download_bagit` 加一个「裸 XML→无需解压直接喂解析器」的小 adapter。

### 4.1 步骤 A — Dry-run（先跑这个！不写库，只验证合规闭环）

dry-run 会执行 **harvest → 下载 BagIt → 解压到临时目录 → 解析 JATS → NER → 删除临时文件 → 记录审计**，但**不写 Postgres / 不写 Vertex VS**。用来安全地验证「全文被删除」这一合规闭环，以及暴露 APS endpoint/字段问题。

```bash
cd /opt/sclib
docker compose run --rm ingestion \
  python -m ingestion.aps_pipeline --doi 10.1103/PhysRevB.104.014501 --dry-run -v \
  2>&1 | tee /tmp/aps_dryrun.log
```

**预期成功输出（关键行）：**
- `harvested metadata (PRB, <标题前 60 字>)` —— 元数据拉取成功，期刊识别为 PRB。
- `extracted BagIt for ... : N files, M zip bytes` —— BagIt 下载并解压成功。
- 一行形如 `DRY RUN — skipping DB/VS. audit={...}`，其中 audit 字典里 **`deletion_confirmed: True`**、`status: 'deleted'`。
- 末尾：`aps temp dir purged + verified gone: /dev/shm/sclib-aps/aps-...`
- 退出码 `0`，`done: 1/1 ok`。

**合规硬性检查（dry-run 后立即做）：** 确认临时目录已无残留：
```bash
ls -la /dev/shm/sclib-aps/ 2>/dev/null || echo "tmpfs base 不存在（也正常，说明已清空）"
find /dev/shm /tmp -maxdepth 3 -name 'aps-*' -type d 2>/dev/null || echo "无 aps-* 残留目录 —— 合规 OK"
```
**预期：** 没有任何 `aps-*` 残留目录。**如果有残留，立即停止并报告 Jack（合规问题）。**

### 4.2 步骤 B — 正式入库（dry-run 成功后再做）

```bash
cd /opt/sclib
docker compose run --rm ingestion \
  python -m ingestion.aps_pipeline --doi 10.1103/PhysRevB.104.014501 -v \
  2>&1 | tee /tmp/aps_ingest.log
```

**预期成功输出（关键行）：**
- 同 dry-run 的 harvest / BagIt / 删除行。
- `[OK ] 10.1103/PhysRevB.104.014501 — journal=PRB secs=<N> mats=<M> chunks=<K> deleted=True related_arxiv=<None 或 arxiv:...>`
- `tdm_audit_log written: doi=10.1103/PhysRevB.104.014501 status=deleted deleted=True`
- 退出码 `0`，`done: 1/1 ok`。

---

## 5. 入库结果校验（SQL，步骤 B 之后）

### 5.1 papers 行：source / 标识 / 期刊正确
```bash
docker compose exec postgres psql -U sclib -d sclib -x -c "
SELECT id, source, arxiv_id, doi, external_id, id_scheme,
       journal, journal_abbrev, publication_ref, related_paper_id,
       chunk_count, jsonb_array_length(materials_extracted) AS n_materials
FROM papers WHERE doi='10.1103/PhysRevB.104.014501';"
```
**预期（逐字段）：**
- `id` = `aps:10.1103/PhysRevB.104.014501`
- `source` = `aps`
- `arxiv_id` = 空（NULL）
- `doi` = `10.1103/PhysRevB.104.014501`
- `external_id` = `10.1103/PhysRevB.104.014501`，`id_scheme` = `doi`
- `journal_abbrev` = `PRB`，`journal` = `Physical Review B`
- `publication_ref` = 含 volume/article_id 等的 JSON（可能部分字段为空，正常）
- `related_paper_id` = NULL（除非库里已有同 DOI 的 arXiv 预印本，那样会是 `arxiv:...`）
- `chunk_count` > 0，`n_materials` ≥ 0

### 5.2 合规核心：chunks 不含全文正文
```bash
docker compose exec postgres psql -U sclib -d sclib -c "
SELECT section, count(*) FROM chunks
WHERE paper_id='aps:10.1103/PhysRevB.104.014501'
GROUP BY section ORDER BY section;"
```
**预期：** `section` 只能是 **`Abstract`** 和/或 **`Facts`** 两种。
**如果出现任何其它 section（如 Introduction/Results/Methods 等正文章节名）→ 严重合规问题，立即停止并报告 Jack。**

### 5.3 TDM 审计行：删除已确认
```bash
docker compose exec postgres psql -U sclib -d sclib -x -c "
SELECT doi, paper_id, status, deletion_confirmed,
       bagit_bytes, ner_record_count,
       jsonb_array_length(files_processed) AS n_files,
       harvested_at, processed_at, deleted_at, temp_path, error
FROM tdm_audit_log
WHERE doi='10.1103/PhysRevB.104.014501'
ORDER BY created_at DESC LIMIT 1;"
```
**预期：**
- `status` = `deleted`
- `deletion_confirmed` = `t`（true）
- `bagit_bytes` > 0，`n_files` > 0（处理过的全文文件数，仅记录文件名/大小，不含内容）
- `harvested_at` / `processed_at` / `deleted_at` 都有时间戳
- `error` = NULL

### 5.4（可选）抽取出的结构化数据合理性
```bash
docker compose exec postgres psql -U sclib -d sclib -x -c "
SELECT jsonb_pretty(materials_extracted) FROM papers
WHERE doi='10.1103/PhysRevB.104.014501';"
```
**预期：** 一个 JSON 数组，每条含 `formula` 等字段；该论文若报道了 Tc，应能看到 `tc_kelvin` 等。数组为空也不算失败（取决于论文内容），但通常 PRB 超导论文会有材料记录。

> 注意：本阶段（Phase 5）**尚未**做跨源聚合（Phase 6 才做），所以**不要**期望 `materials` 表里立刻出现按 source 标签聚合的 APS 材料。本次只验证到 `papers` + `chunks` + `tdm_audit_log` 这一层。

---

## 6. 失败处理与回报规范

### 6.1 如果 dry-run / 入库失败
最可能的原因是 **APS Harvest endpoint 路径或元数据 JSON 字段不对**（已知风险）。**不要自行改代码猜测**。收集以下信息回报 Jack：

1. 完整日志：`/tmp/aps_dryrun.log` 和/或 `/tmp/aps_ingest.log`。
2. 如果是 HTTP 错误，记录状态码：
   - **401 且报错点名 DOI**（`{"...not authorized"}`）→ 该请求的来源 IP 不在 APS 白名单。按 §4.0(a) 查**容器内**出口 IP 是否为 `72.62.251.29` / `76.13.191.130`；若是第三个 IP，需把它加进白名单。
   - **401 且报错泛化**（`{"Unauthorized"}`，不点名 DOI）→ endpoint 路径打错（命中无效子路由）。确认已部署含「`aps_bagit_path` = base 路径」修正的代码。
   - **404** → endpoint 路径不对（`aps_metadata_path` / `aps_bagit_path` 需按真实 API 校准）。
   - 全文返回 **200 但不是 ZIP**（裸 XML 等）→ `download_bagit` 的 ZIP 假设需要加 adapter，停下报告 Jack。
   - **解析错误 `ApsParseError` / `no JATS <article> XML`** → BagIt 内部结构与预期不同。
3. 如果 metadata 能拉到但字段为空（如 title/abstract 空、journal_abbrev 不是 PRB），把 **原始 JSON 响应**抓回来——这能让 Jack 校准字段映射。抓原始响应的方法（只读，不入库）：
   ```bash
   docker compose run --rm ingestion python -c "
   import asyncio, json
   from ingestion.collect.aps_harvest import ApsClient
   async def main():
       async with ApsClient() as c:
           # 直接打印 metadata 原始 JSON（注意：这是授权范围内的元数据）
           import httpx
           from ingestion.config import get_settings
           s = get_settings()
           path = s.aps_metadata_path.format(doi='10.1103/PhysRevB.104.014501')
           print('GET', s.aps_harvest_url + path)
           r = await c._client.get(path)
           print('status', r.status_code)
           print(r.text[:3000])
   asyncio.run(main())
   "
   ```
   把输出回报。

### 6.2 合规失败（最高优先级）
若出现以下任一情况，**立即停止后续操作并报告 Jack**：
- §4.1 / §4.2 后 `/dev/shm` 或 `/tmp` 残留 `aps-*` 目录。
- §5.2 chunks 出现正文章节（非 Abstract/Facts）。
- §5.3 `deletion_confirmed = f` 或 `status = error` 但临时文件仍在。

---

## 7. 回滚（仅在需要时）

如果验证后 Jack 要求回滚迁移：
```bash
cd /opt/sclib
docker compose exec api alembic downgrade 0037_paper_geo
# 或从备份恢复：
# docker compose exec postgres pg_restore -U sclib -d sclib --clean /tmp/pre_aps_0038.dump
```
代码回滚：`git -C /opt/sclib checkout <上一个部署的 commit>` 后 `docker compose build api ingestion && docker compose up -d api`。

---

## 8. 给 Jack 的回报模板（验证完成后填写）

```
APS 验证报告 — DOI 10.1103/PhysRevB.104.014501
- VPS2 部署前 HEAD: __________  → 部署后 HEAD: 1efd6b9 (是/否)
- alembic: 0037 → 0039 (成功/失败)
- §3.1 5 个新列存在: (是/否)   tdm_audit_log 表存在: (是/否)
- §3.2 arXiv 行数 迁移前/后: ______ / ______ (一致/不一致)
- dry-run: (成功/失败)  deletion_confirmed: (true/false)  tmpfs 残留: (无/有)
- 正式入库: (成功/失败)  退出码: ___
- §5.1 source=aps / id_scheme=doi / journal_abbrev=PRB: (全对/有误: ___)
- §5.2 chunks section 仅 Abstract/Facts: (是/否，若否列出: ___)
- §5.3 tdm_audit_log status=deleted & deletion_confirmed=t: (是/否)
- §5.4 materials_extracted 条数: ___
- 失败/异常: (无 / 贴 §6 信息)
```
```
```
