"""正文变动判定业务规则。

承载四件事：
1. 采集快照登记（同一网址连续采集），缺页在原始响应里标出缺失区间。
2. 用连续两个快照套正文选择器算差异，排除页脚/栏目导航，缺页期间不出删除结论。
3. 把判定记录里的段落改动写成变化事件，事件关联旧/新节选与各自采集时间。
4. 日期类变化事件由监控员决定通知前台，并保留两次实际抓取文字可查回。

为避免 import 阶段的循环依赖（store -> seed -> service -> store），这里对
app.store 采用方法内懒加载；bootstrap 由 Store 初始化完成后调用。
"""
from __future__ import annotations

from typing import Any

from app.services import content_diff_engine as engine

SNAPSHOT_TABLE = "content_snapshot"
DIFF_TABLE = "content_diff"
EVENT_TABLE = "content_change_event"

SNAPSHOT_REQUIRED = ["url", "rule_code", "captured_at", "raw_html"]
EVENT_NOTIFY_FLOW = ["待通知", "已通知前台", "前台已确认"]
DIFF_STATUS_ORDER = ["待补采", "已判定", "无变化"]


class ContentDiffService:
    # ------------------------------------------------------------------ #
    # 采集快照
    # ------------------------------------------------------------------ #
    def _snapshots(self) -> list[dict[str, Any]]:
        from app.store import store

        return store.rows(SNAPSHOT_TABLE)

    def list_snapshots(
        self,
        *,
        url: str | None = None,
        rule_code: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._snapshots()
        if url:
            rows = [r for r in rows if url in str(r.get("url", ""))]
        if rule_code:
            rows = [r for r in rows if rule_code in str(r.get("rule_code", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        from app.store import store

        return store.find(SNAPSHOT_TABLE, snapshot_id)

    def create_snapshot(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [f for f in SNAPSHOT_REQUIRED if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing
        rows = self._snapshots()
        config = self._rule_config(str(values.get("rule_code") or ""))
        raw_html = str(values.get("raw_html") or "")
        missing_pages, missing_ranges = engine.find_missing_pages(raw_html)
        extraction = engine.extract_segments(raw_html, config)
        snapshot = {
            "id": self._next_id(rows),
            "snapshot_no": str(values.get("snapshot_no") or f"SNAP-{self._next_id(rows):04d}"),
            "url": values.get("url"),
            "rule_code": values.get("rule_code"),
            "rule_version": values.get("rule_version") or "",
            "captured_at": values.get("captured_at"),
            "page_count": int(values.get("page_count") or 0),
            "missing_pages": missing_pages,
            "missing_ranges": missing_ranges,
            "segment_count": len(extraction.segments),
            "excluded_hits": extraction.excluded_hits,
            "raw_html": raw_html,
            "refetch_of": values.get("refetch_of"),
            "remark": values.get("remark") or "",
        }
        rows.append(snapshot)
        return snapshot, []

    def refetch_snapshot(self, snapshot_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """补采：以新的完整响应登记一张补采快照，并对原缺页快照重算配对判定。"""
        origin = self.get_snapshot(snapshot_id)
        if origin is None:
            return None, f"快照 {snapshot_id} 不存在，无法补采"
        values = dict(values)
        values.setdefault("url", origin["url"])
        values.setdefault("rule_code", origin["rule_code"])
        values.setdefault("rule_version", origin["rule_version"])
        values.setdefault("page_count", origin["page_count"])
        values["refetch_of"] = origin["snapshot_no"]
        new_snapshot, missing_fields = self.create_snapshot(values)
        if missing_fields:
            return None, f"补采缺少必填字段：{'、'.join(missing_fields)}"
        if new_snapshot and new_snapshot["missing_pages"]:
            return new_snapshot, "补采响应仍标注缺页，已登记但暂不参与差异判定"
        return new_snapshot, "补采成功，可对原始缺页快照重新套用同一正文选择器核算"

    # ------------------------------------------------------------------ #
    # 正文变动判定记录
    # ------------------------------------------------------------------ #
    def _diffs(self) -> list[dict[str, Any]]:
        from app.store import store

        return store.rows(DIFF_TABLE)

    def _events(self) -> list[dict[str, Any]]:
        from app.store import store

        return store.rows(EVENT_TABLE)

    def list_diffs(
        self,
        *,
        url: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._diffs()
        if url:
            rows = [r for r in rows if url in str(r.get("url", ""))]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_diff(self, diff_id: int) -> dict[str, Any] | None:
        from app.store import store

        return store.find(DIFF_TABLE, diff_id)

    def compute_diff(self, old_snapshot_id: int, new_snapshot_id: int) -> tuple[dict[str, Any] | None, str]:
        old_snapshot = self.get_snapshot(old_snapshot_id)
        new_snapshot = self.get_snapshot(new_snapshot_id)
        if old_snapshot is None or new_snapshot is None:
            return None, "参与对比的快照不存在，请核对快照编号"
        if old_snapshot.get("url") != new_snapshot.get("url"):
            return None, "只允许对同一网址的连续采集快照做正文差异核算"
        old_config = self._rule_config(str(old_snapshot["rule_code"]))
        new_config = self._rule_config(str(new_snapshot["rule_code"]))
        result = engine.diff_snapshots(old_snapshot, new_snapshot, old_config, new_config)

        diff_id = self._next_id(self._diffs())
        if result["blocked_by_missing"]:
            status = "待补采"
        elif result["changes"]:
            status = "已判定"
        else:
            status = "无变化"
        diff = {
            "id": diff_id,
            "diff_no": f"DIFF-{diff_id:04d}",
            "url": result["url"],
            "status": status,
            "old_snapshot_id": old_snapshot_id,
            "new_snapshot_id": new_snapshot_id,
            "old_snapshot_no": old_snapshot["snapshot_no"],
            "new_snapshot_no": new_snapshot["snapshot_no"],
            "old_rule_code": old_snapshot["rule_code"],
            "new_rule_code": new_snapshot["rule_code"],
            "old_captured_at": result["old_captured_at"],
            "new_captured_at": result["new_captured_at"],
            "blocked_by_missing": result["blocked_by_missing"],
            "old_missing_ranges": result["old_missing_ranges"],
            "new_missing_ranges": result["new_missing_ranges"],
            "cross_version_regions": result["cross_version_regions"],
            "new_track_regions": result["new_track_regions"],
            "retired_regions": result["retired_regions"],
            "excluded_hits": result["excluded_hits"],
            "change_count": len(result["changes"]),
            "date_change_count": 0,
            "changes": result["changes"],
        }
        self._diffs().append(diff)

        if status != "待补采":
            events = engine.build_change_events(result, diff_id)
            # 事件入内存仓库时统一分配自增 id，event_no 保留业务编号。
            for event in events:
                event["id"] = self._next_id(self._events())
                self._events().append(event)
            diff["date_change_count"] = sum(1 for e in events if e["date_changed"])
        return diff, self._diff_message(diff)

    def _diff_message(self, diff: dict[str, Any]) -> str:
        if diff["status"] == "待补采":
            ranges = diff["new_missing_ranges"] or diff["old_missing_ranges"]
            return f"存在缺页区间 {ranges}，已挂起判定，补采成功后再套同一正文选择器重算"
        if diff["status"] == "无变化":
            return "两次快照正文一致，未产生变化事件"
        return f"判定完成，命中 {diff['change_count']} 处段落改动，其中日期变更 {diff['date_change_count']} 处"

    # ------------------------------------------------------------------ #
    # 变化事件与前台通知
    # ------------------------------------------------------------------ #
    def list_events(
        self,
        *,
        diff_id: int | None = None,
        date_changed: bool | None = None,
        notify_status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._events()
        if diff_id is not None:
            rows = [r for r in rows if r.get("diff_id") == diff_id]
        if date_changed is not None:
            rows = [r for r in rows if bool(r.get("date_changed")) == date_changed]
        if notify_status:
            rows = [r for r in rows if r.get("notify_status") == notify_status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        from app.store import store

        return store.find(EVENT_TABLE, event_id)

    def notify_event(self, event_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """监控员用变化事件决定哪些日期要通知前台：待通知 -> 已通知前台 -> 前台已确认。"""
        event = self.get_event(event_id)
        if event is None:
            return None, f"变化事件 {event_id} 不存在"
        if not event.get("date_changed"):
            return None, "该事件不涉及开放日期变更，无需通知前台"
        current = EVENT_NOTIFY_FLOW.index(event["notify_status"]) if event["notify_status"] in EVENT_NOTIFY_FLOW else 0
        if action == "通知前台":
            target = "已通知前台"
        elif action == "前台确认":
            target = "前台已确认"
        else:
            return None, f"动作「{action}」不属于日期通知流转范围"
        if EVENT_NOTIFY_FLOW.index(target) <= current:
            return None, f"事件当前为「{event['notify_status']}」，不能重复执行「{action}」"
        event["notify_status"] = target
        return event, f"日期变更已{action}，旧/新节选与两次采集时间保留在事件中可查回"

    # ------------------------------------------------------------------ #
    # 规则配置与启动装配
    # ------------------------------------------------------------------ #
    def _rule_config(self, rule_code: str) -> dict[str, Any]:
        """取规则的选择器配置；种子规则走内置样例，外部登记的规则可携带 selector_config。"""
        from app import content_diff_seed as seed
        from app.store import store

        if rule_code in seed.RULE_CONFIGS:
            return seed.RULE_CONFIGS[rule_code]
        for row in store.rows("crawler"):
            if row.get("规则编号") == rule_code:
                config = row.get("selector_config")
                if isinstance(config, dict):
                    return config
        return {"selectors": [], "exclude": []}

    def bootstrap(self, store_obj: Any) -> None:
        """仓库初始化后装配文化馆场景：登记快照 -> 连续配对核算 -> 生成事件。

        store_obj 由 Store.__init__ 直接传入，避免在 store 模块尚未初始化完成时
        再回头 import app.store 造成循环导入。
        """
        from app import content_diff_seed as seed

        # 幂等：重复调用不重复灌数据。
        if store_obj.rows(SNAPSHOT_TABLE):
            return
        snapshot_id_by_no: dict[str, int] = {}
        for item in seed.SNAPSHOT_SEED:
            snapshot, missing_fields = self.create_snapshot(item)
            if missing_fields:  # 种子数据理论上不会缺字段
                raise RuntimeError(f"种子快照字段缺失：{missing_fields}")
            snapshot_id_by_no[snapshot["snapshot_no"]] = snapshot["id"]  # type: ignore[index]

        for old_no, new_no in seed.DIFF_PLAN:
            self.compute_diff(snapshot_id_by_no[old_no], snapshot_id_by_no[new_no])

        # 场景里第一处日期更正（闭馆日期）已经通知前台并获确认，第二处仍待通知。
        date_events = [e for e in self._events() if e["date_changed"]]
        if len(date_events) >= 1:
            date_events[0]["notify_status"] = "前台已确认"
        if len(date_events) >= 2:
            date_events[1]["notify_status"] = "待通知"

    @staticmethod
    def _next_id(rows: list[dict[str, Any]]) -> int:
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1


service = ContentDiffService()
