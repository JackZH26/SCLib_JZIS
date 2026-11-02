# pgvector 迁移实施记录

2026-11-02，执行 run `20261102T084847Z`。依据已确认的 [迭代计划](../PGVECTOR_MIGRATION_PLAN.md) 和 [下架方案](GOOGLE_VECTOR_SEARCH_RETIREMENT.md)。这是本批提交时点的实际状态，后续运行结果另留回执，原验收门槛继续有效。

## 旧部署已取消

从重新核实的生产 / origin/main `984d5d96f7bc5a8727fab20579e4016f740bef42` 建立独立 worktree，原工作目录未提交内容保留。核对生产、基线、运行配置、VPS timer/cron/nginx 和 Mac LaunchAgents，没有旧部署的有效依赖。采集暂停标记及生产 Actions environment 的 `SCLIB_INGESTION_MODE=paused` 保留。

完整分页读取 10 月 1 日至操作时的查询和更新监控，没有旧部署序列；无序列与观测值为零分开记录。使用现有获授权身份提交一次取消请求，操作 `projects/524541993265/locations/us-central1/indexEndpoints/5476212220138356736/operations/318126694311395328` 于 `2026-11-02T08:59:19Z` 核实成功。旧 endpoint 无部署，旧 index `7874607720131723264` 仍存在。`09:58Z` 后续控制面和副本监控仍只显示当前部署 `sclib_retained_20260922`。

Home、version、stats、论文详情、Materials、时间线、SCWiki 和 Similar 检查返回 200。Mac 访客额度使 Search/Ask 各一次返回 429；保留失败记录，随后从 VPS 正常公开出口完成两条 200 检查，未修改配额或伪造 IP。结果绑定原 generation、activation 和 manifest；Ask 返回两个来源。

旧 serving 费用仍待 24–72 小时及完整计费日复核。按原账单预计减少约 HK$4,300–4,400/月，尚不能认定账单已停止累计。当前 Google 部署继续服务。

## 完整副本与数据核验

- 固定 PostgreSQL 16.13 / Alpine / amd64 基础和 pgvector 0.8.7 源码、摘要及编译方式。最终非 root 本地镜像 ID `sha256:b305bbcd1aee8d79ecd7c5e11a1095d203feb78f69c4026d3a912fe43c1d71bd`。正式发布仍须签名、SBOM 和安全检查。生产数据库镜像和 schema 未切换。
- 真实生产备份 `sclib-20261102T060029Z.dump` 为 8,881,260,355 字节，SHA-256 `356d02ea6c414f4c02584f50abacf26c00434990eec25679fd6d94b0c69dfc0f` 与 manifest 一致。于 `09:47:33Z` 完成独立 volume、network=none 的完整恢复及读取核查；包含下载的实际用时约 47 分 46 秒。没有验证 WAL 连续归档。
- 恢复库为 16.13 / vector 0.8.7，schema `0106_materials_source_notation`；75,202 篇论文、26,510 条数据库材料行、4 个用户、1,183,943 个冻结成员，损坏索引及未验证约束均为零。材料行数与公开可见统计口径不同，不要求它们相等。
- 最终非 root 镜像重启及清单核对通过；当前 API 镜像使用副本专用 SELECT-only 账号完成五条实际读取，均为 200。探针不连接生产、云模型或邮件，API/Redis 探针完成后已移除。没有在恢复库运行 pytest。
- 全部 1,183,943 个向量于 `10:21:03Z` 完成导入，约 31 分 56 秒。逐条核对正文、快照、证据、embedding 回执及原始 float32 摘要。
- `10:26:20Z` 全部成员二进制读回通过：缺失 0、额外 0、绑定或原始 float32 字节差异 0。投影表约 4.98 GiB，含主键约 5.13 GiB。这不等于检索质量验收。
- HNSW 仍在构建，m=16、ef_construction=64、维护内存 4 GiB、一个并行维护 worker、2 CPU。平行构建需要动态共享内存，已通过重启副本把 /dev/shm 从 1 GiB 改为 5 GiB，并加入构建前门槛，不能用容器总内存替代。
- 4 GiB 图内存在 1,142,894 个成员后溢出到磁盘。6 GiB 容器上限产生明显回收压力，未发生 OOM；`10:46:14Z` 在整机可用内存约 24 GiB、生产 API 正常的条件下，仅将隔离副本上限提高为 12 GiB。维护内存、共享内存和 CPU 上限保留，资源回执继续采集。初始 6 GiB 不是已验证的生产预算。
- 固定 200 条真实 RETRIEVAL_QUERY 查询及其 768 维 embedding；完整精确 SQL 参照和 ANN 对照待 HNSW 完成后执行。尚无完整召回率、过滤难例、相关性、全站或负载验收结论。

源 generation `5e76b262-3c7f-41ee-a3c2-9034ce4f3053`、manifest `d25baf524060f268bd2d9c581909c9d57bf779237ecb4179d6eb252036fa652d` 保留。投影仅作隔离容量演练，不能激活生产，没有修改 v1 历史资源字段。

## 运行、恢复与代码检查

原基线 API 因旧 schema admission 循环重启超过 22,000 次。已只更换该 API 的镜像及正确代码身份，禁用其后台周期写入；最终报告版本 984d5d9、healthy、重启 0，ready、version、Materials 和论文读取通过。主 API 身份及零重启保持。基线前端仍为旧版本；完整备用站点、未来 v2 schema 和 pgvector 回退验收尚未完成。

约 09:14Z Mac 到 VPS 的 SSH/HTTPS 曾持续超时，Hostinger 显示 IPv4 TCP DDoS 过滤。面板随后确认过滤结束，09:33Z 已重新验证 SSH、公开 Home/version 正常。没有重启主机或关闭防护，确切原因未归因。应用 SLO 不涵盖到达应用前的 TCP 失败，不能用内网健康替代外部可用性。

30 日 SLO 门槛通过：公开 API 99.90371%、AI API 99.85735%；采集新鲜度 DEFERRED。已冻结性能基线；最近 24 小时 Search 约 4 次、Ask 约 1 次，样本不足以作为可靠延迟比较，后续须固定查询及受控负载对照。

锁定运行环境的离线脚本测试 3,827 项通过；Mac 用户目录 PostgreSQL 16.15 / 同版 vector 的 144 项检索历史测试、7 项真实扩展测试、完整一次性 schema 演练通过。Linux CI 已通过固定 16.13 镜像的扩展、完整 schema、安全及部分应用/前端检查；全部 API 分片以本批最终 CI 为准，不用先前 revision 替代。所有 API pytest 和 migration tests 均通过当次创建并核验所有权的一次性空库运行，清理已核实。

固定镜像、签名发布路径、独立 CI、原字节 COPY 编解码、副本导入/续跑/读回/构建及共享内存门槛进入 PR #186。单独的 P3 SQL 查询适配器进入 PR #187，仍未接入路由；它不替代内容/后端注册表、验证回执或激活机制。

## 未关闭的门槛

1. 完成 HNSW、200 查询精确参照及资源测量；继续演练含向量数据的备份恢复和完整维护窗口，不能把容器重启当成全站维护验收。
2. 完成 P3–P6 的 v2 内容/后端契约、原生增量发布、SQL adapter 接入、缓存及历史/API/前端兼容、相关性/引用/全站/压力评测、生产灰度、完整基线和本地回退。
3. 全流量 pgvector 且 Google fallback 关闭后，取得至少 7 个完整日稳定证据，才处理当前 Google 部署。观察窗口尚未开始。
4. 复核旧部署账单，再按第二次退役门槛处理当前部署及其费用。永久删除 index/endpoint 另列范围。

私有回执位于仓库外 `SCWiki/reports/pgvector-migration/20261102T084847Z/`；服务器工作区 `/opt/sclib-pgvector-migration/20261102T084847Z/`。密钥、连接串和备份不提交 Git。本次未永久删除 Google 对象、研究数据或 APS 全文。
