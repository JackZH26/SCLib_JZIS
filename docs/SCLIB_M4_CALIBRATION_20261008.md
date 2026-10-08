# M4 首轮真实计算校准（2026-10-08）

本方案冻结已经准备好的 MgB₂ 母体 2×2×1 坐标模型，先打通真实任务回传，再测 MPI 并行和有限 k 网格敏感性。它不生成新候选、不预测 Tc，也不把测试通过写成科学批准。冻结状态及文件摘要见 [m4-calibration-v1.json](data/discovery-batches-20261008/m4-calibration-v1.json)。实际执行与验收需要另存记录；此摘要始终表示 `prepared_not_run`。

2026-10-08 的实际初始化与 1/2/4-rank SCF 结果另见 [首轮观测记录](SCLIB_M4_CALIBRATION_OBSERVED_20261008.md)。该记录不改变本冻结方案或 prepared snapshot。

## 固定科学输入

母体 `Mg4B8`，12 个原子，来源 COD 1526507 固定坐标，均匀线性应变 0%。完整源包 manifest SHA-256 为 `af978e9f847a77913a32b19f09910b67d42c8d185943b25c5e1f8ffd9277f838`。64 个 UPF 价电子是计算记账，不是自由载流子数量。

沿用原始字节：PBE PAW、60/480 Ry、MV 展宽 0.02 Ry、`conv_thr=1e-10 Ry`、`electron_maxstep=100`、`mixing_beta=0.3`、引擎 `max_seconds=600`。电荷 0、`nspin=1`、无 SOC、固定几何、`from_scratch`。不把应变标成压力，也不把展宽标成实验温度。B 的来源坐标有舍入精度限制；保留原数值，不在校准时悄悄理想化。

首个 SCF 为 4×4×6 零平移网格，输入 SHA-256 为 `3f1bebeda26ff3bde30e66e51c47a6fb781fdb7f616e1f60e73fca528faca8d4`；独立 `nstep=0` 初始化输入 SHA-256 为 `fcce36f4e0ee3d8243f57805894e94b716f5bafc3d591f69ce2a1086fbd64902`。原始准备 manifest 为 `f701a8ea7bff17378d730f0f73a1988e088464eaf5a7d78838d0991e8b032119`。

| 完整赝势文件 | SHA-256 |
|---|---|
| B.pbe-n-kjpaw_psl.1.0.0.UPF | `4a41b06dfc361efde113fc033a06b9103e6d09df58f6f167c44b47e5ed082135` |
| Mg.pbe-spnl-kjpaw_psl.1.0.0.UPF | `c6420b82107b1fe96a798a0232093dacb0e0917dbb49bccbff5f845525b2810a` |

全部 .in、准备 manifest 和 UPF 逐字节复制到私有包；没有重新生成、下载或覆盖旧文件。记录中仍保留赝势来源/许可尚未独立核实的原始说明，摘要不重写该 provenance。

## 顺序与预算边界

先核验 Mini 报告的 `qe-7.5-770a0b2-arm64`，实际 pw.x、MPI、SDK、动态库和运行配置必须另有哈希记录。只使用 1 个重任务并发，每个 MPI rank 单线程，BLAS 单线程。不得因为机器有 14 个核就同时释放 36 项输入。

| 阶段 | 冻结提案 | CPU×wall 保守预约上限 |
|---|---|---|
| 首个真实闭环 | 2 ranks 初始化 ≤180 秒；检查后 2 ranks SCF ≤900 秒 | 2,160 core-seconds（0.6 core-hours） |
| MPI 校准 | 同一 4×4×6 输入再跑 1 rank 和 4 ranks，各 ≤900 秒；使用已完成的 2-rank 结果作参照 | 额外 4,500 core-seconds（1.25 core-hours） |
| 有限 k 网格 | 固定通过校准的同一 rank 数，4×4×6、6×6×10、8×8×12 各 ≤900 秒，最多 4 ranks | 至多额外 10,800 core-seconds（3 core-hours） |

上述是分阶段提案，不是已消耗成本，也不代表整批 RPS 预算。每个阶段完成后才由协调端释放下一阶段；每项只有 1 次尝试。粗网格可以复用完全同一设置/rank/runtime 的既有不可变结果，此时不重复预约或声称新执行。若新增初始化、复跑或跨平台对照，必须单独预约并计入追加额度，不能挤进未记录的开销。

每任务建议 12 GiB 进程树 RSS 上限，启动时至少 24 GiB 可用内存；磁盘同时满足 20 GiB 临时空间下限和节点已设置的更高保留线。这些边界可能让资源繁忙的节点暂缓启动，这是有效状态。macOS 的进程树采样/终止不是 Linux cgroup 硬限额，MPI rank 与线程设置也不是 CPU 硬配额：回执必须记录实际约束方式、采样周期、峰值及任何越界，不能声称未实施的隔离。

900 秒是外部执行上限，原始输入的 600 秒引擎上限保持不变。若 QE 按时停止，保留该结果并重新制定输入版本；不得把它改成成功，也不得直接修改原队列输入的时限。执行器需为上传和租约续期另有明确安排，不能把“回执送达”混同成计算在期限内结束。

## 真实完成判据

1. **传输与身份**：输入、原始准备 manifest、全部 UPF、执行文件和 runtime 绑定一致；输出 stdout、stderr、原始 XML、执行回执齐全。初始化结果单独判读，不当作 SCF 收敛。
2. **MPI 数值可复现**：三个 SCF 均由原生 XML/stdout 读出电子收敛；`(max E−min E)/12 ≤1e−7 Ha/atom`，最大 SCF 误差/原子严格低于此阈值。逐原子同一顺序的力分量相对 2-rank 参照最大差 ≤1e−5 Ha/bohr，应力张量分量最大差 ≤1e−6 Ha/bohr³。缺失、非有限值或身份不一致则未完成。这里检查的是 rank 改变的重复性，不是几何已经松弛或力/应力已收敛。
3. **性能校准**：记录墙钟时间、core-seconds、采样峰值和系统状态。每个 rank 只有一次观测，不能据此保证稳定加速比；时间差不明确时优先保留 2 ranks，再安排有预算的重复测试。
4. **有限网格窗口**：同状态、同 runtime、同 rank 数和其他设置；三个 SCF 全部收敛、最大 SCF 误差/原子 `<1e−4 Ha`，能量窗口/12 `≤1e−4 Ha`。只通过本次有限采样检查；截断能、展宽、可观测量和无限网格极限仍未建立。

exit code 0、`JOB DONE`、队列回执已接受都不能单独满足科学判据。缺失、非收敛、终止、资源超限及比较不通过均保留原始证据，并阻止依赖阶段。不能自动重试求解器、放宽阈值、把未知补为零或删掉失败读数。精确对照和所有判据都应在结果到达之前冻结。

此前 VPS 九个 `Mg7AlB16` SCF 均电子收敛，但三组能量窗口 `0.0006334573`、`0.0007494048`、`0.0008587644 Ha/atom` 均超过 `1e−4`。这个结果仍为 k 网格精度未达标。它的组成、原子数和网格不同，不能充当本次 Mini 的跨平台总能量参照或性能加速基线。历史记录见 [VPS pilot](discovery_vps_pilot.md)。

## 操作工具及接口

`scripts/build_sclib_m4_calibration.py` 只读取已经存在的源包，先校验整包所有文件及固定 manifest，再输出新的私有子集和无私有路径的摘要。无网络、无求解器、无队列调用。示例路径自行指定，输出和摘要必须都不存在：

```sh
python3 scripts/build_sclib_m4_calibration.py \
  --source /absolute/private/factorial-v1 \
  --output /absolute/private/m4-parent-calibration-v1 \
  --summary /absolute/new/m4-calibration-v1.json
```

六个 payload 覆盖每个网格的初始化与 SCF，提供 `native.json`、原始 .in、原始准备 .json 和两个完整 UPF 的扁平 basename/hash/size 清单；执行器复制赝势到受控的 `pseudo/`，不改输入。`native.json` 使用 `sclib-native-qe/1`，字段为 `input_name`、`source_manifest_name`、`prefix`、`pseudo_names`。最终 `JobSpec` 的 job_id、deadline、runtime 权限、资源和批准后的 rank 数由协调端另行冻结，不能把提案 JSON 直接当已授权队列任务。

输出固定为 `stdout.txt`（≤8 MiB）、`stderr.txt`（≤1 MiB）、`data-file-schema.xml`（≤8 MiB）、`execution.json`（≤128 KiB）。超出或缺失必须显式处理，不能静默截断后按完整成功返回。原始输出经现有严格原生 reader 独立检查后，才进入上述比较。

此轮通过后，按计划开展零应变的母体、Al、C、Al+C 四态，再扩展应变。跨组成不直接按绝对总能量排序；使用已收敛的共同可观测量及相应物理参照。现有 103 项材料的评级只因真实新增证据而更新，不能因硬件上线或 SCF 完成统一加分。
