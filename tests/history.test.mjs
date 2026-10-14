import test from 'node:test'
import assert from 'node:assert/strict'
import { makeSavedArticle, validSavedArticle } from '../src/historyRecord.ts'

test('historico guarda somente metadados, não salva corpo de artigo nem alegações', () => {
  const item = makeSavedArticle({ analysisId: 'id-123', title: 'Teste', source: 'PubMed',
    publishedDate: 'Hoje', overallVerdict: 'uncertain', healthArea: 'Geral',
    claims: [{ text: 'DADO PRIVADO DO ESTUDO' }], supportingLinks: [], redFlags: [],
  })
  assert.equal(item.analysisId, 'id-123')
  assert.equal(JSON.stringify(item).includes('DADO PRIVADO'), false)
  assert.ok(validSavedArticle(item))
  assert.deepEqual(Object.keys(item).sort(), ['analysisId', 'title', 'source', 'publishedDate', 'overallVerdict', 'healthArea', 'savedAt'].sort())
})
test('registro adulterado ou incompleto não entra no histórico', () => {
  assert.equal(validSavedArticle({ analysisId: 'x' }), false)
  assert.equal(validSavedArticle(null), false)
  assert.equal(validSavedArticle({ analysisId: 'x', title: 't', source: '', publishedDate: '',
    overallVerdict: 'fake', healthArea: '', savedAt: -1 }), false)
})
