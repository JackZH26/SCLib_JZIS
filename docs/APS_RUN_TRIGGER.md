# APS 入库链路 — 给瓦力(openclaw)的触发任务（VPS2 执行）

> 创建：2026-06-03 ｜ 执行环境：VPS2（`/opt/sclib`，APS Harvest IP 白名单内）
> 关联：`docs/APS_VALIDATION_FOR_OPENCLAW.md`（完整说明）、`docs/APS_INGESTION_PLAN.md`（设计）
> 直接把本文件内容发给瓦力即可；它按序执行，遇到任一「停下报告」点立即中止。

---

**【任务：跑通 APS 入库链路 — 在 VPS2 执行】**

背景：APS 全文 401 的根因已查明并修复——全文 ZIP 与 metadata 是**同一 base 路径**
`/v2/journals/articles/{doi}`，靠 `Accept: application/zip` 区分，**不需要 key**，由同一
IP 白名单授权（`72.62.251.29` / `76.13.191.130`）。代码已修正并 push（含修正 commit `8ae983b`）。
请按下列四步执行，每步贴出实际输出。

## 步骤 1 — 确认代码已部署

```bash
cd /opt/sclib && git fetch origin && git log --oneline -5
```

- HEAD 含 `8ae983b fix(ingestion): correct APS full-text endpoint` → 进步骤 2。
- 不含 → 先部署，再继续：

```bash
git pull --ff-only origin main
export GIT_SHA=$(git rev-parse --short HEAD)
docker compose build api ingestion
docker compose up -d api
```

> 注意：本仓库 GitHub Actions 自动部署已知静默失效，`git push` ≠ 已部署，必须手动核对 HEAD。
> 只重启 api，**不要** `docker compose up` 整栈（避免影响现有 jzis.org / asrp.jzis.org）。

## 步骤 2 — 出口 IP 核验 + APS 直连冒烟（关键，先于管线）

**(a) 宿主 + 容器各自的出口 IP**（容器的才是 APS 真正看到的来源）：

```bash
curl -s https://api.ipify.org; echo
docker compose run --rm ingestion \
  python -c "import urllib.request;print(urllib.request.urlopen('https://api.ipify.org',timeout=10).read().decode())"
```

两者都应是 `72.62.251.29` 或 `76.13.191.130`。
**若容器出口是第三个 IP，停下报告 Jack**（需把该 IP 加入 APS 白名单）。

**(b) 用 APS IT 的可用示例直连冒烟**（白名单 DOI `10.1103/hbdj-2hgf`）：

```bash
curl -s -H "accept: application/json" -o /tmp/aps_meta.json \
  -w "meta http=%{http_code} ctype=%{content_type} size=%{size_download}\n" \
  "https://harvest.aps.org/v2/journals/articles/10.1103/hbdj-2hgf"
curl -s -H "accept: application/zip" -o /tmp/aps_full.zip \
  -w "full http=%{http_code} ctype=%{content_type} size=%{size_download}\n" \
  "https://harvest.aps.org/v2/journals/articles/10.1103/hbdj-2hgf"
file /tmp/aps_full.zip; head -c 4 /tmp/aps_full.zip | xxd
```

判读：

- 两条都 `200`，且 zip 文件头是 `PK..`（`50 4b 03 04`）→ ✅ 链路前提成立，进步骤 3。
- 全文 `200` 但不是 ZIP（裸 XML）→ **停下报告 Jack**（需给 `download_bagit` 加 XML adapter）。
- `401 {"…not authorized"}`（点名 DOI）→ 来源 IP 不在白名单，回步骤 2(a)。
- `401 {"Unauthorized"}`（泛化、不点名）→ 代码未含路径修正，回步骤 1 部署。

## 步骤 3 — 应用数据库迁移（先备份）

```bash
cd /opt/sclib
docker compose exec postgres pg_dump -U sclib -d sclib -Fc -f /tmp/pre_aps_0038.dump
docker compose exec api alembic current        # 现应为 0037_paper_geo
docker compose exec api alembic upgrade head
docker compose exec api alembic current        # 应到 0039_tdm_audit_log (head)
```

回归校验现有 arXiv 未受损：

```bash
docker compose exec postgres psql -U sclib -d sclib -c \
 "SELECT source,count(*) FROM papers GROUP BY source ORDER BY source;"
```

## 步骤 4 — 跑入库管线（目标 DOI `10.1103/PhysRevB.104.014501`）

**4.1 先 dry-run**（不写库，验证「全文抽完即删」的合规闭环）：

```bash
docker compose run --rm ingestion \
  python -m ingestion.aps_pipeline --doi 10.1103/PhysRevB.104.014501 --dry-run -v \
  2>&1 | tee /tmp/aps_dryrun.log
# 合规硬检查：必须无残留
find /dev/shm /tmp -maxdepth 3 -name 'aps-*' -type d 2>/dev/null || echo "无 aps-* 残留 — 合规 OK"
```

dry-run 成功标志：日志含 `deletion_confirmed: True`、`done: 1/1 ok`，且无 `aps-*` 残留目录。
**若有残留，立即停止报告 Jack（合规问题）。**

**4.2 正式入库**（dry-run 成功后）：

```bash
docker compose run --rm ingestion \
  python -m ingestion.aps_pipeline --doi 10.1103/PhysRevB.104.014501 -v \
  2>&1 | tee /tmp/aps_ingest.log
```

期望关键行：
`[OK ] 10.1103/PhysRevB.104.014501 — journal=PRB secs=<N> mats=<M> chunks=<K> deleted=True related_arxiv=<…>`
与 `tdm_audit_log written: … status=deleted deleted=True`，退出码 `0`。

随后按 `docs/APS_VALIDATION_FOR_OPENCLAW.md` §5 跑 SQL 校验：papers 行 `source='aps'`/期刊正确、
chunks 不含全文正文、`tdm_audit_log.deletion_confirmed=true`。

## 回报清单

- 步骤 2：宿主 + 容器两个出口 IP；metadata / full 两条 curl 的 `http_code`。
- 步骤 3：`alembic current` 结果；各 source 行数。
- 步骤 4：dry-run 与正式入库的关键行 + 退出码；§5 SQL 校验结果。
- 任一「停下报告」点请立即中止并说明现象。
