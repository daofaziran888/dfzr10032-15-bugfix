"""正文变动判定接口：采集快照、差异判定记录、变化事件三组资源。

- 快照：登记连续采集、补采缺页。
- 判定：对同一网址的连续快照套正文选择器核算差异。
- 事件：段落改动落成事件，日期类事件走前台通知流转。
列表沿用平台统一的 {items,total,page,size} 口径，动作返回 {ok,message}。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.content_diff import (
    DIFF_STATUS_ORDER,
    EVENT_NOTIFY_FLOW,
    service,
)

router = APIRouter(prefix="/api/content-diff", tags=["正文变动判定"])


# --------------------------------------------------------------------------- #
# 采集快照
# --------------------------------------------------------------------------- #
@router.get("/snapshots", response_model=PageResult[dict])
def list_snapshots(
    url: str | None = Query(default=None, description="按目标网址过滤"),
    rule_code: str | None = Query(default=None, description="按采集规则编号过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_snapshots(url=url, rule_code=rule_code, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/snapshots/{snapshot_id}", response_model=dict)
def get_snapshot(snapshot_id: int) -> dict:
    snapshot = service.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"采集快照 {snapshot_id} 不存在")
    return snapshot


@router.post("/snapshots", response_model=ActionResult)
def create_snapshot(payload: EntryPayload) -> ActionResult:
    snapshot, missing = service.create_snapshot(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="采集快照已登记，缺页区间已在原始响应中标出", entry=snapshot)


@router.post("/snapshots/{snapshot_id}/refetch", response_model=ActionResult)
def refetch_snapshot(snapshot_id: int, payload: EntryPayload) -> ActionResult:
    snapshot, message = service.refetch_snapshot(snapshot_id, payload.values)
    if snapshot is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=snapshot)


# --------------------------------------------------------------------------- #
# 正文变动判定记录
# --------------------------------------------------------------------------- #
@router.get("/diffs", response_model=PageResult[dict])
def list_diffs(
    url: str | None = Query(default=None),
    status: str | None = Query(default=None, description="待补采、已判定、无变化"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_diffs(url=url, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/diffs/{diff_id}", response_model=dict)
def get_diff(diff_id: int) -> dict:
    diff = service.get_diff(diff_id)
    if diff is None:
        raise HTTPException(status_code=404, detail=f"正文变动判定记录 {diff_id} 不存在")
    return diff


@router.post("/diffs/compute", response_model=ActionResult)
def compute_diff(payload: EntryPayload) -> ActionResult:
    try:
        old_id = int(payload.values.get("old_snapshot_id"))
        new_id = int(payload.values.get("new_snapshot_id"))
    except (TypeError, ValueError):
        return ActionResult(ok=False, message="请提供 old_snapshot_id 与 new_snapshot_id 两个快照编号")
    diff, message = service.compute_diff(old_id, new_id)
    if diff is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=diff)


# --------------------------------------------------------------------------- #
# 变化事件
# --------------------------------------------------------------------------- #
@router.get("/events", response_model=PageResult[dict])
def list_events(
    diff_id: int | None = Query(default=None),
    date_changed: bool | None = Query(default=None, description="只看涉及开放日期变更的事件"),
    notify_status: str | None = Query(default=None, description="、".join(EVENT_NOTIFY_FLOW)),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_events(
        diff_id=diff_id,
        date_changed=date_changed,
        notify_status=notify_status,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/events/{event_id}", response_model=dict)
def get_event(event_id: int) -> dict:
    event = service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"变化事件 {event_id} 不存在")
    return event


@router.post("/events/{event_id}/actions", response_model=ActionResult)
def notify_event(event_id: int, payload: EntryPayload) -> ActionResult:
    action = str(payload.values.get("action") or "").strip()
    event, message = service.notify_event(event_id, action)
    if event is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=event)
