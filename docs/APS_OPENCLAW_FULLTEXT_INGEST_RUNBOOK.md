# APS 全文入库监控任务说明（给 OpenClaw）

> 创建日期：2026-06-16  
> 目标环境：VPS2 `72.62.251.29`  
> 执行目录：`/opt/SCLib_JZIS`  
> 适用对象：OpenClaw（负责持续监控和推进 APS 全量全文入库）  
> 关联文档：`docs/APS_VALIDATION_FOR_OPENCLAW.md`、`docs/APS_RUN_TRIGGER.md`、`docs/APS_INGESTION_PLAN.md`

---

## 1. 当前状态

截至 **2026-06-16**，APS 入库基建已经可用于全量推进：

- APS Harvest 白名单与 VPS2 主流程已打通。
- 生产环境已验证 APS metadata / full-text ZIP 可正常拉取。
- `Gemini 3.5 flash` 已替换旧接口；NER 运行要求 `temperature=0`。
- DOI manifest + checkpoint/resume 批处理 runner 已可用。
- 现代窗口 calibration 已完成一轮 **500 篇** 实跑，主流程验证通过。
- 这轮 500 篇中，最终结果为：
  - `499` 篇 `ok`
  - `1` 篇 `error`
  - 唯一确认异常 DOI：`10.1103/466c-8sl4`（APS Harvest 返回 `404`，后续应视为无效 DOI，从全量清单中排除）
- 生产环境已完成一次 APS 聚合，说明 NER -> papers -> aggregate-materials 主链路可闭环运行。

这意味着：**现在不需要再做 20 篇 smoke run / 100 篇 pilot / 500 篇 calibration**，而是进入 **OpenClaw 监控下的全量分批入库阶段**。

---

## 2. 本轮任务目标

请 OpenClaw 在 VPS2 上制定并执行一个可持续监控的 APS 全量入库任务，要求如下：

1. **只使用授权范围内的 DOI manifest**。
2. **年份从新到旧**推进，即 `2026 -> 2025 -> ... -> 1986`。
3. **按批次推进**，每批可 checkpoint / resume，不做一口气全量跑完。
4. **每一批结束后必须做聚合和验收**，确认新增论文产生的数据已经真正进入系统。
5. **任何明显错误、合规风险、异常高失败率，都必须停止该批并回报**。
6. **不恢复 nightly 自动审计**；本轮重点是 APS 正式论文的全文入库、NER、聚合与监控。

---

## 3. 只能使用的权威清单

OpenClaw 后续全量任务，统一只使用下面这套清单：

- DOI 列表：`/opt/sclib_aps_manifests/aps_superconductivity_authorized_19860101_20261231_dois.txt`
- Manifest JSONL：`/opt/sclib_aps_manifests/aps_superconductivity_authorized_19860101_20261231_manifest.jsonl`

这套 manifest 已经完成授权窗口过滤：

- **保留范围：** `1986-01-01` 到 `2026-12-31`
- **已剔除：** `1986-01-01` 之前论文
- 当前授权窗口内 DOI 总量：**28,577**
- 已剔除的 pre-1986 DOI 数量：**3,204**

额外排除规则：

- 必须排除已确认无效 DOI：`10.1103/466c-8sl4`
- 若后续又发现 Harvest `404` 的 DOI，应追加到单独 invalid list，并从后续批次中移除

建议维护：

- `/opt/sclib_aps_manifests/invalid_dois.txt`
- `/opt/sclib_aps_manifests/yearly/`
- `/opt/sclib_aps_manifests/checkpoints/`
- `/opt/sclib_aps_manifests/reports/`

---

## 4. 年份拆分与推进顺序

### 4.1 总原则

- 严格按 **published year 降序**推进
- 同一年内按 `published_date` 降序推进
- 先跑新年份，再跑旧年份
- 不允许把 `1986` 之前论文重新混入

### 4.2 推荐执行顺序

1. `2026 -> 2020`
2. `2019 -> 2010`
3. `2009 -> 2000`
4. `1999 -> 1986`

这四段不是重新做 calibration，而是为了控制风险、方便监控和汇报。

### 4.3 推荐批大小

- `2026-2020`：每批 `500`
- `2019-2010`：每批 `300`
- `2009-2000`：每批 `200`
- `1999-1986`：每批 `100-150`

动态调节规则：

- 如果连续两批 `error rate <= 1%`，下一批可维持当前上限
- 如果某批 `error rate > 3%`，下一批应减半并先分析错误类型
- 如果同一类错误连续出现，先停下排查，不要机械继续推进

---

## 5. OpenClaw 的执行流程

## 5.1 开始当天先做的前置检查

进入目录：

```bash
cd /opt/SCLib_JZIS
git rev-parse --short HEAD
docker compose ps
```

确认：

- `main` 上代码为最新可用版本
- `api` / `frontend` / `postgres` / `redis` healthy

然后做 APS 直连检查：

```bash
curl -s https://api.ipify.org; echo
docker compose run --rm ingestion \
  python -c "import urllib.request;print(urllib.request.urlopen('https://api.ipify.org',timeout=10).read().decode())"
```

预期：

- 宿主与容器出口 IP 都是授权白名单 IP

然后做 Harvest 冒烟：

```bash
curl -s -H "accept: application/json" -o /tmp/aps_meta.json \
  -w "meta http=%{http_code} ctype=%{content_type} size=%{size_download}\n" \
  "https://harvest.aps.org/v2/journals/articles/10.1103/hbdj-2hgf"

curl -s -H "accept: application/zip" -o /tmp/aps_full.zip \
  -w "full http=%{http_code} ctype=%{content_type} size=%{size_download}\n" \
  "https://harvest.aps.org/v2/journals/articles/10.1103/hbdj-2hgf"
```

只有两条都 `200` 时，才继续当天批处理。

---

## 5.2 先生成按年拆分的 manifest

在 VPS2 上基于权威 JSONL 清单生成按年文件；同时剔除 invalid DOI。

参考命令：

```bash
cd /opt/SCLib_JZIS
mkdir -p /opt/sclib_aps_manifests/yearly /opt/sclib_aps_manifests/reports

python - <<'PY'
import json
from pathlib import Path
from collections import defaultdict

src = Path("/opt/sclib_aps_manifests/aps_superconductivity_authorized_19860101_20261231_manifest.jsonl")
invalid_path = Path("/opt/sclib_aps_manifests/invalid_dois.txt")
out_dir = Path("/opt/sclib_aps_manifests/yearly")
report = Path("/opt/sclib_aps_manifests/reports/year_manifest_summary.csv")

invalid = set()
if invalid_path.exists():
    invalid = {line.strip().lower() for line in invalid_path.read_text().splitlines() if line.strip()}

rows_by_year = defaultdict(list)
for line in src.read_text().splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    doi = str(row.get("doi", "")).strip()
    year = row.get("year")
    if not doi or not year:
        continue
    if doi.lower() in invalid:
        continue
    if int(year) < 1986:
        continue
    rows_by_year[int(year)].append(row)

for year, rows in rows_by_year.items():
    rows.sort(key=lambda r: (r.get("published_date") or "", r.get("doi") or ""), reverse=True)
    txt = out_dir / f"aps_{year}.txt"
    jsl = out_dir / f"aps_{year}.jsonl"
    txt.write_text("\n".join(r["doi"] for r in rows) + "\n")
    with jsl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

lines = ["year,count"]
for year in sorted(rows_by_year.keys(), reverse=True):
    lines.append(f"{year},{len(rows_by_year[year])}")
report.write_text("\n".join(lines) + "\n")
print(report)
PY
```

---

## 5.3 每一批的执行方式

示例：跑 `2026` 年的第 1 批 `500` 篇

```bash
cd /opt/SCLib_JZIS
mkdir -p /opt/sclib_aps_manifests/checkpoints /opt/sclib_aps_manifests/logs

docker compose run --rm \
  -v /opt/sclib_aps_manifests:/manifests \
  ingestion \
  python -m ingestion.aps_batch \
    --manifest /manifests/yearly/aps_2026.txt \
    --checkpoint /manifests/checkpoints/aps_2026.batch01.checkpoint.jsonl \
    --limit 500 \
    --retry-failed \
    -v \
  2>&1 | tee /opt/sclib_aps_manifests/logs/aps_2026_batch01.log
```

说明：

- `--limit` 控制单次批量规模
- `checkpoint` 是 append-only，可多次 resume
- `--retry-failed` 允许对上次 error DOI 重试
- 不要用 `--dry-run`
- 不要用 `--skip-ner`
- 不要用 `--skip-vector-search`

NER 约束：

- 继续保持 **temperature=0**
- 不允许临时切回旧 Vertex SDK 接口或旧 Gemini 2.5 flash

---

## 5.4 每一批跑完后的强制动作

### A. 检查批处理摘要

日志里必须提取最后一行：

- `APS batch done: selected=... ok=... error=... skipped=... manifest=...`

并据此计算：

- 本批处理数
- 本批成功数
- 本批失败数
- 本批失败率

### B. 立刻做一次聚合

```bash
cd /opt/SCLib_JZIS
docker compose run --rm ingestion sclib-ingest --mode aggregate-materials
```

### C. 合规检查

```bash
find /dev/shm /tmp -maxdepth 3 -name 'aps-*' -type d 2>/dev/null || echo "无 aps-* 残留"
```

预期：没有任何 APS 临时目录残留。

### D. 数据检查

每一批结束后，至少检查下面几项：

```bash
cd /opt/SCLib_JZIS

docker compose exec -T postgres psql -U sclib -d sclib -c "
SELECT status, deletion_confirmed, count(*)
FROM tdm_audit_log
WHERE source='aps'
GROUP BY 1,2
ORDER BY 1,2;"

docker compose exec -T postgres psql -U sclib -d sclib -c "
SELECT section, count(*)
FROM chunks
WHERE paper_id LIKE 'aps:%'
GROUP BY 1
ORDER BY 1;"

docker compose exec -T postgres psql -U sclib -d sclib -c "
SELECT credibility_tier, count(*)
FROM papers
WHERE source='aps'
GROUP BY 1
ORDER BY 1;"

docker compose exec -T postgres psql -U sclib -d sclib -c "
SELECT count(*) AS aps_papers
FROM papers
WHERE source='aps';"
```

验收标准：

- `tdm_audit_log.deletion_confirmed=true` 为主状态
- `chunks.section` 对 APS 只能出现 `Abstract` / `Facts`
- APS 正式论文应全部为 `credibility_tier='T1'`

### E. 产出批次报告

每一批结束后，OpenClaw 都要生成一段简报，至少包含：

- 年份
- 批次编号
- manifest 文件名
- checkpoint 文件名
- 本批 `selected / ok / error / skipped`
- 本批新增 APS paper 数
- 本批新增含材料抽取的 APS paper 数
- 聚合后新增 material 数 / 新增 APS-backed record 数
- 新发现 invalid DOI
- 前 5 个错误样本及错误类型

报告建议写到：

- `/opt/sclib_aps_manifests/reports/aps_YYYY_batchNN.md`

---

## 6. 必须停止并回报的情况

出现以下任一情况，OpenClaw 必须停止当批并回报，不要自行硬跑：

1. Harvest 冒烟不是双 `200`
2. 容器出口 IP 不在 APS 白名单
3. APS 临时目录没有被清干净
4. `chunks` 中出现 `Abstract` / `Facts` 之外的 section
5. 某批错误率超过 `3%`
6. 同类错误连续出现 `>=5` 次
7. 出现大面积 `401 not authorized`
8. 出现大面积 `404`，说明 manifest 质量异常
9. 新入库 APS paper 没有 `date_published` / `year` / `T1`
10. 聚合阶段报错，或明显没有把新论文数据并入 materials

---

## 7. 关于重复论文与跨源聚合

OpenClaw 在监控过程中要默认接受以下事实，不把它们当成错误：

- 同一 work 可能同时存在 arXiv 和 APS 两条 paper
- APS 正式发表版仍然需要独立跑全文 NER
- 聚合时会按现有规则处理重复工作：
  - 完全相同的记录可折叠
  - **只要 Tc 或条件不同，就保留为新记录**

因此：

- 看到 arXiv overlap 并不表示要跳过 APS
- 监控重点是“新增 APS 论文是否被成功入库、抽取、聚合”，不是简单按 DOI 去重后就不处理

---

## 8. OpenClaw 的推荐工作节奏

建议按“年度 + 批次”推进，而不是长时间单任务失控运行。

推荐节奏：

1. 先完成 `2026`
2. 再完成 `2025`
3. 再完成 `2024`
4. 依次往前推到 `1986`

每完成一个年份后，更新一份年度覆盖状态：

- 该年 DOI 总数
- 已入库数
- 成功率
- invalid DOI 数
- 需要人工复查的 error DOI 数

年度报告建议文件：

- `/opt/sclib_aps_manifests/reports/aps_year_2026_summary.md`

---

## 9. OpenClaw 回报模板

每次向 Jack 汇报时，使用下面这个最小模板：

```md
# APS ingest update

- Date:
- Year:
- Batch:
- Manifest:
- Checkpoint:
- Selected:
- OK:
- Error:
- Skipped:
- Error rate:
- New APS papers persisted:
- New APS papers with materials:
- Aggregate-materials:
- New invalid DOI:
- Residual temp dirs:
- Notes / blockers:
```

---

## 10. 一句话任务指令

可直接发给 OpenClaw：

> 请在 VPS2 ` /opt/SCLib_JZIS ` 基于授权窗口 manifest  
> `/opt/sclib_aps_manifests/aps_superconductivity_authorized_19860101_20261231_manifest.jsonl`  
> 制定并执行 APS 全文入库监控任务：按 **年份从新到旧（2026 -> 1986）** 拆分 DOI 清单，按批次跑 `ingestion.aps_batch`，每批完成后必须执行 `aggregate-materials`、合规检查、数据检查和批次报告；遇到高失败率、401/404 异常、清理残留、非 `Abstract/Facts` chunk、或明显数据不一致时立即停止并回报。

