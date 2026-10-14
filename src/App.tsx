import { useState, useRef, useCallback, useEffect, useId, type FormEvent, type KeyboardEvent } from 'react'
import { startAnalysis, pollAnalysis, selectClaims, extractedClaims, mapResult, getSavedAnalysis, reportUrl, type Job, type ExtractedClaim, type AnalysisResult, type Verdict } from './api'
import { onAuthStateChanged } from 'firebase/auth'
import { auth, loginWithGoogle, loginWithEmail, registerWithEmail, requestPasswordReset, logout, authErrorMessage } from './firebase'
import pubmedGovLogo from './assets/pubmed-gov-logo.png'
import type { Indicators, OverallIndicators } from './scientificIndicators.ts'
import { makeSavedArticle, type SavedArticle } from './historyRecord.ts'
import { loadHistory, saveHistory, deleteHistoryEntry } from './history.ts'
import { TopicExplorer, ScientificReader } from './BackendFeatures'

type VerifyMode = 'url' | 'image' | 'topic'
type AnalysisStatus = 'idle' | 'loading' | 'selecting' | 'done'
type SearchMode = 'quick' | 'advanced'
type AdvancedSearchType = 'pubmed' | 'doi' | 'url'
type ResearchDepth = 'QUICK' | 'DEEP'
type TopicArticleType = 'ALL' | 'REVIEWS' | 'TRIALS'
type TopicLanguage = 'ALL' | 'PORTUGUESE' | 'ENGLISH' | 'SPANISH' | 'FRENCH' | 'GERMAN' | 'ITALIAN'
type TopicIndexing = 'ALL' | 'MEDLINE'
type TopicAvailability = 'ALL' | 'PMC_FULL_TEXT'

interface TopicArticle {
  pmid: string
  title: string
  title_pt?: string | null
  journal?: string | null
  publication_date?: string | null
  authors?: string[]
  doi?: string | null
  publication_type_labels?: string[]
  language_labels?: string[]
  title_pt_source?: 'PUBMED' | 'AI_TRANSLATION' | null
  has_full_text?: boolean
}
interface TopicSearchResponse {
  articles: TopicArticle[]
  source: string
  topic: string
  query_results: { query: string; total_matches: number }[]
  excluded_by_language?: number
  language_note?: string
  pagination: {
    page: number
    total_results: number
    total_pages: number
    has_previous: boolean
    has_next: boolean
    limited_by_pubmed: boolean
  }
}


const BUTTON_GREEN = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[--color-teal] px-4 py-2.5 text-sm font-semibold text-[--color-teal] transition-all duration-200 hover:bg-[#00d4aa] hover:text-[#080c18] hover:shadow-[0_8px_24px_rgba(0,212,170,0.16)] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-[--color-teal] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[--color-teal]'
const BUTTON_DANGER = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[--color-red] px-4 py-2.5 text-sm font-semibold text-[--color-red] transition-all duration-200 hover:bg-[--color-red] hover:text-[--color-background] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40'
const BUTTON_FILLED = 'inline-flex min-h-12 items-center justify-center gap-2 rounded-lg border border-[--color-teal] bg-[--color-teal] px-6 py-3 text-sm font-bold text-black transition-all duration-200 hover:bg-[#14f4c6] hover:border-[#14f4c6] hover:shadow-[0_10px_28px_rgba(0,212,170,0.25)] active:scale-[0.99] disabled:cursor-not-allowed disabled:border-[--color-border] disabled:bg-[--color-border] disabled:text-[--color-muted] disabled:shadow-none'

interface AccessibilitySettings {
  highContrast: boolean
  textScale: number
  reducedMotion: boolean
}

const HEALTH_AREAS: Record<string, { color: string; bg: string }> = {
  'Neurologia':    { color: '#4d9fff', bg: '#4d9fff18' },
  'Cardiologia':   { color: '#f04060', bg: '#f0406018' },
  'Nutrição':      { color: '#00d4aa', bg: '#00d4aa18' },
  'Oncologia':     { color: '#a78bfa', bg: '#a78bfa18' },
  'Saúde Mental':  { color: '#f5a623', bg: '#f5a62318' },
  'Infectologia':  { color: '#fb923c', bg: '#fb923c18' },
  'Genética':      { color: '#34d399', bg: '#34d39918' },
  'Geral':         { color: '#6b7fa3', bg: '#6b7fa318' },
}

function detectHealthArea(title: string): string {
  const t = title.toLowerCase()
  if (/alzheimer|neuro|cerebr|cogni|memória|demência/.test(t)) return 'Neurologia'
  if (/cardio|coração|pressão|infarto|colesterol|heart|cardiac|hypertension|cholesterol|stroke/.test(t)) return 'Cardiologia'
  if (/câncer|cancer|lung cancer|carcinoma|adenocarcinoma|tumou?r|neoplasm|oncolog|quimio|chemotherap|metast|leukemia|leukaemia|lymphoma/.test(t)) return 'Oncologia'
  if (/café|vitamin|nutri|diet|aliment|prote[ií]n|metaboli/.test(t)) return 'Nutrição'
  if (/ansied|anxiet|depress|mental|psyc|psiq|estresse|stress/.test(t)) return 'Saúde Mental'
  if (/vírus|virus|bact[eé]ria|bacter|infec|infect|vacci|vacina|covid|gripe|influenza/.test(t)) return 'Infectologia'
  if (/gen[eé]tic|dna|rna|genom|chromos|cromossomo/.test(t)) return 'Genética'
  return 'Geral'
}

function VerdictBadge({ verdict, size = 'sm' }: { verdict: Verdict; size?: 'sm' | 'lg' }) {
  const map = {
    verified: { label: 'COMPATÍVEL', color: 'text-[--color-teal] border-[--color-teal] bg-[--color-teal-faint]' },
    fake: { label: 'DIVERGENTE', color: 'text-[--color-red] border-[--color-red] bg-[--color-red-faint]' },
    uncertain: { label: 'INCONCLUSIVO', color: 'text-[--color-amber] border-[--color-amber] bg-[--color-amber-faint]' },
  }
  const { label, color } = map[verdict]
  const px = size === 'lg' ? 'px-3 py-1 text-xs' : 'px-2 py-0.5 text-[10px]'
  return (
    <span className={`font-mono font-semibold border rounded ${px} ${color} tracking-widest`}>
      {label}
    </span>
  )
}


function CountSummary({ evidence }: { evidence: Indicators['evidence'] }) {
  if (!evidence) return <p className="text-xs text-[--color-muted]">Contagens não disponibilizadas pela API.</p>
  const labels = [
    { name: 'Compatíveis', value: evidence.supports, color: 'var(--color-teal)' },
    { name: 'Divergentes', value: evidence.contradicts, color: 'var(--color-red)' },
    { name: 'Contextuais', value: evidence.neutral, color: 'var(--color-blue)' },
    { name: 'Inconclusivas', value: evidence.uncertain, color: 'var(--color-amber)' },
  ]
  return <div className="flex flex-wrap gap-2">
    {labels.map(item => <span key={item.name} className="px-2 py-1 rounded border border-[--color-border] text-xs">
      <strong className="tabular-nums" style={{ color: item.color }}>{item.value}</strong> {item.name}
    </span>)}
  </div>
}
/**
 * A API não informa um score validado de veracidade nem confiança percentual.
 * O indicador circular utiliza somente a cobertura documental disponibilizada:
 * artigos avaliados / artigos recuperados. Não representa probabilidade de verdade.
 */
function CoverageScore({ coverage }: { coverage: number | null }) {
  const value = coverage === null || !Number.isFinite(coverage)
    ? null : Math.max(0, Math.min(100, Math.round(coverage)))
  const color = value === null ? 'var(--color-muted)'
    : value >= 75 ? 'var(--color-teal)' : value >= 50 ? 'var(--color-blue)' : 'var(--color-amber)'
  const radius = 49
  const circumference = 2 * Math.PI * radius

  return (
    <div className="relative mx-auto h-32 w-32 shrink-0 sm:h-36 sm:w-36"
      role="img" aria-label={value === null
        ? 'Score de cobertura documental indisponível'
        : `Score de cobertura documental: ${value} em 100; não é um percentual de veracidade`}
      title="Score de cobertura = artigos avaliados ÷ artigos recuperados. Não é confiança, veracidade ou qualidade científica.">
      <svg className="h-full w-full" viewBox="0 0 128 128" aria-hidden="true">
        <circle cx="64" cy="64" r={radius} fill="none" stroke="var(--color-border)" strokeWidth="8" />
        {value !== null && <circle cx="64" cy="64" r={radius} fill="none" stroke={color} strokeWidth="8"
          strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - value / 100)}
          transform="rotate(-90 64 64)" className="transition-all duration-700" />}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5">
        <strong className="text-3xl font-bold tabular-nums" style={{ color }}>{value === null ? 'N/D' : value}</strong>
        <span className="font-mono text-[10px] font-semibold tracking-[0.16em] text-[--color-foreground]">SCORE*</span>
      </div>
    </div>
  )
}

function ClaimCoverageBar({ coverage, verdict }: { coverage: number | null; verdict: Verdict }) {
  const value = coverage === null || !Number.isFinite(coverage)
    ? null : Math.max(0, Math.min(100, Math.round(coverage)))
  const color = verdict === 'verified' ? 'var(--color-teal)'
    : verdict === 'fake' ? 'var(--color-red)' : 'var(--color-amber)'
  return (
    <div className="flex items-center gap-4" title="Cobertura documental da alegação, não nível de confiança no veredito">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[--color-border]"
        role={value === null ? undefined : 'progressbar'}
        aria-label="Cobertura documental da alegação" aria-valuemin={value === null ? undefined : 0}
        aria-valuemax={value === null ? undefined : 100} aria-valuenow={value === null ? undefined : value}>
        {value !== null && <div className="h-full rounded-full transition-all duration-700"
          style={{ width: `${value}%`, backgroundColor: color }} />}
      </div>
      <span className="w-14 text-right font-mono text-xs font-semibold tabular-nums text-[--color-foreground]">
        {value === null ? 'N/D' : `${value}%`}
      </span>
    </div>
  )
}

function ScientificSummary({ data }: { data: OverallIndicators }) {
  const metrics = [
    ['Cobertura da análise', data.coverage === null ? 'N/D' : `${data.coverage}%`],
    ['Artigos recuperados*', data.retrieved ?? 'N/D'],
    ['Artigos avaliados*', data.assessed ?? 'N/D'],
    ['Textos completos*', data.fullText ?? 'N/D'],
  ]
  return <section aria-labelledby="metrics-heading" className="rounded-xl border border-[--color-border] bg-[--color-surface] p-5 space-y-4 sm:p-6">
    <div>
      <h3 id="metrics-heading" className="font-mono text-xs uppercase tracking-[0.18em] text-[--color-foreground]">◎ Indicadores científicos</h3>
      <p className="mt-2 text-xs leading-relaxed text-[--color-muted]">Dados observados na busca e na avaliação das evidências, não porcentagens de veracidade.</p>
    </div>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {metrics.map(([name, val]) => <div key={name} className="rounded-lg border border-[--color-border] bg-[--color-background] p-4">
        <div className="text-2xl font-semibold tabular-nums text-[--color-foreground]">{val}</div>
        <div className="mt-1 text-xs leading-snug text-[--color-muted]">{name}</div>
      </div>)}
    </div>
    <CountSummary evidence={data.evidence} />
    <p className="text-[11px] leading-relaxed text-[--color-muted]">
      *Somatório de {data.claimsMeasured} alegação(ões); um mesmo estudo pode aparecer em várias alegações. N/D significa dados insuficientes.
    </p>
  </section>
}

// Os cards de alegações aparecem logo após a busca e controlam a aba da análise.
function ClaimOverviewCards({ result, activeIndex, onChoose }: {
  result: AnalysisResult
  activeIndex: number
  onChoose: (index: number) => void
}) {
  const [minimized, setMinimized] = useState(false)
  return (
    <section aria-labelledby="selected-claims-heading" className="mt-6 space-y-4 rounded-xl border border-[--color-border] bg-[--color-surface] p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="selected-claims-heading" className="font-mono text-xs font-semibold uppercase tracking-[0.16em] text-[--color-foreground]">Alegações do artigo</h2>
          <p className="mt-2 text-xs text-[--color-muted]">Escolha uma alegação para abrir sua análise e consultar as evidências.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-[--color-border] px-3 py-1 font-mono text-[10px] text-[--color-muted]">{result.claims.length} alegação(ões)</span>
          <button type="button" onClick={() => setMinimized(value => !value)} aria-expanded={!minimized}
            aria-controls="selected-claims-grid" className={`${BUTTON_GREEN} min-h-9 px-3 py-1.5 text-xs`}>
            {minimized ? '＋ Expandir cards' : '− Minimizar cards'}
          </button>
        </div>
      </div>
      {!minimized && <div id="selected-claims-grid" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {result.claims.map((claim, index) => {
          const active = activeIndex === index
          return <button key={`${result.analysisId}-${index}`} type="button" aria-pressed={active}
            onClick={() => onChoose(index)}
            className={`min-h-32 space-y-3 rounded-xl border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[--color-teal] ${active
              ? 'border-[--color-teal] bg-[--color-teal-faint]'
              : 'border-[--color-border] bg-[--color-background] hover:border-[--color-teal] hover:bg-[--color-teal-faint]'}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-[--color-teal]">Alegação {index + 1}</span>
              <VerdictBadge verdict={claim.verdict} />
            </div>
            <p className="line-clamp-3 text-sm leading-relaxed text-[--color-foreground]">{claim.text}</p>
          </button>
        })}
      </div>}
    </section>
  )
}

function AnalysisCard({ result, activeClaimIndex, onSelectClaim }: {
  result: AnalysisResult
  activeClaimIndex: number
  onSelectClaim: (index: number) => void
}) {
  const [sourceQuery, setSourceQuery] = useState('')
  const [sourceSort, setSourceSort] = useState<'original' | 'title'>('original')
  const tabId = useId()
  const claimTabRefs = useRef<Array<HTMLButtonElement | null>>([])
  const handleClaimTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const count = result.claims.length
    if (!count) return
    let next: number
    switch (event.key) {
      case 'ArrowRight': next = (index + 1) % count; break
      case 'ArrowLeft': next = (index - 1 + count) % count; break
      case 'Home': next = 0; break
      case 'End': next = count - 1; break
      default: return
    }
    event.preventDefault()
    onSelectClaim(next)
    claimTabRefs.current[next]?.focus()
  }
  const sourceSearchText = sourceQuery.trim().toLocaleLowerCase('pt-BR')
  const visibleSources = result.supportingLinks.filter(link => !sourceSearchText
    || link.label.toLocaleLowerCase('pt-BR').includes(sourceSearchText)
    || link.url.toLocaleLowerCase('pt-BR').includes(sourceSearchText)
  ).sort((a, b) => sourceSort === 'title' ? a.label.localeCompare(b.label, 'pt-BR') : 0)
  const verdictLabel = {
    verified: 'Compatibilidade preliminar',
    fake: 'Possível divergência',
    uncertain: 'Verificação parcial ou inconclusiva',
  }

  return (
    <div className="mt-10 space-y-5 animate-slide-up">
      {/* Cabeçalho: resultado e indicador circular, no estilo do exemplo. */}
      <section className="rounded-xl border border-[--color-border] bg-[--color-surface] p-5 sm:p-7">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-[11px] tracking-widest text-[--color-muted]">
              <span className="break-all">#{result.analysisId}</span>
              <span>{result.publishedDate}</span>
            </div>
            <h2 className="text-xl font-semibold leading-snug text-[--color-foreground] sm:text-2xl">{result.title}</h2>
            <p className="break-all text-sm text-[--color-muted]">{result.source}</p>
          </div>
          <CoverageScore coverage={result.indicators.coverage} />
        </div>
        <p className="mt-4 text-[11px] leading-relaxed text-[--color-muted]">
          *Score de cobertura documental (artigos avaliados ÷ recuperados). Não mede a veracidade ou a confiabilidade do artigo.
        </p>
        <div className="mt-5 flex flex-col gap-3 border-t border-[--color-border] pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <VerdictBadge verdict={result.overallVerdict} size="lg" />
            <span className="text-sm text-[--color-muted]">{verdictLabel[result.overallVerdict]}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <a href={reportUrl(result.analysisId)} target="_blank" rel="noopener noreferrer"
              className="inline-flex min-h-10 items-center justify-center rounded-md border border-[--color-border] px-3 py-2 text-xs font-medium text-[--color-foreground] transition-colors hover:border-[--color-teal] hover:bg-[--color-teal] hover:text-[#080c18]">
              Relatório completo ↗
            </a>
            {result.articleUrl && <a href={result.articleUrl} target="_blank" rel="noopener noreferrer"
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-[--color-border] px-3 py-2 text-xs font-medium text-[--color-foreground] transition-colors hover:border-[--color-teal] hover:bg-[--color-teal] hover:text-[#080c18]">
              ↗ Ver artigo original
            </a>}
          </div>
        </div>
      </section>

      {/* Abas individuais por alegação; cada painel mantém as evidências da própria afirmação. */}
      <section id="artfact-claims-panel" aria-labelledby="claims-heading" className="overflow-hidden rounded-xl border border-[--color-border] bg-[--color-surface]">
        <div className="border-b border-[--color-border] px-5 py-4 sm:px-7">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="claims-heading" className="font-mono text-xs font-semibold uppercase tracking-[0.18em] text-[--color-foreground]">Análise de afirmações</h3>
            <span className="rounded-full border border-[--color-border] px-2.5 py-1 font-mono text-[10px] text-[--color-muted]">{result.claims.length} alegação(ões)</span>
          </div>
          <p className="mt-2 text-[11px] text-[--color-muted]">Escolha uma alegação para ver seu resultado, cobertura documental e evidências. As barras não representam certeza do veredito.</p>
        </div>
        {result.claims.length > 0 ? <>
          <div role="tablist" aria-label="Alegações analisadas"
            className="flex gap-2 overflow-x-auto border-b border-[--color-border] px-4 py-3 sm:px-7">
            {result.claims.map((claim, i) => {
              const active = activeClaimIndex === i
              const marker = claim.verdict === 'verified' ? 'var(--color-teal)'
                : claim.verdict === 'fake' ? 'var(--color-red)' : 'var(--color-amber)'
              return <button key={i} type="button" role="tab" id={`${tabId}-tab-${i}`}
                ref={element => { claimTabRefs.current[i] = element }}
                aria-selected={active} aria-controls={`${tabId}-panel-${i}`}
                title={claim.text} tabIndex={active ? 0 : -1}
                onClick={() => onSelectClaim(i)}
                onKeyDown={event => handleClaimTabKeyDown(event, i)}
                className={`inline-flex min-h-11 shrink-0 items-center gap-2 rounded-lg border px-4 py-2.5 text-xs font-semibold transition-all duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[--color-teal] ${active
                  ? 'border-[--color-teal] bg-[--color-teal-faint] text-[--color-foreground] shadow-[0_0_0_1px_rgba(0,212,170,0.15)]'
                  : 'border-[--color-border] text-[--color-muted] hover:border-[--color-teal] hover:bg-[--color-teal] hover:text-black'}`}>
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: marker }} />
                Alegação {i + 1}
              </button>
            })}
          </div>
          <div>
          {result.claims.map((claim, i) => (
            <article key={i} role="tabpanel" id={`${tabId}-panel-${i}`}
              aria-labelledby={`${tabId}-tab-${i}`} tabIndex={0} hidden={activeClaimIndex !== i}
              className="space-y-4 px-5 py-5 sm:px-7 sm:py-6">
              <p className="font-mono text-[10px] uppercase tracking-widest text-[--color-teal]">Alegação {i + 1} de {result.claims.length}</p>
              <div className="flex flex-wrap items-start gap-3">
                <VerdictBadge verdict={claim.verdict} />
                <h4 className="min-w-0 flex-1 text-sm font-medium leading-snug text-[--color-foreground] sm:text-base">{claim.text}</h4>
              </div>
              {claim.sourceQuote && <details className="rounded-lg border border-[--color-border] bg-[--color-background] p-3">
                <summary className="cursor-pointer text-xs font-semibold text-[--color-teal]">Trecho de origem da alegação</summary>
                <blockquote className="mt-2 border-l-2 border-[--color-teal] pl-3 text-xs leading-relaxed text-[--color-foreground]">{claim.sourceQuote}</blockquote>
                {(claim.sourceSection || claim.sourcePage) && <p className="mt-2 text-[11px] text-[--color-muted]">{[claim.sourceSection, claim.sourcePage ? 'Página ' + claim.sourcePage : ''].filter(Boolean).join(' · ')}</p>}
              </details>}
              <ClaimCoverageBar coverage={claim.indicators.coverage} verdict={claim.verdict} />
              <p className="text-xs leading-relaxed text-[--color-muted] sm:text-sm">{claim.note}</p>
              {(claim.findings.length > 0 || claim.indicators.evidence || claim.indicators.methodology || claim.indicators.methodologyNote) &&
                <details className="rounded-lg border border-[--color-border] bg-[--color-background] px-3 py-2">
                  <summary className="cursor-pointer text-xs font-medium text-[--color-teal] hover:text-[--color-foreground]">
                    Ver evidências e metodologia
                  </summary>
                  <div className="space-y-3 pt-3">
                    <CountSummary evidence={claim.indicators.evidence} />
                    {claim.indicators.methodology && <p className="text-xs text-[--color-muted]">Triagem metodológica: {claim.indicators.methodology}</p>}
                    {claim.indicators.methodologyNote && <p className="text-xs text-[--color-muted]">{claim.indicators.methodologyNote}</p>}
                    {claim.findings.length > 0 && <div className="space-y-3">
                      <p className="font-mono text-[10px] uppercase tracking-widest text-[--color-muted]">Trechos localizados e rastreabilidade</p>
                      {claim.findings.map((finding, fi) => <div key={fi} className="space-y-2 rounded-md border border-[--color-border] p-3">
                        <div className="flex flex-wrap justify-between gap-2">
                          <span className="text-xs font-semibold text-[--color-foreground]">{finding.articleTitle}</span>
                          <span className="font-mono text-[10px] text-[--color-muted]">{({
                            SUPPORTS: 'Compatível', CONTRADICTS: 'Divergente', NEUTRAL: 'Contextual', UNCERTAIN: 'Inconclusivo',
                          } as Record<string, string>)[finding.relation] || 'Avaliação parcial'}</span>
                        </div>
                        <blockquote className="border-l-2 border-[--color-teal] pl-3 text-xs leading-relaxed text-[--color-muted]">{finding.text}</blockquote>
                        <div className="flex flex-wrap items-center gap-3">
                          {finding.doi && <span className="break-all font-mono text-[10px] text-[--color-muted]">DOI: {finding.doi}</span>}
                          {finding.pmid && <span className="font-mono text-[10px] text-[--color-muted]">PMID: {finding.pmid}</span>}
                          {finding.url && <a href={finding.url} target="_blank" rel="noopener noreferrer" className="text-xs text-[--color-teal] underline">Consultar fonte ↗</a>}
                        </div>
                      </div>)}
                      <p className="text-[11px] leading-relaxed text-[--color-muted]">Trechos extraídos automaticamente. Confira o contexto integral das fontes e do relatório.</p>
                    </div>}
                  </div>
                </details>}
            </article>
          ))}
          </div>
        </> : <p className="px-5 py-6 text-sm text-[--color-muted]">Nenhuma alegação foi disponibilizada nesta análise.</p>}
      </section>

      {/* Métricas científicas continuam disponíveis sem interromper a leitura das afirmações. */}
      <ScientificSummary data={result.indicators} />

      {/* Alertas */}
      <section className="space-y-3 rounded-xl border border-[--color-red] bg-[--color-red-faint] p-5 sm:p-6">
        <h3 className="font-mono text-[11px] uppercase tracking-widest text-[--color-red]">Alertas detectados</h3>
        {result.redFlags.length === 0 && <p className="text-sm text-[--color-foreground]">Nenhum alerta informado nesta análise.</p>}
        {result.redFlags.map((flag, i) => <div key={i} className="flex items-start gap-3">
          <span className="font-mono text-xs text-[--color-red]">!</span>
          <p className="text-sm text-[--color-foreground]">{flag}</p>
        </div>)}
      </section>

      {/* Links das fontes consultadas */}
      <section className="space-y-3 rounded-xl border border-[--color-border] bg-[--color-surface] p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-mono text-[11px] uppercase tracking-widest text-[--color-foreground]">Fontes consultadas</h3>
          <span className="font-mono text-[10px] text-[--color-muted]">{visibleSources.length} de {result.supportingLinks.length} fonte(s)</span>
        </div>
        {result.supportingLinks.length > 1 && <div className="flex flex-col gap-2 sm:flex-row">
          <label htmlFor={`${tabId}-source-search`} className="flex-1 text-[11px] text-[--color-muted]">
            Filtrar artigos por título ou link
            <input id={`${tabId}-source-search`} type="search" value={sourceQuery} onChange={event => setSourceQuery(event.target.value)}
              placeholder="Buscar nas fontes consultadas…"
              className="mt-1 min-h-11 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-3 text-sm text-[--color-foreground] focus:border-[--color-teal]" />
          </label>
          <label htmlFor={`${tabId}-source-order`} className="text-[11px] text-[--color-muted] sm:w-40">
            Ordenação
            <select id={`${tabId}-source-order`} value={sourceSort} onChange={event => setSourceSort(event.target.value as 'original' | 'title')}
              className="mt-1 min-h-11 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-3 text-xs text-[--color-foreground] focus:border-[--color-teal]">
              <option value="original">Padrão</option>
              <option value="title">Título (A–Z)</option>
            </select>
          </label>
        </div>}
        {result.supportingLinks.length === 0 && <p className="text-sm text-[--color-muted]">Nenhuma fonte independente disponível nesta análise.</p>}
        {result.supportingLinks.length > 0 && visibleSources.length === 0 && <p className="rounded-lg border border-[--color-border] px-3 py-4 text-sm text-[--color-muted]">Nenhuma fonte corresponde à busca.</p>}
        <div className="space-y-2">
          {visibleSources.map((link, i) => <a key={`${link.url}-${i}`} href={link.url} target="_blank" rel="noopener noreferrer"
            className="flex items-center justify-between gap-3 rounded-md border border-[--color-border] px-3 py-2.5 text-sm text-[--color-blue] transition-colors hover:border-[--color-teal] hover:bg-[--color-teal] hover:text-black">
            <span className="min-w-0 truncate">{link.label}</span><span aria-hidden="true">↗</span>
          </a>)}
        </div>
      </section>
    </div>
  )
}

// ── LGPD Terms content (shared between modal and footer) ─────
const LGPD_SECTIONS = [
  {
    title: '1. Identificação do Controlador',
    text: 'A plataforma ArtFact, doravante denominada "Controlador", é responsável pelo tratamento dos dados pessoais coletados neste site, nos termos da Lei nº 13.709/2018 (Lei Geral de Proteção de Dados — LGPD).',
  },
  {
    title: '2. Dados Coletados',
    text: 'Coletamos os seguintes dados pessoais: (a) nome completo; (b) endereço de e-mail; (c) dados de acesso fornecidos via autenticação Google (nome e e-mail públicos); (d) histórico de artigos verificados associado à conta do usuário. Não coletamos dados sensíveis conforme definido no art. 11 da LGPD.',
  },
  {
    title: '3. Finalidade do Tratamento',
    text: 'Os dados são tratados exclusivamente para: (a) criar e gerenciar a conta do usuário; (b) salvar e recuperar artigos verificados; (c) melhorar a experiência da plataforma; (d) cumprir obrigações legais aplicáveis. O tratamento é fundamentado no consentimento do titular (art. 7º, I, LGPD) e no legítimo interesse do Controlador (art. 7º, IX, LGPD).',
  },
  {
    title: '4. Compartilhamento de Dados',
    text: 'Não comercializamos, alugamos ou compartilhamos dados pessoais com terceiros para fins comerciais. Poderemos compartilhar dados com prestadores de serviços de infraestrutura (ex.: provedores de nuvem) estritamente para operação da plataforma, sob acordo de confidencialidade e com as mesmas garantias desta Política.',
  },
  {
    title: '5. Retenção de Dados',
    text: 'Os dados são mantidos enquanto a conta estiver ativa. Após a exclusão da conta, os dados pessoais serão removidos em até 30 (trinta) dias, salvo obrigação legal de retenção por prazo superior.',
  },
  {
    title: '6. Direitos do Titular',
    text: 'Nos termos dos arts. 17 a 22 da LGPD, o titular tem direito a: (a) confirmação da existência de tratamento; (b) acesso aos dados; (c) correção de dados incompletos, inexatos ou desatualizados; (d) anonimização, bloqueio ou eliminação de dados desnecessários; (e) portabilidade dos dados; (f) eliminação dos dados tratados com consentimento; (g) informação sobre compartilhamentos; (h) revogação do consentimento a qualquer momento.',
  },
  {
    title: '7. Segurança',
    text: 'Adotamos medidas técnicas e administrativas adequadas para proteger os dados pessoais contra acessos não autorizados, destruição, perda, alteração ou comunicação indevida, em conformidade com o art. 46 da LGPD.',
  },
  {
    title: '8. Encarregado (DPO)',
    text: 'Para exercer seus direitos ou esclarecer dúvidas sobre o tratamento de dados, entre em contato com nosso Encarregado de Proteção de Dados pelo e-mail: privacidade@artfact.com.br. Responderemos em até 15 (quinze) dias úteis.',
  },
  {
    title: '9. Alterações desta Política',
    text: 'Esta Política pode ser atualizada periodicamente. Alterações relevantes serão comunicadas por e-mail ou notificação na plataforma. A data da última atualização consta no rodapé deste documento.',
  },
]

// ── Terms Modal ───────────────────────────────────────────────
function TermsModal({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(8,12,24,0.88)', backdropFilter: 'blur(6px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="terms-title"
    >
      <div
        className="w-full max-w-lg rounded-xl border bg-[--color-surface] relative animate-slide-up flex flex-col"
        style={{ borderColor: '#00d4aa', maxHeight: 'calc(100vh - 3rem)' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[--color-border] shrink-0">
          <div className="space-y-0.5">
            <span className="font-mono text-[10px] text-[--color-teal] tracking-widest uppercase">ArtFact</span>
            <h2 id="terms-title" className="text-sm font-semibold text-[--color-foreground]">Política de Privacidade e Proteção de Dados</h2>
            <p className="font-mono text-[10px] text-[--color-muted]">Atualizado em 30 set. 2026 · Conforme LGPD (Lei 13.709/2018)</p>
          </div>
          <button onClick={onClose} className="text-[--color-muted] hover:text-white transition-colors text-lg leading-none ml-4 shrink-0" aria-label="Fechar">✕</button>
        </div>
        {/* Scrollable content */}
        <div className="overflow-y-auto px-6 py-5 space-y-5">
          {LGPD_SECTIONS.map((s) => (
            <div key={s.title} className="space-y-1.5">
              <h3 className="font-mono text-[11px] text-[--color-teal] tracking-widest uppercase">{s.title}</h3>
              <p className="text-xs text-[--color-muted] leading-relaxed" style={{ fontFamily: 'Helvetica, Arial, sans-serif' }}>{s.text}</p>
            </div>
          ))}
          <div className="pt-2 border-t border-[--color-border]">
            <p className="font-mono text-[10px] text-[--color-subtle] text-center">
              ArtFact — Verificação Científica · privacidade@artfact.com.br
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Login Modal ──────────────────────────────────────────────
function LoginModal({ onClose, onRegistered }: { onClose: () => void; onRegistered: (name: string) => void }) {
  const [step, setStep] = useState<'login' | 'register' | 'reset'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const switchStep = (next: 'login' | 'register' | 'reset') => {
    setStep(next)
    setError('')
    setMessage('')
    setPassword('')
  }
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (pending) return
    setError('')
    setMessage('')
    if (step === 'register' && !name.trim()) { setError('Informe seu nome para se cadastrar.'); return }
    if (step !== 'reset' && password.length < 6) { setError('A senha precisa ter pelo menos 6 caracteres.'); return }
    setPending(true)
    try {
      if (step === 'reset') {
        await requestPasswordReset(email)
        setMessage('Se este e-mail estiver cadastrado, você receberá as instruções de recuperação.')
        return
      }
      if (step === 'register') { await registerWithEmail(name, email, password); onRegistered(name.trim()) }
      else await loginWithEmail(email, password)
      onClose()
    } catch (e) {
      setError(authErrorMessage(e))
    } finally {
      setPending(false)
    }
  }
  const googleLogin = async () => {
    if (pending) return
    setPending(true)
    setError('')
    setMessage('')
    try { await loginWithGoogle(); onClose() }
    catch (e) { setError(authErrorMessage(e)) }
    finally { setPending(false) }
  }
  return <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80" role="dialog" aria-modal="true" aria-labelledby="login-title">
    <div className="w-full max-w-md rounded-lg p-6 bg-[--color-surface] border border-[--color-border] space-y-4">
      <h2 id="login-title" className="font-semibold">{step === 'register' ? 'Criar conta na ArtFact' : step === 'reset' ? 'Recuperar senha' : 'Entrar na ArtFact'}</h2>
      <p className="text-xs text-[--color-muted]">A autenticação é feita pelo Firebase. Não armazenamos sua senha no ArtFact.</p>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      {message && <p role="status" className="text-sm text-[--color-teal]">{message}</p>}
      <form onSubmit={e => void submit(e)} className="space-y-3">
        {step === 'register' && <label className="block text-xs space-y-1">Nome
          <input type="text" autoComplete="name" required maxLength={100} value={name} onChange={e => setName(e.target.value)}
            disabled={pending} className="w-full p-3 bg-[--color-background] text-[--color-foreground] border border-[--color-border] rounded-md" />
        </label>}
        <label className="block text-xs space-y-1">E-mail
          <input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)}
            disabled={pending} className="w-full p-3 bg-[--color-background] text-[--color-foreground] border border-[--color-border] rounded-md" />
        </label>
        {step !== 'reset' && <label className="block text-xs space-y-1">Senha
          <input type="password" autoComplete={step === 'register' ? 'new-password' : 'current-password'} minLength={6} required value={password}
            onChange={e => setPassword(e.target.value)} disabled={pending}
            className="w-full p-3 bg-[--color-background] text-[--color-foreground] border border-[--color-border] rounded-md" />
        </label>}
        <button type="submit" disabled={pending} className="w-full rounded-md bg-[--color-teal] text-[--color-background] py-3 font-semibold disabled:opacity-50">
          {pending ? 'Aguarde…' : step === 'register' ? 'Criar conta' : step === 'reset' ? 'Enviar recuperação' : 'Entrar com e-mail'}
        </button>
      </form>
      {step !== 'reset' && <>
        <div className="flex items-center gap-3 text-xs text-[--color-muted]"><span className="flex-1 border-t border-[--color-border]" />ou<span className="flex-1 border-t border-[--color-border]" /></div>
        <button type="button" disabled={pending} onClick={() => void googleLogin()}
          className="w-full px-4 py-3 rounded-md bg-white text-black font-semibold disabled:opacity-50">Entrar com Google</button>
      </>}
      <div className="flex flex-wrap gap-3 text-xs">
        {step === 'login' && <>
          <button disabled={pending} onClick={() => switchStep('register')} className="underline">Criar conta</button>
          <button disabled={pending} onClick={() => switchStep('reset')} className="underline">Esqueci minha senha</button>
        </>}
        {step !== 'login' && <button disabled={pending} onClick={() => switchStep('login')} className="underline">Voltar ao login</button>}
      </div>
      <button type="button" disabled={pending} onClick={onClose} className="text-sm underline text-[--color-muted]">Continuar sem conta</button>
    </div>
  </div>
}

// ── Login Banner ──────────────────────────────────────────────
function LoginBanner({ onLogin, onDismiss }: { onLogin: () => void; onDismiss: () => void }) {
  return (
    <div
      className="flex items-center justify-between gap-4 px-4 py-3 rounded-lg border animate-slide-up flex-wrap"
      style={{ borderColor: '#f5a623', background: '#f5a62310' }}
      role="status"
    >
      <div className="flex items-center gap-2.5">
        <span className="text-[--color-amber] text-base">⚠</span>
        <p className="text-xs text-[--color-foreground]" style={{ fontFamily: 'Helvetica, Arial, sans-serif' }}>
          <span className="font-semibold">Você não está logado.</span> Este artigo será perdido ao sair da página.
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={onLogin}
          className="px-3 py-1.5 rounded-md text-xs font-semibold bg-[--color-teal] text-[--color-background] hover:bg-white hover:text-black transition-all duration-150"
          style={{ fontFamily: 'Helvetica, Arial, sans-serif' }}
        >
          Fazer login
        </button>
        <button
          onClick={onDismiss}
          className="px-3 py-1.5 rounded-md text-xs text-[--color-muted] hover:text-white transition-colors"
          aria-label="Dispensar"
        >✕</button>
      </div>
    </div>
  )
}

// ── Saved Articles Panel ──────────────────────────────────────
function SavedPanel({
  articles, onClose, error, loading, busyId, onOpen, onDelete,
}: {
  articles: SavedArticle[]
  onClose: () => void
  error: string
  loading: boolean
  busyId: string
  onOpen: (id: string) => void
  onDelete: (id: string) => void
}) {
  const [activeArea, setActiveArea] = useState<string>('Todas')
  const [search, setSearch] = useState('')
  const [activeVerdict, setActiveVerdict] = useState<'all' | Verdict>('all')
  const [period, setPeriod] = useState<'all' | '7' | '30' | '90'>('all')
  const [order, setOrder] = useState<'newest' | 'oldest' | 'title'>('newest')
  const verdictColor = {
    verified: 'var(--color-teal)',
    fake: 'var(--color-red)',
    uncertain: 'var(--color-amber)',
  }
  const verdictLabel = { verified: 'Compatível', fake: 'Divergente', uncertain: 'Inconclusivo' }

  const articleArea = (a: SavedArticle) => a.healthArea && a.healthArea !== 'Geral' ? a.healthArea : detectHealthArea(a.title)
  const areas = ['Todas', ...Array.from(new Set(articles.map(articleArea)))]
  const query = search.trim().toLocaleLowerCase('pt-BR')
  const cutoff = period === 'all' ? 0 : Date.now() - Number(period) * 86400000
  const filtered = articles.filter(a =>
    (activeArea === 'Todas' || articleArea(a) === activeArea)
    && (activeVerdict === 'all' || a.overallVerdict === activeVerdict)
    && (period === 'all' || a.savedAt >= cutoff)
    && (!query || a.title.toLocaleLowerCase('pt-BR').includes(query)
      || a.source.toLocaleLowerCase('pt-BR').includes(query)
      || a.analysisId.toLocaleLowerCase('pt-BR').includes(query))
  ).sort((a, b) => order === 'title'
    ? a.title.localeCompare(b.title, 'pt-BR')
    : order === 'oldest' ? a.savedAt - b.savedAt : b.savedAt - a.savedAt)
  const hasFilters = Boolean(query) || activeArea !== 'Todas' || activeVerdict !== 'all' || period !== 'all' || order !== 'newest'
  const clearFilters = () => {
    setSearch('')
    setActiveArea('Todas')
    setActiveVerdict('all')
    setPeriod('all')
    setOrder('newest')
  }

  return (
    <div
      className="fixed inset-0 z-[80] flex items-stretch justify-end p-0 sm:items-start sm:p-4"
      style={{ background: 'rgba(8,12,24,0.7)', backdropFilter: 'blur(4px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="saved-title"
    >
      <div
        className="w-full sm:max-w-md lg:max-w-lg rounded-none sm:rounded-2xl border border-[--color-teal] bg-[--color-surface] flex flex-col animate-slide-up shadow-2xl min-h-0 h-[100dvh] sm:h-[min(88dvh,840px)]"
        style={{ borderColor: '#00d4aa' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[--color-border] shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-[--color-teal]" />
            <span id="saved-title" className="font-mono text-[11px] text-[--color-muted] tracking-widest uppercase">Histórico da conta</span>
            {articles.length > 0 && (
              <span className="font-mono text-[10px] text-[--color-teal] border border-[--color-teal] rounded px-1">{articles.length}</span>
            )}
          </div>
          <button onClick={onClose} className="h-10 w-10 rounded-lg border border-[--color-border] text-[--color-muted] hover:border-[--color-teal] hover:bg-[--color-teal] hover:text-[--color-background] transition-all text-sm" aria-label="Fechar artigos salvos">✕</button>
        </div>

        {error && <p role="alert" className="px-5 py-3 text-xs text-red-400 border-b border-[--color-border]">{error}</p>}
        <div className="px-4 pt-3">
          <label htmlFor="history-search" className="block text-[10px] text-[--color-muted] mb-1">Buscar no histórico</label>
          <input id="history-search" type="search" value={search} onChange={event => setSearch(event.target.value)}
            placeholder="Pesquisar por título ou fonte" className="w-full rounded-lg bg-[--color-background] border border-[--color-border] focus:border-[--color-teal] outline-none px-4 py-3 text-sm text-[--color-foreground] transition-colors" />
          {articles.length > 0 && <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            <label htmlFor="history-verdict" className="block text-[11px] text-[--color-muted]">Resultado
              <select id="history-verdict" value={activeVerdict} onChange={event => setActiveVerdict(event.target.value as 'all' | Verdict)}
                className="mt-1 min-h-10 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-2 text-xs text-[--color-foreground] focus:border-[--color-teal]">
                <option value="all">Todos</option>
                <option value="verified">Compatíveis</option>
                <option value="fake">Divergentes</option>
                <option value="uncertain">Inconclusivos</option>
              </select>
            </label>
            <label htmlFor="history-period" className="block text-[11px] text-[--color-muted]">Período
              <select id="history-period" value={period} onChange={event => setPeriod(event.target.value as 'all' | '7' | '30' | '90')}
                className="mt-1 min-h-10 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-2 text-xs text-[--color-foreground] focus:border-[--color-teal]">
                <option value="all">Qualquer data</option>
                <option value="7">Últimos 7 dias</option>
                <option value="30">Últimos 30 dias</option>
                <option value="90">Últimos 90 dias</option>
              </select>
            </label>
            <label htmlFor="history-order" className="col-span-2 block text-[11px] text-[--color-muted] sm:col-span-1">Ordenar
              <select id="history-order" value={order} onChange={event => setOrder(event.target.value as 'newest' | 'oldest' | 'title')}
                className="mt-1 min-h-10 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-2 text-xs text-[--color-foreground] focus:border-[--color-teal]">
                <option value="newest">Mais recentes</option>
                <option value="oldest">Mais antigos</option>
                <option value="title">Título (A–Z)</option>
              </select>
            </label>
          </div>}
        </div>
        <p className="px-4 pt-2 text-[10px] text-[--color-muted]">
          Os metadados ficam no Firestore. Para reabrir o relatório, o backend original deve continuar disponível.
        </p>
        {/* Area filters */}
        {articles.length > 0 && (
          <div className="px-4 py-3 border-b border-[--color-border] shrink-0">
            <p className="font-mono text-[9px] text-[--color-subtle] tracking-widest uppercase mb-2">Área de saúde</p>
            <div className="flex flex-wrap gap-1.5">
              {areas.map((area) => {
                const cfg = area === 'Todas' ? null : HEALTH_AREAS[area]
                const isActive = activeArea === area
                return (
                  <button
                    key={area}
                    onClick={() => setActiveArea(area)}
                    aria-pressed={isActive}
                    className="health-area-badge px-2.5 py-1 rounded-full text-[10px] font-mono tracking-wide transition-all duration-150"
                    style={{
                      border: `1px solid ${isActive ? (cfg?.color ?? '#00d4aa') : 'var(--color-border)'}`,
                      background: isActive ? (cfg?.bg ?? '#00d4aa18') : 'transparent',
                      color: isActive ? (cfg?.color ?? '#00d4aa') : 'var(--color-muted)',
                    }}
                  >
                    {area}
                    {area !== 'Todas' && (
                      <span className="ml-1 opacity-70">
                        {articles.filter((a) => articleArea(a) === area).length}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {articles.length > 0 && <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[--color-border] px-4 py-2">
          <span role="status" className="text-[11px] text-[--color-muted]">{filtered.length} de {articles.length} artigo(s) encontrado(s)</span>
          {hasFilters && <button type="button" onClick={clearFilters}
            className="rounded-md px-2 py-1 text-xs font-semibold text-[--color-teal] transition-colors hover:bg-[--color-teal] hover:text-black">Limpar filtros</button>}
        </div>}
        {/* Articles list */}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-10 pt-3 space-y-3 sm:px-4">
          {loading ? (
            <p className="px-5 py-10 text-center text-xs text-[--color-muted]" role="status">Carregando histórico…</p>
          ) : articles.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-14 gap-3">
              <span className="font-mono text-3xl text-[--color-subtle]">⊡</span>
              <p className="text-xs text-[--color-muted] text-center font-mono">Nenhum artigo salvo ainda.</p>
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-xs text-[--color-muted] text-center py-10 font-mono">Nenhuma análise encontrada para os filtros.</p>
          ) : filtered.map((a, i) => {
            const area = articleArea(a)
            const cfg = HEALTH_AREAS[area] ?? HEALTH_AREAS['Geral']
            return (
            <div key={a.analysisId} className="rounded-xl border border-[--color-border] bg-[--color-background] p-4 space-y-3 transition-all duration-200 hover:border-[--color-teal] hover:bg-[--color-surface-2] hover:shadow-[0_8px_30px_rgba(0,212,170,0.07)]">
              {/* Area tag + verdict */}
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className="health-area-badge font-mono text-[9px] tracking-widest uppercase rounded-full px-2 py-0.5"
                  style={{ color: cfg.color, background: cfg.bg }}
                >
                  {area}
                </span>
                <span
                  className="font-mono text-[9px] tracking-widest uppercase border rounded px-1.5 py-0.5"
                  style={{ color: verdictColor[a.overallVerdict], borderColor: verdictColor[a.overallVerdict] }}
                >
                  {verdictLabel[a.overallVerdict]}
                </span>
                <span className="font-mono text-[9px] text-[--color-subtle] ml-auto">Análise científica</span>
              </div>
              <p className="text-xs text-[--color-foreground] leading-snug line-clamp-2">{a.title}</p>
              <p className="font-mono text-[10px] text-[--color-muted] break-all">{a.source}</p>
              <p className="font-mono text-[10px] text-[--color-subtle]">
                Salvo em {new Date(a.savedAt).toLocaleString('pt-BR')}
              </p>
              <div className="grid grid-cols-1 gap-2 pt-2 sm:grid-cols-2">
                <button type="button" disabled={Boolean(busyId)} onClick={() => onOpen(a.analysisId)}
                  className={`${BUTTON_GREEN} w-full text-xs`}>
                  {busyId === `open:${a.analysisId}` ? 'Abrindo…' : 'Abrir resultado'}
                </button>
                <button type="button" disabled={Boolean(busyId)} onClick={() => onDelete(a.analysisId)}
                  className={`${BUTTON_DANGER} w-full text-xs`}
                  aria-label={`Excluir ${a.title} do histórico`}>
                  {busyId === `delete:${a.analysisId}` ? 'Excluindo…' : 'Excluir registro'}
                </button>
              </div>
            </div>
          )})}
        </div>
      </div>
    </div>
  )
}

function AccessibilityMenu({
  settings,
  onChange,
}: {
  settings: AccessibilitySettings
  onChange: (settings: AccessibilitySettings) => void
}) {
  const [open, setOpen] = useState(false)
  const options: { key: 'highContrast' | 'reducedMotion'; label: string; description: string }[] = [
    { key: 'highContrast', label: 'Alto contraste', description: 'Recurso voltado para pessoas com baixa visão ou daltonismo' },
    { key: 'reducedMotion', label: 'Reduzir movimento', description: 'Desativa animações e transições' },
  ]
  const activeCount = Number(settings.highContrast) + Number(settings.textScale > 0) + Number(settings.reducedMotion)
  const textScalePercent = 100 + settings.textScale * 10

  return (
    <aside className="a11y-menu fixed bottom-4 right-4 z-[60] flex flex-col items-end gap-2" aria-label="Recursos de acessibilidade">
      {open && (
        <div
          id="accessibility-options"
          className="w-[min(19rem,calc(100vw-2rem))] rounded-xl border border-[--color-border-bright] p-4 shadow-2xl"
          style={{ backgroundColor: 'var(--color-surface)' }}
        >
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-[--color-foreground]">Acessibilidade</h2>
              <p className="mt-1 text-xs leading-relaxed text-[--color-muted]">Ajuste a visualização conforme sua preferência.</p>
            </div>
            {activeCount > 0 && (
              <button
                type="button"
                onClick={() => onChange({ highContrast: false, textScale: 0, reducedMotion: false })}
                className="a11y-reset rounded-md px-2 py-1 text-[10px] font-mono uppercase tracking-wide text-[--color-teal] hover:text-[--color-foreground]"
              >
                Redefinir
              </button>
            )}
          </div>
          <div className="space-y-2">
            <div className="flex w-full items-center justify-between gap-4 rounded-lg border border-[--color-border] px-3 py-2.5">
              <span>
                <span className="block text-xs font-semibold text-[--color-foreground]">Tamanho do texto</span>
                <span className="mt-0.5 block text-[10px] leading-snug text-[--color-muted]">
                  Nível atual: {textScalePercent}%
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => onChange({ ...settings, textScale: Math.max(0, settings.textScale - 1) })}
                  disabled={settings.textScale === 0}
                  aria-label="Diminuir tamanho do texto"
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-[--color-border-bright] font-mono text-xs font-bold text-[--color-foreground] disabled:cursor-not-allowed disabled:opacity-35"
                >
                  A−
                </button>
                <button
                  type="button"
                  onClick={() => onChange({ ...settings, textScale: Math.min(3, settings.textScale + 1) })}
                  disabled={settings.textScale === 3}
                  aria-label="Aumentar tamanho do texto"
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-[--color-border-bright] font-mono text-sm font-bold text-[--color-foreground] disabled:cursor-not-allowed disabled:opacity-35"
                >
                  A+
                </button>
              </span>
            </div>
            {options.map(({ key, label, description }) => {
              const active = settings[key]
              return (
                <button
                  key={key}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onChange({ ...settings, [key]: !active })}
                  className="accessibility-option flex w-full items-center justify-between gap-4 rounded-lg border border-[--color-border] px-3 py-2.5 text-left transition-colors hover:border-[--color-teal]"
                >
                  <span>
                    <span className="block text-xs font-semibold text-[--color-foreground]">{label}</span>
                    <span className="mt-0.5 block text-[10px] leading-snug text-[--color-muted]">{description}</span>
                  </span>
                  <span className="accessibility-toggle" aria-hidden="true">
                    <span className="accessibility-toggle-dot" />
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="accessibility-options"
        className="a11y-trigger relative flex h-12 items-center gap-2 rounded-full border border-[--color-teal] px-4 text-xs font-semibold text-[--color-foreground] shadow-xl transition-colors hover:bg-[--color-teal] hover:text-[--color-background]"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="4.5" r="2.25" fill="currentColor" />
          <path d="M5 8.5c4.4 1.4 9.6 1.4 14 0M12 9.5V14m0 0-4 6m4-6 4 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Acessibilidade
        {activeCount > 0 && <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[--color-teal] px-1 font-mono text-[9px] text-[--color-background]">{activeCount}</span>}
      </button>
    </aside>
  )
}

export default function App() {
  const [mode, setMode] = useState<VerifyMode>('url')
  const [url, setUrl] = useState('')
  const [searchMode, setSearchMode] = useState<SearchMode>('quick')
  const [advancedSearchType, setAdvancedSearchType] = useState<AdvancedSearchType>('pubmed')
  const [advancedPubmed, setAdvancedPubmed] = useState('')
  const [advancedDoi, setAdvancedDoi] = useState('')
  const [advancedUrl, setAdvancedUrl] = useState('')
  const [topic, setTopic] = useState('')
  const [topicArticleType, setTopicArticleType] = useState<TopicArticleType>('ALL')
  const [topicLanguage, setTopicLanguage] = useState<TopicLanguage>('ALL')
  const [topicIndexing, setTopicIndexing] = useState<TopicIndexing>('MEDLINE')
  const [topicAvailability, setTopicAvailability] = useState<TopicAvailability>('ALL')
  const [topicResult, setTopicResult] = useState<TopicSearchResponse | null>(null)
  const [topicGrouping, setTopicGrouping] = useState(false)
  const [topicFilteredPmids, setTopicFilteredPmids] = useState<string[] | null>(null)
  const [topicBusy, setTopicBusy] = useState(false)
  const [topicError, setTopicError] = useState('')
  const topicController = useRef<AbortController | null>(null)
  useEffect(() => () => topicController.current?.abort(), [])
  // A profundidade selecionada é preservada até a etapa de escolha das alegações.
  const depthRef = useRef<ResearchDepth>('QUICK')
  const [dragOver, setDragOver] = useState(false)
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [status, setStatus] = useState<AnalysisStatus>('idle')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [activeResultClaim, setActiveResultClaim] = useState(0)
  const [analysisMinimized, setAnalysisMinimized] = useState(false)
  const [topicMinimized, setTopicMinimized] = useState(false)
  const [minimizedDrafts, setMinimizedDrafts] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const controller = useRef<AbortController | null>(null)
  const busy = useRef(false)
  const [apiError, setApiError] = useState('')
  const [jobId, setJobId] = useState('')
  const [progress, setProgress] = useState(0)
  const [choices, setChoices] = useState<ExtractedClaim[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const addUserClaim = (claim: ExtractedClaim) => {
    setChoices(current => current.some(item => item.claim_id === claim.claim_id) ? current : [...current, claim])
    setSelected(current => current.length >= 10 ? current : [...current, claim.claim_id])
  }
  useEffect(() => () => controller.current?.abort(), [])

  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [userName, setUserName] = useState('')
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [showBanner, setShowBanner] = useState(false)
  const [showSaved, setShowSaved] = useState(false)
  const [showTermsModal, setShowTermsModal] = useState(false)
  const [savedArticles, setSavedArticles] = useState<SavedArticle[]>([])
  const [historyError, setHistoryError] = useState('')
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyBusyId, setHistoryBusyId] = useState('')
  const [accessibility, setAccessibility] = useState<AccessibilitySettings>(() => {
    const defaults = {
      highContrast: false,
      textScale: 0,
      reducedMotion: typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    }
    try {
      const saved = localStorage.getItem('artfact-accessibility')
      if (!saved) return defaults
      const parsed = JSON.parse(saved)
      return {
        highContrast: Boolean(parsed.highContrast),
        textScale: typeof parsed.textScale === 'number'
          ? Math.min(3, Math.max(0, parsed.textScale))
          : parsed.largeText ? 1 : 0,
        reducedMotion: typeof parsed.reducedMotion === 'boolean' ? parsed.reducedMotion : defaults.reducedMotion,
      }
    } catch {
      return defaults
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem('artfact-accessibility', JSON.stringify(accessibility))
    } catch {
      // The controls still work when browser storage is unavailable.
    }
  }, [accessibility])

  useEffect(() => onAuthStateChanged(auth, user => {
    setIsLoggedIn(Boolean(user))
    setUserName(user?.displayName || user?.email?.split('@')[0] || '')
    setSavedArticles([])
    setHistoryError('')
    setHistoryLoading(Boolean(user))
    setHistoryBusyId('')
    setShowSaved(false)
    if (user) {
      setShowLoginModal(false)
      setShowBanner(false)
      void loadHistory(user.uid).then(entries => {
        if (auth.currentUser?.uid === user.uid) {
          setSavedArticles(current => [...current, ...entries.filter(entry => !current.some(item => item.analysisId === entry.analysisId))]
            .sort((a, b) => b.savedAt - a.savedAt))
          setHistoryLoading(false)
        }
      }).catch(() => {
        if (auth.currentUser?.uid === user.uid) {
          setHistoryError('Não foi possível carregar o histórico. Confira o Firestore e suas regras de acesso.')
          setHistoryLoading(false)
        }
      })
    }
  }, error => setApiError(authErrorMessage(error))), [])

  const handleLogout = async () => {
    try { await logout() }
    catch (error) { setApiError(authErrorMessage(error)) }
  }

  const openHistoryItem = async (id: string) => {
    const uid = auth.currentUser?.uid
    if (!uid || historyBusyId || busy.current) return
    setHistoryBusyId(`open:${id}`)
    setHistoryError('')
    try {
      const job = await getSavedAnalysis(id, new AbortController().signal)
      if (auth.currentUser?.uid !== uid) return
      const data = mapResult(job)
      data.healthArea = detectHealthArea(data.title)
      setResult(data)
      setActiveResultClaim(0)
      setAnalysisMinimized(false)
      setJobId(id)
      setApiError('')
      setStatus('done')
      setShowSaved(false)
      window.requestAnimationFrame(() => document.getElementById('artfact-analysis-result')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    } catch (error) {
      if (auth.currentUser?.uid === uid) setHistoryError(error instanceof Error ? error.message : 'Não foi possível reabrir esta análise.')
    } finally {
      if (auth.currentUser?.uid === uid) setHistoryBusyId('')
    }
  }

  const removeHistoryItem = async (id: string) => {
    const uid = auth.currentUser?.uid
    if (!uid || historyBusyId) return
    if (!window.confirm('Excluir este item do histórico? O relatório do backend não será apagado.')) return
    setHistoryBusyId(`delete:${id}`)
    setHistoryError('')
    try {
      await deleteHistoryEntry(uid, id)
      if (auth.currentUser?.uid === uid) {
        setSavedArticles(current => current.filter(item => item.analysisId !== id))
      }
    } catch {
      if (auth.currentUser?.uid === uid) setHistoryError('Não foi possível excluir o registro. Confira sua conexão e as regras do Firestore.')
    } finally {
      if (auth.currentUser?.uid === uid) setHistoryBusyId('')
    }
  }

  const receiveJob = (job: Job) => {
    if (job.status === 'AWAITING_CLAIM_SELECTION') {
      const items = extractedClaims(job)
      // Mesmo sem alegações automáticas, o usuário pode criar as próprias no leitor.
      setChoices(items)
      // Deixa vagas para que o usuário selecione trechos do artigo diretamente.
      setSelected(items.slice(0, 3).map(c => c.claim_id))
      setMinimizedDrafts([])
      setStatus('selecting')
    } else {
      const data = mapResult(job)
      data.healthArea = detectHealthArea(data.title)
      setResult(data)
      setActiveResultClaim(0)
      setAnalysisMinimized(false)
      const currentUser = auth.currentUser
      if (currentUser) {
        const entry = makeSavedArticle(data)
        void saveHistory(currentUser.uid, entry).then(() => {
          if (auth.currentUser?.uid === currentUser.uid) {
            setSavedArticles(prev => [entry, ...prev.filter(item => item.analysisId !== entry.analysisId)].sort((a, b) => b.savedAt - a.savedAt))
          }
        }).catch(() => {
          if (auth.currentUser?.uid === currentUser.uid) setHistoryError('Não foi possível salvar a análise no histórico. Verifique as regras do Firestore.')
        })
      }
      setStatus('done')
    }
  }

  // QUICK e DEEP são opções reais do backend, aplicadas à pesquisa de alegações.
  const inputValue = searchMode === 'quick' ? url
    : advancedSearchType === 'pubmed' ? advancedPubmed
    : advancedSearchType === 'doi' ? advancedDoi : advancedUrl
  const setInputValue = (value: string) => {
    if (searchMode === 'quick') setUrl(value)
    else if (advancedSearchType === 'pubmed') setAdvancedPubmed(value)
    else if (advancedSearchType === 'doi') setAdvancedDoi(value)
    else setAdvancedUrl(value)
  }
  const articleReference = (() => {
    const value = inputValue.trim()
    if (!value) return ''
    if (searchMode === 'quick') return value
    if (advancedSearchType === 'pubmed') {
      if (/^[0-9]{1,12}$/.test(value)) return `https://pubmed.ncbi.nlm.nih.gov/${value}/`
      try {
        const link = new URL(value)
        if (link.protocol === 'https:' && link.hostname === 'pubmed.ncbi.nlm.nih.gov' && /^\/[0-9]+\/?$/.test(link.pathname)) return link.href
      } catch { /* PMID ou link inválido */ }
      return ''
    }
    if (advancedSearchType === 'doi') {
      const doi = value.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '')
      return /^10\.[0-9]{4,9}\/\S+$/.test(doi) ? doi : ''
    }
    // Na opção URL, não aceitar DOI isolado: manter a escolha de origem explícita.
    return /^https?:\/\/\S+$/i.test(value) ? value : ''
  })()

  const clearTopicSearch = () => {
    topicController.current?.abort()
    topicController.current = null
    setTopicBusy(false)
    setTopicError('')
    setTopicResult(null)
    setTopicFilteredPmids(null)
  }

  // Usa a rota PubMed existente do Flask. Não envia o tema para o endpoint de DOI/URL.
  const runTopicSearch = async (page = 1) => {
    const cleanTopic = topic.trim()
    if (cleanTopic.length < 2 || cleanTopic.length > 300) {
      setTopicError('Informe um tema com 2 a 300 caracteres.')
      return
    }
    if (topicBusy || busy.current || status === 'selecting') return
    topicController.current?.abort()
    const active = new AbortController()
    topicController.current = active
    setTopicBusy(true)
    setTopicError('')
    try {
      const preparedQuery = page > 1 ? topicResult?.query_results?.[0]?.query : undefined
      const body = {
        topic: cleanTopic,
        article_type: topicArticleType,
        language: topicLanguage,
        indexing: topicIndexing,
        availability: topicAvailability,
        page,
        page_size: 8,
        ...(page > 1 && preparedQuery ? { prepared_query: preparedQuery } : {}),
      }
      const base = (import.meta.env?.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
      const response = await fetch(`${base}/pubmed-search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.any([active.signal, AbortSignal.timeout(60000)]),
      })
      const json: unknown = await response.json().catch(() => null)
      const payload = json && typeof json === 'object' ? json as Record<string, unknown> : {}
      if (!response.ok) {
        const error = payload.error && typeof payload.error === 'object'
          ? payload.error as Record<string, unknown> : {}
        throw new Error(typeof error.message === 'string' ? error.message : `Falha ao consultar o PubMed (HTTP ${response.status}).`)
      }
      if (!Array.isArray(payload.articles) || !payload.pagination || typeof payload.pagination !== 'object') {
        throw new Error('O backend retornou um resultado de busca por tema inesperado.')
      }
      if (active.signal.aborted) return
      setTopicResult(payload as unknown as TopicSearchResponse)
      setTopicMinimized(false)
      setTopicFilteredPmids(null)
    } catch (error) {
      if (!active.signal.aborted) setTopicError(error instanceof TypeError ? 'Não foi possível acessar o servidor de pesquisa. Confira se o Flask está funcionando na porta 5000.' : error instanceof Error ? error.message : 'Não foi possível pesquisar o tema.')
    } finally {
      if (topicController.current === active) { topicController.current = null; setTopicBusy(false) }
    }
  }

  // Escolher um artigo encontrado reaproveita a análise de URL já existente.
  const analyzeTopicArticle = (pmid: string) => {
    if (!/^\d{1,12}$/.test(pmid) || busy.current || status === 'loading' || status === 'selecting') return
    depthRef.current = searchMode === 'advanced' ? 'DEEP' : 'QUICK'
    void runAnalysis('new', `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`)
  }

  const runAnalysis = async (action: 'new' | 'select' | 'resume', articleOverride?: string) => {
    if (busy.current) return
    busy.current = true
    const active = new AbortController()
    controller.current = active
    setApiError('')
    setStatus('loading')
    setProgress(0)
    try {
      let id = jobId
      if (action === 'new') {
        setResult(null)
        setChoices([])
        setJobId('')
        const job = await startAnalysis(articleOverride || (mode === 'url' ? articleReference : ''), mode === 'image' ? uploadedFile : null, active.signal)
        if (active.signal.aborted) return
        id = job.analysis_id
        setJobId(id)
      } else if (action === 'select') {
        await selectClaims(id, choices.filter(c => selected.includes(c.claim_id)), active.signal, depthRef.current)
      }
      const job = await pollAnalysis(id, active.signal, j => setProgress(j.progress))
      if (!active.signal.aborted) receiveJob(job)
    } catch (error) {
      if (!active.signal.aborted) {
        setApiError(error instanceof Error ? error.message : 'Falha inesperada ao analisar.')
        setStatus('idle')
      }
    } finally {
      if (controller.current === active) busy.current = false
    }
  }
  const handleAnalyze = () => {
    if ((mode === 'url' && !articleReference) || (mode === 'image' && !uploadedFile)) {
      setApiError('Informe uma referência válida ou selecione um arquivo compatível.')
      return
    }
    depthRef.current = searchMode === 'advanced' ? 'DEEP' : 'QUICK'
    void runAnalysis('new')
  }
  const stopPolling = () => {
    controller.current?.abort()
    controller.current = null
    busy.current = false
    setStatus('idle')
    setApiError('Consulta interrompida. O processamento pode continuar no servidor; use Retomar para consultar o resultado.')
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) setUploadedFile(file)
  }, [])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) setUploadedFile(file)
  }

  const canAnalyze = mode === 'url' ? articleReference.length > 0 : mode === 'image' ? uploadedFile !== null : topic.trim().length >= 2 && topic.trim().length <= 300
  const accessibilityClasses = [
    accessibility.highContrast && 'a11y-high-contrast',
    accessibility.textScale > 0 && `a11y-text-scale-${accessibility.textScale}`,
    accessibility.reducedMotion && 'a11y-reduced-motion',
  ].filter(Boolean).join(' ')

  return (
    <div className={`min-h-screen bg-[--color-background] grid-bg scan-line ${accessibilityClasses}`}>
      <a href="#main-content" className="skip-link">Pular para o conteúdo principal</a>
      {/* Nav */}
      <header className="border-b border-[--color-border] bg-[--color-background] bg-opacity-90 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* ArtFact wordmark logo */}
          <div className="logo-mark cursor-pointer" style={{ lineHeight: 0 }}>
              <svg
                height="42"
                viewBox="0 0 142 76"
                fill="none"
                aria-label="ArtFact"
                style={{ width: 'auto' }}
              >
                {/* Magnifying glass — animates on hover */}
                <g className="logo-glass">
                  {/* Outer ring */}
                  <circle cx="36" cy="36" r="28" stroke="#00d4aa" strokeWidth="6"/>
                  {/* Handle */}
                  <line x1="57" y1="57" x2="75" y2="75" stroke="#00d4aa" strokeWidth="6" strokeLinecap="round"/>
                </g>
                {/* ART inside lens */}
                <text
                  x="36" y="42"
                  textAnchor="middle"
                  fontFamily="Instrument Sans, sans-serif"
                  fontWeight="700"
                  fontSize="15"
                  fill="#00d4aa"
                  className="logo-art"
                  letterSpacing="1"
                >
                  ART
                </text>
                {/* Fact outside lens */}
                <text
                  x="72" y="48"
                  fontFamily="Instrument Sans, sans-serif"
                  fontWeight="700"
                  fontSize="27"
                  fill="#dce6f5"
                  className="logo-fact"
                >
                  Fact
                </text>
              </svg>
            </div>
          </div>
          <nav className="flex items-center gap-2">
            <a href="#sobre" className="text-xs text-[--color-muted] px-3 py-1.5 rounded-md transition-all duration-150 hover:bg-white hover:text-black" style={{ fontFamily: 'Helvetica, Arial, sans-serif' }}>Sobre</a>
            <a href="#como" className="text-xs text-[--color-muted] px-3 py-1.5 rounded-md transition-all duration-150 hover:bg-white hover:text-black" style={{ fontFamily: 'Helvetica, Arial, sans-serif' }}>Como funciona</a>
            {isLoggedIn ? (
              <div className="flex items-center gap-2 ml-2">
                <button
                  onClick={() => setShowSaved(true)}
                  className="flex min-h-10 items-center gap-1.5 rounded-lg border border-[--color-border] px-3 py-2 text-xs text-[--color-muted] transition-all duration-200 hover:border-[--color-teal] hover:bg-[--color-teal] hover:text-[--color-background]"
                  style={{ fontFamily: 'Helvetica, Arial, sans-serif' }}
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                    <path d="M2 1h8a1 1 0 011 1v9l-4.5-2.5L2 11V2a1 1 0 011-1z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
                  </svg>
                  {savedArticles.length > 0 && (
                    <span className="font-mono text-[10px] text-[--color-teal]">{savedArticles.length}</span>
                  )}
                  Histórico
                </button>
                <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-[--color-surface] border border-[--color-border]">
                  <div className="w-5 h-5 rounded-full bg-[--color-teal] flex items-center justify-center">
                    <span className="font-mono text-[9px] font-bold text-[--color-background]">
                      {userName.charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <span className="text-xs text-[--color-foreground] max-w-[80px] truncate" style={{ fontFamily: 'Helvetica, Arial, sans-serif' }}>{userName}</span>
                </div>
                <button onClick={() => void handleLogout()} className="text-xs underline underline-offset-4 hover:text-[--color-teal] transition-colors">Sair</button>
              </div>
            ) : (
              <button
                onClick={() => setShowLoginModal(true)}
                className="ml-2 px-3 py-1.5 rounded-md text-xs font-semibold border border-[--color-teal] text-[--color-teal] hover:border-[#00d4aa] hover:bg-[#00d4aa] hover:text-[#080c18] transition-all duration-150"
                style={{ fontFamily: 'Helvetica, Arial, sans-serif' }}
              >
                Entrar
              </button>
            )}
          </nav>
        </div>
      </header>

      <main id="main-content" className={`${status === 'done' && result ? 'max-w-5xl' : 'max-w-3xl'} mx-auto px-4 py-14 pb-24`}>
        {/* Hero */}
        <div className="mx-auto mb-12 max-w-3xl space-y-3">
          <div className="font-mono text-[11px] text-[--color-teal] tracking-widest uppercase mb-4">
            Verificador de artigos científicos 
          </div>
        <h1
          className="text-4xl leading-tight text-[--color-foreground]"
          style={{ fontFamily: "'Special Elite', cursive" }}
        >

          <br />
          <span className="typewriter-line-delay text-[--color-teal]">
            Busque por um artigo e verifique a qualidade das evidências
          </span>
        </h1>
        </div>

        {/* Input card */}
        <div className="verification-card mx-auto max-w-3xl overflow-hidden rounded-2xl border border-[--color-border] bg-[--color-surface] shadow-[0_20px_60px_rgba(0,0,0,0.2)]">
          {/* Mode toggle */}
          <div className="grid grid-cols-3 border-b border-[--color-border]">
            {(['url', 'topic', 'image'] as VerifyMode[]).map((m) => (
              <button
                key={m}
                onClick={() => { if (status !== 'loading' && status !== 'selecting') { setMode(m); setResult(null); setStatus('idle'); setApiError('') } }}
                disabled={status === 'loading' || status === 'selecting'}
                aria-pressed={mode === m}
                className={`flex-1 py-3.5 font-mono text-xs tracking-widest uppercase transition-colors duration-150 ${
                  mode === m
                    ? 'text-[--color-teal] bg-[--color-teal-faint] border-b-2 border-[--color-teal]'
                    : 'text-[--color-muted] hover:bg-[--color-teal-faint] hover:text-[--color-teal] hover:border-b-2 hover:border-[--color-teal]'
                }`}
              >
                {m === 'url' ? '⌘  Link / DOI' : m === 'topic' ? '⌕  Por tema' : '⊡  PDF / Imagem'}
              </button>
            ))}
          </div>

          <div className="border-b border-[--color-border] px-4 py-5 sm:px-6">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="font-mono text-[10px] uppercase tracking-widest text-[--color-muted]">Profundidade da pesquisa</p>
              <span className="text-[11px] text-[--color-muted]">Aplicada após a seleção de alegações</span>
            </div>
            <div role="group" aria-label="Profundidade da pesquisa" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {([['quick', 'Pesquisa rápida'],
                ['advanced', 'Pesquisa avançada']] as const).map(([kind, label]) => (
                <button key={kind} type="button" disabled={status === 'loading' || status === 'selecting'}
                  onClick={() => setSearchMode(kind)} aria-pressed={searchMode === kind}
                  className={`min-h-14 rounded-xl border px-4 py-3 text-center transition-all duration-200 disabled:opacity-50 ${searchMode === kind
                    ? 'border-[--color-teal] bg-[--color-teal-faint] shadow-[inset_0_0_0_1px_rgba(0,212,170,0.15)]'
                    : 'border-[--color-border] bg-[--color-background] hover:border-[--color-teal] hover:bg-[--color-teal-faint]'}`}>
                  <span className={`block text-sm font-semibold ${searchMode === kind ? 'text-[--color-teal]' : 'text-[--color-foreground]'}`}>{label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="p-4 space-y-5 sm:p-6">
            {mode === 'url' ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <label htmlFor="article-url" className="font-mono text-[11px] uppercase tracking-widest text-[--color-foreground]">
                    {searchMode === 'quick' ? 'Link ou DOI do artigo' : 'Referência científica'}
                  </label>
                  <span className="rounded-full border border-[--color-border] px-2 py-1 text-[10px] text-[--color-teal]">
                    {searchMode === 'advanced' ? 'DEEP' : 'QUICK'}
                  </span>
                </div>
                {searchMode === 'advanced' && (
                  <div className="grid grid-cols-3 gap-2" role="group" aria-label="Tipo de referência científica">
                    {([['pubmed', 'PubMed / PMID'], ['doi', 'DOI'], ['url', 'URL']] as const).map(([kind, label]) => (
                      <button type="button" key={kind} aria-pressed={advancedSearchType === kind}
                        onClick={() => setAdvancedSearchType(kind)}
                        className={`min-h-11 rounded-lg border px-2 py-2 text-xs font-semibold transition-all duration-200 ${advancedSearchType === kind
                          ? 'border-[--color-teal] bg-[--color-teal-faint] text-[--color-teal]'
                          : 'border-[--color-border] text-[--color-muted] hover:border-[--color-teal] hover:bg-[--color-teal-faint] hover:text-[--color-teal]'}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                )}
                <div className="flex min-h-14 items-center gap-3 rounded-xl border border-[--color-border] bg-[--color-background] px-4 transition-colors duration-200 focus-within:border-[--color-teal] focus-within:shadow-[0_0_0_3px_rgba(0,212,170,0.1)]">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="shrink-0 text-[--color-teal]" aria-hidden="true">
                    <circle cx="10.7" cy="10.7" r="6.7" /><path d="m16 16 5 5" strokeLinecap="round" />
                  </svg>
                  <input
                    id="article-url" type="text" autoComplete="url" value={inputValue}
                    onChange={(event) => setInputValue(event.target.value)}
                    onKeyDown={(event) => { if (event.key === 'Enter' && canAnalyze && status !== 'loading' && status !== 'selecting') handleAnalyze() }}
                    placeholder={searchMode === 'quick' ? 'Cole o link PubMed, DOI ou URL do artigo'
                      : advancedSearchType === 'pubmed' ? 'PMID: 36842787 ou link do PubMed'
                      : advancedSearchType === 'doi' ? '10.1016/j.ccm.2019.10.001'
                      : 'https://exemplo.org/artigo'}
                    className="min-w-0 w-full bg-transparent py-4 text-sm text-[--color-foreground] placeholder:text-[--color-subtle] outline-none font-mono"
                    aria-describedby="search-input-hint"
                  />
                </div>
                <p id="search-input-hint" className="text-xs leading-relaxed text-[--color-muted]">
                  {searchMode === 'quick'
                    ? 'Cole a referência completa. O protocolo https:// não será duplicado.'
                    : advancedSearchType === 'pubmed' ? 'Digite apenas o PMID ou o link do PubMed.'
                    : advancedSearchType === 'doi' ? 'Informe um DOI válido (ou um link doi.org).'
                    : 'Informe a URL completa do artigo, começando por https://.'}
                </p>
                {searchMode === 'advanced' && <p className="rounded-lg border border-[--color-border] bg-[--color-background] px-4 py-3 text-xs leading-relaxed text-[--color-muted]">
                  <strong className="text-[--color-teal]">Pesquisa aprofundada:</strong> após selecionar as alegações, o backend utilizará a profundidade DEEP. O processamento pode demorar mais e consumir mais chamadas de API.
                </p>}
              </div>
            ) : mode === 'topic' ? (
              <div className="space-y-5">
                <div className="space-y-2">
                  <label htmlFor="topic-search" className="font-mono text-[11px] uppercase tracking-widest text-[--color-foreground]">Pesquisar artigos por tema no PubMed</label>
                  <div className="flex min-h-14 items-center gap-3 rounded-xl border border-[--color-border] bg-[--color-background] px-4 focus-within:border-[--color-teal]">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="shrink-0 text-[--color-teal]" aria-hidden="true">
                      <circle cx="10.7" cy="10.7" r="6.7"/><path d="m16 16 5 5" strokeLinecap="round"/>
                    </svg>
                    <input id="topic-search" type="search" maxLength={300} value={topic}
                      onChange={event => { setTopic(event.target.value); clearTopicSearch() }}
                      onKeyDown={event => { if (event.key === 'Enter' && !topicBusy && canAnalyze) void runTopicSearch(1) }}
                      placeholder="Ex.: IA no diagnóstico do câncer de mama"
                      className="min-w-0 w-full bg-transparent py-4 text-sm text-[--color-foreground] placeholder:text-[--color-subtle] outline-none"
                      aria-describedby="topic-help" />
                  </div>
                  <p id="topic-help" className="text-xs text-[--color-muted]">Encontre artigos reais sobre o assunto e escolha qual deseja analisar. Uma busca temática não é, por si só, uma análise de evidências.</p>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className="space-y-1.5 text-xs text-[--color-muted]">Tipo de publicação
                    <select value={topicArticleType} onChange={event => { setTopicArticleType(event.target.value as TopicArticleType); clearTopicSearch() }}
                      className="min-h-11 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-3 text-sm text-[--color-foreground] focus:border-[--color-teal]">
                      <option value="ALL">Todos os tipos</option>
                      <option value="REVIEWS">Revisões sistemáticas / metanálises</option>
                      <option value="TRIALS">Ensaios clínicos randomizados</option>
                    </select>
                  </label>
                  <label className="space-y-1.5 text-xs text-[--color-muted]">Idioma
                    <select value={topicLanguage} onChange={event => { setTopicLanguage(event.target.value as TopicLanguage); clearTopicSearch() }}
                      className="min-h-11 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-3 text-sm text-[--color-foreground] focus:border-[--color-teal]">
                      <option value="ALL">Todos os idiomas</option>
                      <option value="PORTUGUESE">Português</option>
                      <option value="ENGLISH">Inglês</option>
                      <option value="SPANISH">Espanhol</option>
                      <option value="FRENCH">Francês</option>
                      <option value="GERMAN">Alemão</option>
                      <option value="ITALIAN">Italiano</option>
                    </select>
                  </label>
                  <label className="space-y-1.5 text-xs text-[--color-muted]">Indexação
                    <select value={topicIndexing} onChange={event => { setTopicIndexing(event.target.value as TopicIndexing); clearTopicSearch() }}
                      className="min-h-11 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-3 text-sm text-[--color-foreground] focus:border-[--color-teal]">
                      <option value="MEDLINE">Somente MEDLINE</option>
                      <option value="ALL">Todo o PubMed</option>
                    </select>
                  </label>
                  <label className="space-y-1.5 text-xs text-[--color-muted]">Disponibilidade
                    <select value={topicAvailability} onChange={event => { setTopicAvailability(event.target.value as TopicAvailability); clearTopicSearch() }}
                      className="min-h-11 w-full rounded-lg border border-[--color-border] bg-[--color-background] px-3 text-sm text-[--color-foreground] focus:border-[--color-teal]">
                      <option value="ALL">Todos</option>
                      <option value="PMC_FULL_TEXT">Texto completo no PMC</option>
                    </select>
                  </label>
                </div>
                <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-[--color-border] bg-[--color-background] p-4 text-xs text-[--color-foreground]">
                  <input type="checkbox" checked={topicGrouping} onChange={event => { setTopicGrouping(event.target.checked); setTopicFilteredPmids(null) }} />
                  <span><strong className="block font-semibold">Agrupar artigos por tema</strong><span className="mt-1 block leading-relaxed text-[--color-muted]">Encontra grupos pela similaridade entre os títulos desta página (BERTopic). Você poderá filtrar por grupos e visualizar o mapa de relações.</span></span>
                </label>
              </div>
            ) : (
              <div className="space-y-3">
                <label htmlFor="article-image" className="font-mono text-[10px] text-[--color-muted] tracking-widest uppercase">
                  PDF ou imagem do artigo
                </label>
                <div
                  onClick={() => fileRef.current?.click()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      fileRef.current?.click()
                    }
                  }}
                  onDrop={handleDrop}
                  onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                  onDragLeave={() => setDragOver(false)}
                  className={`relative border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-all duration-200 ${
                    dragOver
                      ? 'border-[--color-teal] bg-[--color-teal-faint]'
                      : uploadedFile
                      ? 'border-[--color-teal] bg-[--color-teal-faint]'
                      : 'border-[--color-border] hover:border-[--color-teal] hover:bg-[--color-teal-faint] bg-[--color-background]'
                  }`}
                  role="button"
                  tabIndex={0}
                  aria-label={uploadedFile ? `Arquivo selecionado: ${uploadedFile.name}. Ativar para substituir.` : 'Selecionar imagem do artigo'}
                >
                  {uploadedFile ? (
                    <div className="space-y-1">
                      <div className="font-mono text-xs text-[--color-teal] tracking-wide">✓ Arquivo carregado</div>
                      <div className="text-sm text-[--color-foreground]">{uploadedFile.name}</div>
                      <div className="font-mono text-[10px] text-[--color-muted]">
                        {(uploadedFile.size / 1024).toFixed(1)} KB
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="text-3xl text-[--color-subtle]">⊡</div>
                      <div className="text-sm text-[--color-muted]">
                        Arraste um print aqui ou <span className="text-[--color-teal]">clique para selecionar</span>
                      </div>
                      <div className="font-mono text-[10px] text-[--color-subtle]">PDF, PNG, JPG, WEBP — máx. 25 MB</div>
                    </div>
                  )}
                </div>
                <input
                  id="article-image"
                  ref={fileRef}
                  type="file"
                  accept="application/pdf,image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </div>
            )}

            <button
              onClick={mode === 'topic' ? () => void runTopicSearch(1) : handleAnalyze}
              disabled={!canAnalyze || topicBusy || status === 'loading' || status === 'selecting'}
              className={`w-full min-h-12 py-3.5 rounded-lg border border-[--color-teal] text-sm tracking-wide transition-all duration-200 ${
                canAnalyze && !topicBusy && status !== 'loading' && status !== 'selecting'
                  ? 'bg-[--color-teal] text-black hover:text-black hover:bg-[#14f4c6] hover:shadow-[0_10px_28px_rgba(0,212,170,0.25)] active:scale-[0.99]'
                  : 'bg-[--color-border] text-[--color-subtle] cursor-not-allowed'
              }`}
              style={{ fontFamily: 'Helvetica, Arial, sans-serif', fontWeight: 600 }}
            >
              {mode === 'topic' ? (topicBusy ? 'Buscando artigos no PubMed…' : 'Buscar artigos por tema') : status === 'loading' ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-4 h-4 border-2 border-[--color-background] border-t-transparent rounded-full animate-spin" />
                  Processando artigo...
                </span>
              ) : (
                searchMode === 'advanced' ? 'Iniciar pesquisa avançada' : 'Verificar artigo'
              )}
            </button>
          </div>
        </div>

        {mode === 'topic' && topicError && <p role="alert" className="mx-auto mt-4 max-w-3xl rounded-lg border border-[--color-red] bg-[--color-red-faint] p-4 text-sm text-[--color-foreground]">{topicError}</p>}

        {apiError && <div role="alert" className="mt-5 p-4 rounded-lg border border-red-400 text-sm">{apiError}
          {jobId && <button onClick={() => void runAnalysis('resume')} disabled={status === 'loading'} className={`${BUTTON_GREEN} ml-3`}>Retomar</button>}
        </div>}
        {status === 'loading' && <button onClick={stopPolling} className={`${BUTTON_GREEN} mt-4`}>Interromper consulta</button>}
        {status === 'selecting' && <section className="mt-6 space-y-5 rounded-xl border border-[--color-border] bg-[--color-surface] p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-[--color-foreground]">Selecione as alegações para pesquisar</h2>
            <span className="rounded-full border border-[--color-border] px-3 py-1 text-xs text-[--color-muted]">{selected.length} de 10 selecionadas</span>
          </div>
          <p className="text-sm leading-relaxed text-[--color-muted]">Você pode usar alegações sugeridas pelo sistema <strong>ou selecionar diretamente um trecho do artigo</strong>, revisar a afirmação e adicioná-la à pesquisa. Modo: {depthRef.current === 'DEEP' ? 'avançado (DEEP)' : 'rápido (QUICK)'}.</p>
          <ScientificReader analysisId={jobId} onAdd={addUserClaim} remaining={10 - selected.length} />
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[--color-border] pt-5">
            <div>
              <h3 className="text-sm font-semibold text-[--color-foreground]">Alegações sugeridas e adicionadas</h3>
              <p className="mt-1 text-xs text-[--color-muted]">Marque as afirmações a pesquisar. Minimize individualmente as que não deseja editar.</p>
            </div>
            {choices.length > 0 && <button type="button" className={`${BUTTON_GREEN} min-h-9 px-3 py-2 text-xs`}
              onClick={() => setMinimizedDrafts(current => current.length === choices.length ? [] : choices.map(item => item.claim_id))}>
              {minimizedDrafts.length === choices.length ? '＋ Expandir todas' : '− Minimizar todas'}
            </button>}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {choices.map((c, index) => {
              const isSelected = selected.includes(c.claim_id)
              const isMinimized = minimizedDrafts.includes(c.claim_id)
              return <article key={c.claim_id} className={`space-y-3 rounded-xl border p-4 transition-colors ${isSelected
                ? 'border-[--color-teal] bg-[--color-teal-faint]'
                : 'border-[--color-border] bg-[--color-background] hover:border-[--color-teal]'}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label className="flex min-h-9 cursor-pointer items-center gap-2 text-xs font-semibold text-[--color-foreground]">
                    <input type="checkbox" checked={isSelected}
                      disabled={!isSelected && selected.length >= 10}
                      onChange={event => setSelected(prev => event.target.checked ? [...prev, c.claim_id] : prev.filter(id => id !== c.claim_id))} />
                    <span>{c.source === 'USER' ? 'Alegação criada por você' : `Alegação sugerida ${index + 1}`}</span>
                  </label>
                  <button type="button" aria-expanded={!isMinimized}
                    onClick={() => setMinimizedDrafts(ids => isMinimized ? ids.filter(id => id !== c.claim_id) : [...ids, c.claim_id])}
                    className="min-h-9 rounded-lg border border-[--color-border] px-3 py-1.5 text-xs font-medium text-[--color-teal] hover:border-[--color-teal] hover:bg-[--color-teal-faint]">
                    {isMinimized ? '＋ Expandir' : '− Minimizar'}
                  </button>
                </div>
                {isMinimized ? <p className="line-clamp-2 text-sm leading-relaxed text-[--color-foreground]">{c.text}</p> : <div className="space-y-2">
                  <textarea rows={3} aria-label={`Editar alegação ${index + 1}`} value={c.text} maxLength={2000}
                    onChange={event => setChoices(items => items.map(item => item.claim_id === c.claim_id ? { ...item, text: event.target.value } : item))}
                    className="w-full rounded-md border border-[--color-border] bg-[--color-background] p-2 text-sm text-[--color-foreground]" />
                  {c.quote && <p className="text-[11px] leading-relaxed text-[--color-muted]">Trecho selecionado: “{c.quote.slice(0, 220)}{c.quote.length > 220 ? '…' : ''}”{c.section ? ' · ' + c.section : ''}{c.page ? ' · Página ' + c.page : ''}</p>}
                  {c.source === 'USER' && <button type="button" onClick={() => {
                    setChoices(items => items.filter(item => item.claim_id !== c.claim_id))
                    setSelected(ids => ids.filter(id => id !== c.claim_id))
                    setMinimizedDrafts(ids => ids.filter(id => id !== c.claim_id))
                  }} className="min-h-9 text-xs text-[--color-red] underline">Remover alegação criada</button>}
                </div>}
              </article>
            })}
          </div>
          <button disabled={!selected.length || choices.filter(c => selected.includes(c.claim_id)).some(c => c.text.trim().length < 8)}
            onClick={() => void runAnalysis('select')} className={`${BUTTON_FILLED} w-full sm:w-auto`}>
            Pesquisar {selected.length} alegação(ões)
          </button>
        </section>}
        {/* Loading skeleton */}
        {status === 'loading' && (
          <div className="mt-10 space-y-4 animate-slide-up" role="status" aria-live="polite">
            <div className="border border-[--color-border] rounded-lg p-5 bg-[--color-surface] space-y-3">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-2 h-2 rounded-full bg-[--color-teal] animate-pulse" />
                <span className="font-mono text-[11px] text-[--color-teal] tracking-widest">PROCESSANDO ARTIGO · {Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0}%</span>
              </div>
              <div role="progressbar" aria-label="Progresso da análise" aria-valuemin={0} aria-valuemax={100}
                aria-valuenow={Math.max(0, Math.min(100, Number.isFinite(progress) ? progress : 0))}
                className="h-2 overflow-hidden rounded-full bg-[--color-border]">
                <div className="h-full rounded-full bg-[--color-teal] transition-all duration-500"
                  style={{ width: `${Math.max(0, Math.min(100, Number.isFinite(progress) ? progress : 0))}%` }} />
              </div>
              {[94, 82, 68, 87].map((width, i) => (
                <div key={i} className="shimmer h-4 rounded" style={{ width: `${width}%` }} />
              ))}
            </div>
          </div>
        )}

        {/* Cards das alegações entre a busca e os artigos encontrados. */}
        {status === 'done' && result && <>
          <ClaimOverviewCards result={result} activeIndex={activeResultClaim}
            onChoose={index => {
              setActiveResultClaim(index)
              setAnalysisMinimized(false)
              window.requestAnimationFrame(() => window.requestAnimationFrame(() => document.getElementById('artfact-claims-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })))
            }} />
          <section id="artfact-analysis-result" className="mt-6 space-y-3" aria-label="Resultado da análise científica">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[--color-border] bg-[--color-surface] px-5 py-3">
              <h2 className="text-sm font-semibold text-[--color-foreground]">Análise de afirmações</h2>
              <button type="button" aria-expanded={!analysisMinimized} onClick={() => setAnalysisMinimized(value => !value)}
                className={`${BUTTON_GREEN} min-h-9 px-3 py-2 text-xs`}>
                {analysisMinimized ? '＋ Expandir análise' : '− Minimizar análise'}
              </button>
            </div>
            {!analysisMinimized && <AnalysisCard key={result.analysisId} result={result}
              activeClaimIndex={activeResultClaim} onSelectClaim={setActiveResultClaim} />}
          </section>
        </>}

        {/* Artigos encontrados ficam depois das alegações e da análise de afirmações. */}
        {mode === 'topic' && topicResult && <section id="topic-results" aria-labelledby="topic-results-heading"
          className="mx-auto mt-6 max-w-3xl space-y-4 rounded-2xl border border-[--color-border] bg-[--color-surface] p-4 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[--color-border] pb-4">
            <div>
              <h2 id="topic-results-heading" className="text-base font-semibold text-[--color-foreground]">Artigos encontrados no PubMed</h2>
              <p className="mt-1 text-xs text-[--color-muted]">{topicResult.pagination.total_results.toLocaleString('pt-BR')} resultado(s) para “{topicResult.topic}”</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-full border border-[--color-teal] bg-[--color-teal-faint] px-3 py-1 font-mono text-[10px] text-[--color-teal]">PUBMED</span>
              <button type="button" aria-expanded={!topicMinimized} onClick={() => setTopicMinimized(value => !value)}
                className={`${BUTTON_GREEN} min-h-9 px-3 py-2 text-xs`}>
                {topicMinimized ? '＋ Expandir artigos' : '− Minimizar artigos'}
              </button>
            </div>
          </div>
          {!topicMinimized && <div className="space-y-4">
          {topicResult.language_note && <p className="rounded-lg border border-[--color-border] bg-[--color-background] p-3 text-xs text-[--color-muted]">{topicResult.language_note}{topicResult.excluded_by_language ? ' · ' + topicResult.excluded_by_language + ' registro(s) excluído(s) pelo idioma nesta página.' : ''}</p>}
          {topicGrouping && topicResult.articles.length >= 4 && <TopicExplorer
            key={topicResult.topic + ':' + topicResult.pagination.page + ':' + topicResult.articles.map(a => a.pmid).join(',')}
            articles={topicResult.articles.map(article => ({ pmid: article.pmid, title: article.title }))}
            onFilter={setTopicFilteredPmids} />}
          {topicResult.articles.length === 0 ? <p className="py-6 text-sm text-[--color-muted]">Nenhum artigo encontrado nesta página. Tente outro tema ou remova alguns filtros.</p> :
            <div className="space-y-3">{topicResult.articles.filter(article => !topicFilteredPmids || topicFilteredPmids.includes(article.pmid)).map(article => {
              const validPmid = /^\d{1,12}$/.test(article.pmid)
              return <article key={article.pmid} className="space-y-3 rounded-xl border border-[--color-border] bg-[--color-background] p-4 transition-colors hover:border-[--color-teal]">
                <div className="flex flex-wrap items-center gap-2 text-[10px] text-[--color-muted]">
                  <span className="rounded border border-[--color-border] px-2 py-0.5 font-mono">PMID {article.pmid}</span>
                  {article.publication_date && <span>{article.publication_date}</span>}
                  {article.has_full_text && <span className="text-[--color-teal]">Texto completo no PMC</span>}
                </div>
                <h3 className="text-sm font-semibold leading-relaxed text-[--color-foreground]">{article.title_pt || article.title}</h3>
                {article.title_pt && article.title_pt !== article.title && <p className="text-xs leading-relaxed text-[--color-muted]">Título original: {article.title}{article.title_pt_source === 'AI_TRANSLATION' ? ' · Tradução automática' : ''}</p>}
                {(article.language_labels?.length ?? 0) > 0 && <p className="text-[11px] text-[--color-muted]">Idioma de publicação: {article.language_labels?.join(', ')}</p>}
                <p className="text-xs text-[--color-muted]">{[article.authors?.slice(0, 3).join(', '), article.journal].filter(Boolean).join(' · ')}</p>
                {(article.publication_type_labels?.length ?? 0) > 0 && <p className="text-[11px] text-[--color-muted]">{article.publication_type_labels?.slice(0, 3).join(' · ')}</p>}
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => analyzeTopicArticle(article.pmid)} disabled={!validPmid || status === 'loading' || status === 'selecting' || topicBusy}
                    className={`${BUTTON_GREEN} text-xs`}>Analisar artigo →</button>
                  {validPmid && <a href={`https://pubmed.ncbi.nlm.nih.gov/${article.pmid}/`} target="_blank" rel="noopener noreferrer"
                    className="inline-flex min-h-11 items-center rounded-lg border border-[--color-border] px-3 text-xs text-[--color-muted] transition-colors hover:border-[--color-teal] hover:bg-[--color-teal] hover:text-black">Ver no PubMed ↗</a>}
                </div>
              </article>
            })}</div>}
          {topicResult.pagination.total_pages > 1 && <div className="flex items-center justify-between gap-3 border-t border-[--color-border] pt-4">
            <button type="button" disabled={topicBusy || status === 'loading' || !topicResult.pagination.has_previous}
              onClick={() => void runTopicSearch(topicResult.pagination.page - 1)} className={`${BUTTON_GREEN} text-xs`}>← Anterior</button>
            <span className="text-center font-mono text-xs text-[--color-muted]">Página {topicResult.pagination.page} de {topicResult.pagination.total_pages}</span>
            <button type="button" disabled={topicBusy || status === 'loading' || !topicResult.pagination.has_next}
              onClick={() => void runTopicSearch(topicResult.pagination.page + 1)} className={`${BUTTON_GREEN} text-xs`}>Próxima →</button>
          </div>}
          {topicResult.pagination.limited_by_pubmed && <p className="text-[11px] text-[--color-muted]">O PubMed limita a navegação aos primeiros 10.000 resultados. Refine os filtros para encontrar artigos específicos.</p>}
          </div>}
        </section>}

        {/* Login banner */}
        {showBanner && !isLoggedIn && status === 'done' && (
          <div className="mt-4">
            <LoginBanner
              onLogin={() => { setShowBanner(false); setShowLoginModal(true) }}
              onDismiss={() => setShowBanner(false)}
            />
          </div>
        )}

        {/* Sobre a Plataforma */}
        <section id="sobre" className="mt-16 space-y-6">
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-[--color-border]" />
        <span className="tracking-widest uppercase text-[26px]" style={{ fontFamily: '"Special Elite", cursive' }}>
          Sobre Nós
        </span>
            <div className="flex-1 h-px bg-[--color-border]" />
          </div>

          <div
            className="relative rounded-xl overflow-hidden border"
            style={{ borderColor: '#00d4aa', background: '#0f1526' }}
          >
            <div className="flex flex-col sm:flex-row min-h-[220px]">
              {/* Text side */}
              <div className="flex-1 flex flex-col justify-center gap-5 p-8 sm:pr-6 relative z-10">
                <div
                  className="about-accent absolute left-0 top-6 bottom-6 w-[3px] rounded-r"
                  style={{ background: '#00d4aa' }}
                />
                <p
                  className="text-sm font-normal leading-relaxed"
                  style={{ color: '#ffffff', fontFamily: "'JetBrains Mono', monospace" }}
                >
                  Verificamos a confiabilidade de artigos, notícias e afirmações científicas utilizando evidências provenientes de bases acadêmicas.
                </p>
                <div className="flex items-center gap-3 flex-wrap">
                  <span
                    className="font-mono text-[10px] tracking-widest uppercase"
                    style={{ color: '#6b7fa3' }}
                  >
                  </span>
                </div>
              </div>

              {/* Photo side */}
              <div className="about-image relative sm:w-[45%] h-52 sm:h-auto overflow-hidden">
                <div
                  className="hidden sm:block absolute inset-y-0 left-0 w-20 z-10 pointer-events-none"
                  style={{ background: 'linear-gradient(to right, #0f1526, transparent)' }}
                />
                <div
                  className="sm:hidden absolute inset-x-0 top-0 h-12 z-10 pointer-events-none"
                  style={{ background: 'linear-gradient(to bottom, #0f1526, transparent)' }}
                />
                <img
                  src="https://images.unsplash.com/photo-1766297247924-6638d54e7c89?w=600&h=440&fit=crop&auto=format"
                  alt="Dois cientistas analisando dados em computadores dentro de um laboratório"
                  className="w-full h-full object-cover opacity-80"
                />
              </div>
            </div>
          </div>
        </section>

        {/* How it works */}
        <section id="como" className="mt-24 space-y-8">
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-[--color-border]" />
            <span className="tracking-widest uppercase text-[26px]" style={{ fontFamily: '"Special Elite", cursive' }}>
              Como Funciona
            </span>
            <div className="flex-1 h-px bg-[--color-border]" />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 items-stretch">
            {[
              {
                step: '01',
                title: 'Entrada',
                desc: 'Cole o URL ou envie um print do artigo que você quer verificar.',
                frontColor: '#4d9fff', 
                backBg: '#111112',     
                backBorder: '#111112', 
                backText: '#f7f8fa',   
              },
              {
                step: '02',
                title: 'Análise',
                desc: 'Cada afirmação é confrontada com literatura científica indexada e bases de fatos.',
                frontColor: '#00d4aa',
                backBg: '#111112',
                backBorder: '#111112',
                backText: '#f7f8fa',
              },
              {
                step: '03',
                title: 'Veredito',
                desc: 'Compare as alegações com a literatura e consulte alertas, limitações e fontes originais.',
                frontColor: '#f5a623',
                backBg: '#111112',
                backBorder: '#111112',
                backText: '#f7f8fa',
              },
            ].map(({ step, title, desc, frontColor, backBg, backBorder, backText }) => (
              <div
                key={step}
                tabIndex={0}
                aria-label={`${step} — ${title}: ${desc}`}
                className="flip-card group rounded-lg outline-none"
                style={{ height: 160 }}
              >
                <div className="flip-card-inner w-full h-full">
                  {/* Front */}
                  <div
                    className="process-card-face flip-card-front rounded-lg border border-[--color-border] flex flex-col items-center justify-center gap-2"
                    style={{ boxShadow: 'rgba(0,0,0,0.25) 0px 4px 4px 0px' }}
                  >
                    <div className="font-mono text-3xl font-semibold" style={{ color: frontColor }}>
                      {step}
                    </div>
                    <div
                      className="font-mono text-[11px] font-semibold tracking-widest uppercase"
                      style={{ color: frontColor }}
                    >
                      {title}
                    </div>
                  </div>
                  {/* Back */}
                  <div
                    className="process-card-face flip-card-back rounded-lg border flex flex-col items-center justify-center p-5 text-center"
                    style={{
                      background: backBg,
                      borderColor: backBorder,
                      boxShadow: 'rgba(0,0,0,0.25) 0px 4px 4px 0px',
                    }}
                  >
                    <p className="text-sm leading-relaxed" style={{ color: backText, fontFamily: "'Lora', Georgia, serif", fontWeight: 500 }}>
                      {desc}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Academic Bases */}
        <section id="academic-bases" className="mt-16 space-y-8">
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-[--color-border]" />
            <span className="tracking-widest uppercase text-[26px]" style={{ fontFamily: '"Special Elite", cursive' }}>
              Base Acadêmica Consultada
            </span>
            <div className="flex-1 h-px bg-[--color-border]" />
          </div>

          <div
            className="grid grid-cols-1 gap-6 rounded-xl border border-[--color-border] bg-[--color-surface] p-6 sm:grid-cols-[260px_1fr] sm:items-center sm:p-8"
            style={{ backgroundColor: 'var(--color-surface)', opacity: 1 }}
          >
            <div className="flex min-h-36 items-center justify-center rounded-xl bg-[--color-background] p-4 text-center">
              <a
                href="https://pubmed.ncbi.nlm.nih.gov/"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Acessar o PubMed em uma nova aba"
                className="pubmed-logo-link inline-flex min-h-24 w-full items-center justify-center rounded-lg p-2 transition-transform duration-200 hover:scale-105"
              >
                <img
                  src={pubmedGovLogo}
                  alt="Logo PubMed.gov"
                  className="pubmed-logo h-auto w-full max-w-full object-contain"
                />
              </a>
            </div>
            <p className="text-sm leading-relaxed" style={{ color: "#ffffff", fontFamily: "'Lora', Georgia, serif", fontWeight: 500 }}>
              Mantido pelos <strong className="font-semibold text-[--color-teal]">National Institutes of Health (NIH/EUA)</strong>, o <strong className="font-semibold text-[--color-teal]">PubMed</strong> é a referência global para busca e validação de <strong className="font-semibold text-[--color-teal]">evidências científicas</strong> na área da saúde. A base reúne literatura <strong className="font-semibold text-[--color-teal]">revisada por pares (peer-reviewed)</strong>, garantindo rigor metodológico através do índice <strong className="font-semibold text-[--color-teal]">MEDLINE</strong> e fornecendo rastreabilidade completa por meio de identificadores padronizados como <strong className="font-semibold text-[--color-teal]">PMID</strong> (PubMed Unique Identifier) e <strong className="font-semibold text-[--color-teal]">DOI</strong>.
            </p>
          </div>
        </section>

        {/* Stats bar */}


      </main>

      {/* Footer */}
      <footer className="border-t border-[--color-border] py-8">
        <div className="max-w-3xl mx-auto px-4 flex flex-col items-center justify-center gap-3 text-center">
          <span className="font-mono text-[11px] text-[--color-muted]">
            © 2026 ArtFact — Verificação científica independente
          </span>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setShowTermsModal(true)}
              className="font-mono text-[11px] text-[--color-muted] px-3 py-1.5 rounded-md transition-all duration-150 hover:bg-[--color-teal] hover:text-[--color-background]"
            >
              Privacidade
            </button>
          </div>
        </div>
      </footer>

      {/* Modals */}
      {showLoginModal && (
        <LoginModal
          onClose={() => setShowLoginModal(false)}
          onRegistered={setUserName}
        />
      )}
      {showTermsModal && <TermsModal onClose={() => setShowTermsModal(false)} />}
      {showSaved && (
        <SavedPanel
          articles={savedArticles}
          error={historyError}
          loading={historyLoading}
          busyId={historyBusyId}
          onOpen={id => void openHistoryItem(id)}
          onDelete={id => void removeHistoryItem(id)}
          onClose={() => setShowSaved(false)}
        />
      )}
      <AccessibilityMenu settings={accessibility} onChange={setAccessibility} />
    </div>
  )
}
