# 50 篇来源审查与独立标注规范 v1

当前 50 篇是待审候选；每族 10 篇，10 development / 10 validation / 30 blind。正文都已下载并解析，NER 0 篇、gold 0 篇，尚未指派两名标注者和仲裁者。50 份 source capture 都保留图像或版面待审缺口。模型生成、人工 gold 与论文科学可信性是三种不同验收。

## 冻结来源

[selection](materials-ner-50.selection.v1.json) 是选样依据；[prepared sources](materials-ner-50.sources.prepared.v1.json) 给出实际版本、URL、license 和 hashes，不含全文或本机路径。不能用准备收据当成 frozen manifest。

逐篇审查以下项目，给证据与审查人/时间；未知不能直接改成 verified：

1. SCLib paper 与 canonical Work 的对应；arXiv/期刊版、修订版和引用同一原始数据的论文合并到明确的数据依赖组。同依赖组不得跨 split，既有 prompt 示例不得放 blind。
2. family 标签依据内容而非关键词。当前标题引导选样中包含常压氢化物/负结果等边界候选；若不符合高压族或其他配额，记录同族替补，重新下载和核 hash，冻结前完成替换。
3. source version、URL、真实 license、允许本项目本地转移/推理范围和 cloud 推理范围。可下载不等于可任意发送；附件独立审查。当前这两个 permission 均为 false。
4. supplementary 是否已在正文内，是否另有文件/网页/数据；全部范围确定后才写 `included` 或 `confirmed_absent`，不以没有看到链接当不存在。
5. 每个单独附件通过 `prepare` 建立文档；`supplement_captures` 为每份附件记录 `source_version/source_url/source_license/source_sha256/content_manifest_sha256/source_format/coverage/transfer_allowed/cloud_inference_allowed`。included 但缺 capture、重复 capture、附件 permission 未确认都会拒绝冻结。
6. 核 PDF 旋转文字、数学式、表头/脚注、图注与仅图内的关键数据。图数据另存 digitization 及误差；仍无法处理的缺口保留，不消失在空结果中。
7. 逐篇证实 challenge tags 和原始实验独立材料清单；不能把候选标签或模型说法写成 verified。配额及其错误由 `manifest --freeze-output` 输出；不够则替补或明确未验收。

必须确认的状态为 `work_identity_status=verified`、`family_review_status=verified`、`dependency_group_review_status=verified`、`supplement_status=included/confirmed_absent`、真实来源/解析 hashes、已确认 transfer scope，以及协议要求的难例和独立性配额。

冻结程序自动去掉 `private_*` 路径。文档以内容 manifest hash 为文件名在各主机私有存储；因此 coordinator 与 Mini 使用相同 frozen manifest，不需要修改数据 hash 来迁就不同文件路径。每次替补、源修改或范围改变产生新版本；不能覆盖旧 manifest。

## 独立 gold

每个 A/B 空白包包含固定来源的 hashes/URL、每 work 的 `claims_by_work=null`、空的人名与仲裁信息。待审源的包用于准备；来源冻结后重新生成正式包。两人分别阅读固定源且不看模型输出，再仲裁分歧。未分配、未开始、模型多数票或本系统自动归并不能标为 adjudicated。

逐条标注目标量或结论及其原子关联：

| tuple 字段 | 要求 |
|---|---|
| material | 原文材料表达；明确别名/变量/同位素与 source-scoped 身份，不能靠相同化学式合并样品 |
| sample | 原文 label、form、preparation；没有编号保留 null，不能跨来源复用 S1 |
| state | 有角色的 measurement/calculation/synthesis 条件；量值保留 point/range/bound、单位及不确定性，unknown 不当 ambient |
| point | source byte hash +规范解析文本的 Unicode 起止位置；对数值使用完整数值 witness span，保留 table/page/context 的支持 |
| property / criterion | 每条属性分别记录；Tc onset、zero、midpoint、diamagnetic 等不得互相替代 |
| quantity | 规范值及合法单位变换，原始表示/证据另留；范围不取中点，未检出不造 Tc=0 |
| method | 原文支持的方法；不从材料族或标题猜测计算模型/实验仪器 |
| knowledge_origin | Observed / Computed / Inferred / AI-Proposed / Unknown，体现原文报告的性质 |
| source_role | primary / cited / unknown，区别本研究与引用；不同字段可以有不同来源性质 |
| evidence | 逐字段 quote、精确位置及表头/脚注支撑；能定位与能支持数值/关联分别核对 |

同一论文、材料和压力的重复、加载/卸载、不同 μ*、结构和计算设置分别标注。多个 Tc 判据属于同一物理 point 的不同 claim。正文/表格重复陈述记录多个 occurrence 和明确 same-result 关系；不因为缺条件一致就去重。λ、ω_log、μ*、Tc 只有同一事件时能组成参数 bundle。

记录正结果、负结果、不确定结论、未报告、未知、source/parser/extraction 不可用与不适用。只有指定全部源范围确实处理完，才标 no_claim_found；机器输入无值不能证明图中无值。盲测 gold 覆盖所有目标结果，不能只标某一模型抽到的行。

## 模型输出与证据审计

正式比较只接纳三模型的固定输入、共同 prompt/schema/normalizer/程序与 budget。provider-specific transport/decoding 可以不同，精确模型/config/runtime 另存。三个模型各生成一份 comparison package；补充材料缺 run 会降低 coverage，而不会增加独立 work 数。

gold 在独立阅读后建立。模型预测的额外假阳性和证据支持仍需独立审计：给输出匿名标签，审查包不能包含模型名、provider、性能或已得分结果；真实 config hash 的对应保留在协调方。A/B 审查每个 prediction，仲裁后写 source/config-bound `prediction_audits`，每条项目包含 evidence_support、locator_resolves 和 severe_errors。漏审预测不能给支持率 100%。公开报告可以揭盲，但不能回头调 blind 配置。

CLI 的 comparison input 带 provider/config，供协调方留档；它不是可直接发给盲审者的匿名包。`review-package --models models.json --output review.json --private-mapping-output aliases.json` 核对三模型来源、配置、共同 token/time/budget，生成随机匿名标签，仅保留 source-grounded tuple/evidence 与空白 prediction audit，删除 provider/config/性能元数据。未知 claim 元数据或 Work 范围不一致会拒绝。两个文件均为私有 0600，alias mapping 只由协调方保留。实际三模型输出尚未生成，正式盲审材料的人工分发尚未执行。

## 空值补全与判定

在同一50-work范围导出已有字段快照，保留source/material hold和association状态。已用只读公开paper API取得50/50当前projection，共166个返回材料occurrence，[基线收据](materials-ner-50.public-baseline.v1.json)保留响应SHA、visibility和旧字段实际名称的缺键/值统计；布尔false不按数值0统计。这不是全库Materials汇总页快照，缺键也不证明原文无值或可补。人工确认可重提取的source claim IDs才进入 `baseline_recoverable_claim_ids_by_work`；现有值、原文缺失、未取得源、治理/归并问题不进入这个分母。当前仍不报告实测补全率。

| 路径 | 输入与验收 |
|---|---|
| 正文重提取 | Tc/P/条件/判据/方法、结构、配对、EPC、样品制备：quote +角色 +事件关联通过且治理范围可用 |
| 确定性派生 | 完整固定 composition 才能计算化学计量/描述符；密度/对称性须同一结构晶胞/坐标；记录算法和输入依赖 |
| 同事件公式 | λ/ω_log/μ* 与适用方法齐备才提议新的 Computed Tc；不覆盖报道 Tc，不跨事件拼接，不把该公式用于任意铜/铁/镍体系 |
| 后续科学计算 | DFT/DFPT/EPC 须完整结构、压力、磁性、方法与独立预算；属于另一个科学计算 job，模型输出不是结构有效性证书 |
| 不能确定 | 实验 Tc、配对真值、未知样品对应和未定义方法不能靠 LLM 猜测补齐 |

评分使用 30 blind works，按 Work/原始数据依赖组做 5,000 次 paired bootstrap，分别比较本地与两个云模型，95% 下界≥−2 个百分点。全 50 用于最终同配置流程/运营报告；指标与阈值见 [protocol](materials-ner-50.protocol.v1.json)。分母为空、字段缺覆盖、人工审计或真实 runtime 缺失均保持未验收。
