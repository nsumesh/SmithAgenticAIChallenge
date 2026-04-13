# Generate embeddings for compliance documents using Sentence Transformers
import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List, Union

class EmbeddingGenerator:
    # generate embeddings using Sentence Transformers
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # initialize embedding model
        # model_name: Sentence transformer model - "all-MiniLM-L6-v2"
        print(f"Loading model for embeddings: {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        print(f"Model loaded (dimension: {self.embedding_dim})")
    
    # generate embedding for single text - text to embed - returns embedding vector as list of floats
    def generate_embedding(self, text: str) -> List[float]:
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def generate_embeddings_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        # generate embeddings for multiple texts (batched for speed)
        print(f"Generating embeddings for {len(texts)} texts...")
        
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        
        return embeddings.tolist()
    
    def similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        # calculate cosine similarity between two embeddings
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)
        
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))