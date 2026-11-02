# pgvector 迁移实施记录

2026-11-02，执行 run `20261102T084847Z`。依据已确认的 [迭代计划](../PGVECTOR_MIGRATION_PLAN.md) 和 [下架方案](GOOGLE_VECTOR_SEARCH_RETIREMENT.md)。本记录只登记实际结果，不替代原验收门槛。

## 已完成

- 从重新核实的 `origin/main` / 生产 revision `984d5d96f7bc5a8727fab20579e4016f740bef42` 建立独立 worktree，保留原工作目录未提交内容。
- 核对当前生产、保留基线、运行配置、VPS timer/cron/nginx 和 Mac LaunchAgents；当前配置均未选择旧部署，采集暂停标记保留。历史脚本和配置默认值的旧引用纳入本批代码修正。
- 完整分页读取 10 月 1 日至操作时的查询、更新请求及更新 datapoint 监控；没有旧部署序列，当前副本指标为两套各一副本。无序列与观测值为零分开记录。
- 30 日 SLO：公开 API `99.90371%`、AI API `99.85735%`，均通过既定门槛。采集新鲜度因主动暂停为 `DEFERRED`。
- 使用现有获授权身份提交一次旧部署取消请求。操作 `projects/524541993265/locations/us-central1/indexEndpoints/5476212220138356736/operations/318126694311395328` 于 `2026-11-02T08:59:19Z` 核实完成，无错误；旧 endpoint 无部署，旧 index `7874607720131723264` 仍存在，当前 `sclib_retained_20260922` 部署保持在线。
- 下架后的 Home、version、stats、论文详情、Materials、时间线和 SCWiki 均 HTTP 200，Similar HTTP 200。Mac 访客额度导致 Search/Ask 各一次 429；保留失败记录，随后从 VPS 正常公开出口完成两条 HTTP 200 检查，未修改配额或伪造 IP。两条结果均绑定原 generation、activation 和 manifest；Ask 返回两个来源。
- 构建与生产相同的 PostgreSQL 16.13 / Alpine / amd64 pgvector 0.8.7 镜像，实际本地 ID `sha256:94788d307599ddb26ae66d7d28edc10c2a20c159695ca018e60bddb085a576f3`。生产 PostgreSQL 镜像和 schema 未切换。
- Mac 用户目录内的 PostgreSQL 16.15 + 同一 pgvector 版本通过 144 项扩展及既有检索/历史契约测试；一次性服务已清理。首次新测试的连接清理错误修正后重新执行通过。该结果不代表 Linux 16.13 或完整语料验收。
- 完整一次性 schema 演练通过，包含现有空库升级、保留历史与回退门槛，服务清理已核实。发现 pgvector 的 `avg` 聚合使旧对象核验脚本误调用 `pg_get_functiondef`；修正后保留完整聚合目录定义比较，未通过排除聚合绕过核验。最新 7 项真实 pgvector 专项测试通过。
- 8,881,260,355 字节的真实生产备份已下载，SHA-256 与配套 manifest 一致，恢复于 `09:11:08Z` 开始；恢复容器使用固定新镜像、独立 volume、`network=none`、2 CPU 和 6 GiB 内存限制。

## 本批实现与当前工作

固定镜像与签名发布路径、独立 pgvector CI 测试、保留原字节的 COPY 编解码、带容器及 volume 所有权核查的副本导入/读回/构建工具已进入独立开发分支。真实备份恢复仍进行中，尚无恢复通过或百万条构建完成结论。

约 `09:14Z` 起 Mac 到 VPS 的新 SSH 及 HTTPS 连接持续超时，其他外部网站可达。Hostinger 面板确认 VPS 运行中，并显示 IPv4 TCP DDoS 过滤自 `17:11 +08:00` 开始且仍在过滤。通过已登录的 Web console 取得现场结果：生产 API 与前端 healthy，本地 API HTTP 200、版本 `984d5d9`；负载约 1.8，内存约 13%，空闲磁盘约 234.92 GiB。恢复会话处于 active ALTER 阶段。没有重启主机、修改防火墙或关闭防护；外部可达性及确切原因继续核查，不能用本地健康代替外部可用性。

公开部署仍为 `984d5d96...`，当前 Google 索引继续服务。v2 内容/后端契约、原生增量发布、API 与前端接入、质量评测、生产灰度、兼容基线修复均未完成；不能把本批运行环境准备当作网站改版验收完成。

原保留基线 API 仍有已发现的旧 schema admission 循环重启，尚未修复；不把它列为有效回退。真实恢复演练使用独立网络隔离容器，API pytest 只使用另一组当次创建的空测试数据库。

## 后续门槛

1. 完成真实备份校验/恢复、Linux 16.13 扩展与读取、全部 1,183,943 个向量的导入/读回及资源测量；随后完成 P2 剩余维护窗口与恢复演练。
2. 按 P3–P6 实现、评测和灰度，交付可用的本地回退及精确 schema 兼容基线。
3. 只有全流量 pgvector 且 Google fallback 关闭后取得至少 7 个完整日稳定证据，才处理当前 Google 部署。本轮尚未开始该观察窗口。
4. 旧部署费用在 24–72 小时及完整计费日复核，暂为待到账。预计减少约 HK$4,300–4,400/月，尚无实际账单停止累计结论。

私有原始回执：`SCWiki/reports/pgvector-migration/20261102T084847Z/`；服务器副本工作区：`/opt/sclib-pgvector-migration/20261102T084847Z/`。这些路径不进入公开数据集；密钥、连接串和备份不提交 Git。本次未永久删除 Google index/endpoint、研究数据或 APS 全文。
