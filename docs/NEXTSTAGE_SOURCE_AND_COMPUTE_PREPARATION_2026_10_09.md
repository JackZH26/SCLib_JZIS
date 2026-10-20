# 后续来源与计算准备：2026-10-09

本记录接续[上一阶段记录](NEXTSTAGE_CONTINUATION_2026_10_09.md)。#165、#166 已合并；
#166 的主分支 Test、镜像发布与部署均成功；公开版本 `4c56af1`已通过完整验收，
并保留五个查询的真实scan基线，默认scan约23秒。
新增资料不会将下载、哈希一致或工程回归变成人工科学接纳。

## 首批16个材料的来源访问

[来源获取 v2](data/nextstage-20261009/material-source-acquisition-v2.json)登记了首批16个
候选的完整访问分母。原先5个全文候选新增3个，累计 **8个保留全文候选、8个缺全文**。
所有11个 APS 出版社 HTML 请求均为200，并观察到授权要求文字；没有取得这些出版社的
原始 PDF。其中3个材料另有可公开读取的预印本或作者托管版本，已经保留字节。
对 PuRhGa5 的 JRC 元数据页查询没有观察到可下载 PDF 链接，仍保留缺口。

| 新增材料候选 | 私有保留版本 | 实际 PDF 页数 | 身份与待审范围 |
|---|---|---:|---|
| La4Ni3O9.99 | [arXiv:2309.09462v4](https://arxiv.org/abs/2309.09462v4) | 10 | 当前元数据声明预期 APS DOI；实验样品、压力、onset与计算结构分开审核 |
| Nb0.8B0.2 | [arXiv:1708.08570v1](https://arxiv.org/abs/1708.08570v1) | 7 | arXiv未声明 related DOI；标题对应仅作导航，名义组成、混合相及判据仍待绑定 |
| B-SWNT | 作者课题组公开托管的 PRL PDF，以完整字节哈希固定版本 | 4 | 首页 DOI、卷期和身份已观察；薄膜集合、掺杂、均匀性和 ZFC/FC 协议待审 |

三个 PDF及全部21页抽取文本的字节/哈希均复核通过，首页已做 AI 可视身份检查。
公开 JSON只包含元数据、哈希和定位索引；原 PDF、原文段落和页面图仍在私有档案。
预印本或作者公开托管不是本任务的评估、再分发或训练许可。

新的定位问题包括：

- La4Ni3O9.99 的实验氧含量和高压 onset，是否能与同一记录中的结构/晶格字段绑定；
  不能将计算模型、常压参数和高压实验条件自动合并。
- Nb0.8B0.2 的 Table I 名义组成、Nb-B-20 铸态样品与测量脚注，需要和所选 Result一起核对。
  该文讨论样品组成、相组成及超导信号归属；不同样品的主/少量相关系不能通用。
- B-SWNT 的集合薄膜、浓度与均匀性，需要与磁化测量及理论单管计算分开。

这些是带页/文本跨度哈希的待审问题，没有裁决哪条正式数据正确或错误。
历史目录标签和 Result选择均保留。200条总队列的完整试点边界仍为16/184，
新增保管和部分导航检查未增加完整试点或人工通过数量。

## 首批来源缺口与统一复核入口

[出版社 PDF 访问记录](data/nextstage-20261009/material-publisher-pdf-access-v1.json)
补查了剩余8个候选在既有出版社页面列出的 PDF 链接：各请求一次，均返回 HTTP 401，
没有取得原始 PDF。8次精确 DOI 的 OpenAlex 元数据查询均返回200且 DOI 匹配，
未观察到该索引提供的开放全文地址。这是一次索引观察，不能证明不存在其他合法副本。
请求未使用凭据、重试或访问绕过，所有响应字节和失败分母保存在私有档案。

[200材料队列 v4](data/nextstage-20261009/material-source-acquisition-queue-v4.json)
更新这些访问状态和8份保留候选的精确版本/哈希。其余历史行、人工决定、正式材料属性
和完整试点信用均保留，完整试点仍为16已检查、184待检查。

[统一复核索引](data/nextstage-20261009/material-review-entry-index-v1.json)将8个保留候选
对应到既有及新增的30项材料复核问题、30个页内定位和 ZIP v5 的 A/B/裁决人空白表。
索引核对了8份来源版本/哈希与三套空表的对应关系；这不等同全部论文或字段已经审完。

| 材料候选 | 问题文件中的定位 | 问题数 | 页内定位数 |
|---|---|---:|---:|
| MoSr2Eu1.5Ce0.5Cu2O10 | navigation-questions v1 / cases/0 | 4 | 5 |
| R8Ni7Oy | acquisition v1 / source_role_review_flags/0 | 4 | 2 |
| La0.4Sm0.6O0.5F0.5BiS2 | navigation-questions v1 / cases/1 | 4 | 5 |
| BaPb0.72Bi0.28O3 | navigation-questions v1 / cases/3 | 4 | 5 |
| Bi2TeI | navigation-questions v1 / cases/2 | 4 | 5 |
| La4Ni3O9.99 | acquisition v2 / new_source_review_questions/0 | 3 | 3 |
| Nb0.8B0.2 | acquisition v2 / new_source_review_questions/1 | 4 | 3 |
| B-SWNT | acquisition v2 / new_source_review_questions/2 | 3 | 2 |

[新增导航问题](data/nextstage-20261009/material-source-navigation-questions-v1.json)
覆盖其中4个材料的16项问题与20个定位，保留历史所选 Result 和压力、方法等字段作为
待核对输入。重点包括版本/引用根、样品组成、测量判据、制备压力与测量压力、
升降压和温度历史、背景 Tc 与光学响应的区分。抽取文本与列出的页面图仅作 AI 导航检查；
没有新增完整试点、人工审核、科学接纳或 canonical 数据写入。

BaPb0.72Bi0.28O3 的期刊论文存在涉及化学式的
[公开更正](https://pmc.ncbi.nlm.nih.gov/articles/PMC5625943/)。
[更正来源记录](data/nextstage-20261009/material-correction-source-notice-v1.json)
将原文、通知与冻结预印本列为待审版本关系。当前仅保留网页读取器表示的哈希，
不是原始 HTML/PDF 字节固定；原期刊 PDF 和更正 PDF 的精确版本对仍未取得。
没有据此自动修改材料组成或宣称预印本已包含期刊更正。

[版本关系候选](data/nextstage-20261009/source-version-link-candidates-v1.json)
登记5条由预印本 related DOI 或作者托管 PDF 首页 DOI 支持的身份候选。
这些关系尚未成为已接纳的 Work/root 或同样品 Result 关联；不是穷尽的引文图。
72道检索草稿、26个临时指针连通组、0 gold、未分配 split 保持原状态。
这里的材料问题不会计入检索题数，也不会作为独立实验增加统计分母。

## 检索案例全文与状态导航

[检索缺口获取 v4](data/nextstage-20261009/retrieval-gap-acquisition-v4.json)
通过 HAL 官方 API 的精确 DOI 元数据及其公开提供的文件地址，补取得
[(TMTSF)2PF6 原始报告的存档版本](https://hal.science/jpa-00231730v1)。
PDF 共5页，含1页 HAL 封面和4页期刊扫描页；全部字节及页文本哈希已固定，
封面、首页与相关图页已做 AI 导航检查。API 和封面均标示 v1，下载 URL 本身不带版号，
因此只保证已取得字节的身份，不保证该地址今后的内容。期刊出版年1980、存档提交日期
2008-02-04 分别记录，不能拿后者代替实验或出版时间。

新增六类案例现有4类保留原始全文候选。Hg 出版社 PDF 返回401；Lu-H-N 原文 PDF 请求
转到 HTTP 200 的 HTML 访问页，没有取得 PDF；其既有撤稿通知仍独立保留，版本对未完整。
12道 addendum 问题保持原字节内容，所有人工支持、Work/root、用途决定和 split 均未批准。

[三类既有预印本的复核导航](data/nextstage-20261009/retrieval-source-navigation-v1.json)
补出12项来源复核问题和15个页内定位，分别对应 Pr 镍酸盐的样品/薄膜/判据、
CeCoIn5 的直接测量与 CeIn3 引用、LaAlO3/SrTiO3 的器件、栅压历史和判据。
有机报告另含4项复核问题和5个定位。这些是既有问题的复核提示，检索草稿仍共72道；
没有新答案、人工 gold、可信独立实验数、provider运行或盲测信用。

## 待审包 v5

[ZIP 收据](data/nextstage-20261009/pending-review-materials-v5-receipt.json)固定34个文件的
208,875字节档案。全部 v4 文件保存在 `v4/`；根目录独立 A/B/裁决人空表各含8个材料候选。
原先16材料试点和72道问题草稿的表单、字节及空白决定均保留。

ZIP不含 PDF、抽取段落或图片。两位独立审核人及必要时的裁决人仍待指定；
真实审核需获得精确原文、完整上下文与适当用途权限，再走既有认证准入流程。

## 更新的待审包 v6

[ZIP v6 收据](data/nextstage-20261009/pending-review-materials-v6-receipt.json)
固定44个文件、278,471字节的私有档案，SHA-256 为
`4c0b0771ef9856907a751ed5b28e87a28c58c794bb2bc01dd5f57d589f8d0894`。
全部34个 v5 成员位于 `v5/`，逐文件字节未变；新增8份来源元数据伴随文件、README
和 manifest。来源复核索引仍指向其固定的原 v5 成员，在 v6 中读取时加 `v5/` 前缀。

三套8行材料空表、原16材料试点表与72题空表均保留，原 ZIP v5 也未覆盖。
包内不含原始全文、抽取段落或页面图；本轮没有代填审查人、裁决人、许可或科学结论。

## 既有计算输出的只读复核

[计算准备 v2](data/nextstage-20261009/compute-readiness-v2.json)复核了已经保留的
1次初始化和3次 SCF。4份 server export、16份原始输出、冻结输入与 UPF、runtime配置、
输出 manifest及 completion/receipt绑定均与既有 custody读数一致。
初始化独立保留，不进入三个 SCF 的 MPI比较分母。

复用固定 canonical读数的检查工具后，三个 rank仍满足原先阈值：

| 量 | 复核值 |
|---|---:|
| 每原子能量窗口 | 3.941143707682689e-12 Ha |
| 每原子最大 SCF误差 | 7.957364286940383e-13 Ha |
| 相对2-rank的最大力分量差 | 2.4914198309862027e-7 Ha/bohr |
| 相对2-rank的最大应力分量差 | 2.3194743181690405e-8 Ha/bohr³ |

随后，[计算准备 v3](data/nextstage-20261009/compute-readiness-v3.json)使用原有固定读取器，
在本地重新解析4份已保留 XML，并重做对应原始输入、伪势、输出和 custody绑定。
1份初始化和3份 SCF 新生成的 canonical JSON与旧读数逐字节相同；初始化仍不进入 SCF分母。
读取器及私有 harness哈希保持一致，临时读取入口均清理，计算工作树前后干净。
本次没有联络节点或队列认证端点，没有运行求解器或增加预算预约。
结论仍限于已保留导出、节点声明、原始输出与 canonical读数的一致性，
不提供密码学运行时证明、当前资源 grant、安装验收或新的科学批准。

计算代码链 #155 → #156 → #160 → #161 → #162 → #163 → #164仍开放。
#155的完整检查通过，其余保留堆叠 base并只有 transport契约检查通过。
开放代码、fixture通过与实际安装分别记录，不能批量合并或直接宣称节点能力已发布。

10:00 UTC的保留进程记录仍显示旧 worker运行。远程任务的最新完成记录等待正常管理员认证，
旧 worker停止、历史任务对账和独占交接尚未得到完成证明。没有启动第二个 worker，
没有开始 PBEsol实跑或24小时验收。

## 新有限预算提案

[方案 JSON](data/nextstage-20261009/finite-mesh-budget-proposal-v1.json)复核了原先6个
初始化/SCF payload的30个文件引用，字节和哈希均匹配冻结方案。
提案保留 Mg4B8、PBE PAW、固定几何、原输入及600秒引擎上限，统一2个 MPI ranks。

| 网格 | 初始化外部上限 | SCF外部上限 | 该网格保守预约 |
|---|---:|---:|---:|
| 4×4×6 | 180秒 | 900秒 | 2,160核秒 |
| 6×6×10 | 180秒 | 900秒 | 2,160核秒 |
| 8×8×12 | 180秒 | 900秒 | 2,160核秒 |
| 合计 | 3次初始化 | 3次SCF | **6,480核秒（1.8核小时）** |

最多一个重任务并发，每项最多一次尝试，无自动重试或返还预算。
只有通过精确身份审查才可能复用旧粗网格读数；提案仍保留所有6项的保守预约，
不会把复用标为新运行。内存、磁盘、进程树限制和失败停止条件均写入方案。

旧 campaign仍为6,780/7,200核秒、剩余420，没有重置或追加消耗。
新方案尚未获得明确预算批准，也未提交任何任务。执行还须完成正常管理员认证、
旧 worker停止/对账、无残留 MPI、实际安装/运行时与 grant核验、实时资源检查及逐任务认证准入。

## 发布后的有限采样

[性能观察方案 v2](data/nextstage-20261009/material-performance-observation-plan-v2.json)固定了
5个查询、gzip、顺序调用、每查询5次样本和每个代码臂最多2轮计时捕获，计时最多50个列表 GET。
独立完整公开验收另含24个列表 GET（20个样本、4个422拒绝）及16个
enrichment GET；合计每个代码臂最多90个 Materials列表/恢复窗口请求。v2补明原 v1未列出的
验收分母，固定查询、缓存生命周期、两轮计时上限及全部失败保留规则均未变。
在实际部署及新版本检查后先记录计时，再完成全部206个静态文件和16个恢复窗口的公开验收。
没有自然 scan时最多留存一次相同条件的后续捕获；不清缓存、不改参数绕缓存。

所有失败、缺失 header、版本变化和缓存路径均留在分母。before/after只按相同查询、编码、
数据/响应身份及同一 server path解释；`total`包含其他阶段，不再次相加，`scope`可包含 SQL。
单次 scan可以定位下一项实验，但不能作为 p95、统计显著性或正式 SLO验收。
正式 SLO目标及验收仍待建立，#167尚未获得生产提速信用。

## 本轮准备资料校验

[离线校验记录](data/nextstage-20261009/source-preparation-validation-v1.json)
独立重放了新增20个材料定位、5个有机案例定位和15个其他检索定位，
并核对统一索引与三套空白表的精确来源版本/哈希。200条材料 ID 唯一，
16/184 完整试点边界、12道检索 addendum 原问题、科学/用途空白决定均保留。
新有限预算提案的 SHA-256 未变；未作出的批准不因其他工程检查通过而生效。


## 联合代码的完整本地回归

[完整回归收据](data/nextstage-20261009/material-integration-validation-v1.json)
在固定联合提交 `8a91067f254ee9c2f1cfaafb36d5011023aa74bb` 完成8批普通 API回归，
实际结果为 **8,543通过、9跳过、0失败、0错误；8,552 cases、269个模块**，耗时 3,614.272秒。
独立读取8份 JUnit核对每批全部模块和 counts，与 coordinator结果精确一致；
每批 runner退出码均为0，自有 PostgreSQL/Redis及测试数据已清理。
执行前后工作树干净，941个 API/scripts输入的固定哈希与 HEAD均未变。
容量套件未计入此次分母；跳过项及其原因逐项保留，不获得通过信用。

12:01 UTC观察到 #167已更新到 `8dd638051f04bf31ab125fe150d47196b25b032b`，
其父提交为当前 main `4c56af1`。
[版本关系收据](data/nextstage-20261009/pr167-integration-tree-identity-v1.json)
核对 GitHub提交对象与本地 Git树，两者 tracked tree完全相同
（`dd6111a090c8774ef029712e889706c9a5d6ef9a`）。本地运行记录仍使用实际执行的
`8a91067`，不改写为新 PR提交。新 PR精确版本的 Linux CI仍是独立要求；
本地回归及相同代码树不提供实际部署、生产提速或科学接纳信用。

## 主分支 Linux与镜像发布更新

main `4c56af1` 的 [Test 37917133614](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37917133614)
于12:01 UTC成功完成。[Linux完成收据](data/nextstage-20261009/main-4c56af1-linux-validation-v1.json)
独立重放8份 JUnit，确认8,500通过、9跳过、0失败/错误、8,509 cases及268个模块。
940个枚举 API/scripts输入保持干净且未变；整体工作树 dirty为 true，其他脏路径未由
plan列出，因此不宣称整个工作树干净。该 Linux分母未包括独立容量套件。

[镜像发布 37927409318](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37927409318)
于12:05 UTC成功完成。[发布复核](data/nextstage-20261009/release-after-4c56af1-v1.json)
核对3个组件的提交 SHA和固定 image digest，并用既有比较器重放 API、migration、ingestion
三份测试清单与 release清单，绑定同一个 Test run及其原 artifact ID，均精确匹配。
这是 Linux/amd64的锁定 Python包版本一致性，不提供 OS/ABI或科学运行验收。

[部署 37927770900](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37927770900)
正在执行；12:10 UTC的公开版本仍为 `7efe186`。部署与新版本完整公开验收须另记实际结果；
后续计时先保留自然请求路径，再做完整静态来源与恢复窗口验收。


## 部署完成与真实计时基线

12:34 UTC，[部署](https://github.com/JackZH26/SCLib_JZIS/actions/runs/37927770900)成功完成。
[部署/验收收据](data/nextstage-20261009/deployment-after-4c56af1-v1.json)保留实际 Release ID绑定、
最终 job日志哈希和公开版本围栏。公开版本为 `4c56af1`、dataset `v2026.09.03`、API `1`。

12:36–12:37 UTC先完成[固定查询计时](data/nextstage-20261009/material-profile-4c56af1-v1.json)，
25次请求全部200且具有有效 Server-Timing，5个查询各自然观察到1次 scan和4次 page_hit。
12:39 UTC随后执行[完整公开验收](data/nextstage-20261009/public-after-4c56af1-v1.json)，
253次请求、20项检查全部符合预期，206个静态文件及16个恢复窗口全部匹配；
API/页脚/数据集及前后版本围栏一致，当前公开材料总数10,507。

[诊断收据](data/nextstage-20261009/material-performance-baseline-4c56af1-v1.json)分别保留真实路径分母：

| 固定查询 | scan客户端秒 | scan服务器total秒 | scope秒 | selection秒 | 4次page_hit客户端中位秒 |
|---|---:|---:|---:|---:|---:|
| default | 22.998 | 22.582 | 10.783 | 10.293 | 0.425 |
| formula | 0.593 | 0.173 | 0.017 | 0.020 | 0.399 |
| observed_cuprate | 6.286 | 5.872 | 4.237 | 1.245 | 0.418 |
| source_count | 13.264 | 12.629 | 9.668 | 0.087 | 0.674 |
| source_count_min2 | 12.707 | 12.054 | 9.825 | 0.050 | 0.677 |

默认 scan的 `selection`为10.293秒，占服务器total的45.58%；`scope`为10.783秒，占47.75%。
因此既有 #167 Tc选择优化针对已观察到的一项主要成本；source_count两组则主要消耗在scope。
scope含SQL，不能由该阶段名推出数据库查询计划或纯CPU归因。
默认客户端scan约23秒，尚未证明15秒首次请求目标；每个查询只有1次scan，
不宣称冷数据库、统计p95、生产before/after提速或正式SLO验收。

实际调用为25个计时列表GET、24个验收列表GET和16个enrichment GET，共65个Materials请求。
该数量低于v2有限方案90次的最大分母。已有全部所需自然scan，没有执行第二轮捕获。
材料完整试点、检索草稿、人工审核、用途许可、新科学预算与训练准入均维持各自原门槛。
