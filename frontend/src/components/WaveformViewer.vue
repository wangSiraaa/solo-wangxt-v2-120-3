<template>
  <div class="card">
    <div class="row" style="justify-content: space-between">
      <h2>波形与到时（BHZ · ObsPy 解析 MiniSEED）</h2>
      <div class="row">
        <label v-for="st in stationCodes" :key="st" style="margin:0">
          <input type="radio" name="sta" :value="st" v-model="station" />
          <span style="margin-left:3px">{{ st }}</span>
        </label>
      </div>
    </div>

    <div v-if="loading" class="muted">加载波形…</div>
    <div v-else-if="error" class="warnbox bad">{{ error }}</div>
    <div v-else>
      <div ref="plotEl" style="height: 320px"></div>
      <div class="muted" style="margin-top:4px">
        实线 = 参与定位的有效到时（<span :style="{color:'var(--p-phase)'}">红 P</span> /
        <span :style="{color:'var(--s-phase)'}">蓝 S</span>）；绿色粗线 = 人工修订；
        灰色虚线 = 合成真值（仅教学可见）。<b>点击波形任意位置</b>可在该处放置修订标记。
      </div>

      <div v-if="pendingOffset !== null" class="card" style="background:var(--panel2); margin-top:8px">
        <div class="row">
          <span>在偏移 <b class="mono">{{ pendingOffset.toFixed(2) }} s</b> 处修订：</span>
          <button class="sm" :class="{primary: pendingPhase==='P'}" @click="pendingPhase='P'">P 到时</button>
          <button class="sm" :class="{primary: pendingPhase==='S'}" @click="pendingPhase='S'">S 到时</button>
          <input v-model="note" placeholder="修订说明（可选）" style="width:200px" />
          <button class="primary sm" @click="saveRevise">保存修订</button>
          <button class="sm" @click="pendingOffset = null">取消</button>
        </div>
        <div class="muted" style="margin-top:4px">
          原始拾取只读、永不覆盖；修订写入独立的 manual 字段并改变拾取数据版本。
        </div>
      </div>

      <div v-if="pendingPhase && pendingOffset === null" class="row" style="margin-top:8px">
        <span class="tag" :class="pendingPhase">{{ pendingPhase }}</span>
        <span class="muted">点击波形选择新的到时位置</span>
      </div>
      <div v-else-if="pendingOffset === null" class="row" style="margin-top:8px">
        <button class="sm" @click="startRevise('P')">修订 P</button>
        <button class="sm" @click="startRevise('S')">修订 S</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import Plotly from 'plotly.js-dist-min'
import { api } from '../lib/api.js'

const props = defineProps({
  scenarioKey: String,
  stationCodes: { type: Array, default: () => [] },
  picks: { type: Array, default: () => [] },
})
const emit = defineEmits(['revised'])

const plotEl = ref(null)
const station = ref(props.stationCodes[0] || '')
const loading = ref(false)
const error = ref('')
let wf = null
const pendingOffset = ref(null)
const pendingPhase = ref('P')
const note = ref('')
let plotlyHandler = null

watch(() => props.stationCodes, (codes) => {
  if (codes.length && !codes.includes(station.value)) station.value = codes[0]
}, { immediate: true })

watch(station, loadWaveform)
watch(() => props.picks, () => { if (wf) redraw() }, { deep: false })

onMounted(async () => {
  if (station.value) await loadWaveform()
})
onBeforeUnmount(() => {
  if (plotEl.value && plotlyHandler) plotEl.value.removeListener('plotly_click', plotlyHandler)
})

async function loadWaveform() {
  if (!station.value) return
  loading.value = true
  error.value = ''
  pendingOffset.value = null
  try {
    wf = await api.waveform(props.scenarioKey, station.value)
    redraw()
  } catch (e) {
    error.value = String(e.message || e)
  } finally {
    loading.value = false
  }
}

function startRevise(phase) {
  pendingPhase.value = phase
  pendingOffset.value = null
}

function phaseColor(ph) {
  return ph === 'P' ? '#f85149' : '#58a6ff'
}

function redraw() {
  const trace = {
    x: wf.times_s,
    y: wf.counts,
    type: 'scattergl',
    mode: 'lines',
    line: { color: '#9fb3c8', width: 1 },
    name: `${wf.station_code} BHZ`,
  }
  const shapes = []
  const annotations = []
  for (const pk of wf.picks) {
    // 真值：灰色虚线
    if (pk.true_offset_s != null) {
      shapes.push({
        type: 'line', xref: 'x', yref: 'paper', x0: pk.true_offset_s, x1: pk.true_offset_s,
        y0: 0, y1: 1, line: { color: '#6e7681', width: 1, dash: 'dashdot' },
        layer: 'below',
      })
    }
    if (pk.source === 'missing') {
      annotations.push({
        x: pk.true_offset_s ?? 5, y: 1, yref: 'paper', text: `${pk.phase} 缺测`,
        showarrow: false, font: { color: '#f85149', size: 10 }, bgcolor: '#2d1717',
      })
      continue
    }
    const isManual = pk.source === 'manual'
    shapes.push({
      type: 'line', xref: 'x', yref: 'paper', x0: pk.offset_s, x1: pk.offset_s,
      y0: 0, y1: 1,
      line: { color: isManual ? '#3fb950' : phaseColor(pk.phase), width: isManual ? 2.5 : 1.5 },
    })
    annotations.push({
      x: pk.offset_s, y: 1, yref: 'paper', text: `${pk.phase}${isManual ? '✎' : ''}`,
      showarrow: false,
      font: { color: isManual ? '#3fb950' : phaseColor(pk.phase), size: 11 },
      bgcolor: 'rgba(15,20,32,.7)',
    })
  }
  if (pendingOffset.value !== null) {
    shapes.push({
      type: 'line', xref: 'x', yref: 'paper', x0: pendingOffset.value, x1: pendingOffset.value,
      y0: 0, y1: 1, line: { color: '#e3b341', width: 2, dash: 'dot' },
    })
  }

  const layout = {
    margin: { l: 55, r: 15, t: 25, b: 38 },
    paper_bgcolor: '#181f2e', plot_bgcolor: '#10151f',
    font: { color: '#c9d4e0', size: 11 },
    xaxis: { title: { text: '相对记录起始时间 (s)' }, gridcolor: '#232d3d', zeroline: false },
    yaxis: { title: { text: 'counts' }, gridcolor: '#232d3d', zeroline: false },
    shapes, annotations,
    hovermode: 'x unified',
  }
  const config = { scrollZoom: true, displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'] }
  Plotly.react(plotEl.value, [trace], layout, config)

  if (plotlyHandler) plotEl.value.removeListener('plotly_click', plotlyHandler)
  plotlyHandler = (evt) => {
    if (evt?.points?.length) {
      pendingOffset.value = Number(evt.points[0].x.toFixed(3))
    }
  }
  plotEl.value.on('plotly_click', plotlyHandler)
}

async function saveRevise() {
  if (pendingOffset.value === null) return
  const pick = props.picks.find(p => p.station_code === station.value && p.phase === pendingPhase.value)
  if (!pick) return
  const epoch = wf.starttime_epoch + pendingOffset.value
  await api.revisePick(pick.id, {
    manual_time_epoch: Number(epoch.toFixed(3)),
    note: note.value || '波形上点击修订',
    author: 'student',
  })
  pendingOffset.value = null
  note.value = ''
  emit('revised')
  await loadWaveform()
}
</script>
