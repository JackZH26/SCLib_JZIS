# SCLib 研究平台 v2：第一批实施记录与上线门槛

日期：2026-09-05。实施分支：`codex/sclib-research-v2`。

依据：已确认的《SCLib Schema v2 Final Upgrade Plan》v1.2，特别是 Discovery 的研究优先级积分设计。本批将方案转换为可运行、可测试的数据库骨架、评分契约、发布接口和网站界面；不是整个研究平台的最终验收，也不代表生产数据已经迁移或补全。

## 1. 本批交付

| 层 | 已实施 | 关键边界 |
| --- | --- | --- |
| 数据结构 | 0045 增量迁移，10 张研究表，旧 Tc claim 的可空事件绑定 | shadow mode；无自动回填、无生产写入接口 |
| 科学输入契约 | 6 维物理评估、状态、行动、成本、证据、预注册评分准则、campaign | 分子式不是评分对象；对象为材料—状态—行动 |
| 评分 | `RPS-v1.2`，Decimal 算术、50 分 half-up、完整贡献分解 | 研究优先级，不是超导概率或实验 Tc |
| 发布 | 严格离线 release 校验、独立管理员批准哈希、固定 release 只读 API | 默认关闭；哈希完整性不等于科学真实性 |
| 网站 | 新 Discovery 研究榜、六维矩阵、行动/成本/来源详情、独立历史线索区 | 无真实审核 release 时显示未发布，不填充演示候选 |
| 工具 | 离线校验 CLI、版本化 JSON Schema | CLI 不批准发布，不写数据库 |

实施沿用既有 Next.js/FastAPI/PostgreSQL 架构、页面主题与部署方式，没有创建替代站点或迁移到其他托管平台。

## 2. 数据库升级的实际范围

迁移：`api/alembic/versions/0045_research_shadow_schema.py`。
版本化结构定义：`api/models/research_schema_v2.py`。
该定义文件作为 0045 的版本化依赖，正式发布后必须保持不变；后续变更通过新的 schema 模块与 migration 实施，禁止事后修改历史迁移语义。

| 表 | 本批保存的核心信息 |
| --- | --- |
| `evidence_artifacts` | 来源及版本、记录哈希/实际文件哈希的区别、文件可用性、访问/许可、时间、定位元数据 |
| `research_runs` | extraction/DFT/DFPT/ML/priority assessment 等运行类别、设置版本、输入/输出 manifest、代码/模型版本、运行状态 |
| `research_samples` | 材料、论文工作、样品标签、制备及组成上下文、来源 |
| `material_states` | 材料/可空样品、明确/未知压力、温度角色、条件 JSON、状态解析程度、上下文哈希 |
| `structure_records` | 结构产物或描述、占位上下文、外部版本、派生关系、哈希 |
| `research_events` | 材料—状态—结构归属、Observed/Computed/Inferred/AI-Proposed、运行、修订、审核及有效性 |
| `event_properties` | 非 Tc 的有限属性注册表、规范单位、exact/interval/单侧界/unknown、组件键、原始值和不确定性 |
| `event_evidence` | 原文证据或精确输入结果的互斥关联；claim/property 与所属 event 的复合外键 |
| `snapshot_event_memberships` | 稳定事件在多个来源快照的重复捕获；来源 occurrence、事件 revision、manifest 引用 |
| `ml_example_inputs` | 现有 Tc ML example 的 claim/property/structure/artifact/context 输入谱系 |

### 2.1 已由数据库直接保证

- 状态、样品、结构、事件不能错误跨材料绑定；新引用采用 RESTRICT。
- 未报告压力保留 NULL，不能默认填 0；显式常压要求 0；拒绝 NaN/Infinity。
- 同一次事件允许 onset、zero 等多个 Tc 结果；同 event/result_key 不可重复。
- `material_claims` 是 Tc 的唯一权威结果表；`event_properties` 不接受 Tc 或任意未注册属性。
- 精确输入 claim/property 必须与其 input_event 匹配，不能靠 NULL 绕过组合外键。
- 相同物理属性的不同组件可并存；相同 event/key/version/component 不可重复。
- 允许合理的负形成能，不对所有物理量统一施加非负约束。
- RPS 总分限定 1000–10000，P/G/A 限定 0–100；RPS 属性只能绑定 Inferred 的 priority_assessment 事件及相应类别的运行。
- coordinate-backed 结构要求绑定 `kind=structure` 的产物，而非仅存在一个任意来源 ID。
- 防止直接自引用；重复快照 membership 和错误事件 revision 被拒绝。

`coordinate_artifact_kind`、`assessment_run_kind`、`assessment_event_type` 是复合外键使用的类型判别字段，不是另一份可独立编辑的科学真值。类型必须与被引用对象一致。

### 2.2 明确保留的兼容边界

- 原 `materials.records`、原 claim UUID、source hash、现有 API 返回语义保持不变。
- claim 新增 `event_id/result_key/interpretation_revision` 三字段：历史行都为 NULL，绑定时必须共同有效。
- **仍保留** `(material_id, source_record_hash)` 的旧唯一键。因此本批不支持同一来源的新解释回填；后续稳定 occurrence + interpretation revision loader 完成并验证后，再做专门迁移。
- **仍保留** `ml_examples.claim_id NOT NULL` 和现有两类任务。本批不声称已支持任意非 Tc 训练目标。
- 文件存在、结构类别和哈希形状不等于内容已经科学验证；实际坐标解析、组成一致性、关联匹配仍是 importer 的验收职责。
- **尚未实现**跨多跳/并发的依赖环检查，以及研究数据库完整 dependency-closure 冻结写入事务/触发器。不能将 shadow 表视为已经不可变的训练真值仓库。
- 本批不提供研究表 public write API，也不把这些未验收的表直接作为公开 RPS 榜来源。

## 3. RPS-v1.2 的落地规则

```text
P = 六维物理支持下界的固定分母加权和
G = 100 × D_lower × T_lower
A = 100 × (B_lower + R_lower) / 2
raw = 1000 + 45P + 27G + 18A
display = nearest_50_half_up(raw)
```

六维：stability、electronic、pairing、coherence、geometry、competing_order。

| Profile | 稳定性 | 电子态 | 配对 | 相干 | 几何 | 竞争序 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| common | 20 | 20 | 25 | 15 | 10 | 10 |
| epc_hydride | 20 | 15 | 35 | 10 | 10 | 10 |
| layered_correlated | 20 | 20 | 20 | 15 | 15 | 10 |
| multiband | 20 | 20 | 30 | 15 | 5 | 10 |
| flatband | 15 | 15 | 20 | 25 | 15 | 10 |

最终权重是 common 的 50% 加上预先指定 profile 或 profile mixture 的 50%。不得遍历 profile 后为候选选最高分，也不得按已知维度重新归一化。

物理锚点为 0/25/50/75/100。每个维度明确提供 status、anchor、lower、upper、rule_id、证据、理由。未知量必须为 `anchor=null, [lower,upper]=[0,100]` 并说明 missing_reason。采用下界是保守的研究排序规则，不是把未知材料认定为不超导。

每个 campaign 冻结六个 rubric 引用。Rubric 必须定义五档锚点、适用 profile 和证据要求。评分程序不会自动把某个电子参数解释成跨材料族普适的正/负贡献。首批不提供假装已经校准的通用材料评分模板。

D、T、R 采用 0/.25/.5/.75/1 及上下界。行动至少包含两个不同观察结果及不同后续决策。D/T/R 下界为 0、问题已解决、目标不匹配、预算不满足时不排名；不以最低分 1000 代替不准入。

成本单位固定为 CPU core-hours、GPU-hours、memory GiB、storage GiB、human-hours，分别比较，不直接相加。必需资源取 `cost_upper / budget` 的最大值：≤.10/.25/.50/1 分别得到 B=1/.75/.5/.25；超预算或资源不可用不准入，上界未知待补全。无须使用的资源不进入分母。

当前显式目标契约覆盖压力上限。`matches` 必须与已知状态压力一致；未知压力不能自报匹配。`approved_conversion` 必须有转换行动、目标压力、理由和可追溯证据。更丰富的目标条件与结构/样品科学校验将在后续 loader 中扩展，不能把当前压力门槛宣称为涵盖所有实验条件。

### 3.1 分数解释与比较

贡献以 5500 为算术参考点：

```text
physical = 45(P−50)
gain = 27(G−50)
action = 18(A−50)
rounding = display−raw
5500 + physical + gain + action + rounding = display
```

未知造成的 `missing_support` 和已有反向证据 `adverse_evidence` 独立标注。正/负贡献是对本研究行动优先级的影响，不能解释成超导概率变化。

P60、D1、T.75、B/R.75 的算术测试为 raw7075、display7100，分项 +450/+675/+450、取整+25。该数值仅是测试，不对应真实候选。

只在同 campaign、预算、policy、release 内比较。机制行动单独排名；对照/参考和不准入项不占发现榜名次。同显示分数共享排名，ID 仅用于稳定并列排序。积分区间是评估上下界，不是统计置信区间。跨族锚定及前瞻实验效用校准尚未完成；单项预算通过也不代表 Top-K 组合总预算可行。

## 4. 发布与可追溯性

公开数据使用完整、自包含、不可变的 release 文件；不是一个可任意覆盖的 editable score 真值表。

一个 release 必须包括：固定 campaign/hash、policy/hash、证据截止日期、发布时间、唯一的 artifact 列表、assessment 列表和每个 assessment 的审核引用。

验证器检查：对象/内容哈希、唯一 ID、材料—状态—行动引用、行动说明/结果/成本 hash、固定 profile、rubric 归属、目标压力、来源许可标记、来源有效性、证据 cutoff、assessment/campaign/policy 的审核绑定，并重新计算积分。损坏 release 整体返回 unavailable，不静默变成空榜或旧分数。

科学来源截至 evidence_cutoff；审核记录可以晚于 cutoff，但不得晚于 published_at。公开证据详情只提供标题、URL/DOI、版本、页/表等定位及状态，不返回授权全文。转换行动的证据也包括在详情中。

**信任边界：**同一个人可以制造一份自洽 JSON，哈希不能证明它科学正确。因此验证 CLI 和文件中的 `approved` 都不授予发布权；服务器还须由授权维护者单独配置获批的 `release_id → manifest_sha256`。现阶段审核是人工离线流程，尚无多用户审核后台/签名管理系统。来源 ID 在 release 内可解析，不等于已经自动核验生产数据库所有主键。

### 4.1 API

保持所有旧 `/v1/discovery` 接口及 `schema_version=1` 契约。

```text
GET /v1/discovery/rps/policy
GET /v1/discovery/rps/releases
GET /v1/discovery/rps/releases/{id}/assessments?group=discovery&offset=0&limit=24
GET /v1/discovery/rps/releases/{id}/assessments/{assessment_id}
```

group 支持 all/discovery/mechanism/unranked，先筛选再分页；分页携带固定 release/hash 和组内/全局数量。首次验证及评分在 worker 执行，按管理员 pinned hash 和文件签名缓存两个 release 的只读投影；ETag/304 保留。首发应保持少量小 release，超过该规模应先完成索引化 artifact 存储和容量测试。

### 4.2 配置与 CLI

```text
DISCOVERY_RPS_PUBLIC_ENABLED=false
DISCOVERY_RPS_RELEASE_DIR=/data/sclib/discovery/rps
DISCOVERY_RPS_APPROVED_RELEASES={}
```

启用前，把经过人工科学/许可审核的 `<release-id>.json` 放入既有只读 discovery 挂载下的独立 rps 目录。不要复用旧 feed 文件，不要修改旧同步脚本让其自行批准新评分。

```bash
api/.venv/bin/python scripts/validate_priority_release.py --schema release
api/.venv/bin/python scripts/validate_priority_release.py /path/to/release-id.json --sha256 <expected-manifest>
```

版本化 JSON Schema 位于 `docs/schemas/`，包括 assessment/campaign/release 及 state/action/evidence/rubric 内容。Artifact 的 kind-specific 内容、跨对象关系、数值锚点及哈希必须通过 Python verifier 再校验；仅通过 JSON Schema 不能等同于完成科学契约校验。canonical JSON 采用本项目 Python `canonical_json`/`digest`，不得与原始文件字节 SHA-256 混淆。

## 5. 网站体验

- Discovery 固定主标题，不依赖旧 feed 文案。
- 新榜加载与历史 feed 的 SSR 请求通过 Suspense 解耦。
- 发布列表选择固定 release；三类分组先由服务端筛选，再按 24 条分页。
- 六维矩阵、评估覆盖权重、总分、材料状态和下一步行动同时展示。
- 展开时再请求理由、分项贡献、行动结果—决策、成本、证据定位。
- 详情同时核验 release、assessment ID/revision、material/state/action 和分数，防止同 release 错行拼接。
- API 不可用与“尚未发布”是不同状态；均不产生替代分数。
- 历史候选保留原始来源和 heuristic score，在单独折叠区明确标注“pending RPS assessment”。

## 6. 验证与下一阶段门槛

### Discovery 紧凑表格版式预览（2026-09-05 补充）

用户要求先看“一材料一行、数据和评分横向排列”的简洁版式，因此增加独立的前端布局预览：开发模式访问 `/discovery?preview=layout`。主表使用 12 个唯一材料名，提供材料数据/六维评分两组列，固定材料名和最右侧 RPS，支持搜索、材料族筛选和积分排序；长说明收起，示例行动放在表外详情中，不增加表格行高。

`frontend/lib/discovery-layout-demo.ts` 中所有数值、材料族标签、条件、行动和名次均为合成示例，熟悉的分子式仅用于排版。页首和每行都有 Demo 标记；缺失值仍是 NULL/破折号，未准入示例不生成总分。示例不会导入 API、数据库、release 文件或正式 `ResearchPriorityBoard`，也不会在 API 出错时自动启用。生产模式不响应此预览开关。

本轮预览先用于版式确认；尚未将原真实 release 中不同材料状态/行动擅自合并成一个最高分。正式材料级汇总仍须明确选定状态和行动的规则，不能为了“一材料一行”牺牲评分对象的可追溯性。

验证在隔离的 PostgreSQL 16、Redis 进程中执行；未连接生产写库。API 测试本身会 drop/create 测试库结构，禁止直接继承生产 DATABASE_URL 运行。

已验证的类别：旧 API 回归、严格数值、unknown/真实零、family mixture、成本边界、未准入与 reference、最大分、half-up/贡献守恒、断裂/重复来源、空证据/非法规则、切组分页、错误 release/详情身份、真实形状行的展示、数据库复合 FK/值域/来源类别、onset/zero 并存、重复事件捕获。

已演练空库从最早迁移升至 0045，以及 0044 插入合成旧 Tc 后升至 0045 的兼容迁移；旧 Tc=39 K、来源 hash 保持不变，事件绑定仍 NULL。downgrade 只在该可丢弃空研究库中演练。正式数据回滚应优先恢复备份，而不是删除有数据的研究表。

本次最终结果：API **191 passed**；ingestion **290 passed**；前端源码 **26 passed**、组件 **16 passed**；带 `/sclib` basePath 的 Next.js 生产模式构建通过。十张迁移后表的列及 CHECK 与模型逐项核对通过。没有执行浏览器截图/交互验收或生产性能压测；本地仅做 HTTP smoke 与组件级测试。

新增 Python 模块的 Ruff 检查通过。对既有 `models/db.py` 扩大检查时发现 4 条已有 UP037 类型注解风格告警，已与分支起点版本核实相同，未为了此次升级改动无关代码。API 另有既有 admin 路由 `regex` 弃用警告；无新增测试失败。

### Discovery 跨族字段扩展（2026-09-05，后续补充）

重新核对完整研究提案及最终方案 §17 后，新增版本化展示字段字典（126 项、11 组），将精简演示扩为 16 个唯一材料，保留一材料一行，增加科学分组/可选列、可叠加 profile、状态绑定单元格与缺失原因详情。补齐层状关联、多带、平带/莫尔、重费米子、界面及超导后验字段；不再将 EPC 参数作为全族默认列。细节见 [跨族科学字段契约](DISCOVERY_SCIENTIFIC_FIELDS.md)。

真实页面只新增 definitions-only 字典；合成数值仍严格限制在开发预览，未接入真实发布/训练数据，没有更改评分器和生产库。本轮使用既有网站架构，未创建替代托管站点。第一批导入范围仍为可核验的有限 core 属性；extension 不是要求全库一次补齐。

本轮验证：前端源码测试 **28 passed**、组件/契约测试 **33 passed**（合计 61）；隔离构建目录下的带 `/sclib` basePath 生产构建通过，开发预览 HTTP 200。未运行浏览器截图/交互验收；单元测试覆盖字段组、单元格来源、焦点恢复和真/假数据隔离。未改动后端，因此未重跑有数据库写入副作用的后端套件。

### 下一批实施顺序（不变）

### 全站英文默认（后续用户确认）

网站默认界面统一为英文，包括 126 项科学字段定义、11 组名称、提示/缺失原因、示例内容和可访问性文本。账户与其他页面的日期/数字格式使用显式英文 locale，不再继承浏览器语言。`html lang=en` 与 `en_US` metadata 保持不变；中文查询识别、用户内容、论文原文和内部中文研究文档保留。约定写入 `frontend/AGENTS.md`，并新增 3 项英文默认回归测试。当前测试合计 64 passed（源码 31、组件 33）。本轮仍仅本地修改，未部署。

#### 后续实施队列

1. **真实数据只读预检与 staging 克隆**：依据生产 0043/0044 实际状态、数据量、缺失模式和异常分布制定批次；审核备份恢复能力。不得因本地测试通过而直接运行生产迁移。
2. **稳定身份和 loader**：sample/state/event 匹配、source occurrence 与解释修订、Tc 单一真值绑定、strict dry-run plan、幂等回放、小批差异报告；之后才替换旧 source-hash 唯一键。
3. **冻结与 ML 输入闭包**：先完成跨表依赖完整性、并发防环、父对象锁定、INSERT/UPDATE/DELETE 闭包保护与冻结 manifest 重算，再开放非 Tc 目标或正式训练导出。
4. **首批科学审核**：选取 12–20 个跨族正/负/机制锚点，制定并审查 rubric、成本依据和行动准入；锚点与候选验证隔离。审核后才准备首个真实 release。不能使用本仓库测试 fixtures 作为发布内容。
5. **数据补全**：优先版本化组成描述符、实验压力/Tc 定义/最低测温/样品上下文 NER、可靠结构匹配；明确区分可由组成计算的特征与必须依赖结构/计算/文献的物理量。
6. **灰度发布**：API 默认关闭 → staging 验收 → 备份/迁移审查 → 前后端部署 → 单独批准 release → 监测拒绝率/错误率/缺失覆盖/研究效用。

注意：现有 API 容器 entrypoint 会执行 `alembic upgrade head`，main 上的镜像/发布链可能触发生产部署。本批未 push/合并/部署；“只改页面”不能用来绕过数据库迁移审核。
