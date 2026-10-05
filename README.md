# 百里画廊沿线共益运营

把道路节点、财政公共设施、村集体院落、季节性摊位、民宿导流、农产品寄售、
志愿班次、就业承诺、生态容量、维修工单与收益分配，纳入**持续可审计的运营关系**：
许可到期不沉淀、导流贡献有证据、退货坏账归实际参与方、暴雨检修超载精准暂停且
照护已入住旅客、季度公示四板块分开、运营商退出必须先完成交割清单。

## 核心约定

- **事件流即账本**：`event_id` 唯一，`aggregate_id + version` 递增，
  `occurred_at` 保留真实发生时间，重试沿用原事件标识，重放幂等。
- **四个跨村交换边界**：`shared_asset`、`operating_term`、
  `community_contribution`、`benefit_distribution`（公共标识，只增不改）；
  摊位、寄售、导流、志愿、就业、容量、暂停、工单、公示、交割为村内经营对象。
- **业务字段统一在 `payload`**，结构由事件目录单一来源声明。

## 目录

- `src/catalog.py`：事件目录（44 个事件 / 14 类聚合），契约唯一事实来源。
- `src/validator.py`：信封与载荷静态校验（含季节许可 ≤180 天等跨字段规则）。
- `src/audit.py`：持续审计投影，折叠事件流并返回中文违规项。
- `src/handover.py`：退出交割清单构建（库存/预付款/设备/工单/导流/就业/数据）。
- `src/schema_render.py`：从目录渲染 `contracts/domain.schema.json`。
- `src/scenarios.py`：合规全季日志与 11 类违规片段（同时导出联调样例）。
- `src/report.py`：命令行独立审计入口。
- `contracts/domain.schema.json`：渲染出的 JSON Schema 契约。
- `data/sample.json`：最小跨村边界样例；`data/sample_season.json`：完整旺季样例。
- `docs/共益运营系统设计.md`：对账问题对照、对象模型、不变量与流程说明。
- `tests/`：契约、审计不变量、交割清单共 34 项测试。

## 本地检查

```bash
python3 -m unittest discover -s tests      # 全部测试
python3 -m src.scenarios                   # 重新生成 data/sample_season.json
python3 -m src.schema_render               # 重新生成 JSON 契约
python3 -m src.report data/sample_season.json   # 独立复算任一事件日志
```
