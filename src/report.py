"""命令行审计入口：独立复算事件日志。

用法：
    python3 -m src.report data/sample_season.json
    python3 -m src.report data/sample_season.json --handover term-yunshu-2026

输出中文审计结论：违规清单、寄售/导流/维修/就业投影、交割清单摘要。
不依赖任何运营商自报数据——只认事件流。
"""

import argparse
import json
import sys

from src.audit import audit
from src.validator import validate_event

YUAN = lambda cents: f"{cents / 100:.2f}元"  # noqa: E731


def _load(path: str) -> list[dict]:
    events = json.loads(open(path, encoding="utf-8").read())
    if isinstance(events, dict):
        return [events]
    return events


def report(events: list[dict]) -> str:
    lines: list[str] = []

    envelope_errors = [(e.get("event_id"), validate_event(e)) for e in events]
    envelope_errors = [(eid, msgs) for eid, msgs in envelope_errors if msgs]
    if envelope_errors:
        lines.append("一、信封校验：不通过")
        for eid, msgs in envelope_errors:
            for msg in msgs:
                lines.append(f"  - {eid}：{msg}")
        lines.append("（信封不合法的事件不进入业务审计）")
        events = [e for e in events if not validate_event(e)]

    state = audit(events)
    lines.append(f"审计事件 {len(events)} 条，覆盖 {len(state['assets'])} 项资产、"
                 f"{len(state['terms'])} 个许可、{len(state['batches'])} 个寄售批次、"
                 f"{len(state['repairs'])} 张维修工单。")

    lines.append("")
    lines.append("一、合规结论")
    if not state["violations"]:
        lines.append("  未发现违规。所有经营关系可由事件流逐笔复算。")
    else:
        lines.append(f"  发现 {len(state['violations'])} 项违规：")
        for v in state["violations"]:
            lines.append(f"  - [{v['code']}] {v['message']}（事件：{v['event_id']}）")

    lines.append("")
    lines.append("二、维修负担")
    if not state["repairs"]:
        lines.append("  （无工单）")
    for rid, order in state["repairs"].items():
        status = "完工" if order["completed"] else "未完工"
        claimant = order["claimed_by"] or "无人认领"
        shares = "、".join(f"{s['party_id']} {YUAN(s['share_cents'])}"
                          for s in order["borne_by"]) or "未分摊"
        lines.append(f"  - {rid}：{order['fault']}｜{status}｜认领：{claimant}｜"
                     f"费用 {YUAN(order['cost_cents'])}（{shares}）")

    lines.append("")
    lines.append("三、寄售与坏账归责")
    for bid, b in state["batches"].items():
        lines.append(
            f"  - {bid}：交付{b['delivered']} 售{b['sold']} 退{b['returned']}｜"
            f"应付农户 {YUAN(b['sold_proceeds'] - b['commission_total'] - b['supplier_borne_bad_debt'])}｜"
            f"销售方坏账 {YUAN(b['seller_borne_bad_debt'])}（不扣农户）｜"
            f"{'已结清' if b['settled'] else '未结清'}")

    lines.append("")
    lines.append("四、导流证据")
    for rid, r in state["referrals"].items():
        lines.append(f"  - {rid}：{r['source_village']}→{r['target_village']}｜"
                     f"{r['status']}｜证据 {r['evidence_ref']}")

    lines.append("")
    lines.append("五、就业承诺兑现")
    for p in state["pledges"]:
        lines.append(
            f"  - {p['term_id']}：承诺{p['positions_total']}岗（本地≥{p['local_min']}）｜"
            f"兑现{p['hires_total']}岗（本地{p['hires_local']}）｜"
            f"{'已提交工资凭证' if p['reported'] else '未提交凭证'}")

    if state["handovers_by_term"]:
        lines.append("")
        lines.append("六、在途退出交割")
        for tid, ho in state["handovers_by_term"].items():
            resolved = state["resolved_blockers"].get(ho["handover_id"], set())
            open_items = [b["blocker_id"] for b in ho["checklist"]["blockers"]
                          if b["blocker_id"] not in resolved]
            lines.append(f"  - {tid}（交割单 {ho['handover_id']}）："
                         f"阻断项共 {len(ho['checklist']['blockers'])} 项，"
                         f"待清偿 {len(open_items)} 项")
            for bid_id in open_items:
                detail = next(b["detail"] for b in ho["checklist"]["blockers"]
                              if b["blocker_id"] == bid_id)
                lines.append(f"      · {bid_id}：{detail}")
    if state["pending_handovers"]:
        lines.append("")
        lines.append("六（补）、已提出退出但交割清单尚未正式确认——相关资产款项处于冻结")
        for tid in state["pending_handovers"]:
            lines.append(f"  - {tid}：清单确认前设备/货物/预付款一律不得离场")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="共益运营事件流独立审计")
    parser.add_argument("log", help="事件日志 JSON 文件（单事件或数组）")
    args = parser.parse_args(argv)
    events = _load(args.log)
    print(report(events))
    return 0


if __name__ == "__main__":
    sys.exit(main())
