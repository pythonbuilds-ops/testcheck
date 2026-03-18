"""
Semantic Embeddings Module
Leverages sentence-transformers for local text embeddings and semantic search.
"""

import json
from typing import List
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False

# Initialize the tiny, fast all-MiniLM-L6-v2 model (runs on CPU easily)
_MODEL = None

def get_model():
    global _MODEL
    if _MODEL is None and HAS_EMBEDDINGS:
        # Lazy initialization to keep startup fast
        print("[System] Loading SentenceTransformer model...")
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    return _MODEL

def embed_text(text: str) -> bytes:
    """
    Generate an embedding vector for the given text and return it as bytes
    so it can be safely stored in the SQLite BLOB column.
    """
    if not HAS_EMBEDDINGS:
        return b""
        
    model = get_model()
    # Ensure it's a normalized float32 numpy array
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.astype(np.float32).tobytes()

def calculate_similarities(query_embedding_bytes: bytes, target_embeddings_bytes: List[bytes]) -> List[float]:
    """
    Calculate cosine similarity between a query and multiple byte-encoded targets.
    """
    if not HAS_EMBEDDINGS or not query_embedding_bytes or not target_embeddings_bytes:
        return [0.0] * len(target_embeddings_bytes)
        
    # Convert bytes back to numpy arrays
    q_vec = np.frombuffer(query_embedding_bytes, dtype=np.float32).reshape(1, -1)
    
    t_arrays = []
    for b in target_embeddings_bytes:
        if b:
            t_arrays.append(np.frombuffer(b, dtype=np.float32))
        else:
            t_arrays.append(np.zeros(384, dtype=np.float32))
            
    t_matrix = np.vstack(t_arrays)
    
    similarities = cosine_similarity(q_vec, t_matrix)[0]
    return similarities.tolist()
