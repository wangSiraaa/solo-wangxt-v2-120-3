<template>
  <header class="app-header">
    <h1>TeachLoc · 地震定位教学系统</h1>
    <span class="sub">波形到时 → 候选震源位置（Geiger 最小二乘 · 简化均匀半空间模型）</span>
    <span style="flex:1"></span>
    <span class="sub mono" v-if="health">数据 {{ dataVersion }} · 存储 {{ health.postgis ? 'PostGIS' : 'SQLite' }}</span>
  </header>
  <div class="disclaimer">
    ⚠️ 教学演示系统，<b>不是地震预警 / 速报产品</b>。结果仅在所标注的简化速度模型与
    合成数据版本下成立；真实定位需分层速度模型、质量控制与人工值守。台站不足时系统会
    明确报告「不可定位」，而不会输出一个看似精确的坐标。
  </div>

  <div class="layout">
    <aside class="sidebar">
      <div class="card">
        <h2>教学案例（源位置已知）</h2>
        <button v-for="s in scenarios" :key="s.key" class="scenario-item"
                :class="{active: s.key===scenarioKey}" @click="scenarioKey=s.key">
          <div class="t">{{ s.title }}</div>
          <div class="d">{{ s.description }}</div>
        </button>
      </div>

      <div v-if="scenario" class="card">
        <h2>本案例信息</h2>
        <dl class="kv">
          <dt>真值经纬度</dt>
          <dd class="mono">{{ scenario.true_lon.toFixed(4) }}, {{ scenario.true_lat.toFixed(4) }}</dd>
          <dt>真值深度</dt><dd>{{ scenario.true_depth_km }} km</dd>
          <dt>真值发震时刻</dt><dd class="mono" style="font-size:11px">{{ fmtEpoch(scenario.true_origin_epoch,2) }}Z</dd>
          <dt>数据版本</dt><dd class="mono">{{ scenario.data_version }}</dd>
          <dt>拾取版本</dt>
          <dd class="mono" :style="{color: pickVersionDirty?'var(--bad)':'var(--good)'}"
              :title="pickVersionDirty?'已相对原始拾取发生人工修订':'全部为原始自动拾取'">
            {{ pickVersion || '…' }}
          </dd>
        </dl>
        <div class="muted" style="margin-top:6px">{{ scenario.teaching_note }}</div>
        <div class="muted" style="margin-top:6px">
          {{ pickVersionInfo.n_picks }} 条拾取 ·
          {{ pickVersionInfo.n_manual }} 条人工修订 ·
          {{ pickVersionInfo.n_missing }} 条缺测
        </div>
      </div>

      <div class="card" v-if="models.length">
        <h2>可用速度模型</h2>
        <div v-for="m in models" :key="m.model_id" style="margin-bottom:6px">
          <div style="font-size:12px">{{ m.name }}</div>
          <div class="muted">v<sub>P</sub>={{ m.vp_km_s }} / v<sub>S</sub>={{ m.vs_km_s }} km/s ·
            <span class="mono">{{ m.model_id }}</span></div>
        </div>
      </div>
    </aside>

    <main class="main">
      <LocationPanel
        :models="models" :runs="runs" :selected-run="selectedRun"
        :scenario-key="scenarioKey" :current-pick-version="pickVersion"
        @located="onLocated" @select="selectedRun=$event"
        @refresh-runs="loadRuns" />

      <div class="grid2">
        <GeometryMap :stations="scenarioStations" :scenario="scenario"
                     :runs="runs" :selected-run="selectedRun" />
        <WaveformViewer :key="'wf-'+scenarioKey" :scenario-key="scenarioKey"
                        :station-codes="scenarioStations.map(s=>s.code)"
                        :picks="picks" @revised="loadPicks" />
      </div>

      <PickTable :picks="picks" @clear="clearManual" />

      <div class="footer-note">
        P、S 震相分别独立定位，严禁混用同一残差向量；残差 = 观测到时 − 理论到时；
        所有候选解均绑定速度模型 ID、合成数据版本与拾取内容哈希，便于解释与复算。
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api, fmtEpoch } from './lib/api.js'
import GeometryMap from './components/GeometryMap.vue'
import WaveformViewer from './components/WaveformViewer.vue'
import PickTable from './components/PickTable.vue'
import LocationPanel from './components/LocationPanel.vue'
import { DATA_VERSION_CONST } from './lib/versions.js'

const health = ref(null)
const models = ref([])
const scenarios = ref([])
const scenarioKey = ref('nominal')
const picks = ref([])
const runs = ref([])
const selectedRun = ref(null)
const pickVersionInfo = ref({ pick_data_version: '', n_picks: 0, n_manual: 0, n_missing: 0 })

const dataVersion = DATA_VERSION_CONST
const scenario = computed(() => scenarios.value.find(s => s.key === scenarioKey.value) || null)
const pickVersion = computed(() => pickVersionInfo.value.pick_data_version)
const pickVersionDirty = computed(() => pickVersionInfo.value.n_manual > 0)

const scenarioStations = computed(() => {
  const map = new Map()
  for (const p of picks.value) {
    if (!map.has(p.station_code)) {
      map.set(p.station_code, { code: p.station_code, lon: p.station_lon, lat: p.station_lat })
    }
  }
  return [...map.values()].sort((a, b) => a.code.localeCompare(b.code))
})

onMounted(async () => {
  health.value = await api.health().catch(() => null)
  models.value = await api.models()
  scenarios.value = await api.scenarios()
})

watch(scenarioKey, loadScenario, { immediate: true })

async function loadScenario() {
  selectedRun.value = null
  await Promise.all([loadPicks(), loadRuns()])
}

async function loadPicks() {
  picks.value = await api.picks(scenarioKey.value)
  pickVersionInfo.value = await api.picksVersion(scenarioKey.value)
}

async function loadRuns() {
  runs.value = await api.runs(scenarioKey.value)
  if (selectedRun.value) {
    const still = runs.value.find(r => r.id === selectedRun.value.id)
    selectedRun.value = still || null
  }
}

async function onLocated(created) {
  await loadRuns()
  selectedRun.value = runs.value.find(r => r.id === created.id) || created
}

async function clearManual(id) {
  await api.clearManual(id)
  await loadPicks()
}
</script>
