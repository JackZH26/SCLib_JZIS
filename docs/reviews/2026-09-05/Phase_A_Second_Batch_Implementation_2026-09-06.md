# SCLib 第二批优化实施记录 — 2026-09-06

## 交付结论

第二批已完成 ML02 / SC04 / DR01 的主要本地代码实施，并补齐独立复核发现的数值缓存、负结果别名和 Timeline 条件缓存边界。最终 **1,208 项自动化测试通过**；空库迁移至 `0048_pressure_projection`、TypeScript 和前端生产构建通过。

这不是全部 37 个执行 Issue 或 Phase A 完成。代码仍在既有 `codex/sclib-research-v2` 工作区中，基于 `44fd6ce377c89d4b4e1b78dbe082f420c33b8814`，包含此前未提交改动。本轮保留这些改动，没有提交、推送、部署或更改生产数据，没有全库回填／重新向量化，没有批准真实研究模板或执行计算／实验。相关 Issue 保持打开，等待审查、合并与各自剩余验收。

## 本批对应 Issue

| Issue | 本地实施 | 尚未完成的关键门槛 |
|---|---|---|
| [ML02 #43](https://github.com/JackZH26/SCLib_JZIS/issues/43) | 压力非空约束、accepted negative 一致性、ML target 的 claim/material 联合身份、迁移预检与真实 PG 测试 | 实际数据预检／人工来源审核、迁移窗口及 Linux CI |
| [SC04 #45](https://github.com/JackZH26/SCLib_JZIS/issues/45) | 共享压力解释、同一结果筛选、命中依据、跨页面标签与版本化 Timeline 投影 | 历史提取／向量事实的影响审计和受控重建；真实负载性能验证 |
| [DR01 #55](https://github.com/JackZH26/SCLib_JZIS/issues/55) | RPS 动作模板、前置条件、依赖／资源完整性、审核绑定和诚实贡献理由 | 实际领域模板及证据审核、固定 campaign 预算、正式发布批准和后续实证评估 |
| [SC01 #44](https://github.com/JackZH26/SCLib_JZIS/issues/44)，补充防御 | API 同样重解析原始 Tc；缺原始 typed 提案和近似区间端点不能绕过数值边界 | 不可恢复的历史原始单位仍需返回文献，不进行猜测修复 |

## 1. 数据库真正拒绝矛盾数据，而不只依赖应用验证

新增前向迁移 `0047_claim_integrity`，不改写历史迁移或原 v2 registrar。

- `explicit_ambient + NULL` 和 `reported + NULL` 被数据库拒绝；`explicit_ambient + 0`、`not_reported + NULL` 保持可表达。
- ML example 的 `claim_id` 和 `material_id` 必须指向同一个目标对象。两个 ID 分别存在仍不足以通过；直接 SQL 插入、更新及父 claim 重新分配均有真实 PostgreSQL 反例测试。
- accepted `non_transition` 必须有明确 `not_detected`、兼容的未报告／上界形式、最低测试温度和非占位测量方法；不能通过 unknown/inconclusive 状态绕过 negative property 规则。
- 显式负结果与正 Tc 点值、区间、下界冲突时，mapper 保留原始证据和数值，降为 pending/inconclusive，而不产生已接受的负标签。
- 显式理论／Computed、Inferred、AI-Proposed 来源不能被接受为实验未检出结果。多个结果状态别名、负布尔标记同时检查，前面的 positive 不能掩盖后面的 negative。
- NaN、无穷、缺失必要边界、反向区间和多填不兼容数值字段通过真实数据库矩阵验证；普通可选字段仍可为空。

迁移先取得有等待上限的写排他锁，再执行只读不兼容预检。有问题则整个迁移失败，不填零、不删除证据、不静默重标状态。报告仅输出规则、数量和有限样例 ID，不输出原文。复核中发现当前 SQLAlchemy CHECK 反射可能改变括号优先级，已改为读取 PostgreSQL `pg_get_expr` 原始表达式，并用合法 nullable／全形状夹具防止误报。

**存储合法不等于科学有效。** Tmin 和方法名称不证明测量灵敏度足够；v1 的未知来源、v1/v2 跨表科学来源一致性、样品／状态匹配和训练集准入仍须后续审核／loader／dataset gates。`accepted` 不是通用 ML 入集规则。

详细记录：[ML02_Claim_Integrity_Implementation_2026-09-06.md](ML02_Claim_Integrity_Implementation_2026-09-06.md)。

## 2. 一个科学筛选命中，必须由一条结果共同支持

Search 与 Materials 共用结果级 predicate，不再把不同记录上的家族、Tc、压力及来源条件拼成一个命中。

| 示例 | 新行为 |
|---|---|
| A = 300 K / 200 GPa，B = 5 K / explicit ambient | 不匹配 `Tc ≥ 200 K AND P ≤ 1 GPa` |
| 一篇论文的高 Tc 在 hydride，另一条结果是 cuprate | 不能借 cuprate 标签支持 hydride 的高 Tc 命中 |
| 压力缺失、裸 0、冲突或不可解析 | 默认不满足数值压力或显式常压筛选 |
| 报告压力 1–3 GPa | 可匹配 P ≤ 3，不匹配 P ≤ 2；不能取中点 |
| 缓存写 Tc = 300，原始值是 39 K | 重新解析为 39 K，不相信旧缓存 |
| 缺原始 typed 提案、负不确定度或近似区间端点 | 保留提案并 fail closed，不生成严格边界 |

新增 `matching_results` 返回稳定的 legacy occurrence 引用、原记录位置、Tc 支持下界、压力解释及结果来源。材料列表和搜索卡片显示命中依据；这些引用不是新研究库的已审核事件 ID，也不表明重复文献是独立复现。

温度、压力、来源和结果状态模块采用 API／ingestion 独立部署的字节一致副本，共 **4 组契约副本**有一致性检查。数值源头不被显示注解污染。

### 压力与界面的实际变化

压力区分 `explicit_ambient / reported / not_reported / ambiguous`，保留 raw、关系、区间、不确定度、理由和版本。`bulk_equilibrium`、样品形态、材料族、`ambient_sc` 或旧裸零不再生成常压事实句。

- 材料列表／详情／variants／书签中的常压汇总需同一条 Observed 正结果支持；不支持则显示未知，不新算一个替代最大值，也不推断负结果。
- `ambient_sc=false` 返回解释性 422，界面移除此不成立的负筛选。明确实验负结果由研究 claim 契约承担。
- `include_unknown_pressure=true` 是明确命名的放宽模式；响应仍显示 unknown/unresolved，不把它包装成已符合数值条件。负压／拉伸压力暂不在本策略支持域，原值保留，绝不标为常压。
- 材料页、论文页、氢化物证据、搜索命中和 Timeline 都使用英文压力标签。未带版本的旧标量标为 unverified。
- 材料列表新增压力上限和 Observed-only 控件。来源等级叫 Result source tier，不冒充实验确认。

### 查询性能边界

SQL 仅做必要的 family／APS 候选缩减；真正科学匹配由共享 predicate 判定。材料候选以 128 行批次流式读取，先匹配再计数／分页，因此不会把扫描上限当作准确总数。

这只限制批次内存，**不保证全库查询低延迟**。宽泛压力／Tc 查询仍可能扫描较大候选集，单个巨型 record array 也仍有成本。上线前须测量真实规模、p95 和并发；后续优先建立有版本的结果索引投影，并与共享 predicate 做一致性测试，不通过放松科学条件换取速度。

列表排序仍按明确的 catalogue summary 字段，可能与命中记录值不同；界面已说明。真正逐属性／状态原子选择属于 SC02，未宣称本批完成。

契约：[PRESSURE_SEMANTICS.md](../../PRESSURE_SEMANTICS.md)、[SCIENTIFIC_FILTERS.md](../../SCIENTIFIC_FILTERS.md)。

## 3. Timeline 的数据与缓存都绑定科学策略版本

新增 `0048_pressure_projection`，只为可重建的读投影增加压力元数据和策略就绪字段，不更改原始科学记录。旧投影失效；刷新、读取和健康检查同时核对压力与来源版本。

Unknown、未解释零、显式常压和明确报告的非零压力不会仅因数值取整被合并。Tooltip 区分这些状态；描边图例改为 reported non-zero pressure，避免把 1 atm 叫作高压。

缓存键和 `data_version` 包含策略身份。仅来源更新时间不能证明表示未变，所以 Timeline 使用完整响应 ETag 做条件校验，不再靠 If-Modified-Since 返回 304，也不把来源日期冒称表示的 Last-Modified。来源更新日期仍在 JSON 中保留。

更完整的事件身份、年份基准、300 K 旧上限、来源去重与撤稿失效仍在 SC03／SC06／SC07／SC08，未在本批隐藏或关闭。

## 4. RPS 高分不能抵消“当前动作做不了”

实现 `rps-action-contract/1`，要求 campaign 注册并固定动作模板，明确结构、样品、设备、软件、数据或外部依赖，以及 CPU/GPU、内存、存储和人力五类资源的适用性。

- 缺失／未知关键前置条件、未知成本上界保持 pending，无可执行排名。
- 当前 campaign 中有证据支持的 blocked 关键前置条件或必需依赖为 ineligible；把父条件改成 pending 也不能掩盖已知不可用。
- required 资源必须完整计费，不能因漏写而当作零成本。not applicable 必须被模板允许，并有依据和审核理由。
- 模板、独立完整性审核、动作、依赖状态、资源适用性及成本均参与内容／审核 hash 绑定；更改必须重新审核并产生新发布版本。
- 高 P/G/R 不能覆盖缺结构、缺样品或已知资源不可用。另行设计结构核实／样品制备动作可以，但必须依其自身模板、前置条件和预期结果审核。

数值 RPS-v1.2 公式、六维固定分母、common/profile 50:50 权重与 nearest-50 half-up 舍入不变；7075 → 7100 golden 仍通过。eligibility contract 与 policy hash 已变化，旧缺契约 bundle 明确 fail closed，不能静默显示为新契约下的已审核分数。

贡献说明分离 opposing evidence、missing support、uncertainty discount 和 execution constraint。一个不确定性较宽的正向 anchor 不会仅因下界低于 50 就被叫作反超导证据。

本轮没有批准任何真实科学模板，没有建立校准过的跨家族效用／超导概率，也没有执行实验或购买计算资源。完整公开可重算发布包仍属 DR02，实证价值与主动学习评估仍属 AL01。

契约：[RPS_ACTION_CONTRACT.md](../../RPS_ACTION_CONTRACT.md)。

## 5. 最终验证

以下是所有并行实现与复核修复整合后的结果，不是早期子集或中间失败数。

| 检查 | 结果 |
|---|---:|
| API 完整套件，专用 disposable PostgreSQL／Redis | 578 passed |
| Ingestion 完整套件 | 489 passed |
| 运维／安全脚本 unittest | 61 passed |
| 前端源码测试 | 32 passed |
| 前端组件测试 | 48 passed |
| 空库迁移至 `0048_pressure_projection` | 通过 |
| 有数据迁移兼容／坏数据回退预检 | 已包含于 ML02 真实 PG 测试 |
| TypeScript／Next.js 15.5.21 生产构建 | 通过，30 个页面生成 |
| 4 组 API／ingestion 契约副本字节一致性 | 通过 |
| 本次模块 Ruff／git diff --check | 通过；保留既有告警边界 |

总计 **1,208 项自动化测试**，不含迁移／构建检查；不是 1,208 个真实材料经人工科学验证。API 仍有 1 条既有 FastAPI `regex` 弃用警告；部分既有路由的 `Depends` 风格告警未扩大重构，未声称整个仓库零 lint 问题。

环境为本地 Python 3.12.14、PostgreSQL 16.13、Redis 8.6.1、Node 25.5.0；Linux CI／发布镜像的逐包与运行时一致性仍待 EN04 验收。本轮测试创建的临时服务和临时数据均已正常清理，未删除用户数据。

未执行生产预检、真实浏览器端到端验收、负载压测、全库重提取、向量索引重建、真实模板批准或模型实证评估。

### 安全复现

从仓库根目录，使用已安装的原生 PostgreSQL／Redis 二进制：

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite api -- -q

api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite migrations
```

不要把测试指向开发／生产 DSN，或绕过安全 runner。其他环境见 [TESTING_SAFELY.md](../../TESTING_SAFELY.md)。

## 6. 下一步与发布门槛

下一批按依赖优先推进 **SC02 #47：逐属性与结果／状态原子绑定**，再处理 **SC03 #48：非破坏性异常审核**、**SC07 #49：统一审核可见性** 和 **SC06 #50：Timeline 科学事件语义**。60-event 真实审阅试点仍需真实证据和人工判读，不能以本批合成测试替代。

上线前必须先审查／整理现有脏工作区为明确提交，完成 Linux CI、真实数据只读影响／性能预检和迁移窗口方案。`0047` 遇不兼容数据应停止并审查，不自动填零；`0048` 必须先于新 Timeline 刷新代码启用。避免未经部署审核直接启动会自动迁移的生产入口；迁移与应用启动分离仍由 EN02 跟踪。

旧 RPS bundle 需依新契约真实补充并重新审核；仅替换 hash 不能产生新的批准。旧 Facts/vector 内容也不会因改了 parser 自动变新，重建必须单独规划。回退应协调应用、只读投影和约束版本，保留原始证据与历史发布，不执行破坏性“修复”。
