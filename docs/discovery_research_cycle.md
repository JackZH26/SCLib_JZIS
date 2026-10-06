# Discovery 研究循环合同

实现位置：`frontend/lib/discovery-research-cycle.ts`。这是本地、有界、可导入导出的研究问题合同；不执行计算，不写生产数据库，不产生正式材料、状态、RPS或科学发布。界面英文，本文为内部说明。

## 三条策略及价值含义

用户明确的三条策略是 `high_bandwidth`（高电子带宽）、`high_carrier_density`（高载流子密度）与 `geometry_construction`（几何构筑）。每条策略提供来源检索词、必要证据、竞争解释和ML适用边界。

- 高带宽关注指定轨道/能窗、色散及相互作用变化，不把带宽、DOS(EF)、载流子密度混为一谈，也不假定越宽越好。
- 高载流子关注可移动载流子与局域化、补偿、无序的竞争解释；名义掺杂比例和赝势价电子总数不能替代实测载流子密度。
- 几何构筑关注明确坐标、边界条件、应变/界面/维度；平带或低维本身不能证明稳定性、配对或相干。

300 K及1 atm是明确的`research_target_not_observation`，没有赋给案例的实际条件。1 atm保留为0.000101325 GPa。ML负责提出可检验的下一行动；其计划需要材料/来源分组、数据权利、泄漏检查和外部验证记录，不把模型分数冒充RPS或Tc概率。

行动的价值在于可区分结果是否改变下一步决策。合同要求2–8个不同可观察分支，至少两种不同continue/stop/redirect决定。五项预算逐项允许null；null不等于零。即便前提和预算被声明完整，本合同仍只返回`prerequisites_declared`，`can_execute:false`。没有作业提交功能，没有实验室，外部实验保持未配置。所有数值RPS与rank固定null；正式RPS继续使用原有campaign、实际成本、角色和分发合同。

## 对象与精确引用

`ResearchCaseInput`包含state、六轴evidence、hypothesis和action。

1. `researchStateFromCatalogue(catalog,stateId)`接受经服务端核验的v2目录，保留原`catalogue_version/catalog_group_id/catalog_state_id`；structure引用primary occurrence的原artifact ID和CIF SHA，source引用其COD版本与CIF SHA。它不复制生成另一套原子结构，不重命名原proposal-state。
2. 修改、条件和方法进入研究定义。目录未分配的条件不能用`catalogue_model`宣称已分配；改变条件须选择`proposed_conditions`。研究state摘要随之改变，原目录state引用仍保留。没有native state/material ID。
3. 六轴固定为stability、electronic、pairing、coherence、geometry、competing_order。unknown有空readings；source_reported/ conflicted需要实际引用、原token、单位、来源定位与适用范围。字段名是来源quantity label，不能冒充原生科学属性ID。引用同公式或母体不自动建立同状态关系。
4. case的`definition_sha256`绑定完整定义和parent；state/action分别有独立摘要。返回必须匹配全部四项binding。每个返回有自身摘要。记录decision后不能附加或改写返回，必须形成后续case。
5. follow-up只记录`research_follow_up`关系和确切父decision摘要，`properties_inherited:false`；新case的六轴必须重新保持unknown。该关系不是被科学审核的物理谱系。

工作进度为source_ready/model_ready/action_ready/returned/decision_recorded。它和科学证据状态、公开层级独立。19个坐标状态可以是model_ready，并不意味着19个高价值研究成品或独立材料。

## API和导出

```ts
const state = await researchStateFromCatalogue(validatedCatalogue, stateId);
const input = createResearchCaseInput(state, "high_bandwidth");
const current = await prepareResearchCase(input);
const file = await exportResearchCase(current); // json, sha256, filename
const restored = await importResearchCase(file.json);
```

用户修改input后重新prepare；不能改已封存case再沿用原摘要。`attachResearchReturn`对完全相同返回幂等；`recordResearchDecision`引用已经保留的返回和原行动分支；`deriveResearchCase`要求已记录decision。可验证的分支选择不等于系统核实了研究者的自然语言判断。

导出版本`discovery-research-cycle-export/1.0.0`；包内case版本`discovery-research-cycle/1.0.0`。只接受完整原始格式导出，拒绝未知键、重复键、变更digest、截断和超过512 KiB的输入；树深≤18，返回≤16，artifact列表≤32。验证与异步哈希前深复制，调用方后续编辑不能改变在途操作。既有来源文档或参考标识只是数据，不作为命令执行，不读取其中路径或URL。

摘要验证证明本地字节一致性，**不能证明外部文献真伪、执行真实性或审核资格**。手工导入的return envelope保留`researcher_linked_unverified`。再次核验原始来源和既有计算返回服务仍是独立步骤。没有科学批准、训练许可、数据库写或自动公共发布。

## 复用QE返回，不重写解析器

`prepareQeStudyReturn(case,readings,{kind,tolerance},findings)`直接调用已有`compareQeReadings`或`compareQeMeshSmearing`；原始文件仍由现有`inspectQeResultContext/readQeNativeOutput`读取。研究case只保存结果链接，不复制UPF、XML或另一套解析规则。

行动必须预先声明`numerical_protocol`及精确容差，所有原reading摘要必须在input_artifacts中，CIF、电荷、自旋模型必须对应。看到结果后提高容差不能沿用原行动。返回的numerical assessment来自已有比较结果；决定必须绑定所选返回，within只允许continue/refine_method，outside、precision不足或不完整只允许redirect/refine_method，样本不足只允许stop/pause。界面、保存和导入使用同一约束，不能通过重算导出摘要绕过。有限窗口within也不构成无限网格极限、相稳定、配对或Tc证明。

## 首批实际案例与验收

| 案例 | 当前事实 | 可重复步骤与下一决定 |
|---|---|---|
| AlB2数值反例，高带宽策略 | 真实三原子Mg→Al、+2%构造已有QE 7.5输出；不是MgB2本体结果 | 以已有native readings建立计算复核case；重放单轴及九点联合窗口，保留outside_tolerance，记录redirect/refine_method，产生不继承证据的新case。没有执行新计算 |
| Sr8Ti8O23，高载流子策略 | COD9006864来源已捕获；该recipe本身没有生成空位模型 | 明确SrTiO3 2×2×2中的O位、40→39原子和对照，另行生成/核验模型并指定电荷自旋；再问移动载流子或局域化/补偿。不能用recipe声称已有载流子结果 |
| LaH10，几何构筑压力教师 | arXiv1907.11916v1 Table I已保留4个LaH10和3个LaD10来源行 | 按同位素和单个solver比较，保留量子E(R)压力、结构/run未关联与低压稳定性限制；先形成来源决策，再提出需要验证的常压构筑假设 |

完整17状态包与现有3条去重后的19状态/8组成组属于目录v2；此合同的往返测试逐一保留其group/state/source/occurrence链。MgB2±2%保持宿主应变状态，不能当新化合物。

测试额外覆盖：六轴未知不变零、未知预算不计分、四种错配binding拒绝、重复返回不重复计数、不可覆写decision、子任务无属性继承、动作事前容差、不同坐标或电荷模型拒绝。AlB2测试使用保留的真实native XML/stdout和现有解析器，不以合成数据充当新结果。

用户授权的VPS已完成隔离、受限的真实QE数值pilot：Mg7AlB16的−2%、0%、+2%三个固定坐标状态分别执行2³、4³、6³网格，共9个SCF作业。三组都超出事前1e−4 Hartree/atom容差，形成returned→redirect/refine_method→不继承证据的child案例；详见[实际计算与捕获记录](discovery_vps_pilot.md)。M4尚未就绪。仍需后续完成：正式认证runner、实验返回合同、RPS研究预算和独立科学审核。现有单账号不伪造参与者；公开研究提案与正式RPS/科学分发保持分离。本合同和本地测试本身不记录部署或候选科学批准。
