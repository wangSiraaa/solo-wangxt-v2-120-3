// 后端 API 封装。所有时间都是 UTC 历元秒（浮点）。
const BASE = '/api'

async function req(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  health: () => req('/health'),
  models: () => req('/models'),
  scenarios: () => req('/scenarios'),
  scenario: (key) => req(`/scenarios/${key}`),
  picks: (key) => req(`/scenarios/${key}/picks`),
  picksVersion: (key) => req(`/scenarios/${key}/picks/version`),
  waveform: (key, code) => req(`/scenarios/${key}/waveforms/${code}`),
  revisePick: (id, body) => req(`/scenarios/picks/${id}`, {
    method: 'PATCH', body: JSON.stringify(body),
  }),
  clearManual: (id) => req(`/scenarios/picks/${id}/manual`, { method: 'DELETE' }),
  locate: (body) => req('/scenarios/locate', {
    method: 'POST', body: JSON.stringify(body),
  }),
  runs: (key) => req(`/scenarios/${key}/runs`),
  run: (id) => req(`/scenarios/runs/${id}`),
  deleteRun: (id) => req(`/scenarios/runs/${id}`, { method: 'DELETE' }),
}

export function fmtEpoch(epoch, digits = 2) {
  if (epoch === null || epoch === undefined) return '—'
  const d = new Date(epoch * 1000)
  const p = (n, l = 2) => String(n).padStart(l, '0')
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
    `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}` +
    `.${p(d.getUTCMilliseconds(), 3)}`.slice(0, digits === 3 ? 4 : 3)
}

export function fmtClock(epoch) {
  if (epoch === null || epoch === undefined) return '—'
  const d = new Date(epoch * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`
}

// 公里 -> 经纬度偏移（与后端 equirectangular 近似一致，仅用于画误差椭圆）
export function kmToDeg(dxKm, dyKm, lat0) {
  const R = 6371.0
  return [
    (dxKm / R) * 180 / Math.PI / Math.cos(lat0 * Math.PI / 180),
    (dyKm / R) * 180 / Math.PI,
  ]
}
