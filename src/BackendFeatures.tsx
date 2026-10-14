import { useEffect, useState, useRef } from 'react'
import type { ExtractedClaim } from './api'

const BASE = (import.meta.env?.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
const COLORS = ['#00d4aa', '#5c9aff', '#eabf70', '#c292ff', '#fa8798', '#80cbb4']
interface Article { pmid: string; title: string }
interface Group { topic_id: number; label: string; count: number; pmids: string[]; summary?: string; terms?: string[] }
interface Point { pmid: string; topic_id: number; x: number; y: number }
interface Edge { source: string; target: string; similarity: number }
interface GroupResponse {
  status: string; clusters: Group[]; points: Point[]; edges?: Edge[]
  document_count: number; topic_count?: number; llm_enriched?: boolean
  enrichment_message?: string; limitation?: string; message?: string
}
interface SourcePage { page?: number; page_number?: number; number?: number; text?: string }
interface SourceSection { title: string; text: string }
interface SourceResponse {
  title?: string; journal?: string; content_scope?: string
  source_url?: string; text?: string; pages?: SourcePage[]; sections?: SourceSection[]
}
async function api<T>(path: string, signal: AbortSignal, body?: object): Promise<T> {
  let response: Response
  try {
    response = await fetch(BASE + path, {
      method: body ? 'POST' : 'GET',
      headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.any([signal, AbortSignal.timeout(120000)]),
    })
  } catch (error) {
    if (signal.aborted) throw error
    throw new Error('Não foi possível conectar ao Flask na porta 5000.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(data?.error?.message || 'A API retornou HTTP ' + response.status)
  if (!data || typeof data !== 'object') throw new Error('A API retornou uma resposta inválida.')
  return data as T
}

/** Agrupamento real de títulos via endpoint BERTopic do backend. */
export function TopicExplorer({ articles, onFilter }: { articles: Article[]; onFilter: (pmids: string[] | null) => void }) {
  const [enrich, setEnrich] = useState(true)
  const [showMap, setShowMap] = useState(true)
  const [report, setReport] = useState<GroupResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState<number | null>(null)
  const key = articles.map(a => a.pmid + ':' + a.title).join('|')

  useEffect(() => {
    const ctrl = new AbortController()
    setLoading(true)
    setReport(null)
    setError('')
    setActive(null)
    onFilter(null)
    void api<GroupResponse>('/pubmed-clusters', ctrl.signal, {
      mode: enrich ? 'enrich' : 'cluster',
      articles: articles.map(a => ({ pmid: a.pmid, title: a.title })),
    }).then(data => { if (!ctrl.signal.aborted) setReport(data) })
      .catch(error => { if (!ctrl.signal.aborted) setError(error instanceof Error ? error.message : 'Agrupamento indisponível.') })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false) })
    return () => ctrl.abort()
    // 'key' identifies the exact result page and avoids repeat requests on parent re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enrich])

  const choose = (id: number | null) => {
    setActive(id)
    onFilter(id === null ? null : report?.clusters.find(g => g.topic_id === id)?.pmids || [])
  }
  const pts = report?.points || []
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y)
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys)
  const locate = (p: Point) => ({
    x: 8 + 84 * (p.x - minX) / (maxX - minX || 1),
    y: 8 + 84 * (p.y - minY) / (maxY - minY || 1),
  })
  const pointsById = new Map(pts.map(p => [p.pmid, p]))
  const groups = report?.clusters || []

  return <section className="space-y-3 rounded-xl border border-[--color-border] bg-[--color-background] p-4" aria-label="Organização por temas">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="text-sm font-semibold text-[--color-foreground]">Grupos de temas · BERTopic</h3>
      <div className="flex flex-wrap gap-3 text-xs text-[--color-muted]">
        <label className="flex items-center gap-2"><input type="checkbox" checked={enrich} onChange={e => setEnrich(e.target.checked)} /> Revisar nomes com IA</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={showMap} onChange={e => setShowMap(e.target.checked)} /> Mapa</label>
      </div>
    </div>
    {loading && <p role="status" className="text-xs text-[--color-muted]">Organizando artigos pelos títulos. A primeira execução pode demorar…</p>}
    {error && <p role="alert" className="text-xs text-[--color-red]">{error} A lista do PubMed continua disponível.</p>}
    {report?.status === 'insufficient_documents' && <p className="text-xs text-[--color-muted]">{report.message || 'São necessários pelo menos quatro artigos.'}</p>}
    {report?.status === 'available' && <>
      <p className="text-[11px] text-[--color-muted]">{report.limitation || 'A semelhança dos títulos não indica qualidade, eficácia ou consenso científico.'}</p>
      {enrich && <p className="text-[11px] text-[--color-muted]">{report.llm_enriched ? 'Descrições revisadas por IA.' : report.enrichment_message || 'Descrições baseadas apenas nos títulos.'}</p>}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar artigos por tema">
        <button type="button" aria-pressed={active === null} onClick={() => choose(null)} className="min-h-10 rounded-md border border-[--color-teal] px-3 text-xs text-[--color-teal] hover:bg-[--color-teal-faint]">Todos ({articles.length})</button>
        {groups.map((g, i) => <button key={g.topic_id} type="button" aria-pressed={active === g.topic_id} onClick={() => choose(g.topic_id)}
          className={'min-h-10 rounded-md border px-3 text-xs hover:bg-[--color-teal-faint] ' + (active === g.topic_id ? 'border-[--color-teal] text-[--color-teal]' : 'border-[--color-border] text-[--color-foreground]')}>
          <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />{g.label} ({g.count})
        </button>)}
      </div>
      {active !== null && <p className="text-xs text-[--color-muted]">{groups.find(g => g.topic_id === active)?.summary || 'Lista filtrada por tema.'}</p>}
      {showMap && pts.length > 0 && <div className="rounded-lg border border-[--color-border] p-3">
        <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-[--color-muted]">Relações aproximadas entre títulos</p>
        <svg viewBox="0 0 100 100" role="img" aria-label="Mapa de similaridade entre títulos dos artigos" className="mx-auto aspect-[2/1] max-h-80 w-full rounded-lg bg-[--color-surface]">
          {(report.edges || []).map((e, i) => {
            const a = pointsById.get(e.source), b = pointsById.get(e.target)
            if (!a || !b) return null
            const p = locate(a), q = locate(b)
            return <line key={i} x1={p.x} y1={p.y} x2={q.x} y2={q.y} stroke="var(--color-muted)" strokeOpacity={0.25} strokeWidth={0.3} />
          })}
          {pts.map(p => {
            const pos = locate(p), idx = groups.findIndex(g => g.topic_id === p.topic_id)
            return <circle key={p.pmid} cx={pos.x} cy={pos.y} r={1.7}
              fill={COLORS[(idx < 0 ? COLORS.length - 1 : idx) % COLORS.length]} opacity={active === null || active === p.topic_id ? 1 : 0.2}>
              <title>PMID {p.pmid} · {groups.find(g => g.topic_id === p.topic_id)?.label || 'Artigo'}</title>
            </circle>
          })}
        </svg>
        <p className="mt-2 text-[11px] text-[--color-muted]">O mapa representa títulos similares, não força de evidência.</p>
      </div>}
    </>}
  </section>
}

export function ScientificReader({ analysisId, onAdd, remaining }: {
  analysisId: string; onAdd: (claim: ExtractedClaim) => void; remaining: number
}) {
  // Abra o texto ao chegar à etapa de alegações, sem exigir um clique extra.
  const [open, setOpen] = useState(true)
  const [source, setSource] = useState<SourceResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [quote, setQuote] = useState('')
  const [claimText, setClaimText] = useState('')
  const [section, setSection] = useState('')
  const [page, setPage] = useState<number | undefined>()
  const [feedback, setFeedback] = useState('')
  const contentRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const ctrl = new AbortController()
    setLoading(true)
    setError('')
    void api<SourceResponse>('/analyses/' + encodeURIComponent(analysisId) + '/source', ctrl.signal)
      .then(data => { if (!ctrl.signal.aborted) setSource(data) })
      .catch(error => { if (!ctrl.signal.aborted) setError(error instanceof Error ? error.message : 'Leitor indisponível.') })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false) })
    return () => ctrl.abort()
  }, [open, analysisId])

  const parts = source?.pages?.filter(p => p.text?.trim()).map((p, i) => ({
    heading: 'Página ' + (p.page || p.page_number || p.number || i + 1),
    page: p.page || p.page_number || p.number || i + 1,
    text: p.text || '',
  })) || []
  if (!parts.length && source?.sections?.length) {
    source.sections.forEach(s => { if (s.text?.trim()) parts.push({ heading: s.title || 'Seção', page: 0, text: s.text }) })
  }
  if (!parts.length && source?.text) parts.push({ heading: 'Texto do artigo', page: 0, text: source.text })

  function capture() {
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed || !selection.rangeCount || !contentRef.current) return
    const range = selection.getRangeAt(0)
    if (!contentRef.current.contains(range.startContainer) || !contentRef.current.contains(range.endContainer)) return
    const excerpt = selection.toString().replace(/\s+/g, ' ').trim()
    if (excerpt.length < 2 || excerpt.length > 4000) { setFeedback('Selecione um trecho entre 2 e 4.000 caracteres.'); return }
    const el = range.startContainer.nodeType === Node.TEXT_NODE ? range.startContainer.parentElement : range.startContainer as Element
    const block = el?.closest('[data-reader-section]')
    const location = block?.getAttribute('data-reader-section') || ''
    const locationPage = Number(block?.getAttribute('data-reader-page'))
    setQuote(excerpt)
    setClaimText(excerpt.slice(0, 2000))
    setSection(location.slice(0, 300))
    setPage(Number.isInteger(locationPage) && locationPage > 0 ? locationPage : undefined)
    setFeedback('Trecho selecionado no artigo. Clique em Adicionar trecho à análise ou revise sua alegação abaixo.')
  }

  function add() {
    const text = claimText.trim()
    if (remaining <= 0) { setFeedback('O limite de 10 alegações foi atingido. Desmarque uma sugestão para adicionar sua própria alegação.'); return }
    if (text.length < 8 || text.length > 2000) { setFeedback('A alegação precisa ter de 8 a 2.000 caracteres.'); return }
    if (quote.length === 1) { setFeedback('O trecho da fonte precisa ter ao menos 2 caracteres.'); return }
    onAdd({
      claim_id: 'user-' + Date.now() + '-' + Math.random().toString(36).slice(2, 9),
      text, source: 'USER', ...(quote ? { quote } : {}), ...(section ? { section } : {}), ...(page ? { page } : {}),
    })
    setQuote('')
    setClaimText('')
    setSection('')
    setPage(undefined)
    setFeedback('Alegação adicionada à pesquisa.')
    window.getSelection()?.removeAllRanges()
  }

  return <section className="space-y-3 rounded-xl border border-[--color-border] bg-[--color-surface] p-4">
    <button type="button" onClick={() => setOpen(v => !v)} aria-expanded={open} className="flex min-h-11 w-full items-center justify-between text-left text-sm font-semibold text-[--color-teal]">
      Selecionar alegação diretamente no artigo <span aria-hidden="true">{open ? '− Minimizar' : '+ Expandir'}</span>
    </button>
    {open && <>
      <p className="text-xs leading-relaxed text-[--color-muted]"><strong className="text-[--color-teal]">Como usar:</strong> destaque uma frase ou trecho do artigo com o mouse, dedo ou teclado. A seleção será copiada para o campo de alegação e você poderá adicioná-la para pesquisar junto com as sugestões automáticas. Também é possível escrever a alegação manualmente.</p>
      {loading && <p role="status" className="text-xs text-[--color-muted]">Carregando fonte original…</p>}
      {error && <p role="alert" className="text-xs text-[--color-red]">{error}</p>}
      {source && <div className="space-y-2">
        <h3 className="text-sm font-semibold text-[--color-foreground]">{source.title || 'Artigo analisado'}</h3>
        <p className="text-[11px] text-[--color-muted]">{[source.journal, source.content_scope].filter(Boolean).join(' · ')}</p>
        {source.source_url?.startsWith('https://') && <a href={source.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[--color-teal] underline">Abrir artigo original ↗</a>}
        <div ref={contentRef} onMouseUp={capture} onKeyUp={capture} onTouchEnd={capture} tabIndex={0} aria-label="Texto disponível do artigo. Selecione um trecho para criar sua alegação." className="max-h-[420px] space-y-4 overflow-y-auto rounded-lg border border-[--color-border] bg-[--color-background] p-4 selection:bg-[--color-teal-faint]">
          {parts.length ? parts.map((part, i) => <section key={i} data-reader-section={part.heading} data-reader-page={part.page} className="space-y-2">
            <h4 className="text-xs font-semibold text-[--color-teal]">{part.heading}</h4>
            <p className="whitespace-pre-wrap text-sm leading-7 text-[--color-foreground]">{part.text}</p>
          </section>) : <p className="text-sm text-[--color-muted]">Texto integral não disponível nesta fonte.</p>}
        </div>
        {quote && <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[--color-teal] bg-[--color-teal-faint] p-3">
          <p className="min-w-0 flex-1 text-xs text-[--color-foreground]">Trecho selecionado: “{quote.slice(0, 150)}{quote.length > 150 ? '…' : ''}”</p>
          <button type="button" disabled={remaining <= 0 || claimText.trim().length < 8} onClick={add}
            className="min-h-10 rounded-lg bg-[--color-teal] px-4 text-xs font-semibold text-black hover:bg-[#14f4c6] disabled:opacity-40">Adicionar trecho à análise</button>
        </div>}
      </div>}
      <label className="block text-xs text-[--color-muted]">Trecho da fonte (opcional)
        <textarea rows={2} maxLength={4000} value={quote} onChange={e => setQuote(e.target.value)}
          className="mt-1 w-full rounded-lg border border-[--color-border] bg-[--color-background] p-3 text-sm text-[--color-foreground]"/>
      </label>
      <label className="block text-xs text-[--color-muted]">Alegação a ser analisada
        <textarea rows={2} maxLength={2000} value={claimText} onChange={e => setClaimText(e.target.value)}
          placeholder="Escreva uma afirmação verificável com base no artigo"
          className="mt-1 w-full rounded-lg border border-[--color-border] bg-[--color-background] p-3 text-sm text-[--color-foreground]" />
      </label>
      {(section || page) && <p className="text-xs text-[--color-muted]">{section}{page ? ' · Página ' + page : ''}</p>}
      <button type="button" onClick={add} disabled={remaining <= 0 || claimText.trim().length < 8}
        className="min-h-11 rounded-lg border border-[--color-teal] px-4 text-sm font-semibold text-[--color-teal] hover:bg-[--color-teal] hover:text-black disabled:opacity-40">
        Adicionar alegação à pesquisa ({remaining} vaga(s))
      </button>
      {feedback && <p role="status" className="text-xs text-[--color-muted]">{feedback}</p>}
    </>}
  </section>
}
