import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeReference, filePayload, parseJob, mapResult, startAnalysis, pollAnalysis, selectClaims, extractedClaims, getSavedAnalysis } from '../src/api.ts'

test('URLs/DOI válidos e protocolos bloqueados', () => {
  assert.equal(normalizeReference('10.1000/example'), '10.1000/example')
  assert.equal(normalizeReference('pubmed.ncbi.nlm.nih.gov/123/'), 'https://pubmed.ncbi.nlm.nih.gov/123/')
  assert.throws(() => normalizeReference('javascript:alert(1)'))
})
test('arquivo segue contrato base64 e valida tipo/tamanho', async () => {
  const p = await filePayload(new File(['%PDF-test'], 'estudo.pdf', { type: 'application/pdf' }))
  assert.equal(atob(p.article_file.data_base64), '%PDF-test')
  await assert.rejects(filePayload(new File(['x'], 'x.svg', { type: 'image/svg+xml' })))
  await assert.rejects(filePayload(new File([], 'x.png', { type: 'image/png' })))
  await assert.rejects(filePayload(new File([new Uint8Array(25 * 1024 * 1024 + 1)], 'x.png', { type: 'image/png' })))
})
test('não aceita resposta inesperada', () => {
  assert.throws(() => parseJob({ status: 'ok' }))
  assert.throws(() => mapResult({ analysis_id: '1', status: 'SUCCEEDED', result: {} }))
})
test('múltiplas alegações preservam divergência e falhas sem inventar score', () => {
  const job = { analysis_id: '1', status: 'SUCCEEDED', result: { claim_analyses: [
    { claim: { text: 'A' }, status: 'SUCCEEDED', result: { user_summary: { status: 'PREDOMINANTLY_COMPATIBLE', summary: 'Resumo A' }, articles: [{ title: 'Estudo', url: 'javascript:bad' }] } },
    { claim: { text: 'B' }, status: 'SUCCEEDED', result: { user_summary: { status: 'POTENTIAL_DIVERGENCE', summary: 'Resumo B' }, articles: [{ title: 'Estudo B', pmid: '123' }] } },
    { claim: { text: 'C' }, status: 'FAILED', error: { message: 'Falha parcial' } },
  ] } }
  const result = mapResult(job)
  assert.equal(result.overallVerdict, 'uncertain')
  assert.equal(result.credibilityScore, null)
  assert.equal(result.claims[2].note, 'Falha parcial')
  assert.equal(result.supportingLinks.length, 1)
  assert.equal(result.claims[1].verdict, 'fake')
})
test('cliente envia contrato, consulta estado leve, seleciona alegações e informa erro HTTP', async () => {
  const original = globalThis.fetch, requests = []
  const signal = new AbortController().signal
  globalThis.fetch = async (url, options) => {
    requests.push({ url, ...options })
    if (options.method === 'POST') return Response.json({ analysis_id: 'abc', status: 'QUEUED', progress: 0 }, { status: 202 })
    return Response.json({ analysis_id: 'abc', status: 'AWAITING_CLAIM_SELECTION', progress: 40, result: { submitted_article: { claims: [{ claim_id: 'c1', text: 'Alegação teste' }] } } })
  }
  try {
    const created = await startAnalysis('10.1000/example', null, signal)
    const job = await pollAnalysis(created.analysis_id, signal, () => {})
    await selectClaims(job.analysis_id, extractedClaims(job), signal)
    assert.deepEqual(JSON.parse(requests[0].body), { article_reference: '10.1000/example' })
    assert.ok(requests[1].url.endsWith('?view=status'))
    assert.deepEqual(JSON.parse(requests[3].body), { claims: [{ claim_id: 'c1', text: 'Alegação teste' }], depth: 'QUICK' })
    globalThis.fetch = async () => Response.json({ error: { message: 'Chave ausente' } }, { status: 503 })
    await assert.rejects(startAnalysis('10.1000/example', null, signal), /Chave ausente/)
    globalThis.fetch = async () => Response.json({ analysis_id: 'abc', status: 'FAILED', progress: 100, result: {}, error: { message: 'Falha no pipeline' } })
    await assert.rejects(pollAnalysis('abc', signal, () => {}), /Falha no pipeline/)
  } finally { globalThis.fetch = original }
})

test('exibe somente dados de cobertura e evidências fornecidos pelo backend', () => {
  const result = mapResult({ analysis_id: 'test', status: 'SUCCEEDED', result: { claim_analyses: [
    { status: 'SUCCEEDED', claim: { text: 'Teste A' }, result: {
      user_summary: { reading: { retrieved_count: 4, assessed_count: 3, full_text_count: 2 },
        evidence_balance: { SUPPORTS: 2, CONTRADICTS: 1, NEUTRAL: 0, UNCERTAIN: 1 } },
      verification: { indicators: { methodological_confidence: { label: 'Não avaliada' } } },
    } },
    { status: 'SUCCEEDED', claim: { text: 'Teste B' }, result: {
      user_summary: { reading: { retrieved_count: 2, assessed_count: 1, full_text_count: 1 },
        evidence_balance: { SUPPORTS: 0, CONTRADICTS: 1, NEUTRAL: 1, UNCERTAIN: 0 } },
    } },
  ] } })
  assert.equal(result.credibilityScore, null)
  assert.equal(result.indicators.retrieved, 6)
  assert.equal(result.indicators.assessed, 4)
  assert.equal(result.indicators.coverage, 67)
  assert.equal(result.indicators.evidence.supports, 2)
  assert.equal(result.indicators.evidence.contradicts, 2)
  assert.equal(result.claims[0].indicators.methodology, 'Não avaliada')
})
test('dados ausentes, falhas e contagens incoerentes não geram percentuais', () => {
  const result = mapResult({ analysis_id: 'a', status: 'SUCCEEDED', result: { claim_analyses: [
    { status: 'SUCCEEDED', claim: { text: 'A' }, result: { user_summary: { reading: { retrieved_count: 1, assessed_count: 8 } } } },
    { status: 'FAILED', claim: { text: 'B' }, error: { message: 'Indisponível' } },
  ] } })
  assert.equal(result.credibilityScore, null)
  assert.equal(result.indicators.coverage, null)
  assert.equal(result.indicators.evidence, null)
  assert.equal(result.claims[1].indicators.coverage, null)
})

test('trechos científicos preservam identificadores e rejeitam links não seguros', () => {
  const result = mapResult({ analysis_id: 'evidencias', status: 'SUCCEEDED', result: { claim_analyses: [
    { status: 'SUCCEEDED', claim: { text: 'Alegação' }, result: { user_summary: {
      findings: [
        { relation: 'SUPPORTS', article_title: 'Estudo A', quote: 'Trecho apoiado por evidência', pmid: '123456', source_url: 'javascript:alert(1)' },
        { relation: 'CONTRADICTS', article_title: 'Estudo B', quote_pt: 'Trecho divergente', doi: '10.1234/example', source_url: 'https://example.org/source' },
        { relation: 'NEUTRAL', article_title: 'Estudo C' },
      ],
    } } },
  ] } })
  const findings = result.claims[0].findings
  assert.equal(findings.length, 2)
  assert.equal(findings[0].url, 'https://pubmed.ncbi.nlm.nih.gov/123456/')
  assert.equal(findings[1].url, 'https://example.org/source')
  assert.equal(findings[1].doi, '10.1234/example')
})

test('historico consulta resultado original, sem disparar nova analise', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), method: options.method })
    return Response.json({ analysis_id: 'historico-1', status: 'SUCCEEDED',
      result: { claim_analyses: [{ status: 'SUCCEEDED', claim: { text: 'Teste' },
        result: { user_summary: { status: 'INCONCLUSIVE' } } }] } })
  }
  try {
    const job = await getSavedAnalysis('historico-1', new AbortController().signal)
    assert.equal(job.status, 'SUCCEEDED')
    assert.deepEqual(calls, [{ url: '/api/v1/analyses/historico-1', method: 'GET' }])
  } finally { globalThis.fetch = original }
})

test('historico diferencia registro Firestore de resultado ausente no Flask', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => Response.json({ error: { message: 'Análise não encontrada' } }, { status: 404 })
  try {
    await assert.rejects(getSavedAnalysis('antigo', new AbortController().signal), /registro está no Firestore/)
  } finally { globalThis.fetch = original }
})
