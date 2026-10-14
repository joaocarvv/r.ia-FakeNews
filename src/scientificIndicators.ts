/** Indicadores recuperados do backend, não são percentuais de verdade. */
export type Counts = { supports: number; contradicts: number; neutral: number; uncertain: number }
export type Indicators = {
  retrieved: number | null
  assessed: number | null
  fullText: number | null
  coverage: number | null
  evidence: Counts | null
  methodology: string | null
  methodologyNote: string | null
}
export type OverallIndicators = Indicators & { claimsMeasured: number }

const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const count = (value: unknown): number | null =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null
const first = (...values: unknown[]): number | null => {
  for (const value of values) { const n = count(value); if (n !== null) return n }
  return null
}
const text = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value : null
const percentage = (total: number | null, part: number | null): number | null =>
  total !== null && part !== null && total > 0 && part <= total ? Math.round(part / total * 100) : null

export function readIndicators(value: unknown): Indicators {
  const data = object(value), summary = object(data.user_summary), reading = object(summary.reading)
  const verification = object(data.verification), partial = object(verification.partial_verification)
  const indicators = object(verification.indicators), coverage = object(indicators.search_coverage)
  const methodology = object(indicators.methodological_confidence)
  const e = object(summary.evidence_balance)
  const numbers = [count(e.SUPPORTS), count(e.CONTRADICTS), count(e.NEUTRAL), count(e.UNCERTAIN)]
  const evidence: Counts | null = numbers.some(v => v === null) ? null : {
    supports: numbers[0]!, contradicts: numbers[1]!, neutral: numbers[2]!, uncertain: numbers[3]!,
  }
  const retrieved = first(coverage.retrieved_count, partial.total_count, reading.retrieved_count)
  const assessed = first(coverage.assessed_count, partial.verified_count, reading.assessed_count)
  const fullText = first(coverage.full_text_count, partial.full_text_count, reading.full_text_count)
  return { retrieved, assessed, fullText, coverage: percentage(retrieved, assessed), evidence,
    methodology: text(methodology.label), methodologyNote: text(methodology.explanation) }
}
export function summarizeIndicators(values: Indicators[]): OverallIndicators {
  const sum = (field: 'retrieved' | 'assessed' | 'fullText'): number | null =>
    values.length > 0 && values.every(v => v[field] !== null)
      ? values.reduce((acc, value) => acc + (value[field] ?? 0), 0) : null
  const retrieved = sum('retrieved'), assessed = sum('assessed'), fullText = sum('fullText')
  const evidence: Counts | null = values.length > 0 && values.every(v => v.evidence !== null)
    ? values.reduce<Counts>((acc, v) => ({
      supports: acc.supports + (v.evidence?.supports ?? 0),
      contradicts: acc.contradicts + (v.evidence?.contradicts ?? 0),
      neutral: acc.neutral + (v.evidence?.neutral ?? 0),
      uncertain: acc.uncertain + (v.evidence?.uncertain ?? 0),
    }), { supports: 0, contradicts: 0, neutral: 0, uncertain: 0 }) : null
  return { retrieved, assessed, fullText, coverage: percentage(retrieved, assessed), evidence,
    methodology: null, methodologyNote: null, claimsMeasured: values.length }
}
