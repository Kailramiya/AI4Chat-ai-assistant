import sys
import json
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import os


CUR = os.path.dirname(os.path.abspath(__file__))             # .../ai-assistance/data-extraction
INDEX_DIR = os.path.join(CUR, 'database')

def search_knowledge_base(query, top_k=5):
    try:
        # Load FAISS index and metadata
        idx_path=os.path.join(INDEX_DIR, 'faiss.index')
        meta_path = os.path.join(INDEX_DIR, 'chunks_metadata.json')
        idx_path = os.path.normpath(idx_path)
        meta_path = os.path.normpath(meta_path)
        index = faiss.read_index(idx_path)
        with open(meta_path, 'r', encoding='utf-8') as f:
            chunks = json.load(f)
        
        # Load model (same as used for indexing)
        model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        
        # Create query embedding
        query_embedding = model.encode([query], normalize_embeddings=True)
        query_embedding = np.array(query_embedding, dtype=np.float32)
        
        # Search
        scores, indices = index.search(query_embedding, top_k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx != -1 and idx < len(chunks):
                chunk = chunks[idx]
                result = {
                    'text': chunk['text'],
                    'url': chunk['url'],
                    'title': chunk['title'],
                    'page_type': chunk['page_type'],
                    'score': float(score),
                    'product_info': chunk.get('product_info', {})
                }
                results.append(result)
        
        return results
        
    except Exception as e:
        return {'error': str(e)}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Query required'}))
        sys.exit(1)
    
    query = sys.argv[1]
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    
    results = search_knowledge_base(query, top_k)
    print(json.dumps(results, ensure_ascii=False))
