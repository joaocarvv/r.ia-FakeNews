import { readIndicators, summarizeIndicators, type Indicators, type OverallIndicators } from './scientificIndicators.ts'

export type Verdict = 'verified' | 'fake' | 'uncertain'
export interface Finding { relation: string; articleTitle: string; text: string; url?: string; doi?: string; pmid?: string }
export interface Claim { text: string; verdict: Verdict; confidence: null; note: string; indicators: Indicators; findings: Finding[]; sourceQuote?: string; sourceSection?: string; sourcePage?: number }
export interface AnalysisResult {
  title: string; source: string; publishedDate: string; overallVerdict: Verdict
  credibilityScore: null; claims: Claim[]; redFlags: string[]; indicators: OverallIndicators
  supportingLinks: { label: string; url: string }[]; analysisId: string
  articleUrl?: string; healthArea?: string
}
export interface ExtractedClaim { claim_id: string; text: string; source?: 'USER'; quote?: string; section?: string; page?: number }
export interface Job {
  analysis_id: string; status: string; progress: number; updated_at?: string
  result?: Record<string, unknown>; error?: { message?: string }
}
const base = (import.meta.env?.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
const statuses = new Set(['QUEUED', 'RUNNING', 'AWAITING_CLAIM_SELECTION', 'RESEARCHING', 'SUCCEEDED', 'FAILED'])
const record = (v: unknown): Record<string, unknown> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
const rows = (v: unknown) => Array.isArray(v) ? v.map(record) : []
const str = (v: unknown) => typeof v === 'string' ? v : ''
export function safeUrl(value: unknown): string | undefined {
  try { const u = new URL(str(value)); return ['http:', 'https:'].includes(u.protocol) ? u.href : undefined } catch { return undefined }
}
export function parseJob(value: unknown): Job {
  const v = record(value)
  if (typeof v.analysis_id !== 'string' || !v.analysis_id || !statuses.has(str(v.status))) throw new Error('Resposta incompatível com a API de análise.')
  return v as unknown as Job
}
async function request(path: string, signal: AbortSignal, body?: unknown): Promise<Job> {
  let response: Response
  try {
    response = await fetch(`${base}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.any([signal, AbortSignal.timeout(90000)]),
    })
  } catch (e) {
    if (signal.aborted) throw e
    throw new Error('Não foi possível acessar o backend. Confira se ele está ativo e se o endereço da API está correto.')
  }
  const payload = await response.json().catch(() => null)
  if (!response.ok) throw new Error(str(record(record(payload).error).message) || `Falha na API (HTTP ${response.status}).`)
  return parseJob(payload)
}
export function normalizeReference(value: string): string {
  const input = value.trim()
  if (/^10\.\d{4,9}\//.test(input)) return input
  const url = safeUrl(/^[a-z][a-z\d+.-]*:/i.test(input) ? input : `https://${input}`)
  if (!url) throw new Error('Informe um link HTTP/HTTPS ou DOI válido.')
  return url
}
export async function filePayload(file: File) {
  if (!['application/pdf', 'image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('Envie um PDF, PNG, JPEG ou WebP.')
  if (!file.size || file.size > 25 * 1024 * 1024) throw new Error('O arquivo deve ter conteúdo e no máximo 25 MB.')
  const data = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < data.length; i += 8192) binary += String.fromCharCode(...data.subarray(i, i + 8192))
  return { article_file: { name: file.name, mime_type: file.type, data_base64: btoa(binary) } }
}
export async function startAnalysis(reference: string, file: File | null, signal: AbortSignal) {
  return request('/article-analyses', signal, file ? await filePayload(file) : { article_reference: normalizeReference(reference) })
}
export function selectClaims(id: string, claims: ExtractedClaim[], signal: AbortSignal, depth: 'QUICK' | 'DEEP' = 'QUICK') {
  return request(`/article-analyses/${encodeURIComponent(id)}/claims`, signal, { claims, depth })
}
export async function pollAnalysis(id: string, signal: AbortSignal, update: (job: Job) => void): Promise<Job> {
  const deadline = Date.now() + 30 * 60 * 1000
  while (!signal.aborted) {
    const job = await request(`/analyses/${encodeURIComponent(id)}?view=status`, signal)
    update(job)
    if (['SUCCEEDED', 'FAILED', 'AWAITING_CLAIM_SELECTION'].includes(job.status)) {
      const full = await request(`/analyses/${encodeURIComponent(id)}`, signal)
      if (full.status === 'FAILED') throw new Error(full.error?.message || 'A análise falhou. Tente novamente.')
      if (!full.result) throw new Error('A API não retornou os dados da análise.')
      return full
    }
    if (Date.now() > deadline) throw new Error('A análise continua no servidor. Use Retomar para consultar o resultado sem reenviar o artigo.')
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(new DOMException('Consulta interrompida', 'AbortError')) }
      const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 2000)
      signal.addEventListener('abort', abort, { once: true })
      if (signal.aborted) abort()
    })
  }
  throw new DOMException('Consulta interrompida', 'AbortError')
}
export function extractedClaims(job: Job): ExtractedClaim[] {
  return rows(record(job.result?.submitted_article).claims).filter(c => typeof c.claim_id === 'string' && typeof c.text === 'string').map(c => ({ claim_id: str(c.claim_id), text: str(c.text) }))
}
function verdict(status: unknown): Verdict {
  if (status === 'PREDOMINANTLY_COMPATIBLE') return 'verified'
  if (status === 'POTENTIAL_DIVERGENCE') return 'fake'
  return 'uncertain'
}
export function mapResult(job: Job): AnalysisResult {
  const result = job.result || {}
  const submitted = record(result.submitted_article)
  const entries = rows(result.claim_analyses)
  if (!entries.length) throw new Error('A resposta não contém resultados das alegações selecionadas.')
  const links = new Map<string, string>()
  const flags = new Set<string>()
  const claims = entries.map(entry => {
    const data = record(entry.result), summary = record(data.user_summary)
    const failed = entry.status === 'FAILED'
    for (const f of Array.isArray(summary.caveats) ? summary.caveats : []) if (typeof f === 'string') flags.add(f)
    for (const a of rows(record(data.verification).alerts)) {
      const text = [str(a.title), str(a.detail)].filter(Boolean).join(': ')
      if (text) flags.add(text)
    }
    for (const article of rows(data.articles)) {
      const url = safeUrl(article.url) || (str(article.pmid) ? `https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(str(article.pmid))}/` : undefined)
      if (url) links.set(url, str(article.title) || 'Artigo científico')
    }
    const findings = failed ? [] : rows(summary.findings).slice(0, 3).flatMap(finding => {
      const excerpt = str(finding.quote_pt) || str(finding.quote)
      if (!excerpt) return []
      const pmid = /^[0-9]+$/.test(str(finding.pmid)) ? str(finding.pmid) : undefined
      const doi = /^10[.][0-9]{4,9}[/]/.test(str(finding.doi)) ? str(finding.doi) : undefined
      const url = safeUrl(finding.source_url) || (pmid ? `https://pubmed.ncbi.nlm.nih.gov/${pmid}/` : doi ? `https://doi.org/${encodeURI(doi)}` : undefined)
      return [{ relation: str(finding.relation) || 'UNCERTAIN', articleTitle: str(finding.article_title_pt) || str(finding.article_title) || 'Artigo científico',
        text: excerpt.slice(0, 460), url, doi, pmid }]
    })
    if (failed) flags.add(`Falha na alegação: ${str(record(entry.claim).text)}`)
    const entryClaim = record(entry.claim)
    return { sourceQuote: str(entryClaim.quote) || undefined,
      sourceSection: str(entryClaim.section) || undefined,
      sourcePage: typeof entryClaim.page === 'number' && Number.isInteger(entryClaim.page) ? entryClaim.page : undefined,
      text: str(entryClaim.text) || 'Alegação', verdict: failed ? 'uncertain' as const : verdict(summary.status), confidence: null,
      indicators: readIndicators(failed ? {} : data), findings,
      note: failed ? str(record(entry.error).message) || 'Não foi possível avaliar esta alegação.' : [str(summary.headline), str(summary.summary), str(summary.interpretation)].filter(Boolean).join(' ') || 'Resultado sem resumo. Consulte o relatório completo.' }
  })
  const first = claims[0].verdict
  const overall = claims.every(c => c.verdict === first) ? first : 'uncertain'
  const input = str(record(result.input).source)
  return { title: str(submitted.title) || 'Análise do artigo', source: input || 'Artigo enviado', publishedDate: job.updated_at ? `Analisado em ${new Date(job.updated_at).toLocaleDateString('pt-BR')}` : 'Data de análise não informada', overallVerdict: overall,
    credibilityScore: null, claims, indicators: summarizeIndicators(claims.filter((_c, i) => entries[i].status !== 'FAILED').map(c => c.indicators)), redFlags: [...flags], supportingLinks: [...links].map(([url, label]) => ({ url, label })), analysisId: job.analysis_id,
    articleUrl: safeUrl(input) }
}
/** Reabre um resultado salvo pelo identificador, quando o mesmo backend ainda o mantém. */
export async function getSavedAnalysis(id: string, signal: AbortSignal): Promise<Job> {
  if (!id || id.length > 128) throw new Error('Identificador de análise inválido.')
  let job: Job
  try {
    job = await request(`/analyses/${encodeURIComponent(id)}`, signal)
  } catch (error) {
    if (error instanceof Error && /404|não encontrada|not found/i.test(error.message)) {
      throw new Error('O registro está no Firestore, mas o resultado completo não foi encontrado neste backend. Confira se está usando o servidor original.')
    }
    throw error
  }
  if (job.status !== 'SUCCEEDED' || !job.result) {
    throw new Error('O histórico foi localizado, mas o resultado completo ainda não está disponível no backend.')
  }
  return job
}

export function reportUrl(id: string) { return `${base}/analyses/${encodeURIComponent(id)}/report.md` }
