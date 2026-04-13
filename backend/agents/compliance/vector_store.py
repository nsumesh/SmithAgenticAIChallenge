# Supabase vector store for compliance knowledge
import os
from typing import List, Dict, Optional
from supabase import create_client, Client
# Handle both relative and absolute imports
try:
    from .embeddings import EmbeddingGenerator
    from .mock_vector_store import MockComplianceVectorStore
except ImportError:
    # Fallback for direct execution
    from embeddings import EmbeddingGenerator
    from mock_vector_store import MockComplianceVectorStore

class ComplianceVectorStore:
    # manage compliance knowledge in Supabase pgvector or mock store
    def __init__(self):
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        
        # Try to connect to Supabase, fall back to mock store if not available
        if supabase_url and supabase_key:
            try:
                self.client: Client = create_client(supabase_url, supabase_key)
                self.table_name = 'compliance_knowledge'
                
                # Test connection
                test_result = self.client.table(self.table_name).select("count", count="exact").limit(1).execute()
                
                # initialize embedding generator
                self.embedder = EmbeddingGenerator(model_name="all-MiniLM-L6-v2")
                self.use_mock = False
                
                print(f"Connected to Supabase for vector store operations")
                print(f"Embedding dimension for vector store: {self.embedder.embedding_dim}")
                
            except Exception as e:
                print(f"Failed to connect to Supabase: {e}")
                print("Falling back to mock vector store for testing...")
                self.mock_store = MockComplianceVectorStore()
                self.use_mock = True
        else:
            print("Supabase credentials not found, using mock vector store...")
            self.mock_store = MockComplianceVectorStore()
            self.use_mock = True
    
    def add_documents(self, chunks: List[Dict]) -> int:
        # add document chunks to vector store
        if self.use_mock:
            return self.mock_store.add_documents(chunks)
        
        print(f"Adding {len(chunks)} chunks to vector store")
        
        # generate embeddings for all chunks
        texts = [chunk['content'] for chunk in chunks]
        embeddings = self.embedder.generate_embeddings_batch(texts)
            
        # prepare records for insertion
        records = []
        for chunk, embedding in zip(chunks, embeddings):
            record = {
                'regulation_id': chunk['regulation_id'],
                'regulation_name': chunk['metadata'].get('regulation_name'),
                'authority': chunk['metadata'].get('authority'),
                'section': chunk.get('section'),
                'title': chunk.get('title'),
                'content': chunk['content'],
                'embedding': embedding,
                'metadata': {
                    **chunk['metadata'],
                    'chunk_index': chunk.get('chunk_index'),
                    'source_file': chunk['metadata'].get('source_file')
                }
            }
            records.append(record)
        
        # Insert in batches (Supabase limit: 1000 per request)
        batch_size = 100
        inserted = 0
        
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            try:
                response = self.client.table(self.table_name).insert(batch).execute()
                inserted += len(batch)
                print(f"[VECTOR STORE] Inserted batch {i//batch_size + 1} ({len(batch)} records)")
            except Exception as e:
                print(f"[ERROR] Failed to insert batch: {e}")
                continue
        
        print(f"[VECTOR STORE] ✓ Added {inserted} chunks to database")
        return inserted
    
    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict] = None,
        similarity_threshold: float = 0.3
    ) -> List[Dict]:
        # semantic search for relevant regulations
        if self.use_mock:
            return self.mock_store.search(query, limit, similarity_threshold)
        
        print(f"Searching for: '{query}'")
        
        # Generate query embedding
        query_embedding = self.embedder.generate_embedding(query)
        
        # Build RPC call for vector similarity search
        # Note: Supabase doesn't support vector search in Python SDK yet,
        # so we use RPC to call a PostgreSQL function
        
        try:
            response = self.client.rpc(
                'match_compliance_documents',
                {
                    'query_embedding': query_embedding,
                    'match_threshold': similarity_threshold,
                    'match_count': limit
                }
            ).execute()
            
            results = response.data
            
            print(f"Found {len(results)} results in vector store")
            
            return results
            
        except Exception as e:
            print(f"[ERROR] Search failed: {e}")
            print("[INFO] Falling back to alternative search method...")
            
            # Fallback: Get all documents and calculate similarity in Python
            all_docs = self.client.table(self.table_name).select('*').limit(1000).execute()
            
            results = []
            for doc in all_docs.data:
                similarity = self.embedder.similarity(query_embedding, doc['embedding'])
                if similarity >= similarity_threshold:
                    results.append({
                        **doc,
                        'similarity': similarity
                    })
            
            # Sort by similarity
            results.sort(key=lambda x: x['similarity'], reverse=True)
            return results[:limit]
    
    def get_by_regulation_id(self, regulation_id: str) -> List[Dict]:
        # get all chunks for a specific regulation
        response = self.client.table(self.table_name)\
            .select('*')\
            .eq('regulation_id', regulation_id)\
            .execute()
        
        return response.data
    
    def delete_all(self):
        # delete all documents (for testing)
        print("[WARNING] Deleting all documents...")
        response = self.client.table(self.table_name).delete().neq('id', 0).execute()
        print(f"[VECTOR STORE] Deleted all documents")
    
    def count_documents(self) -> int:
        # get total document count
        if self.use_mock:
            return self.mock_store.count_documents()
        
        response = self.client.table(self.table_name)\
            .select('id', count='exact')\
            .execute()
        return response.count