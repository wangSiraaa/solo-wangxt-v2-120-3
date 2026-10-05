<template>
  <div class="card">
    <h2>到时表 —— 原始拾取与人工修订分开保存</h2>
    <div class="muted" style="margin-bottom:6px">
      raw 为自动拾取（合成发生器按固定种子生成，只读）；manual 为人工修订。
      定位始终使用 COALESCE(manual, raw)，缺测台站自动剔除。「对真值偏差」仅供教学对照。
    </div>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>台站</th><th>震相</th><th>原始到时(UTC)</th><th>raw−真值(s)</th>
            <th>状态</th><th>人工修订(UTC)</th><th>man−真值(s)</th><th>来源</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in picks" :key="p.id"
              :class="{ missing: p.effective_source==='missing',
                        suspect: p.raw_status==='shifted_outlier' }">
            <td>{{ p.station_code }}</td>
            <td><span class="tag" :class="p.phase">{{ p.phase }}</span></td>
            <td class="mono">{{ p.raw_time_epoch ? fmtEpoch(p.raw_time_epoch,2).slice(11) : '— 缺测 —' }}</td>
            <td :class="resClass(p.raw_minus_true_s)">
              {{ p.raw_minus_true_s != null ? (p.raw_minus_true_s>=0?'+':'') + p.raw_minus_true_s.toFixed(2) : '—' }}
            </td>
            <td>
              <span v-if="p.raw_status==='shifted_outlier'" class="tag bad">异常偏移</span>
              <span v-else-if="p.raw_time_epoch===null" class="tag missing">缺测</span>
              <span v-else class="tag good">正常</span>
            </td>
            <td class="mono">{{ p.manual_time_epoch ? fmtEpoch(p.manual_time_epoch,2).slice(11) : '—' }}</td>
            <td :class="resClass(p.manual_minus_true_s)">
              {{ p.manual_minus_true_s != null ? (p.manual_minus_true_s>=0?'+':'') + p.manual_minus_true_s.toFixed(2) : '—' }}
            </td>
            <td><span class="tag" :class="p.effective_source">{{ sourceLabel[p.effective_source] }}</span></td>
            <td>
              <button class="sm" :class="{primary: historyPickId===p.id}"
                      @click="toggleHistory(p)">记录</button>
              <button v-if="p.manual_time_epoch!=null" class="sm danger" @click="$emit('clear',p.id)">
                撤销修订
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="historyPick" class="history-panel">
      <div class="row" style="justify-content:space-between">
        <h3 style="margin:0">
          修订时间线 —— {{ historyPick.station_code }} ·
          <span class="tag" :class="historyPick.phase">{{ historyPick.phase }}</span>
          <span class="muted">（raw 原始到时 {{ fmtEpoch(historyPick.raw_time_epoch,2).slice(11) || '缺测' }}，只读）</span>
        </h3>
        <button class="sm" @click="historyPickId=null">关闭</button>
      </div>
      <div v-if="historyLoading" class="muted" style="margin-top:6px">加载记录…</div>
      <div v-else-if="!revisions.length" class="muted" style="margin-top:6px">
        尚无人工修订记录；在波形上点击放置修订后，这里会按时间顺序留下痕迹。
      </div>
      <ol v-else class="timeline">
        <li v-for="(r, i) in revisions" :key="r.id" :class="r.action">
          <div class="row" style="gap:6px">
            <span class="tl-idx mono">#{{ i + 1 }}</span>
            <span class="tag" :class="r.action==='revise' ? 'manual' : 'warn'">
              {{ r.action==='revise' ? '修订' : '撤销' }}
            </span>
            <span class="mono">{{ fmtEpoch(r.created_at_epoch,3) }}Z</span>
            <span class="muted">by</span><span>{{ r.author || '—' }}</span>
          </div>
          <div class="mono" style="margin-top:2px">
            {{ fmtVal(r.old_time_epoch) }} → {{ fmtVal(r.new_time_epoch) }}
          </div>
          <div v-if="r.note" class="muted">备注：{{ r.note }}</div>
        </li>
      </ol>
      <div class="muted" style="margin-top:6px">
        记录只增不改；定位始终使用当前有效到时 COALESCE(manual, raw)，已保存的候选解快照不受记录影响。
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { api, fmtEpoch } from '../lib/api.js'
const props = defineProps({ picks: { type: Array, default: () => [] } })
defineEmits(['clear'])
const sourceLabel = { raw: '原始', manual: '人工', missing: '缺测' }

const historyPickId = ref(null)
const revisions = ref([])
const historyLoading = ref(false)
const historyPick = computed(() =>
  props.picks.find(p => p.id === historyPickId.value) || null)

async function toggleHistory(p) {
  if (historyPickId.value === p.id) { historyPickId.value = null; return }
  historyPickId.value = p.id
  await loadRevisions()
}

async function loadRevisions() {
  if (!historyPickId.value) return
  historyLoading.value = true
  try {
    revisions.value = await api.pickRevisions(historyPickId.value)
  } finally {
    historyLoading.value = false
  }
}

// 修订/撤销后父组件会重载 picks，这里同步刷新已打开的时间线
watch(() => props.picks, () => { if (historyPickId.value) loadRevisions() })

function fmtVal(epoch) {
  return epoch == null ? '（raw 原始到时）' : fmtEpoch(epoch, 2).slice(11)
}

function resClass(v) {
  if (v == null) return 'res-ok'
  const a = Math.abs(v)
  if (a > 0.6) return 'res-pos'
  if (a > 0.3) return 'res-neg'
  return 'res-ok'
}
</script>
