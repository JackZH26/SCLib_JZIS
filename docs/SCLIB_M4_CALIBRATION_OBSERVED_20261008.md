# M4 首轮真实任务与 MPI 校准结果

2026-10-08，Jian Zhou，JZ Institute of Science。

研究 VPS 下发、Mini 专用账号执行、完整结果回传及独立原生读取已实际完成。固定 Mg₄B₈ 输入的 1、2、4 MPI ranks 均电子收敛，并通过事先冻结的能量、力和应力一致性检查。[机读观测与回执摘要](data/discovery-batches-20261008/m4-calibration-observed-v1.json)保存实测值和证据哈希；[原始校准方案](SCLIB_M4_CALIBRATION_20261008.md)及 prepared snapshot 保持原样。

## 实测范围

原生 adapter 来源为 `75d8e56768d8101b6da9926d1a21ccf90b9abf6d`，QE 7.5，QEXSD 25.05.21。12 原子 Mg₄B₈ 固定坐标、0% 均匀线性应变，PBE PAW，60/480 Ry，4×4×6 网格，MV 0.02 Ry，电子阈值 1e−10 Ry。三个 SCF 的五份输入逐字节相同，每 rank 与 BLAS 均单线程，每次只有一个重任务。输入、UPF、runtime、返回文件和队列回执均绑定核验。

初始化单独读取为 `initialization_only`：进程退出码 0，XML 状态码 255，零 SCF 步骤及空物理观测。它不参与下列 SCF 比较。

| MPI ranks | 求解器 wall time (s) | 采样进程树峰值 RSS (GiB) | SCF 步数 |
|---:|---:|---:|---:|
| 1 | 377.03 | 0.465 | 14 |
| 2 | 199.67 | 0.480 | 12 |
| 4 | 246.00 | 0.536 | 14 |

本次暂选 2 ranks 作为后续基线；每个 rank 只有一次观测，迭代次数也不同，这不是普遍的加速比或最优并行度证明。RSS 是采样峰值，rank×wall 是分配量代理，不是实测 CPU 时间或完整 RPS。

## 事前阈值与实际结果

| 比较量 | 实际 | 预设边界 |
|---|---:|---:|
| 能量窗口 / 原子 (Ha) | 3.941143707682689e−12 | ≤1e−7 |
| 最大 SCF 误差 / 原子 (Ha) | 7.957364286940383e−13 | <1e−7 |
| 力分量最大差 (Ha/bohr) | 2.4914198309862027e−7 | ≤1e−5 |
| 应力分量最大差 (Ha/bohr³) | 2.3194743181690405e−8 | ≤1e−6 |

力和应力以同原子顺序、同坐标系的 2-rank 结果为参照。缺失值、非收敛或身份不符不能进入通过结果。

B、Mg UPF 已追加独立来源核验，与 [QE B 官方文件列表](https://pseudopotentials.quantum-espresso.org/legacy_tables/ps-library/b)及 [Mg 官方文件列表](https://pseudopotentials.quantum-espresso.org/legacy_tables/ps-library/mg)下载文件完全匹配。许可依据为 [PSlibrary 维护者集合级声明](https://github.com/dalcorso/pslibrary/blob/master/AAREADME)的 GPL-2.0-or-later；文件本身没有单独许可字段。来源补充记录不回写旧 manifest 的当时状态，也不证明赝势精度。

## 后续放行边界

本 campaign 已保守预留 6,780/7,200 核秒（包括此前 120 核秒通讯测试），剩余 420；不会按较短的实测 wall time 自动退还预留或放行新 SCF。更密网格先核验初始化与资源需求，再冻结预算。当前 600 秒引擎与 900 秒外部上限能否完成更密网格尚未建立；需要延长时必须建立明确的新输入/资源协议版本。

此结果只支持当前固定输入的端到端运行与 MPI 重现性。更密网格、跨机器同算例、完整故障与生命周期测试及连续 24 小时观察仍待完成。结构稳定性、声子、Tc、候选评级和新材料发现均未由本轮计算建立。原始输出、失败记录、独立读取及来源回执另行保留。
