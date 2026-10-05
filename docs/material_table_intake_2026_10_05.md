# 原始表格热学读数：私有来源录入与待审核关联

材料页已经能展示 Mo 系论文 Table II 的四个原始读数。本次补齐从原始表格包到私有来源记录、材料字段目标、待审核来源关联的操作路径。它解决“单位在行标题、组成在列标题”的来源表达问题。

## 范围与科学边界

| 原文组成 | 电子比热系数 γ | 德拜温度 ΘD |
|---|---|---|
| Mo5P1.1B1.9 | 3.16 mJ/mol-at./K2 | 492 K |
| Mo5PB2 | 3.07 mJ/mol-at./K2 | 501 K |

来源：[arXiv:1603.02892，PDF 第 5 页 Table II](https://arxiv.org/pdf/1603.02892#page=5)。这里沿用已经检查的本地 PDF、提取全文及原始单元格记录；出版版本仍未核验。

- 字段限定为 `electronic_specific_heat_coefficient_source_value`、`debye_temperature_source_value`。
- 数值、单位、组成标题来自原文。保留 `mol-at.` 的计量基准，不换算为每化学式单位，也不借用正文中的不确定度。
- Mo5P1.1B1.9 不自动等同于 Table I 的 Mo5P0.9B2.1 或精修组成 Mo5P1.07(4)B1.93(4)。比较文献的 Mo5SiB2、W5SiB2 列不进入本次包。
- 哈希与位置检查证明所选文字一致。文本表格的行列安排仍是声明，需要对照原 PDF；它不能证明物理样品、相、压力或实验状态一致。
- 材料目标和来源关联都属于待审核记录。现有正式字段审核只覆盖三个 Tc 相关字段，本次没有扩展 γ/ΘD 的独立科学批准流程。
- 不修改材料规范值，不批准公开科学数据或 ML 训练，不执行生产数据库写入。

## 三层实现

1. `source-expression-package/2.2.0` 采用显式 `material-table-field/1.0.0` profile。包中保留原始 UTF-8 字节、完整矩形单元格位置、选中行列和每个跨度的 SHA256。
2. Python、PostgreSQL 和浏览器独立核对：组成来自选中列标题，数值来自同一交叉单元格，属性 cue 和单位来自该行标题；定位编号与选择一致。最多 16 列、32 行，来源窗口最多 4096 个 Unicode 码点。
3. `material-field-case/1.2.0` 把来源提议关联到确切的材料保留记录指纹。源、目标、提议是分开的操作；预览不写入，保存需要固定的预览哈希。旧正文 2.1 / 字段案例 1.1 不会读入这些记录。

接口沿用默认关闭的 `SOURCE_PROPERTY_PENDING_ENABLED`、既有身份验证、curator 权限、请求来源保护和私有缓存策略；没有新增权限或自动公开入口。

数据库变更为 `0091_material_table_fields`。已有 0083/0084/0086 的函数定义保持原样，新增表格校验和显式分派。空表格历史可回滚；有表格包或表格目标历史时拒绝破坏性回滚。

## 生成可选择的本地文件

`scripts/prepare_material_table_package.py` 只读取本地文件。它先核对原始 PDF SHA256、提取全文 SHA256，以及表格在全文中的原始窗口，再构造来源包。输出文件独占创建，权限 0600，不覆盖现有文件。

```bash
python scripts/prepare_material_table_package.py \
  --capture docs/data/materials-thermal-table-capture-2026-10-05.json \
  --metadata /private/path/source-metadata.json \
  --source-parent /private/path/1603.02892.pdf \
  --source-text /private/path/1603.02892.raw.txt \
  --source-text-sha256 cad135f61877a5c6ef43162ec5276992efd5c1df24e6455b7fa80a9990885122 \
  --formula Mo5P1.1B1.9 --formula Mo5PB2 \
  --output /private/path/table-package.json
```

metadata 使用既有来源协议的封闭对象：`source_id`, `url`, `kind`, `content_kind`, `revision`, `revision_status`, `original_parent_sha256`, `parent_hash_status`, `rights_status`, `currentness`, `captured_at`。无法核实的出版版本、权利和当前性应保留为 unresolved；包不会替操作者补造这些声明。

这份已核验本地来源的 PDF SHA256 为 `e132a511543478639f01bf06f43bd7f4d4d1ef4d29415e2024b1a5b1f8747c3e`，表格窗口为全文的 `[18837, 19127)`，表格文本 SHA256 为 `2138d37a234d510afdc05be03601afabf233585dfef9a66f04c4fb168b0ddc1c`。这些是完整性标识，不是论文真实性或科学结论的认证。

## 页面操作

页面：`/dashboard/research/material-table-fields`，工作区导航名称为 **Table source review**。

1. 若要提出材料关联，先加载目标 Material ID 和确切的保留记录序号；核对原有结果与组成。
2. 选择表格 JSON。页面在本地校验原始文本及行列关联，显示全部读数、单位和位置；选择文件不会触发保存。
3. 预览来源导入，再保存。来源包含多个读数，界面说明读数数量，不将其当作独立实验数。
4. 选择 γ 或 ΘD 字段，创建并保存待审核字段目标。
5. 读取已保存的来源、检查确切表达，再读取字段目标。核对列标题组成与材料记录，明确是否提出论文 ID 关联。
6. 预览并保存来源提议。查看当前状态和历史；来源更新、权限撤销、目标指纹变化等会阻止旧表达作为当前关联值展示。

保存结果不明时，当前浏览器标签仅保留 actor、请求/预览/回执哈希等最小恢复标识。通过原请求的 GET outcome 查询确认，禁止自动重发 POST。源全文、记录内容和 token 不存入恢复标识。身份变化清除页面私有内容，未确认的恢复标识保持待处理。

## 验收与后续

- 原始 Table II 四条读数的 Python / SQL / TypeScript 投影一致。
- 错列、错行单位、错误单元格、错误定位、伪造跨度、不规则网格及额外授权字段会被拒绝。
- API 验证默认关闭、身份/权限、预览回滚、保存/重放、旧 profile 隔离、当前来源更换与权限撤销后的保留处理。
- 旧协议函数及材料科学表保持不变；验证 0091 空历史回滚和非空历史拒绝回滚。
- 浏览器验证真实本地文件选择、原始读数显示、预览/保存，以及 320px 可用性。浏览器 API 使用明确标为 synthetic 的本地验收环境；数据库行为另外在一次性 PostgreSQL 中验证。

下一步需要为这些热学字段建立正式的独立科学审核标准与有效值展示规则，核实论文版本和样品状态，再决定是否进入材料规范字段。不能从当前提议数量推断审核完成、实验独立性或训练可用性。
