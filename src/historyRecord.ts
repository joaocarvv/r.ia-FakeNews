import type { AnalysisResult, Verdict } from './api.ts'

/** Histórico enxuto: não contém PDFs, trechos de estudo, tokens ou senhas. */
export interface SavedArticle {
  analysisId: string
  title: string
  source: string
  publishedDate: string
  overallVerdict: Verdict
  healthArea: string
  savedAt: number
}
const text = (value: string, max: number) => value.slice(0, max)
export function makeSavedArticle(result: AnalysisResult): SavedArticle {
  return {
    analysisId: text(result.analysisId, 128),
    title: text(result.title, 256),
    source: text(result.source, 512),
    publishedDate: text(result.publishedDate, 80),
    overallVerdict: result.overallVerdict,
    healthArea: text(result.healthArea || 'Geral', 80),
    savedAt: Date.now(),
  }
}
export function validSavedArticle(value: unknown): value is SavedArticle {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const obj = value as Record<string, unknown>
  return typeof obj.analysisId === 'string' && !!obj.analysisId && obj.analysisId.length <= 128
    && typeof obj.title === 'string' && obj.title.length <= 256
    && typeof obj.source === 'string' && obj.source.length <= 512
    && typeof obj.publishedDate === 'string' && obj.publishedDate.length <= 80
    && ['verified', 'fake', 'uncertain'].includes(String(obj.overallVerdict))
    && typeof obj.healthArea === 'string' && obj.healthArea.length <= 80
    && typeof obj.savedAt === 'number' && Number.isSafeInteger(obj.savedAt) && obj.savedAt > 0
}
