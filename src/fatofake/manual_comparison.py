"""Comparação com um conjunto explícito de documentos, sem busca externa."""
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone

from .analysis_service import AnalysisServiceError
from .vector_store import VectorStoreError
from .gemini_evidence import EvidenceDocument
from .pmc import ArticleContent, ContentSection
from .evidence_table import synthesize_evidence
from .verification_cards import build_abstract_analysis_cards
from .result_presentation import build_user_summary


def compare_documents(runner, claim, documents, claim_profile=None):
    from .retrieval_preview import select_evidence_passages
    if runner.evidence_analyzer is None:
        raise AnalysisServiceError('O modelo de comparação não está configurado.')
    evidence, metadata = [], []
    for article_id, doc in documents:
        key = doc.pmid or f'library:{article_id}'
        url = doc.content_source_url or doc.source_url
        full = 'FULL_TEXT' in doc.content_scope
        sections = tuple(ContentSection(title, text) for title, text in doc.sections)
        if doc.pages:
            sections = tuple(ContentSection('Página do documento', page.text, page.page_number) for page in doc.pages)
        content = ArticleContent(key, doc.pmcid, doc.doi, None if full else doc.text,
                                 doc.text if full else None, sections,
                                 doc.content_scope, url, url if full else None,
                                 parser_version=doc.parser_version)
        from .retrieval_backend import RetrievalSettings
        settings = getattr(runner, "retrieval_settings", None)
        if settings is None:
            settings = RetrievalSettings()
        elif not isinstance(settings, RetrievalSettings):
            raise VectorStoreError("Configuração de recuperação inválida para a comparação manual.")
        passages = select_evidence_passages(
            content, claim, key, max_passages=8,
            vector_store=getattr(runner, "vector_store", None) if settings.hybrid_enabled else None,
            vector_top_k=settings.top_k, minimum_score=settings.minimum_score,
            failure_mode=settings.failure_mode,
        )
        if not passages:
            raise AnalysisServiceError("Não foram recuperados trechos suficientes para comparar este documento; ajuste a consulta ou o limiar vetorial.")
        evidence.append(EvidenceDocument(key, doc.title or 'Documento da biblioteca', '', url, passages))
        metadata.append((article_id, doc, passages, key))
    assessments = runner.evidence_analyzer.analyze(claim, evidence, claim_profile=claim_profile) if claim_profile else runner.evidence_analyzer.analyze(claim, evidence)
    by_key = {item.pmid: item for item in assessments}
    articles = []
    for article_id, doc, passages, key in metadata:
        assessment = by_key.get(key)
        article = {
            'pmid': doc.pmid, 'pmcid': doc.pmcid, 'doi': doc.doi, 'title': doc.title or 'Documento da biblioteca',
            'authors': list(doc.authors), 'journal': doc.journal, 'publication_date': doc.publication_date,
            'publication_types': list(doc.publication_types), 'url': doc.source_url,
            'library_article_id': article_id, 'work_key': key, 'access_level': doc.content_scope,
            'analyzed_passage_count': len(passages), 'analyzed_sections': list(dict.fromkeys(p.section for p in passages)),
            'analyzed_passages': [asdict(p) for p in passages],
            'abstract': doc.text if 'FULL_TEXT' not in doc.content_scope else None,
            'retrieval': {'sources': ['Seleção manual']},
            'quality': {'level': 'NOT_EVALUATED', 'study_design': 'UNKNOWN',
                        'is_retracted': 'Retracted Publication' in doc.publication_types},
            'assessments': [],
        }
        if assessment:
            article['assessments'] = [{
                'relation': assessment.relation, 'confidence': assessment.confidence,
                'rationale': assessment.rationale, 'model_name': assessment.model_name,
                'study_row': assessment.study_row,
                'evidence': {'text': assessment.evidence_quote, 'section': assessment.evidence_section,
                             'page': assessment.evidence_page, 'source_url': assessment.source_url,
                             'passage_id': assessment.passage_id, 'content_scope': assessment.content_scope},
            }]
        articles.append(article)
    counts = Counter(item.relation for item in assessments)
    direction = ('MIXED' if counts['SUPPORTS'] and counts['CONTRADICTS'] else
                 'SUPPORTS' if counts['SUPPORTS'] else 'CONTRADICTS' if counts['CONTRADICTS'] else 'NEUTRAL')
    result = {
        'input': {'claim': claim}, 'articles': articles,
        'search': {'mode': 'MANUAL', 'candidate_count': len(articles), 'query_expansion': [],
                   'reranking': {'evaluated_count': len(articles), 'accepted_count': len(articles)}},
        'synthesis': {'direction': direction, 'article_count': len(articles)},
        'report': {'conclusion': 'DESCRIPTIVE_COMPARISON', 'headline': 'Comparação com artigos escolhidos',
                   'summary': 'Os trechos foram comparados apenas com os documentos selecionados.',
                   'limitations': ['A seleção manual não representa uma busca exaustiva da literatura.']},
        'verification': build_abstract_analysis_cards(
            claim=claim, article_reference=None, retrieved_article_count=len(articles),
            assessments=assessments, content_failure_count=0, assess_methodology=False),
        'reproducibility': {'executed_at': datetime.now(timezone.utc).isoformat(),
                            'comparison_mode': 'MANUAL', 'library_article_ids': [key for key, _ in documents],
                            'claim_profile': claim_profile, 'queries': [],
                            'evidence_model': getattr(runner.evidence_analyzer, 'model_name', None)},
    }
    result['weighted_evidence'] = synthesize_evidence(articles, candidate_count=len(articles),
                                                      assess_methodology=False, sources=['Seleção manual'])
    result['user_summary'] = build_user_summary(result)
    return result
