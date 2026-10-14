"""Biblioteca local de documentos e análises, com busca persistente no texto."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from threading import RLock
from uuid import uuid4

from .article_ingestion import ArticleSubmission, PreparedArticle, ResolvedArticleDocument
from .document_parsing import ParsedPage
from .input_validation import InputValidationError


def restore_document(data):
    fields = dict(data)
    fields['pages'] = tuple(ParsedPage(**page) for page in fields.get('pages') or ())
    fields['sections'] = tuple(tuple(section) for section in fields.get('sections') or ())
    for name in ('authors', 'publication_types'):
        fields[name] = tuple(fields.get(name) or ())
    return ResolvedArticleDocument(**fields)


class ArticleLibrary:
    def __init__(self, database_path=None):
        self._lock = RLock()
        self.connection = sqlite3.connect(str(database_path or ':memory:'), check_same_thread=False, timeout=30)
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.execute('''CREATE TABLE IF NOT EXISTS library_articles (
                article_id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL, reference TEXT, document_json TEXT NOT NULL,
                submission_json TEXT NOT NULL, file_content BLOB, notes TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]', analysis_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            columns = {row['name'] for row in self.connection.execute('PRAGMA table_info(library_articles)')}
            if 'file_content' not in columns:
                self.connection.execute('ALTER TABLE library_articles ADD COLUMN file_content BLOB')
            self.connection.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS library_text
                USING fts5(article_id UNINDEXED, title, notes, text)''')

    def import_prepared_analyses(self):
        """Inclui fontes de análises antigas sem sobrescrever notas ou reler artigos."""
        with self._lock:
            exists = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_jobs'"
            ).fetchone()
            if not exists:
                return 0
            rows = self.connection.execute("""SELECT j.analysis_id, j.workflow_json FROM analysis_jobs j
                WHERE j.workflow_json IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM library_articles a, json_each(a.analysis_ids_json) ids
                    WHERE ids.value=j.analysis_id)""")
            imported = 0
            for row in rows:
                try:
                    prepared = PreparedArticle.from_workflow_payload(json.loads(row['workflow_json']))
                except (KeyError, TypeError, ValueError):
                    continue
                if prepared.resolved and prepared.resolved.text.strip():
                    self.save(prepared.submission, prepared.resolved, analysis_id=row['analysis_id'])
                    imported += 1
            return imported

    def close(self):
        with self._lock:
            self.connection.close()

    def __del__(self):
        connection = getattr(self, 'connection', None)
        if connection is not None:
            connection.close()

    @staticmethod
    def _columns(*, metadata_only=False, include_file=False):
        document = "json_remove(a.document_json, '$.text', '$.pages', '$.sections')" if metadata_only else 'a.document_json'
        content = 'a.file_content' if include_file else 'NULL'
        return f"""a.article_id, a.identity, a.title, a.reference, {document} AS document_json,
            a.submission_json, a.notes, a.tags_json, a.analysis_ids_json, a.created_at, a.updated_at,
            {content} AS file_content, (a.file_content IS NOT NULL) AS has_original_file"""

    def _row(self, article_id, *, include_file=False):
        row = self.connection.execute(
            'SELECT ' + self._columns(include_file=include_file) + ' FROM library_articles a WHERE article_id=?',
            (article_id,),
        ).fetchone()
        if row is None:
            raise InputValidationError('O artigo não foi encontrado na biblioteca.')
        return row

    @staticmethod
    def _public(row):
        document = json.loads(row['document_json'])
        return {
            'article_id': row['article_id'], 'title': row['title'], 'reference': row['reference'],
            'notes': row['notes'], 'tags': json.loads(row['tags_json']),
            'analysis_ids': json.loads(row['analysis_ids_json']),
            'created_at': row['created_at'], 'updated_at': row['updated_at'],
            'has_original_file': bool(row['has_original_file']),
            'doi': document.get('doi'), 'pmid': document.get('pmid'),
            'journal': document.get('journal'), 'authors': document.get('authors') or [],
            'publication_date': document.get('publication_date'),
            'publication_types': document.get('publication_types') or [],
            'content_scope': document.get('content_scope'), 'source_url': document.get('source_url'),
        }

    def save(self, submission, document, *, analysis_id=None):
        if document is None or not document.text.strip():
            raise InputValidationError('Não há texto recuperado para guardar na biblioteca.')
        identity = (f'pmid:{document.pmid}' if document.pmid else
                    f'doi:{document.doi.lower()}' if document.doi else
                    'text:' + hashlib.sha256(document.text.encode()).hexdigest())
        title = document.title or submission.file_name or 'Documento enviado'
        timestamp = datetime.now(timezone.utc).isoformat()
        submission_data = {key: getattr(submission, key) for key in ('reference', 'reference_type', 'file_name', 'mime_type')}
        with self._lock, self.connection:
            old = self.connection.execute('SELECT ' + self._columns() + ' FROM library_articles a WHERE identity=?', (identity,)).fetchone()
            article_id = old['article_id'] if old else str(uuid4())
            analyses = json.loads(old['analysis_ids_json']) if old else []
            if analysis_id and analysis_id not in analyses:
                analyses.append(analysis_id)
            # Uma nova leitura por resumo não substitui texto completo já guardado.
            if old and 'FULL_TEXT' in json.loads(old['document_json']).get('content_scope', '') and 'FULL_TEXT' not in document.content_scope:
                document = restore_document(json.loads(old['document_json']))
                title = old['title']
                submission_data = json.loads(old['submission_json'])
            self.connection.execute('''INSERT INTO library_articles
                (article_id, identity, title, reference, document_json, submission_json,
                 file_content, analysis_ids_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(identity) DO UPDATE SET title=excluded.title,
                document_json=excluded.document_json, submission_json=excluded.submission_json,
                file_content=COALESCE(excluded.file_content, library_articles.file_content),
                analysis_ids_json=excluded.analysis_ids_json, updated_at=excluded.updated_at''',
                (article_id, identity, title, submission.reference, json.dumps(asdict(document), ensure_ascii=False),
                 json.dumps(submission_data), submission.content, json.dumps(analyses), timestamp, timestamp))
            self._index(article_id)
            return self._public(self._row(article_id))

    def _index(self, article_id):
        row = self._row(article_id)
        self.connection.execute('DELETE FROM library_text WHERE article_id=?', (article_id,))
        self.connection.execute('INSERT INTO library_text(article_id, title, notes, text) VALUES (?, ?, ?, ?)',
                                (article_id, row['title'], row['notes'] + ' ' + ' '.join(json.loads(row['tags_json'])), json.loads(row['document_json'])['text']))

    def list(self, query=''):
        if not isinstance(query, str) or len(query) > 500:
            raise InputValidationError('Busca inválida para a biblioteca.')
        terms = re.findall(r'\w+', query, re.UNICODE)[:20]
        with self._lock:
            if terms:
                expression = ' AND '.join('"' + term + '"*' for term in terms)
                rows = self.connection.execute('SELECT ' + self._columns(metadata_only=True) + ''' FROM library_articles a
                    JOIN library_text f ON f.article_id=a.article_id WHERE library_text MATCH ?
                    ORDER BY bm25(library_text), a.updated_at DESC LIMIT 100''', (expression,)).fetchall()
            else:
                rows = self.connection.execute('SELECT ' + self._columns(metadata_only=True) + ' FROM library_articles a ORDER BY updated_at DESC LIMIT 100').fetchall()
            return [self._public(row) for row in rows]

    def get(self, article_id):
        with self._lock:
            row = self._row(article_id)
            return {**self._public(row), 'document': json.loads(row['document_json'])}

    def load(self, article_id):
        with self._lock:
            row = self._row(article_id)
            return ArticleSubmission(**json.loads(row['submission_json']), content=None), restore_document(json.loads(row['document_json']))

    def original_file(self, article_id):
        with self._lock:
            row = self._row(article_id, include_file=True)
            if row['file_content'] is None:
                raise InputValidationError('O arquivo original não está guardado; o texto continua disponível.')
            return row['file_content'], json.loads(row['submission_json'])

    def annotate(self, article_id, notes, tags):
        if not isinstance(notes, str) or len(notes) > 10000:
            raise InputValidationError('As notas devem ter até 10.000 caracteres.')
        if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(tag, str) or not 1 <= len(tag) <= 80 for tag in tags):
            raise InputValidationError('Use até 20 etiquetas de até 80 caracteres.')
        with self._lock, self.connection:
            self._row(article_id)
            self.connection.execute('UPDATE library_articles SET notes=?, tags_json=?, updated_at=? WHERE article_id=?',
                                    (notes, json.dumps(list(dict.fromkeys(tags))), datetime.now(timezone.utc).isoformat(), article_id))
            self._index(article_id)
            return self._public(self._row(article_id))
