# Google Vector Search 托管下架方案

日期：2026-11-02。配套 [SCLib pgvector 网站迭代计划](../PGVECTOR_MIGRATION_PLAN.md)。已按授权启动执行，第一阶段旧部署已取消并完成业务检查；当前生产部署仍保留。操作回执及未完成事项见 [实施记录](PGVECTOR_EXECUTION_20261102.md)。本文件保留完整操作规格，不能将后续步骤视为已完成。

下架分为取消闲置旧部署和取消当前生产部署。`undeployIndex` 移除在线部署并释放其资源；它与删除 index 数据、删除 endpoint、删除 PostgreSQL 数据是不同动作。[官方 API 说明](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1/projects.locations.indexEndpoints/undeployIndex)

## 确切目标

项目 `jzis-sclib`，项目号 `524541993265`，区域 `us-central1`。名称仅作辅助，执行时同时比对完整资源路径和 deployment ID。

| 项目 | 第一阶段旧部署 | 第二阶段当前部署 |
| --- | --- | --- |
| deployed index ID | `sclib_papers_v1` | `sclib_retained_20260922` |
| endpoint ID | `5476212220138356736` | `6002249369191972864` |
| index ID | `7874607720131723264` | `7947470156681183232` |
| endpoint 名称 | `sclib-papers-endpoint` | `sclib-retained-endpoint-20260922-e159c8cc` |
| 已核查向量数 | 1,102,125 | 1,183,943 |
| 已核查副本 | 最少 1，最多 1；当前监控为 1 | 最少 1，最多 1；当前监控为 1 |
| 现网用途 | 当前生产和基线 API 均未指向；10 月 1 日以来未返回该查询时间序列 | 当前生产、基线 API 及 SQL 生效版本均使用 |

完整资源路径：

```text
projects/524541993265/locations/us-central1/indexEndpoints/5476212220138356736
projects/524541993265/locations/us-central1/indexes/7874607720131723264

projects/524541993265/locations/us-central1/indexEndpoints/6002249369191972864
projects/524541993265/locations/us-central1/indexes/7947470156681183232
```

现有查询监控的无旧序列结果不是对所有消费者的完整证明。执行第一阶段前补齐写入监控、定时任务、开发配置及外部调用者清单。

## 先决核查

每次操作使用新的 run ID，保存到仓库外 `SCWiki/reports/pgvector-migration/<run-id>/retirement/`。

1. GET 精确 endpoint 和 index，保存部署绑定、副本、资源配置、维度、距离、归一化、更新方式、创建时间及调用身份。再次确认没有其他项目或其他部署混入。
2. 核查所有运行及可恢复 API、ingestion、corpus operator、VPS timer/cron、Mac mini 配置、CI、手工部署脚本和公开 endpoint 消费者。配置扫描只输出相关键和命中文件，不输出 `.env`、凭据或 token。
3. 查询 Matching Engine 的 `query/request_count` 及 `stream_update/request_count`、`stream_update/datapoint_count`，分别记录查询和 upsert/remove；完整处理分页。数据缺失、权限不足与观测值为零分别记录。
4. 导出正确的恢复配置和向量来源清单；当前索引的 PostgreSQL 原始向量及证据已保留，但取消部署前仍验证可读。旧索引若没有可重建原值，取消部署后保留其 index 对象，不能先删除数据。
5. 确认负责操作的现有身份及其权限。取消部署需要 `aiplatform.indexEndpoints.undeploy`。本轮只确认应用身份可以读索引及 Monitoring，未确认其有此写权限；不把失败后的自动提权或创建新密钥写进流程。
6. 核查生产版本、schema、SLO、备份及当前公开业务；将本次执行范围与目标写入操作清单。

VPS root 的 gcloud 在本次核查时没有活动账号，不能直接照抄命令后认定可执行。可使用已经获准且具备相应权限的操作身份及 SDK/ADC。身份和权限缺失时先记录明确缺口，再由账户所有者完成相应授权，不在 API 容器持久化管理员凭据。

## 第一阶段 取消旧部署

进入条件：消费者清单没有旧 endpoint 的有效读写依赖；至少最近 7 日及可获得的更长监控范围没有未解释的旧查询或更新；监控完整性已核对；当前新索引仍正常且恢复资料可用。

1. 给旧目标生成单独的 `PRECHECK.json`，精确写入三个标识：project、endpoint ID、deployed index ID。执行人再次读取 endpoint，比较导出的配置摘要和绑定。
2. 从正常定时任务、默认运维入口和现有部署配置中移除旧目标；历史 Git 文件保留，创建旧索引的脚本退出默认运行路径，防止后续被自动重建。
3. 对 `5476212220138356736` 发起一次 `sclib_papers_v1` 取消部署请求，立即记录长操作名称及提交时间。
4. 每次最多等待 60 秒后更新进度，查询同一 operation。请求超时或结果未知时先 GET endpoint 和 operation，不盲目重发。
5. operation 成功后 GET endpoint，确认旧 deployment 已缺失；再次读取 index，确认保留对象。观察副本指标停止；监控没有时间序列本身不足以代替控制面确认。
6. 验证新索引仍有正确部署，生产 SQL 指针、公开 version、Search、Ask、Similar、论文详情、Materials、时间线和 SCWiki 正常；使用可审计的最小请求预算。
7. 在随后 24 至 72 小时检查新收到的旧 serving SKU 用量停止累计，再按完整计费日复核。账单延迟只记录待核验，不能提前写“账单归零”。

预计节省约 HK$4,300 至 HK$4,400/月，依据用户提供的十月账单估算。本阶段不改当前生产索引，也不需要等待 pgvector 全部开发结束。

## 第二阶段 取消当前生产部署

必须同时满足：

- pgvector 的全部声明成员、真实增量发布、质量与全站验收通过。
  质量范围遵循2026-11-03最新用户指令：人工相关性/回答复核不再是上线前置，
  未测人工指标不标为通过；自动化检索、引用、来源、性能和恢复检查继续执行。
- Search、Ask、Similar、基线 API、所有 writer 和恢复入口已指向本地版本；API 和数据库镜像对新 schema 兼容。
- 全流量 pgvector 至少稳定运行 7 个完整日，期间关闭 Google fallback；应用调用遥测与消费者配置均没有 Matching Engine 依赖。
- Google 当前 endpoint 最近 7 个完整日没有未解释的查询或写入；有旁路探针则明确记录最后时间，再取得干净观察窗口。监控异常不能解释为零调用。
- pgvector 前一构建回退、备份恢复和 Google ANN RPC 不可达情况下的完整路径已实测；恢复方案不要求即时重新部署 Google。
- 当前 SLO 发布门槛通过；暂停采集按原有 DEFERRED 政策处理，不恢复其他任务以凑通过。

执行顺序：

1. 冻结当前本地构建、内容版本、激活事件和已兼容回退镜像。清理在线配置中的 Google fallback 和 endpoint 默认值，确认进程已加载新值。
2. 保存精确当前 index/endpoint 配置、源向量 manifest 和必要恢复信息。对照下面的第二阶段请求，发起一次取消部署并保存 operation。
3. 等 operation 成功，GET endpoint 确认 `sclib_retained_20260922` 缺失，GET index 确认对象仍保留。
4. 检查两个目标 endpoint 均无部署，并列出项目所在区域全部部署，排除因误重建产生的第三套副本。
5. 对新鲜缓存与冷缓存分别验证三条检索业务；重启受控基线实例，验证重启不会恢复旧 endpoint 配置。检查历史问答引用、材料下载和授权工作台。
6. 保持本地监控，分别记录取消部署完成后的 24 小时、72 小时和 7 日结果；复核延迟 billing 用量及后续月账单。

完成后，预计消除约 HK$8,742/月的两套索引 serving 开销。embedding、模型、GCS、备份和 VPS 费用按各自服务继续核算。

## 具体请求和命令

以下为待执行操作规格，编写方案时没有调用。每次只选择一组已满足先决条件的目标，不能把两个请求合并成一条无条件批处理。

第一阶段：

```http
POST https://us-central1-aiplatform.googleapis.com/v1/projects/524541993265/locations/us-central1/indexEndpoints/5476212220138356736:undeployIndex
Content-Type: application/json

{"deployedIndexId":"sclib_papers_v1"}
```

第二阶段：

```http
POST https://us-central1-aiplatform.googleapis.com/v1/projects/524541993265/locations/us-central1/indexEndpoints/6002249369191972864:undeployIndex
Content-Type: application/json

{"deployedIndexId":"sclib_retained_20260922"}
```

已认证且权限正确的 gcloud 环境也可使用以下等价命令。保留交互核对，不加入 `--quiet`，不在命令或报告中放 access token：

```bash
gcloud ai index-endpoints undeploy-index 5476212220138356736 \
  --deployed-index-id=sclib_papers_v1 \
  --region=us-central1 --project=jzis-sclib
```

```bash
gcloud ai index-endpoints undeploy-index 6002249369191972864 \
  --deployed-index-id=sclib_retained_20260922 \
  --region=us-central1 --project=jzis-sclib
```

Google 说明取消部署可能约需 30 分钟，后台清理还可能需要时间。不能在请求被接受时就宣称完成，也不能假定 deployment ID 可立即复用。[官方操作说明](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search/deploy-index-public#undeploy_an_index)

## 中断和回退

| 情况 | 处理 |
| --- | --- |
| 预检资源与清单不一致 | 停止该目标操作，刷新清单；不按 display name 猜测 |
| 403 或身份未就绪 | 保存错误类别和所需权限，不重试提权，不切用不明身份 |
| 提交超时或响应丢失 | GET 精确 endpoint，查询已保存 operation，无法判定时标记未知并停止重复提交 |
| operation 失败 | 保留完整错误与资源状态，继续使用仍在线的当前有效路径；不执行后续删除 |
| 旧索引取消后发现依赖 | 先禁用错误入口或切到已验证当前索引；必要时按保存配置显式重部署旧 index，等待实际完成并验证 |
| 当前索引取消后 pgvector 故障 | 回退前一 pgvector 构建或兼容应用，必要时恢复独立数据库；不得自动连接已取消的 Google endpoint |
| 必须临时恢复 Google | 使用保留 index 和恢复配置，显式记录应急重部署及重新产生费用；约 20 至 30 分钟是文档参考，不是恢复承诺 |
| 旧版 API 在新 schema 无法启动 | 使用新 schema 兼容回退镜像；不 stamp、强降级或删表绕过 admission |
| 账单仍出现费用 | 先区分迟到的历史用量和取消后的新用量，核查资源标签、时间区间及其他部署，再定位原因 |

正常应用及构建回退保留新产生的用户与研究数据，不把迁移前整库直接覆盖回生产。灾难恢复按既定 RPO 不超过 24 小时、RTO 不超过 4 小时的目标及实际可用备份/日志报告缺口，不承诺未配置的零损失恢复。权限撤销、来源修正和审查状态不能被旧快照恢复。

## 永久清理边界

取消部署成功即可完成本次 serving 退役。索引对象和空 endpoint 暂保留 30 日作为建议恢复窗口，实际期限以数据保留要求为准；期满只形成待清理清单，不自动永久删除。

永久清理需单独明确执行范围，并先验证可重建/恢复资料和来源保留条件：空 endpoint 与 index 按其依赖关系分别删除，保留最终资源及费用回执。不要使用强制删除顺带取消未知部署，不删除整个项目或关闭 `aiplatform.googleapis.com`，因为 embedding 或 Gemini 仍可能需要它。

下列内容不随索引托管退役删除：PostgreSQL 论文与材料、NER 结果、旧检索/问答审计记录、SCWiki 内容、GCS 备份、APS 原文目录。APS 全文及其副本继续按既定项目保留与用户明确删除指令处理；新投影和临时导出也进入适用的清理清单，不额外永久保存全文。

## 操作完成记录

每个阶段分别交付 `PRECHECK.json`、脱敏资源配置、依赖扫描结果、完整查询及更新监控、操作 request/operation ID、完成后 GET 结果、全站检查、恢复资料引用和 billing 复核。

报告将以下状态分开记录：未执行、运行中、未知结果、控制面已完成、业务已验证、费用待到账、费用已核验。只有目标部署实际缺失且业务验证完成，才标记技术下架完成；费用核验单独关闭。

### 协调维护期间的自动部署

在首次 pgvector 数据库/应用联合切换前，将仓库 Actions 变量
`SCLIB_DEPLOY_MODE` 设为 `coordinated`。这只暂停普通 Deploy to VPS2
任务，Test、Security 和签名镜像 Release images 继续运行；工程执行者继续
依据本运行方案完成维护切换，无需再等待人工评审。切换、兼容回退与公开验收
完成后，恢复该变量为 `standard`，后续普通部署沿用现有发布链。

协调维护执行者同时将已校验的 PostgreSQL 镜像摘要和实测资源预算写入
`/etc/sclib/pgvector.env`，由普通部署显式叠加 `docker-compose.pgvector.yml`
继续使用。该文件只保存镜像和资源配置，不保存密钥；Compose 读取文件，
不得将其作为 shell 脚本 source。材料配置与 pgvector 配置在基础 `.env`
之后依次加载，避免后续应用发布意外恢复旧数据库镜像或资源设置。
