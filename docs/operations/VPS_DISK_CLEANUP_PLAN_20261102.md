# VPS 磁盘清理建议

日期：2026-11-02。目标：`jzis-vps2`，`srv1554116`，`72.62.251.29`。当前状态：用户已确认第一轮 A 组，已执行并完成范围核验；B/C 继续保留，未下架 Google 索引或删除云备份。

原提案预计 A 组释放约 30.17 GiB。实际释放 **29.28 GiB**，空闲量由 **232.74 GiB** 增至 **262.02 GiB**。镜像共享层及缓存引用导致实际回收量与估算不同。B 组旧数据库和历史备份先保留，完成异机归档及恢复核验后再处理；C 组科研输入和检索迁移资料不在本轮删除范围。

## 执行结果

执行记录 `20261102T082508Z`，2026-11-02 16:36 左右 UTC+08 完成白名单对象删除，随后完成在线检查。

| 项目 | 实际结果 |
| --- | --- |
| 重复压缩包 | 两份已再次校验 Mac 与 VPS 的 SHA256 后删除；Mac 原包和远端解压输入保留 |
| 历史 Docker 对象 | 指定 110 个停止容器及 16 个镜像均删除成功，无强制删除或批量 prune |
| 恢复资料 | 110 个容器定义和日志、6 个本地独有镜像已归档至 Mac 并核对传输哈希、gzip CRC 和对象清单；10 个发布镜像的固定 digest GHCR manifest 可读取，未重新 pull 或演练 docker load |
| 缓存 | 指定 npm/pip 目录及 Trivy cache 卷已清理；其他卷保留 |
| 保护对象 | 生产/基线容器 ID、镜像和挂载相同，五个线上下载文件逐文件哈希一致；旧数据库副本、科研输入及云备份保留 |
| 空间 | 清理前已用 153.67 GiB、空闲 232.74 GiB；清理后已用 124.39 GiB、空闲 262.02 GiB |
| 业务核查 | 首页、SCWiki 搜索文件、版本、统计、材料、论文详情、时间线、Ask 均返回 200；公开统计数量一致 |

Similar 探针首次返回 503，一次复测返回 200 且 generation 不变，原始失败回执保留，不将其改写为首次通过。下载元数据匿名请求返回 401，未绕过认证；下载内容通过服务器端五个文件的前后 SHA256 比对核验。

另发现保留的旧基线 API 因 schema 与镜像要求不匹配而循环重启，累计重启超过 22,000 次。该容器及其镜像未被本次操作修改，当前生产 API 重启计数为零、health 为 healthy。旧基线兼容性已列入后续 pgvector 迭代前置条件，本轮没有扩大到服务修复。

## 清理前占用

根文件系统总量约 386.43 GiB，使用约 153.67 GiB，空闲约 232.74 GiB，使用率约 40%。空间尚有余量，本轮优先清理已验证的重复副本和可再生文件。

| 位置 | 占用 | 说明 |
| --- | --- | --- |
| `/opt/sclib-materials-transfer` | 46.55 GiB | 其中旧候选目录 44.50 GiB，包含压缩包和大量解压文件；整个根目录不能删除 |
| Docker volumes | 约 47.1 GiB | 包括现用 PostgreSQL、旧升级数据库副本及监控数据 |
| `/var/lib/sclib/maintenance` | 21.52 GiB | 多为九月检索重建、完整输入、embedding 和验收资料 |
| Docker images | Docker 报告总量约 22.19 GB | 包含共享层；不能按每个镜像的显示大小直接相加 |
| `/root` | 2.35 GiB | 旧工作树归档、五月数据库备份及包缓存 |
| `/var/log` | 约 0.47 GiB | 日志不是主要占用，本轮保留 |

Docker 镜像占用采用其 verbose 报告，文件和卷采用实际分配字节。不同层级和共享层的统计不重复累加。Docker 报告可回收不等于项目允许删除，恢复镜像和当前 ingestion 即使没有运行容器也必须保留。[Docker 磁盘统计说明](https://docs.docker.com/reference/cli/docker/system/df/)

## A 组 建议本轮确认的清理

| 对象 | 预计回收 | 已核查依据 | 执行前条件 |
| --- | --- | --- | --- |
| 旧候选目录的 `INPUTS.tar.gz` 和 `CODE.tar.gz` | **19.446 GiB** | VPS 与 Mac mini 两个包均实际计算 SHA-256，与原 manifest 一致；文件各只有一个硬链接；无容器挂载、运行进程或已扫描服务配置引用候选目录 | 再核对文件未变化，只删除这两个压缩包，保留解压输入与所有状态记录 |
| 指定历史镜像 16 个及其关联停止容器 110 个 | 镜像 unique size 估算约 **9.177 GiB** | 关联容器在审计时全部停止；已列出确切 ID，排除当前、两次近期发布、基线、材料发布和运行依赖镜像 | 保存容器定义和日志；本地 canary 镜像须先异机保存并校验，或验证可从受控仓库恢复；执行时再次检查引用 |
| 无容器引用的 `trivy-cache` 卷 | **1.108 GiB** | Docker volume 清单中没有容器引用；属于可重新下载的扫描缓存 | 确认没有扫描任务运行，再按确切卷名清理；下次扫描重新下载缓存 |
| `/root/.npm/_cacache` | **0.410 GiB** | 包管理缓存，无生产 bind mount | 确认无 npm 构建任务，仅清缓存，不删除配置或凭据 |
| `/root/.cache/pip` | **0.034 GiB** | Python 下载缓存，无生产 bind mount | 确认无 pip 安装任务，仅清该缓存 |

停止容器的可写层总量仅约 3.2 MiB，清理它们主要是解除旧镜像引用和整理环境，不将它们宣传为大型空间来源。镜像共享层、后台写入和删除期间变化会影响最终回收量，完成后用 `df` 实测，不预先保证恰好释放 30.17 GiB。

### 已验证的重复压缩包

远端目录：`/opt/sclib-materials-transfer/candidate-926548f2f3e5ab15/`。

Mac mini 已有相同原始包：

```text
/Users/jackzhou/Documents/Sclib/SCWiki/reviews/materials-empirical-plain-20261021/production90-20261026/goal-transition-20261028/server-transfer-package-12944/INPUTS.tar.gz
/Users/jackzhou/Documents/Sclib/SCWiki/reviews/materials-empirical-plain-20261021/production90-20261026/goal-transition-20261028/server-transfer-package-12944/CODE.tar.gz
```

| 文件 | 实际逻辑字节 | VPS 和 Mac 一致的 SHA256 |
| --- | ---: | --- |
| `INPUTS.tar.gz` | 20,872,711,861 | `aef29de3f294efad25cfd1f26d123cd3c9703edb5fca0d005b2ac382eefaacd9` |
| `CODE.tar.gz` | 7,578,454 | `59f4bd0556ffb846818a1851ee427b49fec472f6a472c1ee2620dc76388173ad` |

候选目录的解压输入约 25.03 GiB，涉及约 231 万文件条目及大量内部硬链接。A 组不删除这些内容；因此无需把目录总量 44.50 GiB 当成本轮可释放量，也不依赖对外部硬链接的推测。

### 镜像和容器范围

拟清理镜像短 ID 如下，执行使用清单中的完整 SHA256，不使用通配或 `--force`：

```text
0eff77b7215e  4d80df869d61  6667608a5106  d13d0ae3cb8c
62fbe8925d8c  d7afe4aa4a24  3f5560bab29e  461977e979c4
71996cd81f68  6e3a3447aed5  d66a42efcf89  be7816a932c5
89a2138afd0a  564e1d27172f  ef9f568c9178  62d80ffca5d1
```

明确保留以下发布 revision 对应的镜像，以及 PostgreSQL、Redis 和监控运行镜像：当前 `984d5d9`、近期 `a752f20` 与 `2027693`、基线 `1f9dc6c`、材料发布 `a4a2ade`。当前 ingestion 镜像 `0509989c9c16` 没有运行容器，但由 `.env.release` 引用，必须保留。基线 API 即使处于停止状态，也不在本轮容器清单中。

110 个拟处理容器的完整 ID、名称和绑定镜像位于仓库外审计清单。先归档定义和日志，再按清单删除容器本身，不附加删除卷选项。删除镜像前再次检查所有容器和部署配置，遇到新增引用即从本轮清单移出。

## B 组 归档和恢复核验后再确认

| 对象 | 占用 | 判断与保留条件 |
| --- | --- | --- |
| 九月升级数据库副本 | **23.02 GiB** | 仅由已停止的 `sclib-upgrade-clone-20260921` 引用；不是生产数据库。先异机归档停止卷、验证恢复，并确认所需历史状态已有保存，再单独清理 |
| 六月工作树修复归档 | **1.27 GiB** | `/root/sclib_worktree_repair_20260626T064120Z` 内有 `untracked_files.tgz` 和未提交 patch，不能假定 Git 已保存；异机归档、核验后再移除 VPS 副本 |
| 五月 SQL 备份 | 约 **0.43 GiB** | 三份 root 下 gzip 备份；先保存历史副本并验证当前备份恢复，不仅按日期删除 |

旧升级数据库卷的确切名称：

```text
80b65405b9f30f0c26e267e8a0924824b5a4faf75d883db12fe38f2e45295743
```

现用 PostgreSQL 卷为 **`sclib_jzis_postgres_data`**，与旧副本是不同对象。不得手工删除 `/var/lib/docker/volumes` 内部文件，也不使用全局 volume prune 代替确切目标操作。

已通过专用备份身份只读列出 GCS 中 107 份 dump；最近一份是 `sclib-20261102T060029Z.dump`，大小 8,881,260,355 字节，2026-11-02 14:29 左右 UTC+08 已上传，配套 manifest 存在。本轮没有下载并恢复此备份，因此只证明对象存在，不证明完整恢复已通过。云备份也不占 VPS 这块磁盘，不纳入本轮删除范围；沿用至少 35 个每日恢复点的既有政策。

## C 组 本轮保留

- `/var/lib/sclib/maintenance/index-compatibility-20260922`，约 20.87 GiB，保留完整输入、embedding、生产激活及验收资料；先服务即将实施的 pgvector 迁移，之后另做归档方案。
- 候选目录的 `inputs`、当前 `final-74322bfd56c961e7`、正式 export、CSV、发布目录和其证据。
- `/opt/sclib-materials-transfer/production-publish-a4a2ade-r2-20261031/run/downloads`，它被当前 API 直接挂载，属于线上下载服务。
- PostgreSQL、Redis、Prometheus、Grafana、Alertmanager 的运行卷；生产和基线站；`/data/sclib`、凭据、SSH、身份运行目录与应用配置。
- APS 原文和工作副本按原项目保留及后续明确删除指令处理；本轮不扩大原文删除范围。
- 现有安全、访问、备份和部署日志。全部 Docker 容器日志约 147 MiB，journal 约 240 MiB，收益不足以优先牺牲排障记录。

APT cache 和 Docker build cache 不计入首轮收益：APT 的显示占用未必等于 `apt-get clean` 能释放量，Docker 当前 build cache 显示可回收仅约 35.76 MB。避免把可回收量重复或夸大。

## 用户确认后的执行顺序

1. 刷新磁盘、容器状态、完整镜像 ID、部署引用、挂载和打开文件清单，与已确认的 A 组比对。出现漂移先缩小清单，不扩大删除范围。
2. 将 A 组容器定义、必要日志和只能本地恢复的镜像归档到 Mac mini，记录大小与 SHA256；敏感配置按现有私有凭据规则保存，不打印到报告。
3. 重新确认两份传输包仍与已验证 Mac 副本一致，逐文件删除远端重复压缩包；保留所有解压输入及状态 JSON。
4. 清理确切 npm/pip 缓存和无引用的 Trivy cache；不调整现有服务和扫描安全策略。
5. 逐个移除清单内仍停止的历史容器，再移除对应镜像；不使用强制模式，不删除绑定目录和任何其他卷。
6. 复核磁盘实际变化及现网 version、Search、Similar、论文、Materials、下载、时间线、SCWiki 和监控。需要 Ask 实测时控制模型请求数量。
7. 保存逐项成功、跳过及失败记录，重新计算 pgvector 与 APS 的共同空间预算。B/C 不随 A 组一并执行。

不使用 `docker system prune -a --volumes`、全量删除停止容器、按年龄递归删除 `/opt` 或直接截断运行日志。[Docker 官方清理说明](https://docs.docker.com/engine/manage-resources/pruning/) 表明这些批量操作可能覆盖停止容器、镜像和卷；本次使用逐项白名单保留恢复资产。

## 审计材料

本地私有审计目录：`/Users/jackzhou/Documents/Sclib/SCWiki/reports/vps-disk-audit-20261102/`。执行结果入口为 `cleanup-result.json`，逐项事件及前后状态位于 `execution-20261102T082508Z/`。含原始容器配置的归档按 owner-only 权限保存在 Git 仓库外的 `SCWiki/private/vps-cleanup-20261102/20261102T082508Z/`。

其中 `cleanup-proposal.json` 保留执行前候选清单，`archive-copy-verification.json` 是跨设备哈希校验，`docker-inventory.json` 记录执行前镜像、容器和卷关系，`directory-inventory.json` 记录目录占用，`backup-status.json` 记录云端备份列表摘要。原提案与只读审计文件不覆盖，实际删除以执行事件和完成报告为准。
