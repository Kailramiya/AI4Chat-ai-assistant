import json
import os
import re
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# This indexer:
# - Accepts either:
#   a) data/scraped_data.json: list of {title, content, url, page_type, product_info}
#   b) data/json/shopify_products.json: {"products": [...]} (Shopify format)
# - Converts Shopify products to the page schema, enriching both free text and structured product_info
# - Chunks, embeds (normalized), and writes FAISS (FlatIP = cosine with normalized vectors)
# Outputs:
#   database/faiss.index
#   database/chunks_metadata.json
#   database/index_info.json
# Input/output conventions follow common FAISS + sentence-transformers usage. [web:291][web:286]

class DataIndexer:
    def __init__(self, model_name='sentence-transformers/all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)  # Fast, good quality, 384-dim embeddings normalized for cosine [web:291]
        self.chunks = []
        self.embeddings = None
        self.index = None

    # ---------- Input detection and conversion ----------

    def _html_to_text(self, html):
        text = re.sub(r'<[^>]+>', ' ', html or '')
        text = re.sub(r'\s+', ' ', text).strip()
        return text  # clean description improves embeddings and retrieval [web:522]

    def _parse_variant_label(self, title):
        # Expect labels like "Blue / Small" or "Default Title"
        if not title:
            return None, None
        parts = [p.strip() for p in title.split('/') if p is not None]
        if len(parts) == 1:
            return parts[0] or None, None
        if len(parts) >= 2:
            return parts[0] or None, parts[1] or None
        return None, None

    def _product_to_doc(self, p, base_url='https://b2b-demo-store.myshopify.com/products/'):
        # Map Shopify product to page schema with enriched content and structured product_info. [web:522]
        title = (p.get('title') or '').strip()
        handle = p.get('handle') or re.sub(r'[^a-z0-9-]+', '-', title.lower())
        url = f"{base_url}{handle}"

        # Description to plain text
        body = self._html_to_text(p.get('body_html', ''))

        # Extract simple materials/quality/care hints from description
        low = body.lower()
        materials = None
        care = None
        # naive patterns (extend as needed)
        mat_hits = []
        for token in ['100% cotton', 'cotton', 'leather', 'stainless steel', 'handmade', 'wool', 'linen']:
            if token in low:
                mat_hits.append(token)
        if mat_hits:
            # prefer the longest/most specific token
            materials = sorted(mat_hits, key=len, reverse=True)[0]
        for token in ['machine washable', 'hand wash', 'dry clean', 'wash cold']:
            if token in low:
                care = token
                break

        # Variants summary and structured list
        variants = p.get('variants') or []
        var_lines = []
        var_struct = []
        prices = []
        for v in variants:
            label = v.get('title') or ''
            color, size = self._parse_variant_label(label)
            sku = v.get('sku') or ''
            price = v.get('price') or ''
            available = bool(v.get('available'))
            if price:
                try:
                    prices.append(float(str(price)))
                except Exception:
                    pass
            avail_txt = 'in stock' if available else 'out of stock'
            # Human-readable line for embedding
            var_lines.append(f"{label} (SKU {sku}) {avail_txt}, price {price}")
            # Structured for downstream answer formatting
            var_struct.append({
                'label': label,
                'color': color,
                'size': size,
                'sku': sku,
                'price': str(price) if price is not None else '',
                'available': available
            })

        best_price = None
        if prices:
            best_price = f"{min(prices):.2f}"

        # Options summary
        opts = p.get('options') or []
        opt_parts = []
        for o in opts:
            name = o.get('name', '').strip()
            vals = ", ".join((o.get('values') or []))
            if name and vals:
                opt_parts.append(f"{name}: {vals}")

        # Build content: description + quality + variants + options
        lines = []
        if body:
            lines.append(body)
        qual_bits = []
        if materials:
            qual_bits.append(f"Material: {materials}")
        if care:
            qual_bits.append(f"Care: {care}")
        if qual_bits:
            lines.append(" ".join(qual_bits))
        if var_lines:
            lines.append("Variants: " + "; ".join(var_lines))
        if opt_parts:
            lines.append("Options: " + "; ".join(opt_parts))
        content = ". ".join(lines).strip()

        return {
            "title": title or handle,
            "content": content,
            "url": url,
            "page_type": "product",
            "product_info": {
                "id": p.get('id'),
                "handle": handle,
                "vendor": p.get('vendor', ''),
                "updated_at": p.get('updated_at', ''),
                "best_price": best_price or '',
                "materials": materials or '',
                "care": care or '',
                "variants": var_struct
            }
        }  # Enrichment ensures price and quality questions retrieve clean facts. [web:522]

    def _load_input_docs(self, scraped_path='data/scraped_data.json', shopify_path='data/json/shopify_products.json'):
        # Priority: use scraped_data.json if it exists and is a list; otherwise, convert from Shopify JSON. [web:522]
        if os.path.exists(scraped_path):
            with open(scraped_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise AssertionError("data/scraped_data.json must be a list of pages")
            return data
        elif os.path.exists(shopify_path):
            src = json.load(open(shopify_path, 'r', encoding='utf-8'))
            products = src.get('products', [])
            docs = [self._product_to_doc(p) for p in products]
            os.makedirs('data', exist_ok=True)
            json.dump(docs, open(scraped_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            print(f"Converted {len(docs)} products -> {scraped_path}")
            return docs
        else:
            raise FileNotFoundError("Provide either data/scraped_data.json (array) or data/json/shopify_products.json")

    # ---------- Chunking, embedding, indexing ----------

    def chunk_text(self, text, chunk_size=800, overlap=100):
        """Split text into overlapping chunks with light sentence-awareness."""
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
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = end - overlap
        return chunks  # Keeping 500–800 char chunks improves retrieval fidelity. [web:511]

    def process_scraped_data(self, data_file='data/scraped_data.json'):
        """Load docs (or convert), then produce chunks with metadata."""
        pages = self._load_input_docs(scraped_path=data_file)  # Auto-detect/conversion. [web:522]
        print("Processing data into chunks...")
        for page in tqdm(pages):
            full_text = f"{page.get('title','')}\n\n{page.get('content','')}"
            text_chunks = self.chunk_text(full_text)
            for i, chunk in enumerate(text_chunks):
                self.chunks.append({
                    'text': chunk,
                    'url': page.get('url', ''),
                    'title': page.get('title', ''),
                    'page_type': page.get('page_type', 'general'),
                    'chunk_index': i,
                    'product_info': page.get('product_info', {})
                })
        print(f"Created {len(self.chunks)} chunks from {len(pages)} items")

    def create_embeddings(self):
        """Embed all chunks with normalized vectors (cosine-ready)."""
        print("Creating embeddings...")
        texts = [c['text'] for c in self.chunks]
        self.embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,  # inner product == cosine on normalized vectors [web:291]
            show_progress_bar=True
        )
        self.embeddings = np.array(self.embeddings, dtype=np.float32)
        if self.embeddings.ndim != 2:
            raise ValueError("Embeddings must be 2D [n_chunks, dim]")

    def build_faiss_index(self):
        """Build FAISS FlatIP index (cosine with normalized embeddings)."""
        print("Building FAISS index...")
        dim = int(self.embeddings.shape[1])
        self.index = faiss.IndexFlatIP(dim)  # simple and very fast for small/mid corpora [web:286]
        self.index.add(self.embeddings)
        print(f"Built FAISS index with {self.index.ntotal} vectors")

    def save_index(self, index_dir='database'):
        """Persist FAISS index and metadata files."""
        os.makedirs(index_dir, exist_ok=True)
        faiss.write_index(self.index, os.path.join(index_dir, 'faiss.index'))  # Consumed by search.py. [web:286]
        with open(os.path.join(index_dir, 'chunks_metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(self.chunks, f, ensure_ascii=False, indent=2)
        info = {
            'dimension': int(self.embeddings.shape[1]),
            'num_vectors': int(self.embeddings.shape[0]),
            'model_name': 'sentence-transformers/all-MiniLM-L6-v2'
        }
        with open(os.path.join(index_dir, 'index_info.json'), 'w') as f:
            json.dump(info, f, indent=2)
        print(f"Saved index and metadata to {index_dir}/")  # Standard FAISS persistence pattern. [web:291]

    def search(self, query, top_k=5):
        """Ad-hoc local search to sanity-check results before wiring to an API."""
        if not self.index:
            print("Index not built yet!")
            return []
        qv = self.model.encode([query], normalize_embeddings=True)
        qv = np.array(qv, dtype=np.float32)
        D, I = self.index.search(qv, top_k)
        results = []
        for score, idx in zip(D[0], I[0]):
            if idx != -1:
                c = self.chunks[idx]
                results.append({
                    'text': c['text'],
                    'url': c['url'],
                    'title': c['title'],
                    'page_type': c['page_type'],
                    'score': float(score),
                    'product_info': c.get('product_info', {})
                })
        return results  # Mirrors typical FAISS query→metadata join approach. [web:291]

if __name__ == "__main__":
    indexer = DataIndexer()
    indexer.process_scraped_data()        # Detects/creates data/scraped_data.json if Shopify JSON provided. [web:522]
    indexer.create_embeddings()           # Normalized embeddings for cosine via FlatIP. [web:291]
    indexer.build_faiss_index()           # Write FAISS index in memory. [web:286]
    indexer.save_index()                  # Persist to database/ for search.py to read. [web:291]
    # Smoke test
    results = indexer.search("What is the price of the blue shirt?", top_k=3)
    for r in results:
        print(f"Score: {r['score']:.3f}")
        print(f"Title: {r['title']}")
        print(f"Text: {r['text'][:200]}...")
        print(f"URL: {r['url']}\n")
