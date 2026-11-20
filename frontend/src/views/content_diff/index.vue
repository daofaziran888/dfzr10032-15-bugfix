<template>
  <section class="page" data-module="content-diff">
    <header class="page-head">
      <div>
        <h2>正文变动判定</h2>
        <p class="page-desc">
          对同一网址的连续采集快照套正文选择器核算差异：页脚、栏目导航不参与比较；缺页只挂起不判删除，
          补采后同选择器重算。段落改动落成变化事件，日期变更由监控员决定是否通知前台。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="activeTab = 'snapshot'">采集快照</button>
        <button class="btn" type="button" @click="activeTab = 'diff'">判定记录</button>
        <button class="btn primary" type="button" @click="activeTab = 'event'">变化事件</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <!-- 采集快照 -->
    <div v-if="activeTab === 'snapshot'">
      <form class="filter-bar" @submit.prevent="loadSnapshots">
        <label class="filter-item">
          <span>目标网址</span>
          <input v-model="snapshotFilters.url" placeholder="按网址检索" />
        </label>
        <label class="filter-item">
          <span>规则编号</span>
          <input v-model="snapshotFilters.rule_code" placeholder="按规则编号检索" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetSnapshotFilters">重置条件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in snapshotColumns" :key="column">{{ column }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in snapshots" :key="String(row.id)">
            <td v-for="column in snapshotColumns" :key="column">
              <template v-if="column === 'missing_ranges'">
                <span v-if="row.missing_ranges && row.missing_ranges.length" class="warn-text">
                  缺页 {{ formatRanges(row.missing_ranges) }}
                </span>
                <span v-else>完整</span>
              </template>
              <template v-else-if="column === 'excluded_hits'">
                <span>{{ (row.excluded_hits || []).map((h: any) => h.selector).join('、') || '—' }}</span>
              </template>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="openRaw(row)">查看原始响应</button>
              <button
                v-if="row.missing_pages && row.missing_pages.length"
                class="link"
                type="button"
                @click="openRefetch(row)"
              >
                补采
              </button>
            </td>
          </tr>
          <tr v-if="!snapshots.length">
            <td :colspan="snapshotColumns.length + 1" class="empty-state">暂无采集快照</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ snapshotTotal }} 张采集快照</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>

    <!-- 判定记录 -->
    <div v-if="activeTab === 'diff'">
      <form class="filter-bar" @submit.prevent="loadDiffs">
        <label class="filter-item">
          <span>目标网址</span>
          <input v-model="diffFilters.url" placeholder="按网址检索" />
        </label>
        <label class="filter-item">
          <span>判定状态</span>
          <input v-model="diffFilters.status" placeholder="待补采/已判定/无变化" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetDiffFilters">重置条件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in diffColumns" :key="column">{{ column }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in diffs" :key="String(row.id)">
            <td v-for="column in diffColumns" :key="column">
              <template v-if="column === 'status'">
                <span :class="statusClass(row.status)">{{ row.status }}</span>
              </template>
              <template v-else-if="column === 'missing'">
                <span v-if="row.blocked_by_missing" class="warn-text">
                  缺失 {{ formatRanges(row.old_missing_ranges.concat(row.new_missing_ranges)) }}
                </span>
                <span v-else>无缺页</span>
              </template>
              <template v-else-if="Array.isArray(row[column])">
                {{ row[column].join('、') || '—' }}
              </template>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="openDiff(row)">查看区段核对</button>
            </td>
          </tr>
          <tr v-if="!diffs.length">
            <td :colspan="diffColumns.length + 1" class="empty-state">暂无判定记录</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ diffTotal }} 条判定记录</span>
      </footer>
    </div>

    <!-- 变化事件 -->
    <div v-if="activeTab === 'event'">
      <form class="filter-bar" @submit.prevent="loadEvents">
        <label class="filter-item">
          <span>只看日期变更</span>
          <select v-model="eventFilters.date_changed">
            <option value="">全部</option>
            <option value="true">是</option>
            <option value="false">否</option>
          </select>
        </label>
        <label class="filter-item">
          <span>通知状态</span>
          <input v-model="eventFilters.notify_status" placeholder="待通知/已通知前台/前台已确认" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetEventFilters">重置条件</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in eventColumns" :key="column">{{ column }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in events" :key="String(row.id)">
            <td v-for="column in eventColumns" :key="column">
              <template v-if="column === 'kind'">
                {{ kindLabel(row.kind) }}
              </template>
              <template v-else-if="column === 'date_changed'">
                <span :class="row.date_changed ? 'warn-text' : ''">{{ row.date_changed ? '是' : '否' }}</span>
              </template>
              <template v-else-if="column === 'notify_status'">
                <span :class="notifyClass(row.notify_status)">{{ row.notify_status }}</span>
              </template>
              <template v-else-if="column === 'excerpt'">
                <div class="excerpt-cell">
                  <div><span class="muted">旧：</span>{{ row.old_excerpt || '—' }}</div>
                  <div><span class="muted">新：</span>{{ row.new_excerpt || '—' }}</div>
                </div>
              </template>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
            <td class="row-actions">
              <template v-if="row.date_changed">
                <button v-if="row.notify_status === '待通知'" class="link" type="button" @click="runEventAction(row, '通知前台')">
                  通知前台
                </button>
                <button v-if="row.notify_status === '已通知前台'" class="link" type="button" @click="runEventAction(row, '前台确认')">
                  前台确认
                </button>
                <span v-else class="muted">已闭环</span>
              </template>
              <span v-else class="muted">无需通知</span>
            </td>
          </tr>
          <tr v-if="!events.length">
            <td :colspan="eventColumns.length + 1" class="empty-state">暂无变化事件</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ eventTotal }} 条变化事件，旧/新节选与两次采集时间均可点明细查回</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>

    <!-- 原始响应弹窗 -->
    <Teleport to="body">
      <div v-if="rawModal" class="modal-overlay" @click.self="rawModal = null">
        <div class="modal-card modal-wide">
          <header class="modal-head">
            <h3>原始响应 · {{ rawModal.snapshot_no }}</h3>
            <button class="btn ghost" type="button" @click="rawModal = null">&times;</button>
          </header>
          <div class="modal-body">
            <p class="muted small">采集时间 {{ rawModal.captured_at }} · 规则 {{ rawModal.rule_code }} · 抓取页次 {{ rawModal.page_count }}</p>
            <pre class="raw-box">{{ rawModal.raw_html }}</pre>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 补采弹窗 -->
    <Teleport to="body">
      <div v-if="refetchTarget" class="modal-overlay" @click.self="refetchTarget = null">
        <div class="modal-card modal-wide">
          <header class="modal-head">
            <h3>缺页补采 · {{ refetchTarget.snapshot_no }}</h3>
            <button class="btn ghost" type="button" @click="refetchTarget = null">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitRefetch">
            <p class="warn-text small">原响应缺失页次：{{ formatRanges(refetchTarget.missing_ranges) }}，补采将套用同一正文选择器重算。</p>
            <label class="modal-field">
              <span>补采采集时间</span>
              <input v-model="refetchForm.captured_at" placeholder="2026-11-20 17:00:00" required />
            </label>
            <label class="modal-field">
              <span>补采完整原始响应（HTML）</span>
              <textarea v-model="refetchForm.raw_html" class="raw-input" rows="10" required></textarea>
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="refetchTarget = null">取消</button>
              <button class="btn primary" type="submit">提交补采</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- 区段核对弹窗 -->
    <Teleport to="body">
      <div v-if="diffModal" class="modal-overlay" @click.self="diffModal = null">
        <div class="modal-card modal-wide">
          <header class="modal-head">
            <h3>区段核对 · {{ diffModal.diff_no }}</h3>
            <button class="btn ghost" type="button" @click="diffModal = null">&times;</button>
          </header>
          <div class="modal-body">
            <div class="scope-box">
              <p><b>可跨版核对区域：</b>{{ diffModal.cross_version_regions.join('、') || '—' }}</p>
              <p><b>从当次开始跟踪：</b>{{ diffModal.new_track_regions.join('、') || '—' }}</p>
              <p><b>不参与比较区域：</b>{{ (diffModal.excluded_hits || []).map((h: any) => h.selector).join('、') || '—' }}</p>
              <p v-if="diffModal.blocked_by_missing" class="warn-text">
                存在缺页，已挂起判定，补采后再套同一正文选择器重算，缺失区间：
                {{ formatRanges(diffModal.old_missing_ranges.concat(diffModal.new_missing_ranges)) }}
              </p>
            </div>
            <table v-if="diffModal.changes && diffModal.changes.length" class="data-table">
              <thead>
                <tr><th>改动</th><th>核对口径</th><th>旧区段（页次）</th><th>新区段（页次）</th></tr>
              </thead>
              <tbody>
                <tr v-for="(c, i) in diffModal.changes" :key="i">
                  <td>{{ kindLabel(c.kind) }}</td>
                  <td>{{ c.tracking === 'cross-version' ? '跨版核对' : '当次起跟踪' }}</td>
                  <td>
                    <div v-if="c.old_segment" class="excerpt-cell">
                      <div class="muted">[{{ c.old_segment.region }} · 第{{ c.old_segment.page }}页]</div>
                      <div>{{ c.old_segment.text }}</div>
                    </div>
                    <span v-else>—</span>
                  </td>
                  <td>
                    <div v-if="c.new_segment" class="excerpt-cell">
                      <div class="muted">[{{ c.new_segment.region }} · 第{{ c.new_segment.page }}页]</div>
                      <div>{{ c.new_segment.text }}</div>
                    </div>
                    <span v-else>—</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else class="muted">本次对比无段落改动。</p>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

const ENDPOINT = '/api/content-diff'
const activeTab = ref<'snapshot' | 'diff' | 'event'>('diff')
const errorMessage = ref('')

type Row = Record<string, any>

const snapshotColumns = ['snapshot_no', 'url', 'rule_code', 'captured_at', 'page_count', 'segment_count', 'missing_ranges', 'excluded_hits', 'refetch_of']
const diffColumns = ['diff_no', 'status', 'old_snapshot_no', 'new_snapshot_no', 'old_captured_at', 'new_captured_at', 'change_count', 'date_change_count', 'cross_version_regions', 'new_track_regions', 'missing']
const eventColumns = ['event_no', 'kind', 'date_changed', 'excerpt', 'old_captured_at', 'new_captured_at', 'notify_status']

const stats = ref([
  { label: '采集快照', value: 0 },
  { label: '待补采判定', value: 0 },
  { label: '段落改动事件', value: 0 },
  { label: '待通知日期变更', value: 0 },
])

const snapshots = ref<Row[]>([])
const snapshotTotal = ref(0)
const snapshotFilters = ref<Record<string, string>>({})

const diffs = ref<Row[]>([])
const diffTotal = ref(0)
const diffFilters = ref<Record<string, string>>({})

const events = ref<Row[]>([])
const eventTotal = ref(0)
const eventFilters = ref<Record<string, string>>({})

const rawModal = ref<Row | null>(null)
const diffModal = ref<Row | null>(null)
const refetchTarget = ref<Row | null>(null)
const refetchForm = ref<{ captured_at: string; raw_html: string }>({ captured_at: '', raw_html: '' })

function formatRanges(ranges: number[][]): string {
  return (ranges || []).map(([a, b]) => (a === b ? `第${a}页` : `第${a}-${b}页`)).join('、')
}
function statusClass(status: string): string {
  return status === '待补采' ? 'warn-text' : status === '无变化' ? 'muted' : ''
}
function notifyClass(status: string): string {
  return status === '待通知' ? 'warn-text' : status === '前台已确认' ? 'muted' : ''
}
function kindLabel(kind: string): string {
  const map: Record<string, string> = {
    modified: '内容更正',
    moved: '区段迁移',
    'moved-modified': '迁移并更正',
    added: '新增段落',
    deleted: '删除段落',
    unchanged: '无变化',
  }
  return map[kind] || kind
}

async function getJson(path: string) {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return response.json()
}

async function loadSnapshots() {
  const query = new URLSearchParams(snapshotFilters.value).toString()
  const data = await getJson(`${ENDPOINT}/snapshots?size=200&${query}`)
  snapshots.value = data.items
  snapshotTotal.value = data.total
}
function resetSnapshotFilters() {
  snapshotFilters.value = {}
  void loadSnapshots()
}

async function loadDiffs() {
  const query = new URLSearchParams(diffFilters.value).toString()
  const data = await getJson(`${ENDPOINT}/diffs?size=200&${query}`)
  diffs.value = data.items
  diffTotal.value = data.total
}
function resetDiffFilters() {
  diffFilters.value = {}
  void loadDiffs()
}

async function loadEvents() {
  const query = new URLSearchParams(eventFilters.value).toString()
  const data = await getJson(`${ENDPOINT}/events?size=200&${query}`)
  events.value = data.items
  eventTotal.value = data.total
}
function resetEventFilters() {
  eventFilters.value = {}
  void loadEvents()
}

async function refreshStats() {
  const [snap, diff, evt] = await Promise.all([
    getJson(`${ENDPOINT}/snapshots?size=200`),
    getJson(`${ENDPOINT}/diffs?size=200`),
    getJson(`${ENDPOINT}/events?size=200&date_changed=true`),
  ])
  stats.value[0].value = snap.total
  stats.value[1].value = diff.items.filter((d: Row) => d.status === '待补采').length
  stats.value[2].value = (await getJson(`${ENDPOINT}/events?size=200`)).total
  stats.value[3].value = evt.items.filter((e: Row) => e.notify_status === '待通知').length
}

function openRaw(row: Row) {
  rawModal.value = row
}

function openDiff(row: Row) {
  diffModal.value = row
}

function openRefetch(row: Row) {
  errorMessage.value = ''
  refetchTarget.value = row
  refetchForm.value = { captured_at: '', raw_html: '' }
}

async function submitRefetch() {
  if (!refetchTarget.value) return
  try {
    const response = await request(`${ENDPOINT}/snapshots/${refetchTarget.value.id}/refetch`, {
      method: 'POST',
      body: JSON.stringify({ values: refetchForm.value }),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.message || '补采失败')
    refetchTarget.value = null
    await Promise.all([loadSnapshots(), refreshStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补采失败'
  }
}

async function runEventAction(row: Row, action: string) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/events/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.message || '动作未生效')
    await Promise.all([loadEvents(), refreshStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '通知动作失败'
  }
}

onMounted(async () => {
  try {
    await Promise.all([loadSnapshots(), loadDiffs(), loadEvents(), refreshStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '正文变动判定数据读取失败'
  }
})
</script>

<style scoped>
.warn-text { color: #b42318; font-weight: 600; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.modal-wide { width: 760px; }
.raw-box { background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 6px; font-size: 12px; max-height: 360px; overflow: auto; white-space: pre-wrap; }
.raw-input { font-family: monospace; font-size: 12px; padding: 8px; border: 1px solid var(--border); border-radius: 6px; }
.excerpt-cell { display: flex; flex-direction: column; gap: 2px; max-width: 320px; }
.scope-box { background: #f8fafc; border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; font-size: 13px; }
.scope-box p { margin: 4px 0; }
select { padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
</style>
