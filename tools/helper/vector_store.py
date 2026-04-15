"""
Supabase pgvector store for compliance regulatory knowledge.

Falls back to MockComplianceVectorStore when Supabase credentials are
missing or the ``compliance_knowledge`` table is unreachable.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class ComplianceVectorStore:

    def __init__(self):
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")

        if supabase_url and supabase_key:
            try:
                from supabase import create_client

                self.client = create_client(supabase_url, supabase_key)
                self.table_name = "compliance_knowledge"

                self.client.table(self.table_name).select(
                    "count", count="exact"
                ).limit(1).execute()

                from tools.helper.embeddings import EmbeddingGenerator

                self.embedder = EmbeddingGenerator(model_name="all-MiniLM-L6-v2")
                self.use_mock = False
                logger.info(
                    "Vector store connected (dim=%d)", self.embedder.embedding_dim
                )
                return
            except Exception as exc:
                logger.warning("Supabase vector store unavailable: %s", exc)

        logger.info("Using mock vector store (no Supabase or table missing)")
        from tools.helper.mock_vector_store import MockComplianceVectorStore

        self.mock_store = MockComplianceVectorStore()
        self.use_mock = True

    # ── write ────────────────────────────────────────────────────────
    def add_documents(self, chunks: List[Dict]) -> int:
        if self.use_mock:
            return self.mock_store.add_documents(chunks)

        texts = [c["content"] for c in chunks]
        embeddings = self.embedder.generate_embeddings_batch(texts)

        records = []
        for chunk, emb in zip(chunks, embeddings):
            records.append(
                {
                    "regulation_id": chunk["regulation_id"],
                    "regulation_name": chunk["metadata"].get("regulation_name"),
                    "authority": chunk["metadata"].get("authority"),
                    "section": chunk.get("section"),
                    "title": chunk.get("title"),
                    "content": chunk["content"],
                    "embedding": emb,
                    "metadata": {
                        **chunk["metadata"],
                        "chunk_index": chunk.get("chunk_index"),
                        "source_file": chunk["metadata"].get("source_file"),
                    },
                }
            )

        inserted = 0
        for i in range(0, len(records), 100):
            batch = records[i : i + 100]
            try:
                self.client.table(self.table_name).insert(batch).execute()
                inserted += len(batch)
            except Exception as exc:
                logger.error("Batch insert failed: %s", exc)
        return inserted

    # ── search ───────────────────────────────────────────────────────
    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict] = None,
        similarity_threshold: float = 0.3,
    ) -> List[Dict]:
        if self.use_mock:
            return self.mock_store.search(query, limit, similarity_threshold)

        query_embedding = self.embedder.generate_embedding(query)

        try:
            resp = self.client.rpc(
                "match_compliance_documents",
                {
                    "query_embedding": query_embedding,
                    "match_threshold": similarity_threshold,
                    "match_count": limit,
                },
            ).execute()
            return resp.data
        except Exception:
            logger.warning("RPC search failed, falling back to brute-force")
            all_docs = (
                self.client.table(self.table_name).select("*").limit(1000).execute()
            )
            results = []
            for doc in all_docs.data:
                sim = self.embedder.similarity(query_embedding, doc["embedding"])
                if sim >= similarity_threshold:
                    results.append({**doc, "similarity": sim})
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:limit]

    # ── helpers ──────────────────────────────────────────────────────
    def get_by_regulation_id(self, regulation_id: str) -> List[Dict]:
        return (
            self.client.table(self.table_name)
            .select("*")
            .eq("regulation_id", regulation_id)
            .execute()
            .data
        )

    def delete_all(self):
        self.client.table(self.table_name).delete().neq("id", 0).execute()

    def count_documents(self) -> int:
        if self.use_mock:
            return self.mock_store.count_documents()
        resp = (
            self.client.table(self.table_name)
            .select("id", count="exact")
            .execute()
        )
        return resp.count
