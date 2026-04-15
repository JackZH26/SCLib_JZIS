# SCLib_JZIS — Materials Database Schema v2
> **Date:** 2026-04-15 | **Author:** Jian Zhou / JZIS
> **Purpose:** Enhanced materials schema + optimization guide for Claude Code
> **Based on:** Night 1-29 SC research + literature analysis (50+ papers)

---

## 一、材料字段完整定义

### 1.1 核心字段（现有，保持不变）

| 字段名 | 类型 | 可提取率 | 说明 |
|--------|------|---------|------|
| `id` | VARCHAR(100) PK | — | 归一化化学式，如 `La3Ni2O7` |
| `formula` | VARCHAR(200) | — | Unicode 化学式，如 `La₃Ni₂O₇` |
| `formula_normalized` | VARCHAR(200) | — | ASCII 化学式，用于查询 |
| `formula_latex` | VARCHAR(200) | — | LaTeX 格式 |
| `family` | VARCHAR(50) | ~90% | 材料族：cuprate / hydride / nickelate / iron_based / topological / 2d_moire / kagome / conventional / other |
| `subfamily` | VARCHAR(100) | ~70% | 如 bilayer_ruddlesden_popper, infinite_layer |
| `tc_max` | REAL | — | 所有记录中最高 Tc（K），汇总字段 |
| `tc_max_conditions` | VARCHAR(300) | — | tc_max 对应的实验条件描述 |
| `tc_ambient` | REAL | — | 常压下最高 Tc（GPa=0），无则 NULL |
| `total_papers` | INTEGER | — | 引用该材料的论文总数 |
| `status` | VARCHAR(50) | — | active_research / confirmed / retracted / disputed |
| `records` | JSONB | — | TcRecord 数组，见 1.3 节 |
| `updated_at` | TIMESTAMPTZ | — | 最后更新时间 |

---

### 1.2 新增字段（v2 扩展）

#### A. 结构信息（可提取率高）

| 字段名 | 类型 | 可提取率 | 说明 | 示例 |
|--------|------|---------|------|------|
| `crystal_structure` | VARCHAR(100) | ~75% | 晶体结构类型 | `I4/mmm`, `Fd-3m` |
| `space_group` | VARCHAR(50) | ~75% | 空间群符号或编号 | `I4/mmm (#139)` |
| `structure_phase` | VARCHAR(50) | ~60% | RP 相标记（对镍基/铜基） | `1212`, `2222`, `1313`, `infinite_layer` |
| `lattice_params` | JSONB | ~40% | 晶格参数（Å）| `{"a": 3.81, "c": 20.5}` |

**structure_phase 说明：**
Ruddlesden-Popper 系列的层堆叠标记，决定能带结构和超导性：
- 镍基：1212/2222（超导）vs 1313（不超导）
- 铜基：214 = La₂CuO₄ 类，123 = YBa₂Cu₃O₇ 类
- infinite_layer = NdNiO₂ 类

---

#### B. 超导参数（可提取率中等，专项论文）

| 字段名 | 类型 | 可提取率 | 说明 | 示例 |
|--------|------|---------|------|------|
| `pairing_symmetry` | VARCHAR(50) | ~70% | 配对对称性 | `d-wave`, `s±`, `s-wave`, `p-wave`, `unknown` |
| `gap_structure` | VARCHAR(50) | ~55% | 能隙结构 | `full_gap`, `nodal`, `multi_gap`, `unknown` |
| `Hc2_tesla` | REAL | ~65% | 上临界场（Tesla），0 GPa 时 | `150.0` |
| `Hc2_conditions` | VARCHAR(200) | ~65% | Hc2 对应条件 | `@0K, H∥c` |
| `lambda_eph` | REAL | ~40% | 电声耦合强度 λ | `2.13` |
| `omega_log_K` | REAL | ~35% | 对数平均声子频率（K） | `1200.0` |
| `rho_s_meV` | REAL | ~30% | 超流密度 ρ_s（meV）| `45.0` |

**注意：** lambda/omega_log 仅在 DFT/Eliashberg 计算类论文中出现（约占 10-15%），优先从标题含 "first-principles", "DFT", "Eliashberg", "Allen-Dynes" 的论文提取。

---

#### C. 竞争序与正常态（可提取率中等）

| 字段名 | 类型 | 可提取率 | 说明 | 示例 |
|--------|------|---------|------|------|
| `T_CDW_K` | REAL | ~60% | 电荷密度波转变温度（K） | `92.0` |
| `T_SDW_K` | REAL | ~55% | 自旋密度波转变温度（K） | `140.0` |
| `T_AFM_K` | REAL | ~60% | 反铁磁转变温度（K） | `300.0` |
| `rho_exponent` | REAL | ~50% | 正常态电阻率指数 n，ρ∝Tⁿ | `1.0` (NFL/Planckian), `2.0` (FL) |
| `competing_order` | VARCHAR(100) | ~65% | 主要竞争序描述 | `CDW`, `AFM`, `SDW+CDW`, `Mott_insulator` |

**rho_exponent 物理意义：**
- n=1：Planckian/非费米液体（NFL），如铜氧化物最优掺杂
- n=2：费米液体（FL），常规金属
- n 介于 1-2：量子临界区间
- 与我们 Night 14-16 的 Planckian 散射研究直接对应

---

#### D. 样品与合成信息（NIMS 已有，扩展）

| 字段名 | 类型 | 可提取率 | 说明 | 示例 |
|--------|------|---------|------|------|
| `ambient_SC` | BOOLEAN | ~90% | 常压（0 GPa）下是否超导 | `true` / `false` |
| `pressure_type` | VARCHAR(50) | ~70% | 压力类型 | `hydrostatic`, `uniaxial`, `chemical`, `none` |
| `sample_form` | VARCHAR(50) | ~85% | 样品形态（已有，扩展枚举）| `single_crystal`, `polycrystal`, `thin_film`, `powder`, `wire` |
| `substrate` | VARCHAR(100) | ~80% | 薄膜基底（对薄膜样品）| `SrTiO₃ (STO)`, `LaAlO₃ (LAO)`, `SLAO` |
| `doping_type` | VARCHAR(50) | ~65% | 掺杂类型 | `hole`, `electron`, `isovalent`, `none` |
| `doping_level` | REAL | ~60% | 掺杂量 x（归一化） | `0.16` |

---

#### E. 布尔标志字段（推断或 NER）

| 字段名 | 类型 | 可提取率 | 说明 |
|--------|------|---------|------|
| `is_topological` | BOOLEAN | ~70% | 是否有拓扑超导特征 |
| `is_unconventional` | BOOLEAN | ~80% | 是否非常规超导（非 BCS 声子） |
| `has_competing_order` | BOOLEAN | ~85% | 是否存在竞争序 |
| `is_2D_or_interface` | BOOLEAN | ~90% | 是否为二维/界面超导 |
| `retracted` | BOOLEAN | — | 是否撤稿 |
| `disputed` | BOOLEAN | — | 数据是否存在争议（如 Dias 案） |

---

### 1.3 TcRecord 结构（JSONB records 数组）

每个 record 代表一篇论文中的一次测量：

```json
{
  "tc_kelvin": 80.0,
  "tc_type": "onset",
  "pressure_gpa": 14.0,
  "pressure_type": "hydrostatic",
  "measurement": "resistivity",
  "sample_form": "single_crystal",
  "substrate": null,
  "doping": null,
  "structure_phase": "1212",
  "pairing_symmetry": "s±",
  "Hc2_tesla": 150.0,
  "competing_order": "SDW",
  "paper_id": "arxiv:2306.07275",
  "year": 2023,
  "verified": true,
  "confidence": 0.95,
  "notes": "First report"
}
```

---

## 二、PostgreSQL Schema 变更

```sql
-- 新增列（在现有 materials 表上 ALTER TABLE）
ALTER TABLE materials
  ADD COLUMN crystal_structure VARCHAR(100),
  ADD COLUMN space_group VARCHAR(50),
  ADD COLUMN structure_phase VARCHAR(50),
  ADD COLUMN lattice_params JSONB,
  ADD COLUMN pairing_symmetry VARCHAR(50),
  ADD COLUMN gap_structure VARCHAR(50),
  ADD COLUMN Hc2_tesla REAL,
  ADD COLUMN Hc2_conditions VARCHAR(200),
  ADD COLUMN lambda_eph REAL,
  ADD COLUMN omega_log_K REAL,
  ADD COLUMN rho_s_meV REAL,
  ADD COLUMN T_CDW_K REAL,
  ADD COLUMN T_SDW_K REAL,
  ADD COLUMN T_AFM_K REAL,
  ADD COLUMN rho_exponent REAL,
  ADD COLUMN competing_order VARCHAR(100),
  ADD COLUMN ambient_SC BOOLEAN,
  ADD COLUMN pressure_type VARCHAR(50),
  ADD COLUMN doping_type VARCHAR(50),
  ADD COLUMN doping_level REAL,
  ADD COLUMN is_topological BOOLEAN DEFAULT FALSE,
  ADD COLUMN is_unconventional BOOLEAN,
  ADD COLUMN has_competing_order BOOLEAN DEFAULT FALSE,
  ADD COLUMN is_2D_or_interface BOOLEAN DEFAULT FALSE,
  ADD COLUMN retracted BOOLEAN DEFAULT FALSE,
  ADD COLUMN disputed BOOLEAN DEFAULT FALSE;

-- 新增索引
CREATE INDEX idx_materials_pairing ON materials(pairing_symmetry);
CREATE INDEX idx_materials_phase ON materials(structure_phase);
CREATE INDEX idx_materials_ambient ON materials(ambient_SC) WHERE ambient_SC = TRUE;
CREATE INDEX idx_materials_unconventional ON materials(is_unconventional) WHERE is_unconventional = TRUE;

-- 自动填充 ambient_SC（从 records 推断）
-- 可在入库时计算：若 records 中存在 pressure_gpa=0 的记录，则 ambient_SC=true
```

---

## 三、NER 脚本优化建议（给 Claude Code）

### 3.1 当前 NER prompt 问题

当前 `ingestion/ingestion/nims.py` 和 `material_ner.py` 只提取：
- formula, tc_kelvin, tc_type, pressure_gpa, measurement, confidence

**需要扩展为 v2 NER prompt：**

```python
MATERIAL_NER_PROMPT_V2 = """
Extract superconducting material data from this text. Return JSON array only.

For each material found, extract ALL available fields:

REQUIRED:
- formula: chemical formula (e.g., "La3Ni2O7")
- tc_kelvin: critical temperature in Kelvin (null if not stated)
- tc_type: "onset" | "zero_resistance" | "midpoint" | "unknown"
- pressure_gpa: pressure in GPa (0.0 if ambient, null if not stated)
- measurement: "resistivity" | "susceptibility" | "specific_heat" | "muSR" | "unknown"
- confidence: 0.0-1.0

EXTRACT IF PRESENT:
- pairing_symmetry: "d-wave" | "s-wave" | "s±" | "p-wave" | "unknown"
- gap_structure: "full_gap" | "nodal" | "multi_gap" | "unknown"
- crystal_structure: space group or structure type (e.g., "I4/mmm", "Fd-3m")
- structure_phase: RP phase label (e.g., "1212", "2222", "1313", "infinite_layer")
- T_CDW_K: charge density wave temperature in Kelvin
- T_SDW_K: spin density wave temperature in Kelvin
- T_AFM_K: antiferromagnetic transition temperature in Kelvin
- Hc2_tesla: upper critical field in Tesla
- lambda_eph: electron-phonon coupling constant (only from DFT/Eliashberg papers)
- omega_log_K: logarithmic average phonon frequency in Kelvin
- rho_exponent: normal state resistivity exponent n (rho ~ T^n)
- competing_order: "CDW" | "AFM" | "SDW" | "Mott_insulator" | "PDW" | null
- ambient_SC: true if superconducting at 0 GPa
- sample_form: "single_crystal" | "polycrystal" | "thin_film" | "powder"
- substrate: substrate material for thin films
- pressure_type: "hydrostatic" | "uniaxial" | "chemical" | "none"
- is_unconventional: true if explicitly described as unconventional/non-BCS
- disputed: true if results are contested or retraction mentioned

RULES:
- Only extract materials explicitly measured for superconductivity
- Do not invent data not in the text
- Flag Tc > 300K or Tc < 0.01K with confidence < 0.3
- Distinguish experimental measurements from theoretical predictions
- For structure_phase: look for patterns like "1212 phase", "2222 structure",
  "Ruddlesden-Popper n=2", "infinite layer", etc.
- For rho_exponent: look for "T-linear", "T^2", "ρ∝T^n with n=..."
- lambda_eph ONLY if paper explicitly calculates it (DFT/Eliashberg papers)

Return: [{"formula": ..., "tc_kelvin": ..., ...}, ...]
Return [] if no superconducting materials found.

Text:
{text}
"""
```

### 3.2 分类 NER 策略（提高 lambda/omega_log 提取率）

针对不同类型论文用不同 prompt：

```python
def classify_paper_type(title: str, abstract: str) -> str:
    """
    Classify paper to determine which NER extraction mode to use.
    """
    calc_keywords = ["first-principles", "DFT", "density functional",
                     "Eliashberg", "Allen-Dynes", "electron-phonon",
                     "McMillan", "phonon calculation", "ab initio"]
    
    exp_keywords = ["single crystal", "thin film", "polycrystal",
                    "resistivity", "susceptibility", "specific heat",
                    "μSR", "ARPES", "STM", "neutron"]
    
    text = (title + " " + abstract).lower()
    
    calc_score = sum(1 for k in calc_keywords if k.lower() in text)
    exp_score = sum(1 for k in exp_keywords if k.lower() in text)
    
    if calc_score >= 2:
        return "computational"   # → use extended prompt with lambda/omega_log
    elif exp_score >= 2:
        return "experimental"    # → use standard prompt
    else:
        return "theoretical"     # → use minimal prompt
```

### 3.3 结构相识别模式（structure_phase）

```python
STRUCTURE_PHASE_PATTERNS = {
    # Ruddlesden-Popper notation
    r'\b1212\b|\b1212 phase\b': '1212',
    r'\b2222\b|\b2222 phase\b': '2222',
    r'\b1313\b|\b1313 phase\b': '1313',
    r'infinite[- ]layer': 'infinite_layer',
    r'n\s*=\s*1\s+Ruddlesden': 'RP_n1',
    r'n\s*=\s*2\s+Ruddlesden': 'RP_n2',
    r'n\s*=\s*3\s+Ruddlesden': 'RP_n3',
    # Cuprate notation
    r'\bLa214\b|\bLSCO\b': 'cuprate_214',
    r'\bYBCO\b|\bY123\b': 'cuprate_123',
    r'\bBi2212\b|\bBi-2212\b': 'cuprate_2212',
    r'\bHg1201\b|\bHg1212\b|\bHg1223\b': 'cuprate_Hg',
}

def extract_structure_phase(text: str) -> str | None:
    import re
    for pattern, phase in STRUCTURE_PHASE_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return phase
    return None
```

---

## 四、表格优化建议（给 Claude Code）

### 4.1 Materials List 页面（/materials）

**当前：** 只显示 formula, family, tc_max, pressure, year, papers

**优化：**
```
新增列（可选显示，用户可切换）:
- ambient_SC 标志（✅/—）
- pairing_symmetry 徽章（d-wave 蓝色，s± 绿色，s-wave 灰色）
- structure_phase 标签
- 竞争序标志（⚠️ 如果 has_competing_order=true）
- Hc2（如果有）

新增筛选器:
- ambient_SC = true（只看常压超导）
- is_unconventional = true
- pairing_symmetry 多选
- structure_phase 多选
- rho_exponent 范围
- T_CDW 是否存在（竞争序筛选）
```

### 4.2 Material Detail 页面（/materials/{formula}）

**新增 section：**
```
📐 结构信息
  - 空间群、晶格参数、结构相

🔬 超导参数
  - 配对对称性、能隙结构、Hc2、λ（如有）

⚡ 正常态与竞争序
  - ρ∝Tⁿ 指数、T_CDW/T_AFM、竞争序类型

📊 Tc vs 压力 图表
  - 横轴：压力（GPa），纵轴：Tc（K）
  - 数据点来自 records，按 sample_form 颜色区分
```

### 4.3 搜索结果（/search）

**增加语义标签过滤：**
```python
# 在 Vertex AI VS 查询时增加 restricts
restricts = [
    {"namespace": "pairing_symmetry", "allow_list": ["d-wave"]},
    {"namespace": "ambient_SC", "allow_list": ["true"]},
]
```

---

## 五、Alembic Migration 脚本

```python
# alembic/versions/002_materials_v2_schema.py
"""Add v2 material fields

Revision ID: 002
Down revision: 001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def upgrade():
    op.add_column('materials', sa.Column('crystal_structure', sa.String(100)))
    op.add_column('materials', sa.Column('space_group', sa.String(50)))
    op.add_column('materials', sa.Column('structure_phase', sa.String(50)))
    op.add_column('materials', sa.Column('lattice_params', JSONB))
    op.add_column('materials', sa.Column('pairing_symmetry', sa.String(50)))
    op.add_column('materials', sa.Column('gap_structure', sa.String(50)))
    op.add_column('materials', sa.Column('Hc2_tesla', sa.Float))
    op.add_column('materials', sa.Column('Hc2_conditions', sa.String(200)))
    op.add_column('materials', sa.Column('lambda_eph', sa.Float))
    op.add_column('materials', sa.Column('omega_log_K', sa.Float))
    op.add_column('materials', sa.Column('rho_s_meV', sa.Float))
    op.add_column('materials', sa.Column('T_CDW_K', sa.Float))
    op.add_column('materials', sa.Column('T_SDW_K', sa.Float))
    op.add_column('materials', sa.Column('T_AFM_K', sa.Float))
    op.add_column('materials', sa.Column('rho_exponent', sa.Float))
    op.add_column('materials', sa.Column('competing_order', sa.String(100)))
    op.add_column('materials', sa.Column('ambient_SC', sa.Boolean))
    op.add_column('materials', sa.Column('pressure_type', sa.String(50)))
    op.add_column('materials', sa.Column('doping_type', sa.String(50)))
    op.add_column('materials', sa.Column('doping_level', sa.Float))
    op.add_column('materials', sa.Column('is_topological', sa.Boolean, server_default='false'))
    op.add_column('materials', sa.Column('is_unconventional', sa.Boolean))
    op.add_column('materials', sa.Column('has_competing_order', sa.Boolean, server_default='false'))
    op.add_column('materials', sa.Column('is_2D_or_interface', sa.Boolean, server_default='false'))
    op.add_column('materials', sa.Column('retracted', sa.Boolean, server_default='false'))
    op.add_column('materials', sa.Column('disputed', sa.Boolean, server_default='false'))

    # Backfill ambient_SC from records
    op.execute("""
        UPDATE materials
        SET ambient_SC = EXISTS (
            SELECT 1 FROM jsonb_array_elements(records) r
            WHERE (r->>'pressure_gpa')::float = 0.0
              AND r->>'tc_kelvin' IS NOT NULL
        )
    """)

    # Indexes
    op.create_index('idx_materials_pairing', 'materials', ['pairing_symmetry'])
    op.create_index('idx_materials_phase', 'materials', ['structure_phase'])

def downgrade():
    cols = [
        'crystal_structure', 'space_group', 'structure_phase', 'lattice_params',
        'pairing_symmetry', 'gap_structure', 'Hc2_tesla', 'Hc2_conditions',
        'lambda_eph', 'omega_log_K', 'rho_s_meV', 'T_CDW_K', 'T_SDW_K', 'T_AFM_K',
        'rho_exponent', 'competing_order', 'ambient_SC', 'pressure_type',
        'doping_type', 'doping_level', 'is_topological', 'is_unconventional',
        'has_competing_order', 'is_2D_or_interface', 'retracted', 'disputed'
    ]
    for col in cols:
        op.drop_column('materials', col)
```

---

## 六、实施优先级

| 优先级 | 任务 | 预计工时 |
|--------|------|---------|
| P0 | 运行 Alembic migration（`alembic upgrade head`）| 5 min |
| P0 | 更新 NER prompt 为 v2 版本 | 1 hr |
| P1 | 添加 paper_type 分类器（computational/experimental） | 2 hr |
| P1 | 添加 structure_phase 正则提取 | 1 hr |
| P1 | 在 /materials 列表页加 ambient_SC 和 pairing 筛选器 | 3 hr |
| P2 | Material detail 页加 Tc vs Pressure 图表 | 4 hr |
| P2 | VS restricts 支持 pairing_symmetry 过滤 | 2 hr |
| P3 | 从 Geisler+ 数据库批量导入 Hc2 数据 | 4 hr |

---

*SCLib_JZIS Materials Schema v2 | 瓦力 | 2026-04-15*
