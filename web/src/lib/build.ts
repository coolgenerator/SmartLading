// Derived values come from the API (models' computed fields); these keep call sites short.
import type { Brand, Supplier } from './types'

export const safetyLine = (b: Brand) => b.cash_safety_line
export const defaultProb = (s: Supplier) => s.default_prob
