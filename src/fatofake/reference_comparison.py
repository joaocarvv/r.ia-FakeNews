"""Cruza bibliografias reais do PubMed/PMC por PMID, PMCID e DOI, sem LLM."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from threading import RLock
from urllib.parse import unquote
import xml.etree.ElementTree as ET

from .pmc import NCBI_EFETCH_URL, PMC_ID_CONVERTER_URL, ContentRetrievalError


def text(node):
    return ' '.join(''.join(node.itertext()).split()) if node is not None else ''


def identifiers(record):
    ids = []
    for kind in ('pmid', 'pmcid', 'doi'):
        value = str(record.get(kind) or '').strip()
        if kind == 'doi':
            value = unquote(value).lower()
            value = re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', value).rstrip(' .;,')
            valid = bool(re.fullmatch(r'10\.\d{4,9}/\S+', value))
        elif kind == 'pmcid':
            value = value.upper(); valid = bool(re.fullmatch(r'PMC\d+', value))
        else:
            valid = bool(re.fullmatch(r'\d{1,12}', value))
        if value and valid:
            ids.append(f'{kind}:{value}')
    return ids


def parse_reference(node, *, pmc=False):
    record = {'reference_id': node.get('id'), 'label': text(node.find('./label')),
              'title': text(node.find('.//article-title')) or None,
              'citation': text(node.find('./Citation')) if not pmc else text(node),
              'year': text(node.find('.//year')) or None}
    for item in node.findall('.//pub-id') + node.findall('.//ArticleId'):
        kind = (item.get('pub-id-type') or item.get('IdType') or '').lower()
        if kind == 'pubmed': kind = 'pmid'
        if kind in {'doi', 'pmid', 'pmcid'}:
            record[kind] = text(item)
    record['identifiers'] = identifiers(record)
    record['contexts'] = []
    return record


def parse_pubmed(raw):
    root = ET.fromstring(raw)
    result = {}
    for article in root.findall('.//PubmedArticle'):
        pmid = text(article.find('./MedlineCitation/PMID'))
        refs = article.find('./PubmedData/ReferenceList')
        result[pmid] = {'status': 'available' if refs is not None else 'unavailable',
                        'source': 'PubMed XML', 'source_url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
                        'pmcid': text(article.find('./PubmedData/ArticleIdList/ArticleId[@IdType="pmc"]')) or None,
                        'references': [parse_reference(ref) for ref in refs.findall('.//Reference')] if refs is not None else []}
    return result


def parse_pmc(raw):
    root = ET.fromstring(raw)
    articles = [root] if root.tag == 'article' else root.findall('./article')
    result = {}
    for article in articles:
        meta = article.find('./front/article-meta')
        if meta is None: continue
        pmcid = next((text(item) for item in meta.findall('./article-id') if item.get('pub-id-type') in {'pmc','pmcid'}), '')
        if pmcid.isdigit(): pmcid = 'PMC' + pmcid
        if not re.fullmatch(r'PMC\d+', pmcid): continue
        lists = article.findall('./back//ref-list')
        refs = [parse_reference(ref, pmc=True) for ref_list in lists for ref in ref_list.findall('./ref')]
        by_id = {ref['reference_id']: ref for ref in refs if ref['reference_id']}
        for paragraph in article.findall('./body//p'):
            for xref in paragraph.findall('.//xref[@ref-type="bibr"]'):
                for rid in (xref.get('rid') or '').split():
                    if rid in by_id and text(paragraph) not in by_id[rid]['contexts']:
                        by_id[rid]['contexts'].append(text(paragraph)[:1200])
        result[pmcid] = {'status': 'available' if lists else 'unavailable', 'source': 'PMC JATS XML',
                         'source_url': f'https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/', 'references': refs}
    return result


def compare_references(articles, bibliographies):
    """Une aliases explícitos; títulos parecidos não confirmam identidade/citação."""
    parent = {}
    def find(value):
        parent.setdefault(value, value)
        if parent[value] != value: parent[value] = find(parent[value])
        return parent[value]
    def join(ids):
        for value in ids[1:]: parent[find(value)] = find(ids[0])
    for article in articles:
        join(identifiers(article))
        for reference in bibliographies.get(article['node_id'], {}).get('references', []):
            join(reference['identifiers'])
    nodes, edges, sets, representatives = [], [], {}, {}
    for article in articles:
        bibliography = bibliographies.get(article['node_id'], {})
        refs = bibliography.get('references', [])
        identified = {find(value) for reference in refs for value in reference['identifiers']}
        sets[article['node_id']] = identified
        for ref in refs:
            for value in ref['identifiers']: representatives.setdefault(find(value), ref)
        nodes.append({**article, 'bibliography_status': bibliography.get('status', 'unavailable'),
                      'bibliography_source': bibliography.get('source'), 'bibliography_url': bibliography.get('source_url'),
                      'reference_count': len(refs), 'identified_reference_count': len(identified),
                      'unidentified_reference_count': sum(not ref['identifiers'] for ref in refs),
                      'references': refs})
        for target in articles:
            if target['node_id'] == article['node_id']: continue
            target_ids = {find(value) for value in identifiers(target)}
            matches = [ref for ref in refs if target_ids & {find(value) for value in ref['identifiers']}]
            if matches:
                edges.append({'from': article['node_id'], 'to': target['node_id'],
                              'type': 'bibliographic_reference', 'references': matches,
                              'source_url': bibliography.get('source_url'),
                              'has_in_text_context': any(ref['contexts'] for ref in matches)})
    pairs = []
    for i, a in enumerate(nodes):
        for b in nodes[i+1:]:
            comparable = a['bibliography_status'] == b['bibliography_status'] == 'available'
            common = sets[a['node_id']] & sets[b['node_id']]
            union = sets[a['node_id']] | sets[b['node_id']]
            pairs.append({'a': a['node_id'], 'b': b['node_id'], 'comparable': comparable,
                          'shared_count': len(common) if comparable else None,
                          'jaccard_identified': round(len(common)/len(union), 4) if comparable and union else None,
                          'shared_references': [representatives[value] for value in sorted(common)] if comparable else []})
    return {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'status': 'available' if all(n['bibliography_status']=='available' for n in nodes) else 'partial',
            'nodes': nodes, 'edges': edges, 'pairs': pairs,
            'available_bibliographies': sum(n['bibliography_status']=='available' for n in nodes),
            'limitations': ['A comparação usa as referências disponíveis no PubMed/PMC, que podem estar incompletas.',
                            'Ausência de ligação identificada não demonstra ausência de citação.',
                            'Referências compartilhadas não demonstram que os estudos reutilizam dados ou deixam de ser independentes.',
                            'As ligações são confirmadas por identificadores; títulos semelhantes não são usados como prova.']}


def analysis_articles(result, submitted=None):
    candidates = [dict(article, role='retrieved') for article in result.get('articles', [])]
    submitted = submitted or result.get('submitted_article') or {}
    if submitted and (submitted.get('pmid') or submitted.get('doi') or submitted.get('pmcid')):
        candidates.insert(0, dict(submitted, role='submitted', title=submitted.get('title') or 'Artigo enviado'))
    selected, known = [], set()
    for article in candidates:
        ids = identifiers(article)
        if set(ids) & known: continue
        known.update(ids)
        selected.append({'node_id': f'article-{len(selected)+1}', 'title': article.get('title') or 'Artigo sem título',
                         'pmid': article.get('pmid'), 'pmcid': article.get('pmcid'), 'doi': article.get('doi'),
                         'role': article['role']})
    return selected[:21]


class ReferenceComparisonService:
    def __init__(self, client):
        self.client = client
        self._lock = RLock()

    @staticmethod
    def fingerprint(articles):
        return hashlib.sha256(json.dumps(articles, sort_keys=True).encode()).hexdigest()

    def compare(self, articles):
        with self._lock:
            bibliographies = {}
            original_articles = articles
            articles = [dict(article) for article in articles]
            unresolved = [article for article in articles if not article.get('pmid') and not article.get('pmcid') and identifiers({'doi': article.get('doi')})]
            if unresolved:
                params = self.client._identification_params(include_api_key=False)
                params.update(ids=','.join(article['doi'] for article in unresolved), idtype='doi', format='json')
                try:
                    records = self.client._fetch_json(PMC_ID_CONVERTER_URL, params).get('records', [])
                    for article in unresolved:
                        doi_ids = set(identifiers({'doi': article.get('doi')}))
                        for record in records:
                            if doi_ids & set(identifiers({'doi': record.get('doi')})):
                                for kind in ('pmid', 'pmcid'):
                                    if identifiers({kind: record.get(kind)}): article[kind] = str(record[kind])
                except ContentRetrievalError:
                    pass
            pmids = [a['pmid'] for a in articles if f"pmid:{a.get('pmid')}" in identifiers(a)]
            pmcids = [a['pmcid'] for a in articles if f"pmcid:{a.get('pmcid')}" in identifiers(a)]
            pubmed, pmc = {}, {}
            for db, parser in [('pubmed', parse_pubmed), ('pmc', parse_pmc)]:
                if db == 'pmc':
                    pmcids += [source['pmcid'] for source in pubmed.values() if source.get('pmcid') and identifiers({'pmcid': source['pmcid']})]
                ids = sorted(set(str(value) for value in (pmids if db == 'pubmed' else pmcids)))
                if not ids: continue
                params = self.client._identification_params()
                params.update(db=db, id=','.join(ids), retmode='xml')
                try:
                    parsed = parser(self.client._fetch_xml(NCBI_EFETCH_URL, params))
                    if db == 'pubmed': pubmed = parsed
                    else: pmc = parsed
                except (ContentRetrievalError, ET.ParseError):
                    pass
            effective_articles = []
            for original in articles:
                article = dict(original)
                if not article.get('pmcid'):
                    article['pmcid'] = pubmed.get(str(article.get('pmid')), {}).get('pmcid')
                effective_articles.append(article)
                sources = [pubmed.get(str(article.get('pmid'))), pmc.get(str(article.get('pmcid')))]
                available = [source for source in sources if source and source['status']=='available']
                bibliography = max(available, key=lambda source: (len(source['references']), source['source']=='PMC JATS XML')) if available else {'status':'unavailable','references':[]}
                bibliographies[article['node_id']] = bibliography
            report = compare_references(effective_articles, bibliographies)
            report['fingerprint'] = self.fingerprint(original_articles)
            return report
