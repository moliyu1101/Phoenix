from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict

import httpx

from .budget import Ledger
from .config import ModelProfile, Settings
from .domain import digest, dump, now, uid
from .store import Store


def terms(text: str) -> list[str]:
    result = re.findall(r'[a-z0-9_]+', text.lower())
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        result.extend(run[i:i+2] for i in range(max(1, len(run)-1)))
    return list(dict.fromkeys(result))


def chunk_text(text: str, size: int = 2200, overlap: int = 220) -> list[str]:
    if size < 100 or not 0 <= overlap < size:
        raise ValueError('Invalid chunk dimensions')
    chunks, pos = [], 0
    while pos < len(text):
        end = min(len(text), pos + size)
        if end < len(text):
            cut = text.rfind('\n', pos + size // 2, end)
            if cut > pos:
                end = cut + 1
        chunk = text[pos:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        pos = max(pos + 1, end - overlap)
    return chunks


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return -1
    norm_a, norm_b = math.sqrt(sum(x*x for x in a)), math.sqrt(sum(x*x for x in b))
    if not norm_a or not norm_b:
        return -1
    return sum(x*y for x, y in zip(a, b)) / (norm_a * norm_b)


class Knowledge:
    def __init__(self, store: Store, settings: Settings | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.store, self.settings, self.transport = store, settings, transport

    def ingest(self, title: str, body: str, category: str = 'general', source: str = 'operator',
               trusted: bool = False) -> str:
        if not body.strip() or len(body.encode()) > 2_000_000:
            raise ValueError('Knowledge documents must contain 1 byte..2 MiB of UTF-8 text')
        if category not in ('general', 'web', 'crypto', 'pwn', 'reverse', 'forensics', 'misc'):
            raise ValueError('Unknown category')
        sha = digest(body)
        existing = self.store.all('SELECT id FROM documents WHERE sha256=? AND source=?', (sha, source))
        if existing:
            return existing[0]['id']
        did = uid('doc')
        with self.store.tx() as db:
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)',
                       (did, title[:300], category, body, source[:1000], sha, 'trusted' if trusted else 'draft', now()))
            for i, chunk in enumerate(chunk_text(body)):
                kid = uid('chunk')
                tokens = ' '.join(terms(title + '\n' + chunk))
                db.execute('INSERT INTO chunks(id,doc_id,ordinal,body,terms) VALUES(?,?,?,?,?)',
                           (kid, did, i, chunk, tokens))
                db.execute('INSERT INTO chunks_fts(id,terms) VALUES(?,?)', (kid, tokens))
        self.store.audit('knowledge.ingest', {'document_id': did, 'source': source, 'trusted': trusted})
        return did

    def trust(self, did: str, approved: bool):
        self.store.one('SELECT id FROM documents WHERE id=?', (did,))
        self.store.execute('UPDATE documents SET trust=? WHERE id=?', ('trusted' if approved else 'retired', did))
        self.store.audit('knowledge.review', {'document_id': did, 'approved': approved})

    def search(self, query: str, category: str | None = None, limit: int = 6,
               snapshot: list[str] | None = None, vector: list[float] | None = None,
               space: str | None = None) -> list[dict]:
        if not 1 <= limit <= 30:
            raise ValueError('Retrieval limit must be 1..30')
        if snapshot == []:
            return []
        conditions, args = ["d.trust='trusted'"], []
        if category:
            conditions.append("d.category IN (?, 'general')")
            args.append(category)
        if snapshot is not None:
            conditions.append('d.id IN (' + ','.join('?' for _ in snapshot) + ')')
            args.extend(snapshot)
        where = ' AND '.join(conditions)
        query_terms = terms(query)[:64]
        sparse = []
        if query_terms:
            match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in query_terms)
            sparse = self.store.all(
                'SELECT c.id,c.doc_id,c.body,d.title,d.source,d.category,bm25(chunks_fts) AS rank '
                'FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.id JOIN documents d ON d.id=c.doc_id '
                'WHERE chunks_fts MATCH ? AND ' + where + ' ORDER BY rank LIMIT 60', tuple([match] + args))
        dense = []
        if vector is not None and space:
            dense_rows = self.store.all(
                'SELECT c.id,c.doc_id,c.body,c.embedding,d.title,d.source,d.category FROM chunks c '
                'JOIN documents d ON d.id=c.doc_id WHERE c.embedding_space=? AND ' + where,
                tuple([space] + args))
            for row in dense_rows:
                row['similarity'] = cosine(vector, json.loads(row.pop('embedding')))
                if row['similarity'] > 0:
                    dense.append(row)
            dense.sort(key=lambda x: x['similarity'], reverse=True)
            dense = dense[:60]
        scores: dict[str, float] = defaultdict(float)
        items = {}
        for ranking in (sparse, dense):
            for i, row in enumerate(ranking):
                scores[row['id']] += 1 / (60 + i + 1)
                items[row['id']] = row
        selected = sorted(items, key=lambda k: scores[k], reverse=True)
        return [{**items[k], 'score': scores[k], 'retrieval': 'hybrid_rrf' if vector is not None else 'fts5_bm25'}
                for k in selected[:limit]]

    def embedding_space(self, dimensions: int) -> str:
        s = self.settings
        return digest(dump([s.embedding_base_url, s.embedding_model, dimensions]))

    async def embed(self, texts: list[str], rid: str | None = None) -> tuple[list[list[float]], str]:
        s = self.settings
        if not s or not s.embedding_base_url or not s.embedding_model:
            raise ValueError('No embedding endpoint configured; lexical retrieval remains available')
        if len(texts) > 32:
            raise ValueError('Embedding batches are capped at 32 texts')
        ledger, reservation = Ledger(self.store), None
        if rid:
            # Paid query embeddings share the run's token/cost admission ledger.
            p = ModelProfile(base_url=s.embedding_base_url, model=s.embedding_model,
                             api_key_env=s.embedding_key_env, output_tokens=256,
                             input_usd_per_million=s.embedding_input_usd_per_million,
                             output_usd_per_million=0)
            reservation = ledger.reserve(rid, 'retrieval', p, sum(len(t.encode()) for t in texts) + 256)
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=45, trust_env=False,
                                         follow_redirects=False) as client:
                response = await client.post(s.embedding_base_url.rstrip('/') + '/embeddings',
                                             headers={'Authorization': 'Bearer ' + os.environ.get(s.embedding_key_env, '')},
                                             json={'model': s.embedding_model, 'input': texts})
                response.raise_for_status()
                raw = response.json()
            rows = sorted(raw['data'], key=lambda r: r['index'])
            if [x['index'] for x in rows] != list(range(len(texts))):
                raise ValueError('Embedding response indices do not match the request')
            vectors = [r['embedding'] for r in rows]
            dims = len(vectors[0])
            if not 1 <= dims <= 65536 or any(len(v) != dims or not all(math.isfinite(float(x)) for x in v) for v in vectors):
                raise ValueError('Invalid embedding dimensions or non-finite values')
            usage = raw.get('usage', {}).get('prompt_tokens', raw.get('usage', {}).get('total_tokens'))
            if reservation:
                ledger.settle(reservation, usage, 0 if usage is not None else None)
            else:
                self.store.audit('embedding.index_usage', {'model': s.embedding_model, 'tokens': usage,
                                                          'texts': len(texts), 'scope': 'operator_indexing'})
            return vectors, self.embedding_space(dims)
        except BaseException:
            if reservation:
                ledger.uncertain(reservation)
            raise

    async def index(self, did: str, confirm_paid: bool = False) -> int:
        if not confirm_paid:
            raise ValueError('Indexing may incur API charges; explicit confirmation is required')
        chunks = self.store.all('SELECT * FROM chunks WHERE doc_id=? ORDER BY ordinal', (did,))
        count = 0
        for offset in range(0, len(chunks), 16):
            batch = chunks[offset:offset+16]
            vectors, space = await self.embed([c['body'] for c in batch])
            with self.store.tx() as db:
                for chunk, vector in zip(batch, vectors):
                    db.execute('UPDATE chunks SET embedding=?,embedding_space=? WHERE id=?',
                               (dump(vector), space, chunk['id']))
                    count += 1
        return count

    async def retrieve(self, query: str, category: str, rid: str, limit: int = 6) -> list[dict]:
        snapshot = self.store.run(rid)['knowledge_snapshot']
        vector, space = None, None
        if self.settings and self.settings.embedding_model and self.settings.embedding_base_url:
            try:
                vectors, space = await self.embed([query], rid)
                vector = vectors[0]
            except Exception as exc:
                self.store.event(rid, 'retrieval.lexical_fallback', {'reason': type(exc).__name__})
        return self.search(query, category, limit, snapshot, vector, space)
