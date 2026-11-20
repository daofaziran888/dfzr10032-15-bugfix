"""端到端验证：文化馆改版场景的全部判定规则。用 python3 -I 运行。"""
from __future__ import annotations

import json
import os
import sys

# 隔离模式(-I)不自动注入当前目录，显式加入脚本所在的 backend 目录以便导入 app。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.store import store
from app.services.content_diff import service, SNAPSHOT_TABLE, DIFF_TABLE, EVENT_TABLE
from app.services import content_diff_engine as engine

failures: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" -> {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


snapshots = store.rows(SNAPSHOT_TABLE)
diffs = store.rows(DIFF_TABLE)
events = store.rows(EVENT_TABLE)

# 1. 快照与缺页区间
check("装配4张采集快照", len(snapshots) == 4, len(snapshots))
s2 = next(s for s in snapshots if s["snapshot_no"] == "SNAP-0002")
check("缺页快照标出缺失页次", s2["missing_pages"] == [2], s2["missing_pages"])
check("缺页区间压缩为[[2,2]]", s2["missing_ranges"] == [[2, 2]], s2["missing_ranges"])
s3 = next(s for s in snapshots if s["snapshot_no"] == "SNAP-0003")
check("补采快照无缺失页次", s3["missing_pages"] == [] and s3["refetch_of"] == "SNAP-0002")
check("页脚/栏目导航被排除", any(h["selector"] == "footer.site-footer" for h in s3["excluded_hits"])
      and any(h["selector"] == "nav.column-nav" for h in s3["excluded_hits"]), s3["excluded_hits"])

# 2. 第一条判定：缺页挂起，不算删除
d1 = next(d for d in diffs if d["old_snapshot_no"] == "SNAP-0001" and d["new_snapshot_no"] == "SNAP-0002")
check("缺页对比状态=待补采", d1["status"] == "待补采", d1["status"])
check("缺页对比不产生任何改动结论", d1["change_count"] == 0 and d1["changes"] == [])
check("缺页对比不产生变化事件", not [e for e in events if e["diff_id"] == d1["id"]])
check("挂起记录保留缺失区间", d1["new_missing_ranges"] == [[2, 2]], d1["new_missing_ranges"])

# 3. 第二条判定：补采后重算
d2 = next(d for d in diffs if d["old_snapshot_no"] == "SNAP-0001" and d["new_snapshot_no"] == "SNAP-0003")
check("补采后判定=已判定", d2["status"] == "已判定", d2["status"])
kinds = {c["kind"] for c in d2["changes"]}
check("命中迁移+更正(moved-modified)", "moved-modified" in kinds, kinds)
check("命中正文更正(modified)", "modified" in kinds, kinds)
check("没有把段落误判为deleted", "deleted" not in kinds, kinds)
mm = next(c for c in d2["changes"] if c["kind"] == "moved-modified")
check("闭馆通知从公告正文迁入通知栏",
      mm["old_segment"]["region"] == "公告正文" and mm["new_segment"]["region"] == "通知栏"
      and mm["old_segment"]["page"] == 1 and mm["new_segment"]["page"] == 1)
check("迁移段落携带抓取页次", mm["old_segment"]["page"] == 1 and mm["new_segment"]["page"] == 1)

# 4. 跨版核对 / 新跟踪交代
check("公告正文可跨版核对", d2["cross_version_regions"] == ["公告正文"], d2["cross_version_regions"])
check("通知栏从当次开始跟踪", d2["new_track_regions"] == ["通知栏"], d2["new_track_regions"])
trackings = {c["tracking"] for c in d2["changes"]}
check("改动均标注核对口径", trackings <= {"cross-version", "new-track"}, trackings)

# 5. 变化事件：旧/新节选 + 两次采集时间 + 日期
d2_events = [e for e in events if e["diff_id"] == d2["id"]]
check("判定记录段落改动全部写成事件", len(d2_events) == d2["change_count"], (len(d2_events), d2["change_count"]))
for e in d2_events:
    check(f"事件{e['event_no']}关联两次采集时间",
          bool(e["old_captured_at"]) and bool(e["new_captured_at"])
          and e["old_snapshot_id"] and e["new_snapshot_id"])
date_events = [e for e in d2_events if e["date_changed"]]
check("识别出两处开放日期变更", len(date_events) == 2, [(e["event_no"], e["old_dates"], e["new_dates"]) for e in date_events])
closure = next(e for e in date_events if e["region_new"] == "通知栏")
check("闭馆日期更正可查回两次抓取文字",
      "2026年11月20日" in closure["old_excerpt"] and "2026年11月21日" in closure["new_excerpt"],
      (closure["old_excerpt"], closure["new_excerpt"]))
reopen = next(e for e in date_events if e["region_new"] == "公告正文")
check("恢复开放日期更正可查回", "2026年12月1日" in reopen["old_excerpt"] and "2026年12月3日" in reopen["new_excerpt"])
check("日期事件默认待通知/按场景置状态", set(e["notify_status"] for e in date_events) <= {"待通知", "前台已确认"})

# 6. 通知流转
target = next(e for e in date_events if e["notify_status"] == "待通知")
updated, msg = service.notify_event(target["id"], "通知前台")
check("待通知->已通知前台", updated is not None and updated["notify_status"] == "已通知前台", msg)
updated2, msg2 = service.notify_event(target["id"], "前台确认")
check("已通知->前台已确认", updated2 is not None and updated2["notify_status"] == "前台已确认", msg2)
blocked, msg3 = service.notify_event(target["id"], "通知前台")
check("重复通知被拦截", blocked is None, msg3)
# d2 的两处改动都涉及日期，单独构造一条非日期事件验证通知拦截。
non_date = {
    "id": service._next_id(events),
    "event_no": "EVT-TEST-01", "diff_id": d2["id"], "kind": "modified",
    "tracking": "cross-version", "region_old": "公告正文", "region_new": "公告正文",
    "page_old": 1, "page_new": 1, "old_excerpt": "咨询电话：0571-88888000",
    "new_excerpt": "咨询电话：0571-88889999", "old_dates": [], "new_dates": [],
    "date_changed": False, "notify_status": "无需通知",
    "old_captured_at": d2["old_captured_at"], "new_captured_at": d2["new_captured_at"],
    "old_snapshot_id": d2["old_snapshot_id"], "new_snapshot_id": d2["new_snapshot_id"],
}
events.append(non_date)
blocked2, msg4 = service.notify_event(non_date["id"], "通知前台")
check("非日期事件不允许通知", blocked2 is None, msg4)

# 7. 无变化复查不产生事件
d3 = next(d for d in diffs if d["old_snapshot_no"] == "SNAP-0003" and d["new_snapshot_no"] == "SNAP-0004")
check("复查判定=无变化", d3["status"] == "无变化" and d3["change_count"] == 0, d3["status"])
check("复查不产生事件", not [e for e in events if e["diff_id"] == d3["id"]])

# 8. 手工补采流程：登记一张仍缺页的快照，再补采成功重算
new_missing, missing = service.create_snapshot({
    "snapshot_no": "SNAP-0005", "url": "http://www.culture-gov.example/announce",
    "rule_code": "CRAW-0102", "captured_at": "2026-11-20 14:00:00", "page_count": 2,
    "raw_html": '<html><body><!-- 缺页:第1页 --><!-- 缺页:第2页 --></body></html>',
})
check("新缺页快照解析出连续缺失区间", new_missing is not None and new_missing["missing_ranges"] == [[1, 2]],
      new_missing and new_missing["missing_ranges"])
refetched, rmsg = service.refetch_snapshot(new_missing["id"], {
    "captured_at": "2026-11-20 14:40:00",
    "raw_html": store.rows(SNAPSHOT_TABLE)[2]["raw_html"],
})
check("补采成功继承同一规则且无缺页", refetched is not None and refetched["missing_pages"] == []
      and refetched["rule_code"] == "CRAW-0102", rmsg)
rediff, rmsg2 = service.compute_diff(s3["id"], refetched["id"])
check("补采后同选择器重算为无变化", rediff is not None and rediff["status"] == "无变化", rmsg2)

# 9. 不同网址禁止对比
other, _ = service.create_snapshot({
    "snapshot_no": "SNAP-0006", "url": "http://other.example/x", "rule_code": "CRAW-0102",
    "captured_at": "2026-11-20 15:00:00", "raw_html": "<html></html>",
})
cross, cmsg = service.compute_diff(s3["id"], other["id"])
check("跨网址对比被拒绝", cross is None, cmsg)

print("\n事件样例：")
print(json.dumps(closure, ensure_ascii=False, indent=2))
print(f"\n合计 {len(failures)} 项失败" if failures else "\n全部验证通过")
raise SystemExit(1 if failures else 0)
