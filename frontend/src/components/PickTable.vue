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
              <button v-if="p.manual_time_epoch!=null" class="sm danger" @click="$emit('clear',p.id)">
                撤销修订
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { fmtEpoch } from '../lib/api.js'
defineProps({ picks: { type: Array, default: () => [] } })
defineEmits(['clear'])
const sourceLabel = { raw: '原始', manual: '人工', missing: '缺测' }
function resClass(v) {
  if (v == null) return 'res-ok'
  const a = Math.abs(v)
  if (a > 0.6) return 'res-pos'
  if (a > 0.3) return 'res-neg'
  return 'res-ok'
}
</script>
