import json, os, re
import numpy as np, faiss
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import os
CUR = os.path.dirname(os.path.abspath(__file__))          # .../data-extraction
ROOT = os.path.normpath(os.path.join(CUR, '..'))          # .../ai-assistant
DATA_FILE = os.path.join(ROOT,'data-extraction', 'data', 'scraped_data.json')
print (f"Using data file: {DATA_FILE}")
class DataIndexer:
    def __init__(self, model_name='sentence-transformers/all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)
        self.chunks = []
        self.embeddings = None
        self.index = None

    def chunk_text(self, text, chunk_size=800, overlap=100):
        chunks = []
        text = re.sub(r'\s+', ' ', text or '')
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]
            if end < len(text):
                last_period = chunk.rfind('. ')
                if last_period > chunk_size * 0.7:
                    end = start + last_period + 1
                    chunk = text[start:end]
            chunk = chunk.strip()
            if chunk: chunks.append(chunk)
            if end >= len(text): break
            start = end - overlap
        return chunks  # sentence-aware splitting improves retrieval fidelity [web:521]

    def process_scraped_data(self, data_file=DATA_FILE):
        pages = json.load(open(data_file,'r',encoding='utf-8'))
        if not isinstance(pages, list):
            raise AssertionError("data/scraped_data.json must be a list")
        print("Processing data into chunks...")
        for page in tqdm(pages):
            full_text = f"{page.get('title','')}\n\n{page.get('content','')}"
            for i, chunk in enumerate(self.chunk_text(full_text)):
                self.chunks.append({
                    'text': chunk,
                    'url': page.get('url',''),
                    'title': page.get('title',''),
                    'page_type': page.get('page_type','general'),
                    'chunk_index': i,
                    'product_info': page.get('product_info', {})
                })
        print(f"Created {len(self.chunks)} chunks from {len(pages)} items")

    def create_embeddings(self):
        print("Creating embeddings...")
        texts = [c['text'] for c in self.chunks]
        embs = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=True)
        self.embeddings = np.asarray(embs, dtype='float32')
        if self.embeddings.ndim != 2:
            raise ValueError("Embeddings must be 2D [n_chunks, dim]")

    def build_faiss_index(self):
        print("Building FAISS index...")
        dim = int(self.embeddings.shape[1])
        self.index = faiss.IndexFlatIP(dim)  # cosine via inner product on normalized vectors [web:291][web:286]
        self.index.add(self.embeddings)
        print(f"Built FAISS index with {self.index.ntotal} vectors")

    def save_index(self, index_dir='data-extraction/database'):
        os.makedirs(index_dir, exist_ok=True)
        faiss.write_index(self.index, os.path.join(index_dir, 'faiss.index'))
        json.dump(self.chunks, open(os.path.join(index_dir,'chunks_metadata.json'),'w',encoding='utf-8'), ensure_ascii=False, indent=2)
        info = {
            'dimension': int(self.embeddings.shape[1]),
            'num_vectors': int(self.embeddings.shape[0]),
            'model_name': 'sentence-transformers/all-MiniLM-L6-v2'
        }
        json.dump(info, open(os.path.join(index_dir,'index_info.json'),'w'), indent=2)
        print(f"Saved index and metadata to {index_dir}/")

    def search(self, query, top_k=5):
        if not self.index: return []
        qv = self.model.encode([query], normalize_embeddings=True)
        qv = np.asarray(qv, dtype='float32')
        D, I = self.index.search(qv, top_k)
        out = []
        for score, idx in zip(D[0], I[0]):
            if idx != -1:
                c = self.chunks[idx]
                out.append({
                    'text': c['text'], 'url': c['url'], 'title': c['title'],
                    'page_type': c['page_type'], 'score': float(score),
                    'product_info': c.get('product_info', {})
                })
        return out

if __name__ == '__main__':
    # If you prefer auto-conversion, run the converter first
    if not os.path.exists('data-extraction/data/scraped_data.json'):
        raise SystemExit("Run convert_shopify_to_scraped.py first to produce data/scraped_data.json")

    idx = DataIndexer()
    idx.process_scraped_data()
    idx.create_embeddings()
    idx.build_faiss_index()
    idx.save_index()
    # smoke test
    res = idx.search("what is price of blue t shirt?", top_k=3)
    for r in res:
        print(r['title'], r['url'], f"{r['score']:.3f}")
