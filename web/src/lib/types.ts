// Shapes follow docs/design.md §1 so the mock layer can be swapped for /api/v1 later.

export interface Brand {
  id: string
  name: string
  cash_balance: number
  credit_limit: number
  daily_fixed_cost: number
  safety_line_days: number
  cash_safety_line: number
  state_version: number
}

export interface SKU {
  id: string
  name: string
  category: string
  price: number
  unit_platform_fee: number
  on_hand: number
  hts_code: string
  tariff_rate: number
  daily_demand: number
}

export interface Supplier {
  id: string
  name: string
  city: string
  country: string
  lat: number
  lng: number
  lead_time_mean_days: number
  lead_time_std_days: number
  moq: number
  default_prepay_ratio: number
  risk_score: number
  default_prob: number
}

export interface SupplierOffer {
  sku_id: string
  supplier_id: string
  unit_cost: number
  unit_freight: number
}

export type POStatus = 'planned' | 'in_transit' | 'arrived'

export interface PurchaseOrder {
  id: string
  sku_id: string
  supplier_id: string
  quantity: number
  prepay_ratio: number
  ship_day: number // days relative to today (negative = already shipped)
  eta_day: number
  status: POStatus
}

export interface ScenarioOption {
  id: string
  label: string
  quantity: number
  prepay_ratio: number | null
  unit_cost?: number | null
}

export interface CashFan {
  days: number[]
  p10: number[]
  p50: number[]
  p90: number[]
  safety_line: number
}

export type RiskSource = 'demand' | 'lead_time' | 'tariff' | 'default'

export interface OptionMetrics {
  option_id: string
  quantity: number
  prepay_ratio: number
  runway_p10: number
  runway_p50: number
  runway_p90: number
  stockout_prob: number
  expected_profit: number
  worst_case_p5: number
  credit_breach_prob: number
  default_loss_prob: number
  risk_attribution: Partial<Record<RiskSource, number>>
  cash_fan: CashFan
}

export interface SimulationResult {
  seed: number
  horizon_days: number
  n_paths: number
  elapsed_ms: number
  options: OptionMetrics[]
}

export interface Recommendation {
  recommended_option_id: string
  rule: 'max_profit_under_runway_constraint' | 'min_risk_fallback'
  feasible_option_ids: string[]
  min_runway_days: number
  warning: string | null
  counterfactual_option_id: string | null
}

export interface Explanation {
  status: 'ok' | 'rejected_number_mismatch' | 'llm_error' | 'pending'
  sections: { reason: string; main_risks: string; counterfactual: string } | null
}

export interface Scenario {
  id: string
  sku_id: string
  supplier_id: string
  options: ScenarioOption[]
  seed: number
  state_version: number
  result: SimulationResult | null
  recommendation: Recommendation | null
  selected_option_id: string | null
}

export type SignalParameter =
  | 'tariff_rate'
  | 'lead_time_mean_days'
  | 'lead_time_std_days'
  | 'default_prob'
  | 'unit_cost'
  | 'unit_freight'
  | 'moq'
  | 'prepay_ratio'

export type SignalStatus = 'pending' | 'accepted' | 'rejected'

export interface RiskSignal {
  id: string
  source_text: string
  source_type: 'tariff' | 'supplier_news' | 'other'
  quote: string
  quote_span: [number, number]
  target_type: 'hts_code' | 'supplier' | 'sku'
  target_id: string
  parameter: SignalParameter
  change_type: 'set' | 'delta' | 'multiply'
  change_value: number
  probability: number
  llm_probability: number | null
  effective_day: number
  status: SignalStatus
  edited_by_user: boolean
  affected_skus: string[]
}

export interface Alert {
  id: string
  event_id: string
  purchase_order_id: string
  extra_cost: number
  cash_gap: number
  message: string
  next_step: string
  acknowledged: boolean
}

export interface PresetEvent {
  id: string
  name: string
  description: string
  signals: Omit<RiskSignal, 'id' | 'status' | 'edited_by_user' | 'source_text' | 'quote_span' | 'affected_skus'>[]
}

export interface Terms {
  prepay_ratio: number
  quantity: number
  unit_cost: number
}

export interface NegotiationTurn {
  role: 'user' | 'factory'
  message: string
  terms: Terms
  impact: OptionMetrics | null
}
