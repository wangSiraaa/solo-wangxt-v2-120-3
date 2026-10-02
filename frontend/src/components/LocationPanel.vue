<template>
  <div class="card">
    <h2>定位求解</h2>
    <div class="muted" style="margin-bottom:8px">
      Geiger 最小二乘：tᵢ = t₀ + Dᵢ/v，4 个未知量（经度/纬度/深度/发震时刻），
      单次定位<b>只允许单一震相</b>。
    </div>
    <div class="row">
      <label>震相
        <select v-model="phase">
          <option value="P">P 波（单独）</option>
          <option value="S">S 波（单独）</option>
        </select>
      </label>
      <label>速度模型
        <select v-model="modelId">
          <option v-for="m in models" :key="m.model_id" :value="m.model_id">
            {{ m.name }}
          </option>
        </select>
      </label>
      <label style="display:flex;align-items:center;gap:4px">
        <input type="checkbox" v-model="robust" /> 稳健拟合 soft_l1
      </label>
      <button class="primary" :disabled="busy" @click="doLocate">
        {{ busy ? '求解中…' : '运行定位并保存候选解' }}
      </button>
      <button class="sm" @click="$emit('refresh-runs')">刷新候选列表</button>
    </div>
    <div v-if="error" class="warnbox bad" style="margin-top:8px">{{ error }}</div>

    <div v-if="selectedModel" style="margin-top:8px">
      <h3>{{ selectedModel.name }} 的明确假设</h3>
      <ul class="muted" style="margin:2px; padding-left:18px">
        <li v-for="a in selectedModel.assumptions" :key="a">{{ a }}</li>
      </ul>
    </div>

    <div style="margin-top:10px">
      <h3>候选解（点击选中并在地图/残差中比较）</h3>
      <table>
        <thead>
          <tr>
            <th>#</th><th>标签</th><th>震相</th><th>状态</th>
            <th>经度</th><th>纬度</th><th>深度km</th><th>RMS(s)</th><th>最大残差(s)</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!runs.length"><td colspan="10" class="muted">尚无候选解，点上方按钮运行。</td></tr>
          <tr v-for="r in runs" :key="r.id" class="run-pick"
              :class="{active: selectedRun?.id===r.id}" @click="$emit('select',r)">
            <td>{{ r.id }}
              <span v-if="currentPickVersion && r.pick_data_version!==currentPickVersion"
                    class="tag warn" title="该候选解计算后拾取数据已被修订，版本过期">过期</span>
            </td>
            <td style="text-align:left">{{ r.label }}</td>
            <td><span class="tag" :class="r.phase">{{ r.phase }}</span></td>
            <td>
              <span v-if="!r.locatable" class="tag bad">不可定位</span>
              <span v-else class="tag good">已定位</span>
            </td>
            <td class="mono">{{ r.lon?.toFixed(4) ?? '—' }}</td>
            <td class="mono">{{ r.lat?.toFixed(4) ?? '—' }}</td>
            <td class="mono">{{ r.depth_km?.toFixed(2) ?? '—' }}</td>
            <td :class="rmsClass(r.rms_s)">{{ r.rms_s?.toFixed(3) ?? '—' }}</td>
            <td :class="rmsClass(r.max_abs_residual_s)">{{ r.max_abs_residual_s?.toFixed(2) ?? '—' }}</td>
            <td @click.stop>
              <button class="sm danger" @click="remove(r.id)">删</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-if="run" class="card">
    <h2>候选解 #{{ run.id }} 详情：不止一个坐标</h2>

    <div v-if="currentPickVersion && run.pick_data_version!==currentPickVersion" class="warnbox">
      该候选解基于旧版拾取数据（哈希 {{ run.pick_data_version }}）计算，当前拾取已被修订为
      {{ currentPickVersion }}。旧结果保留用于对比，但请重新运行定位以获得可复算的当前解。
    </div>

    <div v-if="!run.locatable" class="notlocatable">
      <div style="font-weight:650;margin-bottom:4px">⛔ 本数据配置下不可定位（不输出坐标）</div>
      <div>{{ run.reason }}</div>
    </div>

    <template v-else>
      <div class="grid2">
        <dl class="kv">
          <dt>经度 / 纬度</dt>
          <dd class="mono">{{ run.lon.toFixed(5) }}°E, {{ run.lat.toFixed(5) }}°N</dd>
          <dt>深度</dt>
          <dd class="mono">{{ run.depth_km.toFixed(2) }} km
            <span v-if="run.uncertainty?.depth_sigma_km==null" class="tag bad">深度不可分辨</span>
            <span v-else class="muted"> ±{{ run.uncertainty.depth_sigma_km }} km (1σ)</span>
          </dd>
          <dt>发震时刻</dt>
          <dd class="mono">{{ fmtEpoch(run.origin_time_epoch,2) }} UTC
            <span v-if="run.uncertainty?.origin_time_sigma_s" class="muted">
              ±{{ run.uncertainty.origin_time_sigma_s }}s</span></dd>
          <dt>使用到时 / 自由度</dt><dd>{{ run.n_used }} 个 / {{ run.dof }}</dd>
        </dl>
        <dl class="kv">
          <dt>RMS 残差</dt><dd>{{ run.rms_s.toFixed(3) }} s</dd>
          <dt>水平 1σ 椭圆半轴</dt>
          <dd>{{ run.uncertainty?.ellipse_semi_axes_km?.join(' / ') }} km
            ，长轴方位 {{ run.uncertainty?.ellipse_major_axis_azimuth_deg }}°</dd>
          <dt>方差估计</dt><dd class="muted">{{ run.uncertainty?.variance_note }}</dd>
          <dt>雅可比秩</dt><dd>{{ run.uncertainty?.jacobian_rank }} / 4</dd>
        </dl>
      </div>

      <div v-if="run.truth" class="warnbox"
           :class="{ bad: run.truth.horizontal_error_km > 5, good: run.truth.horizontal_error_km <= 2 }">
        <b>与已知合成真值的偏差（真实业务没有真值可比，仅教学）：</b>
        水平误差 <b>{{ run.truth.horizontal_error_km }} km</b>，
        深度误差 {{ run.truth.depth_error_km }} km
        <template v-if="run.truth.origin_time_error_s!=null">
          ，发震时刻误差 {{ (run.truth.origin_time_error_s>=0?'+':'') + run.truth.origin_time_error_s }} s
        </template>。
        <span class="muted">注意：RMS 小 ≠ 位置准，错误拾取/几何退化会把解拉偏却保持小残差。</span>
      </div>

      <h3>逐台站残差（观测 − 理论到时，秒）</h3>
      <div class="scroll">
        <table>
          <thead><tr>
            <th>台站</th><th>震相</th><th>到时来源</th><th>残差(s)</th><th>判定</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in run.residuals" :key="row.pick_id"
                :class="{suspect: row.flag==='suspect'}">
              <td>{{ row.station_code }}</td>
              <td><span class="tag" :class="row.phase">{{ row.phase }}</span></td>
              <td><span class="tag raw">{{ row.time_source==='manual'?'人工':'原始' }}</span></td>
              <td :class="resClass(row.residual_s)" style="font-weight:650">
                {{ (row.residual_s>=0?'+':'') + row.residual_s.toFixed(2) }}
              </td>
              <td>
                <span v-if="row.flag==='suspect'" class="tag bad">|残差|&gt;0.6s 可疑</span>
                <span v-else class="tag good">正常</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <div v-if="run.warnings.length" style="margin-top:8px">
      <h3>诊断与警告</h3>
      <div v-for="(w,i) in run.warnings" :key="i"
           class="warnbox"
           :class="{ bad: w.includes('不可分辨') || w.includes('严重') || w.includes('疑似错误') }">
        {{ w }}
      </div>
    </div>

    <div style="margin-top:8px">
      <h3>模型 / 数据版本绑定（重算可解释）</h3>
      <dl class="kv mono" style="font-size:11.5px">
        <dt>速度模型</dt><dd>{{ run.model_id }}</dd>
        <dt>合成数据版本</dt><dd>{{ run.data_version }}</dd>
        <dt>拾取数据版本(内容哈希)</dt><dd>{{ run.pick_data_version }}</dd>
        <dt>拾取表结构版本</dt><dd>{{ run.pick_schema_version }}</dd>
        <dt>求解器版本</dt><dd>{{ run.app_version }}</dd>
      </dl>
      <div class="muted" style="margin-top:4px">
        人工修订任一拾取都会改变「拾取数据版本」；此候选解是在上述版本下算出的，
        版本变化后应重新运行定位以便对比。输入快照保存了当时每条拾取的取值与来源。
        <details style="margin-top:4px">
          <summary style="cursor:pointer">查看输入快照（{{ run.input_snapshot.length }} 条）</summary>
          <div class="scroll mono" style="font-size:11px;margin-top:4px">
            <div v-for="s in run.input_snapshot" :key="s.pick_id"
                 :style="{color: s.excluded?'var(--bad)':(s.time_source==='missing'?'var(--muted)':'inherit')}">
              pick#{{ s.pick_id }} {{ s.station_code }} {{ s.phase }}
              t={{ s.effective_time_epoch?.toFixed(3) ?? 'null' }}
              [{{ s.time_source }}{{ s.raw_status!=='ok' ? '/'+s.raw_status : '' }}]
              {{ s.excluded ? '(用户排除)' : '' }}
            </div>
          </div>
        </details>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { api, fmtEpoch } from '../lib/api.js'

const props = defineProps({
  models: { type: Array, default: () => [] },
  runs: { type: Array, default: () => [] },
  selectedRun: Object,
  scenarioKey: String,
  currentPickVersion: String,
})
const emit = defineEmits(['located', 'select', 'refresh-runs'])

const phase = ref('P')
const modelId = ref('homog-crust-6.0-3.46-v1')
const robust = ref(false)
const busy = ref(false)
const error = ref('')

const run = computed(() => props.selectedRun)
const selectedModel = computed(() => props.models.find(m => m.model_id === modelId.value))

async function doLocate() {
  busy.value = true
  error.value = ''
  try {
    const created = await api.locate({
      scenario_key: props.scenarioKey,
      phase: phase.value,
      model_id: modelId.value,
      robust: robust.value,
      label: '',
    })
    emit('located', created)
  } catch (e) {
    error.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function remove(id) {
  await api.deleteRun(id)
  emit('refresh-runs')
}

function rmsClass(v) {
  if (v == null) return ''
  if (v > 0.6) return 'res-pos'
  if (v > 0.25) return 'res-neg'
  return 'res-ok'
}
function resClass(v) {
  if (Math.abs(v) > 0.6) return 'res-pos'
  if (Math.abs(v) > 0.3) return 'res-neg'
  return 'res-ok'
}
</script>
