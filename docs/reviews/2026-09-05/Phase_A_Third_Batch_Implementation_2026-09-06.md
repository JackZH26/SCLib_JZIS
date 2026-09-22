# SCLib 第三批优化实施记录 — 2026-09-06

## 本批目标与状态

本批针对 [SC02 #47](https://github.com/JackZH26/SCLib_JZIS/issues/47)：将材料目录的科学属性绑定为独立的“数值／关系／单位 + 原始结果 + 状态／条件 + 方法 + 来源”对象，阻止把不同实验、样品或计算的属性拼成一条实际不存在的联合观测。

实现位于既有 `codex/sclib-research-v2` 工作区，基础 HEAD 为 `44fd6ce377c89d4b4e1b78dbe082f420c33b8814`。保留此前未提交改动。本批不是 Phase A 或所有 Issue 完成；没有提交、推送、部署、生产迁移、真实数据回填或科学审核批准。

最终 **1,313 项自动化测试通过**，TypeScript、前端生产构建和空库迁移通过。原始数据库记录不因新显示策略而被重写；上线前仍须进行真实快照的只读影响审计及发布审核。

## 1. 逐属性的证据契约

新增 `property-evidence/1.0.0`，API 与 ingestion 使用字节一致的纯函数实现。材料列表、详情、变体和收藏页通过同一投影逻辑生成 `property_evidence`。

- 每个属性有 `status`、选择策略、`selected`、有限数量的其他证据及警告。
- `selected` 包含独立的 `result_id`、值、原始量值的重新解析结果、单位、误差／近似／区间关系、条件、状态、来源和 Observed／Computed 等来源分类。
- 同一记录中的压力、样品、结构、run、方法、Tc 判据及 Hc2 温度／方向随该属性一起返回；缺少的上下文保持未知。
- 结果 ID 使用 material scope 和原始记录内容生成，排序相同值时用稳定内容身份决胜。显示用派生注解不参与身份，避免同一结果经 API 往返后产生“新来源”。这仍是 legacy occurrence 身份，不是已审核的 v2 科学事件 ID。
- 每个属性最多返回 20 条证据，同时报告总数和截断标记。列表、变体和收藏仅发送已选属性的证据；完整详情提供有限数量的候选记录。
- 来源字段采用明确的可公开字段清单，不把任意嵌套元数据、全文引文或审核者信息复制到新证据对象。

`supported` 只表示已有目录值能在原始记录中找到一致支撑，不表示已阅读并验证论文、实验成立、独立复现或可进入训练集。来源身份、方法或状态缺失会明确显示，而不是由材料族、同一论文或相同压力补造。

**来源分类的粒度仍是 record。** 同一原始条目可能包含实验 Tc、反演 λ 和机制推断，不能因该条目属于 Observed 就把每个属性都称为实测。界面、metadata 与 JSON-LD 明确标注 Record origin；真正逐属性的方法／来源审核仍需后续提取与策展。现有原子关联建立的是“此值来自这条记录及其报告上下文”，不是证明该 NER 条目内部所有信息已经完全消歧。

### 对旧目录值的兼容策略

传入旧 summary 时，仅允许精确支持它的原始记录成为该属性的来源。没有原始支撑的值在新 API 科学显示字段中变为 `null`，证据对象保留 `untraceable` 原因；原始记录继续保留。

旧 headline 若明确选择了 experimental／theoretical 分组，也不能借用另一分组的同值结果冒充来源。原始来源分类仍显示真实的 Computed／Observed；来源分组本身不受支持时，headline 保持 untraceable。变体和收藏即使不输出分组字段，也读取相同选择依据，保证跨入口一致。

例如旧目录写 100 K、原始记录只有 300 K，不得把 300 K 记录的来源贴给 100 K，也不得趁本次升级把显示值改成 300 K。旧 summary 为 `null` 时同样不自动选择一个新值。旧上限、人工 override、三位小数舍入造成的差异都需要显式审计；本批没有用近似匹配为它们伪造来源。

区间、上／下界不能生成中点或无条件的兼容标量。带近似标记或对称误差的中心值保留其元数据，界面同时显示 `≈` 或 `±`，不暗示误差的统计含义。

`disputed`／`retracted` 是目录治理警告，不是数值观测。原记录缺少同名字段不能导致这些安全警告被清空。`ambient_sc` 仍由有显式常压支持的正 Tc 结果派生，未知不成为负样本。

## 2. 修复 Hc2 与晶体结构的错误拼接

| 验收场景 | 本批行为 |
|---|---|
| A：Hc2 = 20 T，沿 c，5 K；B：100 T，沿 ab，0 K | 选择 100 T 时只使用 B 的方向、温度、方法及来源 |
| a 只在 A 中，c 只在 B 中 | 不再将 A 的 a 和 B 的 c 拼成一套晶格；已有拼接目录值不能获得虚假单一来源 |
| 相同最大值来自多条记录 | 使用稳定结果身份选择，输入重排不改变所选来源 |
| 掺杂或输运指数使用了目录中位数 | 标明目录统计；没有真实记录等于该值时不冒充一次实际观测 |
| 一条结果未报告测量温度或结构 ID | 只显示未知，不从另一条结果借用条件 |

ingestion 的结构／空间群／晶格组改为从一条原始结果取值。目录的 `structure_phase` 共识标签仍与具体结果的结构分开；界面不会把独立选出的空间群、晶格和相标签包装成一套联合结构。

Hc2 条件只从相应最大值的记录取得；后续 override／舍入导致值不再匹配时，不保留旧条件字符串。Tc 同值条件选择也改为确定性 tie-break。本批保留旧的数值／可见性政策，后续由 SC03／SC07 改造。

## 3. EPC 配对必须有完整关联依据

λ 与 ωlog 仍可以作为独立、可追溯属性浏览；单独选出的两个最大值不是一对 EPC 输入。

自动关联要求明确、相容的 state、structure、run、protocol、方法与 Computed 来源。检查已知压力、样品、掺杂、温度角色和晶格等冲突。仅同分子式、同一论文、相同压力或同一 NER 行不够；缺少关联信息保持 pending。

实现也提供显式、带 revision 的外部审核匹配入口，但目前公共 API 不传任何此类审核。原始记录中的 `reviewed=true` 不能自我批准，更不能覆盖已知状态或协议冲突。

EPC 的 `eligible` 只表示 **association complete**，不是已验证超导、Allen–Dynes 适用、公式可直接调用或已满足主动学习计算准入。实际方法适用域、μ*、谱信息、稳定性和对应研究动作的资格检查仍需后续专门审核。

实现先按关联键建立候选索引，并限制最多 10,000 次配对比较与 20 个返回 pair。预算用尽时给出下界和不完整标记，绝不把截断数量当作精确总数。列表／变体／收藏不执行联合 EPC 评估，明确返回 `not_evaluated`；详情页执行该检查。

## 4. 页面与接口的变化

- 全部网站自有文本保持英文；原文证据不被翻译或改写。
- 保持每种材料一行的列表，属性可展开查看其来源、状态和条件。
- 详情中的结构、超导参数、竞争序与样品字段都按独立属性展开；显示“不属于一条联合观测”的提示。
- 不具备证据契约或来源身份的旧数值，不再通过标题、变体、收藏、SEO 描述或 JSON-LD 的 fallback 绕回页面。
- 近似值、误差与界限保留科学记号；界面中的字段覆盖率只表示来源关联覆盖，不表示科学确认或 ML 完整度。
- 氢化物专用 NER 表仍是独立 enrichment 结果层；界面说明同一行参数不自动构成有状态／run 依据的联合 EPC 数据。本批没有重构其数据库或声称完成该层的逐结果审核。

API 继续按旧 SQL 目录列排序，返回 `sort_basis=legacy_catalogue` 与 `scientific_display_policy=atomic_property_evidence`，界面同时说明这一限制。缺来源的旧大值可能仍把某行排在前面，但不会以有依据的新标量显示。基于新的、版本化结果投影重新排序属于后续工作，不能在保留旧上限的同时暗中假定已完成。

Pairing、phase、unconventional／competing-order 的分类过滤仍使用目录列，并不等同于 Tc／压力／来源的同结果筛选。界面明确区分这两类语义；更完整的未知值、先验和分类审核属于 SC10。

复核同时修复了一个已有的 SC07 边界：NIMS quarantine 的子变体不能从父详情或父相图中绕过独立详情的 404 隔离策略；变体同值排序补充稳定 ID。此有限防御不代表统一可见性系统已经完成。

## 5. 离线影响审计与 ML 出口边界

新增 `scripts/audit_property_aggregation.py`，仅读取本地材料 JSONL 并向标准输出生成报告，不连接数据库、API、模型或第三方服务，不重写输入。

审计区分：显示值变化、来源新增／变更／移除、条件变化、状态变化及结构变化；保留输入与报告 hash、版本、计数和有限样例。已有派生 envelope 只作 before 比较，绝不成为新科学证据。

已实际执行并保存 [合成输入](SC02_Synthetic_Property_Audit_Input_2026-09-06.jsonl) 与 [合成影响报告](SC02_Synthetic_Property_Impact_2026-09-06.json)：3 个合成材料，1 项 Hc2 条件变化、2 项无支撑显示值被 withheld、3 项新增来源引用、0 次数据库改写；88 个缺少旧 summary 的字段明确不可比较。这些数值只验证工具行为，不代表实际数据库质量。

输入需要材料 ID、原始 records 和待比较的旧 summary。缺少 summary 的 records-only 导出会标明“不可比较”，不能冒称零影响。尚未对真实生产快照执行此审计，因此本报告不提供生产问题数量或完整率提升百分比。

source snapshot exporter 新增明确的非联合观测语义说明，并拒绝 material 导出行夹带未声明的 flat summary 字段或声称已产生科学接受／联合特征行。已有 typed-claim 的接受规则没有放宽；导出完整性校验不是训练准入或科学审核。

## 6. 验证与发布门槛

| 验证范围 | 最终结果 |
|---|---|
| 完整 API 测试，disposable PostgreSQL／Redis | 588 passed；1 项已有 FastAPI `regex` 弃用警告 |
| 完整 ingestion 测试 | 562 passed |
| scripts 运维／测试安全 unittest | 61 passed |
| 前端 source 测试 | 32 passed |
| 前端 component／unit 测试 | 70 passed |
| 合计，未重复累计局部回归 | **1,313 passed** |
| TypeScript `tsc --noEmit` | 通过 |
| Next.js 15.5.21 生产构建 | 通过，30/30 页面生成；未部署 |
| 全新隔离数据库迁移至 `0048_pressure_projection` | 通过；本批没有新增迁移 |
| 5 组 API／ingestion 共享契约文件的字节一致性 | 全部通过 |
| 新模块／适用修改文件 Ruff、`git diff --check` | 通过；不表示全仓库旧 lint 债务全部消除 |

复现核心命令（API／迁移只使用安全入口）：

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

api/.venv/bin/python -m unittest discover -s scripts/tests -q
```

ingestion 在其子目录运行完整 `tests -q`，显式使用指向 `127.0.0.1:1` 的 unused DSN；测试为纯函数／mock，不连接研究库。frontend 子目录运行 `pnpm test`、`pnpm exec tsc --noEmit`、`NEXT_TELEMETRY_DISABLED=1 pnpm build`。详细安全约束见 [TESTING_SAFELY.md](../../TESTING_SAFELY.md)。

本地沿用 Python 3.12.14／PostgreSQL 16.13／Redis 8.6.1／Node 25.5.0；不等同于 Linux CI 的 Python 3.11／Redis 7／Node 20 组合，发布镜像一致性仍待验证。局部回归、重复全量运行和迁移检查没有额外累加到测试总数。

API 测试仅由 EN01 disposable runner 创建全新 PostgreSQL／Redis 运行并清理，不使用开发或生产连接。原始记录保持不变的行为有接口和集成断言。

本地合成 1,000 条不同显式 run/state 的 EPC 记录测试中，一次纯函数投影约 0.20 秒，返回 20 个样例并准确报告 1,000 个配对。这个单机单次合成检查只用于排查全笛卡尔积问题，**不是生产性能、p95、负载容量或 Linux 发布镜像的证明**。大材料的原始记录扫描仍有成本；上线前仍须验证真实分布与并发。

待完成的发布门槛：

1. 授权只读真实数据快照的差异审计，特别检查旧 cap／override／三位小数舍入及缺来源造成的显示减少。
2. Linux 锁定依赖 CI、真实负载及代码合并／发布审核。
3. 将旧 summary 数值政策迁移为 SC03 的版本化异常审核，而不是截断、删除或悄悄恢复高值。
4. SC07 的统一可见性、SC06 的 Timeline 事件与日期语义，以及 SC08 的撤稿／更正传播仍保持独立 Issue；本批不能替代它们。
5. 真实来源核查、样品／结构关联审核与 ML 数据集准入。任何新字段都不会自动变成已接受训练标签。

## 下一批建议

优先推进 [SC03 #48](https://github.com/JackZH26/SCLib_JZIS/issues/48)：把科学数值硬上限和破坏性过滤替换为原值保留、异常规则版本化、明确审核状态与可追溯显示策略。SC02 的逐属性证据与离线影响报告是这一步的前置基础。

相关实现细节见 [逐属性证据契约](../../PROPERTY_EVIDENCE_CONTRACT.md) 和 [聚合／导出／审计实现记录](SC02_Aggregation_Export_Implementation_2026-09-06.md)。SC02 与主 tracker 保持打开；本地测试通过不替代代码审查、真实数据审计及发布门槛。
