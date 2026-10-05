<template>
  <div class="card">
    <div class="row" style="justify-content: space-between">
      <h2>修订时间线 —— 操作记录只追加</h2>
      <button v-if="filterPick" class="sm" @click="$emit('reset-filter')">
        显示全部（当前：{{ filterPick.station_code }}·{{ filterPick.phase }}）
      </button>
    </div>
    <div class="muted" style="margin-bottom:6px">
      每次人工修订 / 撤销都会留下一条记录：前后有效到时、作者、备注与时间。
      raw 到时始终只读；定位仍只使用当前有效到时，已保存的候选解快照不随这些记录变化。
    </div>
    <div v-if="!revisions.length" class="muted">
      尚无修订记录。在波形上点击放置修订，或在到时表中操作后，这里会出现时间线。
    </div>
    <div v-else class="scroll">
      <div v-for="(r, i) in revisions" :key="r.id" class="rev-item">
        <span class="rev-seq mono">#{{ i + 1 }}</span>
        <span class="tag" :class="r.action === 'undo' ? 'warn' : 'manual'">
          {{ r.action === 'undo' ? '↩ 撤销' : '✎ 修订' }}
        </span>
        <b>{{ r.station_code }}</b>
        <span class="tag" :class="r.phase">{{ r.phase }}</span>
        <span class="mono rev-change">
          <span :class="'src-' + r.old_source">{{ srcLabel[r.old_source] }} {{ fmtT(r.old_time_epoch) }}</span>
          →
          <span :class="'src-' + r.new_source">{{ srcLabel[r.new_source] }} {{ fmtT(r.new_time_epoch) }}</span>
        </span>
        <span class="muted">{{ r.author }}<template v-if="r.note">「{{ r.note }}」</template></span>
        <span class="muted mono rev-time">{{ fmtIso(r.created_at) }} UTC</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { fmtEpoch } from '../lib/api.js'

defineProps({
  revisions: { type: Array, default: () => [] },
  filterPick: { type: Object, default: null },
})
defineEmits(['reset-filter'])

const srcLabel = { raw: '原始', manual: '人工', missing: '缺测' }

function fmtT(epoch) {
  return epoch == null ? '—' : fmtEpoch(epoch, 2).slice(11)
}

// SQLite 返回的 ISO 时间可能不带时区后缀，统一按 UTC 解析
function fmtIso(iso) {
  if (!iso) return '—'
  const s = String(iso)
  const utc = s.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(s) ? s : s + 'Z'
  const d = new Date(utc)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
    `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`
}
</script>
