# SCLIB 自动入库与 NER 暂停记录（2026-09-03）

> 状态：暂停已实施。GitHub 日常入库工作流和材料聚合调度已停，APS 保持原停用状态，宿主脚本、Compose ingestion 入口和 systemd service 均已加入维护标记检查。独立备份调度继续保护现有数据。

## 目的与边界

按用户要求，暂停 SCLIB 论文自动入库、NER 和关联自动聚合，为后续改造升级保留稳定的数据基线。不删除代码、已有论文、材料、向量、对象存储内容、检查点或调度配置；保留在线 API、查询、前端、数据库和缓存。

项目目录：`/Users/jackzhou/Documents/JZIS/SCLib`。生产执行目录：VPS2 `72.62.251.29:/opt/SCLib_JZIS`。现场证据目录为本地 `audit/automation_pause_20260903/`，该目录受 Git ignore 排除，勿将可能含运维信息的原始证据加入版本控制。

## 已核验的触发方式与暂停前状态

| 对象 | 暂停前状态或现场观测 | 本次已完成的动作 |
| --- | --- | --- |
| GitHub Actions：`Daily arXiv ingest` | 工作流为 `active`；`.github/workflows/ingest-daily.yml` 设置 UTC 每天 06:00、14:00 及手动触发 | 已在 GitHub 将工作流设为 `disabled_manually`；保留工作流文件 |
| `sclib-aggregate.timer` | `enabled`、`active`、`waiting`；每小时约 :30 触发 | 已停用调度并停止 timer，当前 `inactive`；保留原 unit 软链接，因此 `UnitFileState=linked`，不表示调度仍启用 |
| `sclib-aggregate.service` | `linked`、`inactive`；未运行聚合 | 保持 `inactive`，增加维护标记条件检查 |
| `sclib-aps-yearly-ingest.timer` | `disabled`、`inactive` | 保持 `disabled`、`inactive` |
| `sclib-aps-yearly-ingest.service` | `disabled`、`inactive` | 保持 `disabled`、`inactive`，增加维护标记条件检查 |
| 历史 `sclib-ingest.timer` | `not-found`、`failed`；不存在对应 unit 文件 | 仅记录历史状态，不重建或启动 |
| VPS2 root / 系统 cron | 未发现 SCLIB 入库或 NER 的有效触发条目 | 无条目需要暂停 |
| VPS2 活跃作业 | 未发现入库或 NER 进程、一次性 ingestion 容器 | 无在途论文需要中断；无须终止 API 容器 |
| API / frontend / PostgreSQL / Redis | 均为 healthy | 保持运行 |
| Discovery feed / identity agent | 属于其他在线功能及 API 身份依赖 | 维持现有运行及调度设置 |
| `sclib-maintenance-backup.timer` / `.service` | 本次新增；原无此独立维护备份任务 | timer 每天 UTC 06:00、14:00 调用原备份脚本，并设置 `SCLIB_BACKUP_SKIP_PRUNE=1` 保留旧备份 |

现场证据包括 `github_workflow_before.json`、`github_runs_before.json`、`github_workflow_after.json`、`github_pending_after.json`、`vps_before.json`、`verification.json`、`pause_guard_backup_stub_verification.json`，均位于 `audit/automation_pause_20260903/`。

VPS2 变更前完整脚本及配置副本保存于 `/var/lib/sclib/maintenance/20260903T105201Z/originals/`；状态记录和变更包保存在同一维护目录。保留这些副本供升级核对和必要时回滚，不以覆盖旧代码代替日常恢复。

## 程序入口与调用链

### arXiv 主流程

`.github/workflows/ingest-daily.yml` → SSH 到 VPS2 → `scripts/cron_daily_ingest.sh` → 一次性 Docker Compose `ingestion` 容器：

1. `sclib-ingest --mode incremental`：采集 arXiv、解析、分块、嵌入、Material NER、PostgreSQL 写入、Vertex Vector Search 写入及 Geo NER。
2. `sclib-ingest --mode retry --limit 20`：重试失败池。
3. `sclib-ingest --mode aggregate-materials`：从 `papers.materials_extracted` 汇总材料表。
4. 内部 `POST /v1/stats/refresh`：更新统计缓存。
5. `scripts/backup_postgres.sh`：创建并验证 PostgreSQL 备份。

`ingestion/pyproject.toml` 将 `sclib-ingest` 注册到 `ingestion.pipeline:main`。`docker-compose.yml` 的 ingestion 服务属于 `tools` profile，仅按需运行，无常驻队列 worker。仓库文档同时保留 `/etc/cron.daily/sclib-ingest` 及 root crontab 的安装示例，但 VPS2 本次未发现对应有效 cron。

暂停日常入库工作流会同时停止其末尾备份步骤，因此本次已新增独立的 `sclib-maintenance-backup.timer`，只执行原 PostgreSQL 备份脚本。具体调度与恢复方式见下文。

### APS 全文入库

`sclib-aps-yearly-ingest.timer` → `sclib-aps-yearly-ingest.service` → `scripts/aps-yearly-ingest-once.sh` → `python -m ingestion.aps_batch` → `ingestion.aps_pipeline.process_aps_paper`。

流程从 `/opt/sclib_aps_manifests/yearly/` 选择未完成年份，使用 `/opt/sclib_aps_manifests/checkpoints/` 下的 JSONL 检查点。每篇执行临时 APS 全文下载、Material NER、临时全文清理、授权派生数据入库、向量写入及 `tdm_audit_log`。每批还会调用 `scripts/sclib-daily-aggregate.sh`。

虽然脚本名包含 `once`，当前实现有持续推进的 `while true`，仅停止 timer 不会终止已启动的 runner。本次现场未发现活跃 runner，避免了处理中断。

### 独立 NER 与聚合

| 类型 | 入口 | 写入对象 |
| --- | --- | --- |
| Material NER | `ingestion/extract/material_ner.py`，由 arXiv / APS 主流程调用 | `papers.materials_extracted` |
| Material NER 重跑 | `python -m ingestion.rener`、`scripts/rener_bulk.py`、`scripts/rener_old_batch.py`、`scripts/rerun_ner.py` | 单篇 NER 结果；部分入口随后自动聚合 |
| 作者机构与地理 NER | `ingestion/extract/affiliation_ner.py`、`scripts/backfill_paper_geo.py` | `papers.affiliations`、`papers.paper_geo` |
| Hydride 参数 NER | `python -m ingestion.hydride_parameters` / `sclib-hydride-ner` | `hydride_tc_parameters`，APS 分支另写删除审计 |
| 材料聚合 | `sclib-aggregate.timer` → `scripts/sclib-daily-aggregate.sh` → `sclib-ingest --mode aggregate-materials` | `materials` 与统计缓存 |

上述模块路径以 Python 包目录为基准，实际文件位于仓库的 `ingestion/ingestion/` 下。仓库中未发现这些独立 NER 脚本专属的 Celery、RQ 或 Supervisor worker 定义；实际启停判断仍以现场进程、容器及调度扫描为准。

## 本机、Codex、CI 与外部触发检查

- CI：已定位并停用 GitHub `Daily arXiv ingest`，停用后未发现该流程在途或待处理运行。其他测试、镜像发布、部署和恢复演练工作流保留。
- 本机：已检查进程、`launchctl` 和 cron，未发现相关入库 / NER 自动任务或活跃进程。
- Codex：本机 `/Users/jackzhou/.codex/automations` 目录不存在，未发现该位置定义的 SCLIB 自动任务；没有新增 Codex 自动任务。
- OpenClaw：`docs/APS_OPENCLAW_CRON_FIX.md` 和 `docs/APS_OPENCLAW_FULLTEXT_INGEST_RUNBOOK.md` 明确记载外部监控可能重新启动 APS runner；仓库未保存实际任务 ID。本次遵守 `PROJECT_SPEC.md` 的限制，未访问 VPS1 `76.13.191.130`，也未宣称修改了 VPS1 的 OpenClaw 任务。VPS2 的宿主脚本、Compose 和 systemd 守卫会阻止外部通过现有入口重新触发；这些守卫不覆盖主动绕开 Compose entrypoint、直接执行其他副本等非标准调用。

## 已实施的暂停机制

维护标记为 VPS2 的 `/opt/SCLib_JZIS/scripts/.sclib-ingestion-paused`。标记存在期间，以下入口检查标记并跳过执行；恢复时将标记移入维护备份目录即可，无须删除程序或配置。

1. 三个宿主脚本在正式处理前检查标记：`scripts/cron_daily_ingest.sh`、`scripts/aps-yearly-ingest-once.sh`、`scripts/sclib-daily-aggregate.sh`。这覆盖 cron、SSH 和外部监控调用这些脚本的路径。
2. `scripts/ingestion_pause_guard.sh` 包装 base / production Compose 的 ingestion entrypoint。宿主 `scripts` 目录挂载到容器 `/app/scripts`，容器使用同一标记；标记存在时输出暂停提示并以成功状态退出，不执行传入命令。
3. production Compose 解除暂停后仍经 `validate_gcp_credentials.py exec --` 验证 GCP 工作负载身份；base Compose 显式保留原默认命令 `sclib-ingest --mode smoke --limit 30`。API 的 entrypoint 和身份验证没有改变。
4. 以下 systemd drop-in 增加条件 `ConditionPathExists=!/opt/SCLib_JZIS/scripts/.sclib-ingestion-paused`，阻止维护期经 service 启动：

   - `/etc/systemd/system/sclib-aggregate.service.d/90-ingestion-maintenance.conf`
   - `/etc/systemd/system/sclib-aps-yearly-ingest.service.d/90-ingestion-maintenance.conf`

所有原 unit、调度文件、代码、数据及检查点均保留。已停止的聚合 timer 和原已停止的 APS timer 与入口守卫共同避免定时及外部重新派发。暂停标记不纳入 Git，后续部署应保留该标记及守卫，直到明确执行恢复步骤。

## 维护期间的备份

`sclib-maintenance-backup.timer` 每天 UTC 06:00、14:00（UTC+8 为 14:00、22:00）调用 `sclib-maintenance-backup.service`。service 使用原有 `scripts/backup_postgres.sh`，设置 `SCLIB_BACKUP_SKIP_PRUNE=1`，仅新增、上传和验证备份，不清理旧备份。

本次未额外手动运行新备份任务。此前 2026-09-03 10:34:57 UTC 的备份已成功；安装维护 timer 后的下一次计划运行是当日 14:00 UTC。新调度的首次生产执行尚未发生，不能将脚本检查或隔离验证记作新备份已完成。恢复入库流程前先停用维护 timer，避免与原入库流程末尾的备份重复调度。

## 保留的在线功能

保留 Nginx、SCLIB API、frontend、PostgreSQL、Redis 及现有监控；不执行整栈 `docker compose down`、数据卷删除、数据库迁移或 API 重启。

`sclib-identity-agent.service` 也为 API 提供 GCP 工作负载身份，应保持运行。`sclib-discovery-feed-pull.timer` 只更新 Discovery JSON 缓存，无论文 NER 或入库，维持原设置。

`api/main.py` 内的统计刷新、timeline projection、formula audit、nightly audit 及 Ask history 维护不属于本次论文入库 / NER 流程，保留现场已有设置；不因代码默认值而额外启用已被关闭的功能。

## 数据与恢复边界

- paper 与 chunks 的每篇写入处于同一个 PostgreSQL 事务；PostgreSQL、Vertex 和 Geo NER 之间没有跨服务事务。
- arXiv harvest state 和失败池在批次结束时保存。中断后可能重跑已写入论文，恢复时必须保留原 checkpoint，不能手工前移采集日期。
- APS 检查点每篇先写 `started` 再写最终状态。未完成条目会在恢复时重试；manifest、checkpoint、skip-years 文件和日志全部保留。
- Hydride runner 逐篇提交并记录检查点。恢复须使用原 manifest、原 checkpoint 及合适的 `--retry-failed` 参数。
- 聚合每 200 材料提交，整个聚合不是一个事务。后续如确有在途聚合，应优先让其短批正常结束。
- Python 未安装专用 SIGTERM handler；APS 临时全文清理及审计依赖 Python 上下文管理和 `finally`。本次没有在途任务，因此没有使用硬终止，也没有删除临时文件或检查点。

## 恢复步骤

仅在用户要求恢复自动入库，且确认升级后的代码、配置、原检查点兼容后执行。以下步骤恢复本次变更前已启用的流程；APS 原本停用，保持停用。

1. 在 VPS2 停止维护备份的后续调度，并查看是否已有备份正在执行：

   ```bash
   systemctl disable --now sclib-maintenance-backup.timer
   systemctl show sclib-maintenance-backup.service --property=ActiveState,SubState
   ```

   停 timer 不会停止已开始的 service。如果 service 正在运行，先等它正常结束并检查日志，再继续，避免中断备份。保留维护 backup 的 unit 文件，timer 保持 disabled。

2. 在 VPS2 将暂停标记移到既有维护备份目录，保留记录：

   ```bash
   mv -n /opt/SCLib_JZIS/scripts/.sclib-ingestion-paused /var/lib/sclib/maintenance/20260903T105201Z/ingestion-paused.restored
   test ! -e /opt/SCLib_JZIS/scripts/.sclib-ingestion-paused
   ```

   第二条检查必须成功后才能继续。所有入口守卫和 systemd drop-in 均可保留，标记不存在时会恢复原执行链。

3. 在 VPS2 恢复原本启用的材料聚合 timer：

   ```bash
   systemctl enable --now sclib-aggregate.timer
   systemctl list-timers --all sclib-aggregate.timer
   ```

   timer 带 `Persistent=true`，恢复后可能立即补一次错过的聚合，应在解除暂停前确认已准备好。

4. 在有该仓库 GitHub 管理权限的终端恢复原日常入库工作流：

   ```bash
   gh workflow enable ingest-daily.yml --repo JackZH26/SCLib_JZIS
   gh api repos/JackZH26/SCLib_JZIS/actions/workflows/ingest-daily.yml --jq .state
   ```

   确认状态恢复为 active，并检查是否出现新的排队 / 运行任务；不需要手动 dispatch 来完成恢复。

5. 保持 `sclib-aps-yearly-ingest.timer` 和 `.service` 为原先 `disabled`、`inactive`。如果用户另行要求启动 APS 全文入库，再核对 manifest、checkpoint 和年份范围后启用，不将其并入本次常规恢复。

恢复无需 API 重启、整栈重启或删除守卫配置。不得以全量 `systemctl enable --now sclib-*` 代替逐项恢复。

## 验证记录

暂停前及操作过程中均未发现活跃入库 / NER 作业，因此未中断正在处理的论文，也未删除代码、已有数据或配置。API、frontend、PostgreSQL、Redis 保持 healthy，未为暂停执行 API 重启；Discovery、身份服务和其他 CI 保持原设置。

最终核验时间：2026-09-03 10:55:30 UTC（新加坡 / 香港时间 18:55:30）。原始证据为 `audit/automation_pause_20260903/verification.json`。

| 检查 | 结果 |
| --- | --- |
| 宿主三个调度脚本 | 均输出暂停提示，exit 0；未执行入库、聚合或通知 |
| production Compose ingestion 实际容器探针 | 守卫跳过无副作用的测试命令，exit 0；原有生产容器未启动或重建 |
| PostgreSQL / Redis readiness | `/readyz` HTTP 200，两个依赖均 ok |
| `https://api.jzis.org/sclib/v1/stats` | HTTP 200；75,202 篇论文、11,463 个材料 |
| `https://api.jzis.org/sclib/v1/materials?limit=1` | HTTP 200，返回材料查询结果 |
| `https://api.jzis.org/sclib/v1/paper/arxiv:2306.07275` | HTTP 200，论文 ID 和标题有效 |
| `https://jzis.org/sclib` | HTTP 200 |
| `https://jzis.org/` | HTTP 200 |
| `https://asrp.jzis.org/` | HTTP 200 |
| 现有七个容器 | ID 与 StartedAt 均和暂停前一致；四个核心容器 healthy |
| 采集检查点及相关状态文件 | 抽取的 50 个文件 SHA-256 全部保持不变 |
| 任务状态 | GitHub `disabled_manually`、无待处理运行；无入库 / NER 进程或容器 |
| 独立备份调度 | systemd 配置验证通过；timer enabled / active / waiting，下一次 14:00 UTC |

额外扫描 `/etc/systemd/system`、`/usr/lib/systemd/system`、用户 systemd 目录、Supervisor 配置及 at 队列，没有发现其他生产入库触发器或活跃 worker，见 `extra_trigger_audit.json`。本机进程扫描见 `local_process_scan.json`。

入口守卫及备份脚本的隔离验证见 `pause_guard_backup_stub_verification.json`：暂停时不执行目标命令；恢复后的参数与退出码完整透传；维护备份仍执行生成、验证及模拟上传，但不调用旧备份扫描或删除，即使 env 文件覆盖保护变量为 0 也不能解除外部保护。该验证使用 stub，不代表新维护备份 timer 已在生产执行。

本次未执行带模型调用的语义搜索或 RAG 问答验证；已验证的是在线 readiness、统计、材料及论文查询。源代码的维护变更同时保留在本地工作区和 VPS2，未提交或推送 Git；后续发布时须保留暂停标记、入口守卫和 systemd 条件，直到用户要求恢复。
