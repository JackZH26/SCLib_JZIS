# Materials V3 本地 NER 部署与移交

本说明用于已经授权的「搭建 SCLib M4 计算节点」任务。只使用独立 checkout 和私有影子结果；生产 ingestion/NER/aggregation 的暂停、科研及来源 hold 继续生效。当前可交付的是工程代码和来源准备，实际模型性能与科学质量尚未验收。

## 固定模型与实机边界

实机为 Apple M4 Pro、14 CPU 核、48 GiB 统一内存、macOS arm64。指定模型为 `mlx-community/Qwen3.6-35B-A3B-4bit`，revision `38740b847e4cb78f352aba30aa41c76e08e6eb46`。17 个文件合计 20,429,169,263 字节，逐文件 pin 在 [model-pin.json](../ingestion/ingestion/materials_v3/model-pin.json)。不以 3B 激活参数估计权重内存。

Mini 已报告 17 个文件完整校验、MLX 环境导入和分词/拒绝路径测试通过；`NER_NODE_READY.json` 的实际推理、队列回传、服务账号及 soak 仍 pending。模型路径与原 node 维护流程沿用该任务的实际收据，不猜测账户权限。

加载之前，原 QE worker 停止/移交收据必须成立，且 QE 与 NER 必须使用同一整机重任务锁。原 worker 尚不共享该锁时，创建另一份锁不能证明互斥。共享目录目前归 root 所有，应由原维护流程建立正确的服务账号与锁权限；不重复开认证窗口、不复用旧 QE 预算、不关闭无关应用来腾内存。

初始加载 admission 要求原生 arm64、总内存至少 44 GiB、当前 free+inactive+speculative 至少 36 GiB（24 GiB 尚未实测的峰值估计 + 12 GiB 余量）。运行守卫同时记录 RSS、Metal，使用两者最大值与主机余量：峰值上限 32 GiB，主机余量下限 12 GiB。两项都是停止条件；`mx.set_memory_limit` 不是 OOM 保证。初始并发一个模型、一个重任务。不能把可用内存不足的测试标为成功。

## 安装隔离的代码与环境

将审阅分支的精确 commit fetch 到新的 checkout；保留 Mini 现有用户修改与 node 目录。部署消息会给出最终 commit。以下变量应指向实际存在的隔离路径；不能把其他项目当成输出目录。

```bash
export SCLIB_NER_CHECKOUT=/path/to/isolated/SCLib_JZIS
export SCLIB_NER_STATE=/path/to/private/ner-state
export SCLIB_NER_MODEL=/path/to/verified/model/snapshot
cd "$SCLIB_NER_CHECKOUT/ingestion"
uv sync --frozen --extra mlx --python 3.12
export PYTHONPATH="$SCLIB_NER_CHECKOUT:$SCLIB_NER_CHECKOUT/ingestion"
.venv/bin/python -m ingestion.materials_v3.cli hardware
```

原生 MLX 固定为 `mlx==0.32.3`、`mlx-lm==0.32.0`，完整依赖见 `ingestion/uv.lock`。独立 preparation 环境若版本不同，不能将其旧 runtime receipt 用于本版 worker。队列 adapter 导入仓库里的 `scripts.sclib_compute`，因此运行时必须包含仓库根目录的 `PYTHONPATH`；仅安装 ingestion wheel 不足以启动队列。

部署可先做静态 import、真实 tokenizer、JSON/schema 和拒绝路径测试；这些不加载模型，也不解除 admission。`uv sync` 完成并且代码不再修改后记录实际 runtime：

```bash
.venv/bin/python -m ingestion.materials_v3.cli runtime-lock \
  --output "$SCLIB_NER_STATE/runtime-lock.v1.json"
```

此文件记录已安装 Python、OS、包版本、代码摘要和硬件，`model_loaded=false`。后续 worker 每次启动核对它；安装、升级包或改代码后须产生新版本，旧文件不覆盖。

模型 manifest 必须有精确 `model_id`、`revision` 和全部 17 个 `files[{path,bytes,sha256}]`，可将仓库的 `model-pin.json` 作为待验证清单，再对本地文件逐项核对。CLI 在加载前重新核对实际字节、摘要和 safetensors weight index。保留 Mini 原下载清单与日志，不修改权重。

## 完整输入与合成 smoke

首期配置见 [local](pilot/materials-ner-local.v1.json)、[budget](pilot/materials-ner-budget.v1.json)：16,384 总 tokens，4,096 输出，关闭 thinking，贪心解码；每篇 3,600 秒、120 次尝试、额外基础设施重试至多 2、语法修复至多 1、拆分深度至多 6。

先使用明确标记为 synthetic 的短文本检查真正的 NER schema，不能只让模型回答问候语或无约束 JSON。示例文本仅用于工程 smoke：

```text
Synthetic test only. LaH10 sample S1 was measured by resistivity during
loading at 150 GPa. Its transition onset was 240 K; zero resistance was
232 K. During unloading at 150 GPa its onset was 236 K.
```

```bash
.venv/bin/python -m ingestion.materials_v3.cli prepare \
  "$SCLIB_NER_STATE/synthetic-smoke.txt" --source-id synthetic:smoke:v1 \
  --output "$SCLIB_NER_STATE/synthetic-smoke.document.v1.json"
.venv/bin/python -m ingestion.materials_v3.cli run \
  "$SCLIB_NER_STATE/synthetic-smoke.document.v1.json" \
  --paper-id synthetic:smoke --work-id synthetic:smoke \
  --provider-config "$SCLIB_NER_CHECKOUT/docs/pilot/materials-ner-local.v1.json" \
  --budget "$SCLIB_NER_CHECKOUT/docs/pilot/materials-ner-budget.v1.json" \
  --model-path "$SCLIB_NER_MODEL" \
  --model-manifest "$SCLIB_NER_STATE/model-manifest.v1.json" \
  --heavy-lock /Users/Shared/SCLibCompute/heavy-job.lock \
  --ledger "$SCLIB_NER_STATE/smoke.sqlite" \
  --output "$SCLIB_NER_STATE/synthetic-smoke.run.v1.json"
```

模型生成成功、candidate schema/quote/number/association 校验、三个 Tc 判据与路径是否完整、raw JSON 与修复次数、tokens、耗时、RSS/Metal/主机余量分别保存。空数组虽然可能通过格式校验，在这个合成输入上不表示 NER 语义 smoke 通过。再次运行同输入、同配置、同 ledger 到新输出路径，成功块应复用，生成次数不增加。原失败收据保留。

实际 Qwen tokenizer 必须对含 schema、上下文和 chat template 的完整 prompt 计数；共同 `cl100k_base` 只用于分块。CLI 在 input+output 超过 16k 时拒绝当前块并有界拆分，不截断。图像、PDF 旋转文字、表格版面缺口仍需要源审查，不能被 tokenizer 成功消除。

## 50 篇分批运行

正文 50 篇已准备，许可/族/依赖组/Work 映射/补充材料与难例审查尚未完成。准备收据不是冻结数据集；参见[审查规范](pilot/materials-ner-50.review-guide.v1.md)。每个附件独立记录许可与 capture，不继承正文的宽松许可。可转移源确认后再按任务复制文件到 Mini。

冻结 manifest 不含主机私有路径。文档按 `content_manifest_sha256.json` 放在私有 `--documents-root`；正文及每份附件分别有一个文件。源码与 provider 配置保持固定，采用同一常驻模型顺序运行：

```bash
.venv/bin/python -m ingestion.materials_v3.cli batch \
  "$SCLIB_NER_STATE/corpus.reviewed.v1.json" --split development \
  --documents-root "$SCLIB_NER_STATE/documents" \
  --provider-config "$SCLIB_NER_CHECKOUT/docs/pilot/materials-ner-local.v1.json" \
  --budget "$SCLIB_NER_CHECKOUT/docs/pilot/materials-ner-budget.v1.json" \
  --model-path "$SCLIB_NER_MODEL" \
  --model-manifest "$SCLIB_NER_STATE/model-manifest.v1.json" \
  --heavy-lock /Users/Shared/SCLibCompute/heavy-job.lock \
  --ledger "$SCLIB_NER_STATE/local-development.sqlite" \
  --output-dir "$SCLIB_NER_STATE/local-development-runs" \
  --output "$SCLIB_NER_STATE/local-development.receipt.v1.json"
```

先 10 开发，再 10 验证；校准后冻结配置，再运行 `blind_test` 或最终 `all`。后两种模式在生成前强制核查 frozen manifest、族/挑战配额、Work、附件和传输范围。正文/附件共用每篇 budget；资源失败会停止本批剩余 capture/work。纸面总数、machine-text complete、end-to-end complete 和科学接纳分别记录。

云模型在协调方运行，Mini 不需要云密钥。OpenAI 固定 `gpt-6.1-sol`、Responses、low reasoning、strict schema、`store=false`；[Gemini candidate](pilot/materials-ner-gemini.candidate.v1.json) 只是当前仓库默认，实际旧部署型号仍须核对。标准环境变量或既有秘密管理提供凭据，不能粘贴到聊天、文档或 Git。记录实际返回 model、tokens、reasoning/cache 与错误；费用未知保持 null，不能把失败当零成本。当前尚无实际云请求。

## 接入现有计算协议

使用独立 `ner_qwen_mlx` kind/capability、新 NER grant 和固定 runtime_id。仓库 staging server 默认仍只允许 dummy，新增 contract 不自动开放 NER 派发。旧 QE grant 的剩余 core-seconds不能用于 NER。

`JobSpec` 输入精确为 `document.json`、`ner-job.json`，输出精确为 `result.json`、`execution.json`；closed NERJob 要绑定 source/document/code/schema/provider/budget/model manifest/runtime lock 摘要及已确认传输范围。≤4 CPU、≤32 GiB、wall 预算须覆盖 paper budget 且≤7,200 秒；只允许这套 adapter，没有自由 shell。

现有 mTLS client config 必须为私有 0600 文件，不在消息或 Git 中传证书私钥。节点仅出站调用已有 coordinator，不新增公网推理端口。worker 入口：

```bash
.venv/bin/python -m ingestion.materials_v3.cli worker \
  "$SCLIB_NER_STATE/client-config.json" \
  --state-root "$SCLIB_NER_STATE/queue" --runtime-id ACTUAL_NER_RUNTIME_ID \
  --runtime-lock "$SCLIB_NER_STATE/runtime-lock.v1.json" \
  --provider-config "$SCLIB_NER_CHECKOUT/docs/pilot/materials-ner-local.v1.json" \
  --budget "$SCLIB_NER_CHECKOUT/docs/pilot/materials-ner-budget.v1.json" \
  --model-path "$SCLIB_NER_MODEL" \
  --model-manifest "$SCLIB_NER_STATE/model-manifest.v1.json" \
  --heavy-lock /Users/Shared/SCLibCompute/heavy-job.lock --cycles 1
```

pilot 每次最多 50 cycles，空队列退出；部署到系统服务须由既有 supervisor 接续及调度。持久 claim_request_id、fencing、SQLite block ledger 与完成 outbox 用于恢复；ACK 丢失时先回放完成包，避免重复生成。真实联网、取消、服务账号 Metal、锁屏/退出/重启和 24h soak 收据尚待 Mini 实测，不以本机模拟队列测试替代。

## 回传与页面

`export` 必须用原文档重新跑 validator，再生成私有 import packet。可信 importer 的事务仅追加来源 capture、occurrence、run、candidate 与 coverage，不修改 catalogue 或规范 Tc。显式选择一个来源解释后才能创建不可变 snapshot；多个模型输出不是多个独立实验。

私有预览路径 `/materials/preview/<snapshot-uuid>/<material-id>` 使用 reviewer/admin API，无登录 401、无角色 403、no-store/noindex。source/material hold 会继续过滤候选。生产页保留旧 read path，增加按 work/sample/point 展开的论文报告；本次没有激活新快照或发布候选值。

完成回执应包含精确代码 SHA、model/schema/runtime hashes、真实 model load/generation、资源与失败记录、connected_staging/compute_verified/soak_accepted 状态。四级状态分别证明，任何一项 pending 不能写成整节点或全库就绪。
