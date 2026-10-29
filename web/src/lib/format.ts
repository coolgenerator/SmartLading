export const usd = (v: number, digits = 0) =>
  (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits })

export const usdK = (v: number) => {
  const a = Math.abs(v), s = v < 0 ? '−$' : '$'
  if (a >= 1e6) return s + (a / 1e6).toFixed(2) + 'M'
  if (a >= 1e3) return s + (a / 1e3).toFixed(a >= 1e5 ? 0 : 1) + 'k'
  return s + a.toFixed(0)
}

export const pct = (v: number, digits = 0) => (v * 100).toFixed(digits) + '%'
export const num = (v: number) => Math.round(v).toLocaleString('en-US')
export const runway = (d: number, horizon = 120) => (d > horizon ? `>${horizon}` : String(d))

export const PARAM_LABEL: Record<string, string> = {
  tariff_rate: 'Tariff rate',
  lead_time_mean_days: 'Lead time (mean)',
  lead_time_std_days: 'Lead time (spread)',
  default_prob: 'Default probability',
  unit_cost: 'Unit cost',
  unit_freight: 'Unit freight',
  moq: 'Minimum order qty',
  prepay_ratio: 'Prepay ratio',
}

export const RISK_LABEL: Record<string, string> = {
  demand: 'Demand swings',
  lead_time: 'Lead-time slips',
  tariff: 'Tariff jumps',
  default: 'Supplier default',
}

export function formatChange(parameter: string, type: string, value: number) {
  const isRatio = parameter === 'tariff_rate' || parameter === 'prepay_ratio' || parameter === 'default_prob'
  const v = isRatio && type !== 'multiply' ? pct(value, value * 100 % 1 ? 1 : 0) : type === 'multiply' ? `×${value}` : parameter.includes('days') ? `${value} days` : String(value)
  if (type === 'set') return `→ ${v}`
  if (type === 'delta') return (value >= 0 ? '+' : '') + v
  return v
}
