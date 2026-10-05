# 山地驿站共益运营

本项目保存"山地驿站共益运营"领域中跨机构交换记录的基础约定，并提供一套可运行的共益运营系统：把道路节点、公共设施、村集体院落、季节性摊位、民宿导流、寄售交易、志愿班次、就业承诺、生态容量、维修工单与分配结果放进同一本持续可审计的事件账。

## 领域资料

- `contracts/domain.schema.json`：事件信封与本领域允许的聚合、事件类型（跨村交换边界）。
- `src/events.py`：每个事件类型与聚合的绑定及 payload 必备字段。
- `src/store.py`：追加式事件存储，重试幂等、版本连续，可导出 JSONL 离线审计。
- `src/state.py`：由事件回放得到的状态投影，可随时清空重建。
- `src/system.py`：全部业务命令与守卫。
- `src/disclosure.py`：季度公示（四栏分列）。
- `src/exit.py`：退出交割清单。
- `data/sample.json`：一条可用于本地联调的中文样例。
- `examples/year_end_close.py`：年底对账全流程演示。
- `tests/`：行为测试与公共字段约定。

事件由 `event_id` 唯一标识，`aggregate_id` 指向业务对象，`version` 从 1 开始递增，`occurred_at` 保留真实发生时间。来源系统重试时必须沿用原事件标识：同标识同内容幂等返回，同标识不同内容直接拒绝。

## 领域对象与聚合映射

四类聚合是跨村交换边界，不得新增；所有领域对象都落在其上：

| 领域对象 | 聚合 | 说明 |
| --- | --- | --- |
| 道路节点、公共设施、集体院落、季节摊位 | `shared_asset` | 连同生态容量、设备、维修工单、精准暂停 |
| 经营许可（授予/续期/到期/腾退）、退出交割 | `operating_term` | 许可到期即失效，等待腾退，不沉淀为永久占用 |
| 既有承诺、民宿导流、志愿班次、就业兑现、寄售流水 | `community_contribution` | 导流与志愿必须附证据 |
| 季度公示、分配结果 | `benefit_distribution` | 分配不得超出已公示的可分配总额 |

## 关键规则与实现位置

| 需求 | 机制 | 位置 |
| --- | --- | --- |
| 许可到期不能沉淀成永久占用 | 到期即拒绝经营；未腾退前不得重复授予；到期未腾退列入公示 | `system._require_active_term`、`grant_term`、`expire_due_terms`、`disclosure` |
| 导流贡献必须有证据 | 导流/志愿/就业兑现无证据直接拒绝 | `record_referral`、`record_volunteer_shift`、`record_employment` |
| 退货与坏账只归实际参与方 | 库存按（资产、运营商、供货方、品类）归集；退货坏账从原成交单取参与方，公示单列归集 | `sell_consignment`、`return_consignment`、`write_off_bad_debt`、`disclosure.退货坏账归集` |
| 暴雨/检修/超载精准暂停 | 按资产暂停，未受影响资产照常；容量满员即拒新承诺 | `suspend_assets`、`declare_capacity`、`register_commitment` |
| 照顾已入住旅客的既有承诺 | 暂停事件显式列入保护清单，履约与退订照常，仅拦新单 | `suspend_assets`（protected_commitments）、`fulfill_commitment` |
| 财政设施维修有人认领 | 工单开立必须指定责任方，完工登记费用与分摊 | `open_work_order`、`close_work_order` |
| 季度公示四栏分列 | 公共资产使用、维修负担、就业兑现、可分配收益各自独立；非货币贡献不混入金额 | `publish_disclosure` |
| 退出不得悄悄带出 | 交割清单由账本计算，未清库存/预付款/设备/数据责任未清结则退出被拦；实物事项不可凭口头核销 | `request_exit`、`exit_checklist`、`clear_exit_item`、`confirm_exit` |

## 本地检查

运行 `python3 -m unittest discover -s tests`。

演示年底对账全流程：`python3 examples/year_end_close.py`。
