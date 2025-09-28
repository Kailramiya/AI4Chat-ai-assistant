import sys, json, os
import numpy as np, faiss
from sentence_transformers import SentenceTransformer

CUR = os.path.dirname(os.path.abspath(__file__))   # .../data-extraction
INDEX_DIR = os.path.join(CUR, 'database')
INDEX_PATH = os.path.normpath(os.path.join(INDEX_DIR, 'faiss.index'))
META_PATH  = os.path.normpath(os.path.join(INDEX_DIR, 'chunks_metadata.json'))
MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'

def load_index_and_meta():
    if not os.path.exists(INDEX_PATH):
        raise FileNotFoundError(f"Missing index file: {INDEX_PATH}")
    if not os.path.exists(META_PATH):
        raise FileNotFoundError(f"Missing metadata file: {META_PATH}")
    index = faiss.read_index(INDEX_PATH)
    meta = json.load(open(META_PATH,'r',encoding='utf-8'))
    return index, meta

def embed_query(model, text):
    vec = model.encode([text], normalize_embeddings=True)
    return np.asarray(vec, dtype='float32')

def search_knowledge_base(query, top_k=5):
    try:
        index, meta = load_index_and_meta()
        model = SentenceTransformer(MODEL_NAME)
        qv = embed_query(model, query)
        D, I = index.search(qv, int(top_k))
        out = []
        for idx, score in zip(I[0].tolist(), D[0].tolist()):
            if idx == -1 or idx >= len(meta): continue
            m = meta[idx]
            out.append({
                'text': m.get('text',''),
                'url': m.get('url',''),
                'title': m.get('title',''),
                'page_type': m.get('page_type',''),
                'score': float(score),
                'product_info': m.get('product_info', {})
            })
        return out
    except Exception as e:
        return {'error': str(e)}

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Query required'})); sys.exit(1)
    query = sys.argv[1]
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    results = search_knowledge_base(query, top_k)
    print(json.dumps(results, ensure_ascii=False))
