"""正文变动判定的种子数据：文化馆公告页改版前后的真实采集快照。

场景时间线（同一网址 http://www.culture-gov.example/announce）：
1. 旧规则（CRAW-0101）只识别公告正文，快照 SNAP-0001 完整。
2. 改版当天换用新规则（CRAW-0102），新规则额外识别独立通知栏；
   首次抓取 SNAP-0002 缺第 2 页，原始响应里用注释标出缺失区间，不出删除结论。
3. 补采成功 SNAP-0003，套同一组新选择器重算：闭馆通知由正文迁入通知栏（迁移+更正），
   两处开放日期被更正。
4. SNAP-0004 复查，页面无变化，不产生变化事件。

本模块只放纯数据，避免在 import 阶段产生循环依赖；判定记录与事件由
ContentDiffService.bootstrap 在仓库初始化后现算，保证数据与引擎口径一致。
"""
from __future__ import annotations

from typing import Any

TARGET_URL = "http://www.culture-gov.example/announce"

# 规则指定不参加比较的区域：栏目导航、页脚。
EXCLUDE_SELECTORS = ["nav.column-nav", "footer.site-footer"]

OLD_RULE = {
    "rule_code": "CRAW-0101",
    "rule_name": "文化馆公告-旧版规则",
    "url": TARGET_URL,
    "exclude": EXCLUDE_SELECTORS,
    "selectors": [
        {"selector": "div.article p.body-p", "region": "公告正文", "since": "旧规则"},
    ],
}

NEW_RULE = {
    "rule_code": "CRAW-0102",
    "rule_name": "文化馆公告-新版规则",
    "url": TARGET_URL,
    "exclude": EXCLUDE_SELECTORS,
    "selectors": [
        {"selector": "div.article p.body-p", "region": "公告正文", "since": "新规则"},
        {"selector": "div.notice-bar p.notice-p", "region": "通知栏", "since": "新规则"},
    ],
}

# --- 原始响应 ------------------------------------------------------------- #
_OLD_HTML = """
<html><body>
<nav class="column-nav"><a>首页</a><a>公告栏目</a><a>活动预约</a></nav>
<div class="article" data-page="1">
  <h1>文化馆开放安排公告</h1>
  <p class="body-p">为配合场馆维护，本馆将于2026年11月20日至2026年11月22日闭馆，闭馆期间不对外开放。</p>
  <p class="body-p">常规开放时间为每周二至周日9:00-17:00，周一例行休馆。</p>
</div>
<div class="article" data-page="2">
  <p class="body-p">开放日期：2026年12月1日起恢复正常开放，请广大市民合理安排参观时间。</p>
  <p class="body-p">咨询电话：0571-88888000，如有疑问可在工作日致电。</p>
</div>
<footer class="site-footer"><p>主办：市文化广电旅游局 地址：文化路1号</p></footer>
</body></html>
"""

_NEW_HTML_MISSING = """
<html><body>
<nav class="column-nav"><a>首页</a><a>公告栏目</a><a>活动预约</a></nav>
<div class="notice-bar" data-page="1">
  <h2>通知栏</h2>
  <p class="notice-p">因展陈升级，本馆2026年11月21日至2026年11月23日闭馆，闭馆期间不对外开放。</p>
</div>
<div class="article" data-page="1">
  <h1>文化馆开放安排公告</h1>
  <p class="body-p">常规开放时间为每周二至周日9:00-17:00，周一例行休馆。</p>
</div>
<!-- 缺页:第2页 -->
<footer class="site-footer"><p>主办：市文化广电旅游局 地址：文化路1号</p></footer>
</body></html>
"""

_NEW_HTML_FULL = """
<html><body>
<nav class="column-nav"><a>首页</a><a>公告栏目</a><a>活动预约</a></nav>
<div class="notice-bar" data-page="1">
  <h2>通知栏</h2>
  <p class="notice-p">因展陈升级，本馆2026年11月21日至2026年11月23日闭馆，闭馆期间不对外开放。</p>
</div>
<div class="article" data-page="1">
  <h1>文化馆开放安排公告</h1>
  <p class="body-p">常规开放时间为每周二至周日9:00-17:00，周一例行休馆。</p>
</div>
<div class="article" data-page="2">
  <p class="body-p">开放日期：2026年12月3日起恢复正常开放，请广大市民合理安排参观时间。</p>
  <p class="body-p">咨询电话：0571-88888000，如有疑问可在工作日致电。</p>
</div>
<footer class="site-footer"><p>主办：市文化广电旅游局 地址：文化路1号</p></footer>
</body></html>
"""

SNAPSHOT_SEED: list[dict[str, Any]] = [
    {
        "snapshot_no": "SNAP-0001",
        "url": TARGET_URL,
        "rule_code": "CRAW-0101",
        "rule_version": "旧规则",
        "captured_at": "2026-11-18 09:00:00",
        "page_count": 2,
        "raw_html": _OLD_HTML,
        "refetch_of": None,
        "remark": "改版前最后一次完整采集",
    },
    {
        "snapshot_no": "SNAP-0002",
        "url": TARGET_URL,
        "rule_code": "CRAW-0102",
        "rule_version": "新规则",
        "captured_at": "2026-11-19 09:00:00",
        "page_count": 2,
        "raw_html": _NEW_HTML_MISSING,
        "refetch_of": None,
        "remark": "改版当天首采，第2页缺页",
    },
    {
        "snapshot_no": "SNAP-0003",
        "url": TARGET_URL,
        "rule_code": "CRAW-0102",
        "rule_version": "新规则",
        "captured_at": "2026-11-19 15:20:00",
        "page_count": 2,
        "raw_html": _NEW_HTML_FULL,
        "refetch_of": "SNAP-0002",
        "remark": "缺页补采成功，套用同一新选择器",
    },
    {
        "snapshot_no": "SNAP-0004",
        "url": TARGET_URL,
        "rule_code": "CRAW-0102",
        "rule_version": "新规则",
        "captured_at": "2026-11-20 09:00:00",
        "page_count": 2,
        "raw_html": _NEW_HTML_FULL,
        "refetch_of": None,
        "remark": "次日复查，页面无变化",
    },
]

RULE_CONFIGS: dict[str, dict[str, Any]] = {
    "CRAW-0101": OLD_RULE,
    "CRAW-0102": NEW_RULE,
}

# 连续快照配对：第一对故意落在缺页快照上，验证不会把没抓到的段落算成删除。
DIFF_PLAN: list[tuple[str, str]] = [
    ("SNAP-0001", "SNAP-0002"),
    ("SNAP-0001", "SNAP-0003"),
    ("SNAP-0003", "SNAP-0004"),
]
