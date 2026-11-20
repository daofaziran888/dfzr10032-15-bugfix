"""正文变动判定引擎：从原始响应里按选择器抽取正文段落，并对连续快照做差异核算。

设计约束（对应业务规则）：
- 只依赖标准库，克隆下来即可运行，不引入第三方解析器。
- 规则指定的页脚、栏目导航等区域不参与比较，由选择器配置里的 exclude 明确排除。
- 缺页时不把缺失段落当成删除：extract_segments 会先把缺失页次区间报出来，
  diff_snapshots 在任一侧存在缺失区间时拒绝出差异结论，等补采后再套同一选择器重算。
- 改版（选择器集合变化）时，给出哪些区段可跨版核对、哪些区段从当次开始跟踪的交代。
- 命中的文本区段带抓取页次，变化事件据此关联旧/新节选与各自采集时间。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

# 日期识别：覆盖 2026年11月15日、2026-11-15、11月15日（可带"起/至/到"）。
_DATE_PATTERNS = [
    re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"),
    re.compile(r"\d{4}-\d{1,2}-\d{1,2}"),
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日"),
]

# 缺页标记：原始响应里以 <!-- 缺页:第2页 --> 这类注释声明。
_MISSING_PAGE_RE = re.compile(r"缺页[:：]\s*第?\s*(\d+)\s*页")
# 抓取页次：正文元素上 data-page="2" 或 data-fetch-page，缺省归第 1 页。
_PAGE_ATTRS = ("data-page", "data-fetch-page")


# --------------------------------------------------------------------------- #
# 极简 DOM
# --------------------------------------------------------------------------- #
@dataclass
class DomNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["DomNode | str"] = field(default_factory=list)
    parent: "DomNode | None" = None

    def iter_text(self) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                parts.append(child.iter_text())
        return "".join(parts)


class _DomBuilder(HTMLParser):
    """把 HTML 文本解析成一棵可做简单选择器查询的树。

    注释单独保留，因为缺页区间就是写在原始响应的注释里的。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = DomNode("#root")
        self._stack: list[DomNode] = [self.root]
        self.comments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = DomNode(tag=tag, attrs={k: (v or "") for k, v in attrs})
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)
        self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = DomNode(tag=tag, attrs={k: (v or "") for k, v in attrs})
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        # 容错：只在栈里能找到同名标签时回退，避免外部残缺 HTML 把栈弹空。
        for idx in range(len(self._stack) - 1, 0, -1):
            if self._stack[idx].tag == tag:
                del self._stack[idx:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)

    def handle_comment(self, data: str) -> None:
        self.comments.append(data.strip())


def _parse_html(html: str) -> tuple[DomNode, list[str]]:
    builder = _DomBuilder()
    builder.feed(html or "")
    builder.close()
    return builder.root, builder.comments


# --------------------------------------------------------------------------- #
# 选择器：支持 tag、.class、#id、[attr=v]，以及空格分隔的后代组合
# --------------------------------------------------------------------------- #
_SIMPLE_SELECTOR_RE = re.compile(
    r"(?P<tag>[a-zA-Z][\w-]*)?"
    r"(?:#(?P<id>[\w-]+))?"
    r"(?P<classes>(?:\.[\w-]+)*)"
    r"(?:\[(?P<attr>[\w-]+)(?:=(?P<value>[^\]]+))?\])?"
)


def _match_simple(node: DomNode, part: str) -> bool:
    match = _SIMPLE_SELECTOR_RE.fullmatch(part.strip())
    if not match:
        return False
    if match.group("tag") and node.tag != match.group("tag"):
        return False
    if match.group("id") and node.attrs.get("id") != match.group("id"):
        return False
    classes = [c for c in match.group("classes").split(".") if c]
    if classes:
        node_classes = set(node.attrs.get("class", "").split())
        if any(name not in node_classes for name in classes):
            return False
    attr = match.group("attr")
    if attr:
        if attr not in node.attrs:
            return False
        value = match.group("value")
        if value is not None and node.attrs[attr] != value.strip().strip('"\''):
            return False
    return True


def _walk(node: DomNode) -> list[DomNode]:
    out: list[DomNode] = []
    for child in node.children:
        if isinstance(child, DomNode):
            out.append(child)
            out.extend(_walk(child))
    return out


def select(root: DomNode, selector: str) -> list[DomNode]:
    """按后代组合选择器取节点；写不出的选择器返回空列表而不是抛异常。"""
    parts = [p for p in selector.strip().split() if p]
    if not parts:
        return []
    current = [root]
    for part in parts:
        nxt: list[DomNode] = []
        for scope in current:
            for node in _walk(scope):
                if _match_simple(node, part):
                    nxt.append(node)
        current = nxt
    return current


# --------------------------------------------------------------------------- #
# 数据载体
# --------------------------------------------------------------------------- #
@dataclass
class Segment:
    """参与比较的一个正文区段（段落）。"""

    key: str
    text: str
    region: str
    page: int
    selector: str
    order: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "text": self.text,
            "region": self.region,
            "page": self.page,
            "selector": self.selector,
            "order": self.order,
        }


@dataclass
class ExtractionResult:
    segments: list[Segment]
    missing_pages: list[int]
    missing_ranges: list[list[int]]
    excluded_hits: list[dict[str, str]]
    region_versions: dict[str, str]


def find_missing_pages(html: str) -> tuple[list[int], list[list[int]]]:
    """从原始响应注释里解析缺失页次，并压缩成连续区间。"""
    pages = sorted({int(m) for m in _MISSING_PAGE_RE.findall(html or "")})
    ranges: list[list[int]] = []
    for page in pages:
        if ranges and page == ranges[-1][1] + 1:
            ranges[-1][1] = page
        else:
            ranges.append([page, page])
    return pages, ranges


def _page_of(node: DomNode) -> int:
    cur: DomNode | None = node
    while cur is not None:
        for attr in _PAGE_ATTRS:
            value = cur.attrs.get(attr)
            if value and value.isdigit():
                return int(value)
        cur = cur.parent
    return 1


def extract_segments(html: str, selector_config: dict[str, Any]) -> ExtractionResult:
    """按规则配置抽取正文区段。

    selector_config 结构：
    {
      "selectors": [{"selector": "div.article p", "region": "公告正文", "since": "旧规则"}],
      "exclude": ["footer.site-footer", "nav.column-nav"]   # 页脚、栏目导航不参加比较
    }
    """
    root, comments = _parse_html(html)
    missing_pages, missing_ranges = find_missing_pages(html)
    # 注释里的缺页声明同样落到 missing 上（部分响应只写注释、不写 data-page）。
    excluded_hits: list[dict[str, str]] = []
    for excluded in selector_config.get("exclude", []):
        for node in select(root, excluded):
            text = _normalize(node.iter_text())
            if text:
                excluded_hits.append({"selector": excluded, "text": text[:80]})

    segments: list[Segment] = []
    region_versions: dict[str, str] = {}
    order = 0
    for item in selector_config.get("selectors", []):
        region = str(item.get("region") or "正文")
        region_versions[region] = str(item.get("since") or "")
        css = str(item.get("selector") or "")
        for node in select(root, css):
            text = _normalize(node.iter_text())
            if not text:
                continue
            order += 1
            page = _page_of(node)
            segments.append(
                Segment(
                    key=f"{region}#P{page}#{order}",
                    text=text,
                    region=region,
                    page=page,
                    selector=css,
                    order=order,
                )
            )
    return ExtractionResult(
        segments=segments,
        missing_pages=missing_pages,
        missing_ranges=missing_ranges,
        excluded_hits=excluded_hits,
        region_versions=region_versions,
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip()


def _similarity(a: str, b: str) -> float:
    """字符级相似度：difflib 序列比，足以判定"同一段落被更正/迁移"。"""
    from difflib import SequenceMatcher

    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def extract_dates(text: str) -> list[str]:
    raw: list[str] = []
    for pattern in _DATE_PATTERNS:
        raw.extend(pattern.findall(text or ""))
    found: list[str] = []
    for date in raw:
        # 短模式（11月15日）会命中年月日长模式的子串，剔除已被更长日期包含的重复项。
        if any(date != other and date in other for other in found):
            continue
        if date not in found:
            found.append(date)
    return found


# --------------------------------------------------------------------------- #
# 快照差异核算
# --------------------------------------------------------------------------- #
SIMILAR_THRESHOLD = 0.55


def _pair_segments(old: list[Segment], new: list[Segment]) -> list[dict[str, Any]]:
    """全局贪心配对：计算全部 old×new 相似度后按分数降序撮合。

    不预先按区域限制候选，否则改版迁移的段落会被同区域的弱相关段落先占走，
    进而被误判成"删除+新增"。区域差异只用于后续区分 moved 与 modified。
    """
    scored: list[tuple[float, int, int]] = []
    for i, old_seg in enumerate(old):
        for j, new_seg in enumerate(new):
            scored.append((_similarity(old_seg.text, new_seg.text), i, j))
    scored.sort(reverse=True)

    used_old: set[int] = set()
    used_new: set[int] = set()
    pair_of_old: dict[int, tuple[int, float]] = {}
    for score, i, j in scored:
        if score < SIMILAR_THRESHOLD:
            break  # 后面分数更低，都不值得配对
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        pair_of_old[i] = (j, score)

    results: list[dict[str, Any]] = []
    for i, old_seg in enumerate(old):
        if i in pair_of_old:
            j, score = pair_of_old[i]
            results.append({"old": old_seg, "new": new[j], "score": score})
        else:
            results.append({"old": old_seg, "new": None, "score": 0.0})
    for j, seg in enumerate(new):
        if j not in used_new:
            results.append({"old": None, "new": seg, "score": 0.0})
    return results


def diff_snapshots(
    old_snapshot: dict[str, Any],
    new_snapshot: dict[str, Any],
    old_config: dict[str, Any],
    new_config: dict[str, Any],
) -> dict[str, Any]:
    """对同一网址的连续两个快照核算正文差异。

    返回结论 + 命中区段清单；任一侧缺页时不给出删除结论，只回报待补采。
    """
    old_extract = extract_segments(old_snapshot.get("raw_html", ""), old_config)
    new_extract = extract_segments(new_snapshot.get("raw_html", ""), new_config)

    missing = {
        "old_missing_pages": old_extract.missing_pages,
        "old_missing_ranges": old_extract.missing_ranges,
        "new_missing_pages": new_extract.missing_pages,
        "new_missing_ranges": new_extract.missing_ranges,
    }
    blocked = bool(old_extract.missing_pages or new_extract.missing_pages)

    old_regions = set(old_extract.region_versions)
    new_regions = set(new_extract.region_versions)
    cross_regions = sorted(old_regions & new_regions)
    new_only_regions = sorted(new_regions - old_regions)
    retired_regions = sorted(old_regions - new_regions)

    changes: list[dict[str, Any]] = []
    if not blocked:
        for pair in _pair_segments(old_extract.segments, new_extract.segments):
            old_seg: Segment | None = pair["old"]
            new_seg: Segment | None = pair["new"]
            score: float = pair["score"]
            if old_seg and new_seg:
                if old_seg.text == new_seg.text:
                    kind = "unchanged"
                elif old_seg.region != new_seg.region:
                    kind = "moved-modified" if old_seg.text != new_seg.text else "moved"
                else:
                    kind = "modified"
                if kind == "unchanged":
                    continue
                # 配对成功（含跨区迁移/同区更正）都能在两版快照间核对到原文，属跨版核对；
                # 只有新增区域里首次出现、没有旧对应的段落才从当次开始跟踪。
                tracking = "cross-version"
                changes.append(
                    {
                        "kind": kind,
                        "tracking": tracking,
                        "similarity": round(score, 3),
                        "old_segment": old_seg.to_dict(),
                        "new_segment": new_seg.to_dict(),
                    }
                )
            elif old_seg:
                # 到这一步两侧都不缺页，旧段落确实在新快照消失，才算删除。
                changes.append(
                    {
                        "kind": "deleted",
                        "tracking": "cross-version",
                        "similarity": round(score, 3),
                        "old_segment": old_seg.to_dict(),
                        "new_segment": None,
                    }
                )
            else:
                assert new_seg is not None
                changes.append(
                    {
                        "kind": "added",
                        "tracking": "new-track" if new_seg.region in new_only_regions else "cross-version",
                        "similarity": 0.0,
                        "old_segment": None,
                        "new_segment": new_seg.to_dict(),
                    }
                )

    return {
        "blocked_by_missing": blocked,
        **missing,
        "cross_version_regions": cross_regions,
        "new_track_regions": new_only_regions,
        "retired_regions": retired_regions,
        "excluded_hits": new_extract.excluded_hits,
        "changes": changes,
        "old_segment_count": len(old_extract.segments),
        "new_segment_count": len(new_extract.segments),
        "old_captured_at": old_snapshot.get("captured_at"),
        "new_captured_at": new_snapshot.get("captured_at"),
        "old_snapshot_id": old_snapshot.get("id"),
        "new_snapshot_id": new_snapshot.get("id"),
        "url": new_snapshot.get("url") or old_snapshot.get("url"),
    }


def build_change_events(diff: dict[str, Any], diff_id: int) -> list[dict[str, Any]]:
    """把判定记录里的段落改动落成变化事件；日期更正单独抽出来，供前台通知决策。"""
    events: list[dict[str, Any]] = []
    seq = 0
    for change in diff.get("changes", []):
        seq += 1
        old_seg = change.get("old_segment")
        new_seg = change.get("new_segment")
        old_text = old_seg["text"] if old_seg else ""
        new_text = new_seg["text"] if new_seg else ""
        old_dates = extract_dates(old_text)
        new_dates = extract_dates(new_text)
        date_changed = sorted(old_dates) != sorted(new_dates) and bool(old_dates or new_dates)
        events.append(
            {
                "event_no": f"EVT-{diff_id:04d}-{seq:02d}",
                "diff_id": diff_id,
                "kind": change["kind"],
                "tracking": change["tracking"],
                "region_old": old_seg["region"] if old_seg else "",
                "region_new": new_seg["region"] if new_seg else "",
                "page_old": old_seg["page"] if old_seg else None,
                "page_new": new_seg["page"] if new_seg else None,
                "old_excerpt": old_text[:120],
                "new_excerpt": new_text[:120],
                "old_dates": old_dates,
                "new_dates": new_dates,
                "date_changed": date_changed,
                "old_captured_at": diff.get("old_captured_at"),
                "new_captured_at": diff.get("new_captured_at"),
                "old_snapshot_id": diff.get("old_snapshot_id"),
                "new_snapshot_id": diff.get("new_snapshot_id"),
                "notify_status": "待通知" if date_changed else "无需通知",
            }
        )
    return events
