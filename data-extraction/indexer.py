import json
import os
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import re

class DataIndexer:
    def __init__(self, model_name='sentence-transformers/all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)
        self.chunks = []
        self.embeddings = None
        self.index = None
        
    def chunk_text(self, text, chunk_size=800, overlap=100):
        """Split text into overlapping chunks"""
        chunks = []
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
        
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]
            
            # Try to break at sentence boundaries
            if end < len(text):
                last_period = chunk.rfind('. ')
                if last_period > chunk_size * 0.7:  # Don't break too early
                    end = start + last_period + 1
                    chunk = text[start:end]
            
            chunks.append(chunk.strip())
            
            if end >= len(text):
                break
                
            start = end - overlap
            
        return chunks
    
    def process_scraped_data(self, data_file='data/scraped_data.json'):
        """Process scraped data into chunks with metadata"""
        with open(data_file, 'r', encoding='utf-8') as f:
            scraped_data = json.load(f)
        
        print("Processing scraped data into chunks...")
        
        for page in tqdm(scraped_data):
            # Combine title and content
            full_text = f"{page['title']}\n\n{page['content']}"
            
            # Split into chunks
            text_chunks = self.chunk_text(full_text)
            
            for i, chunk in enumerate(text_chunks):
                chunk_data = {
                    'text': chunk,
                    'url': page['url'],
                    'title': page['title'],
                    'page_type': page['page_type'],
                    'chunk_index': i,
                    'product_info': page.get('product_info', {})
                }
                self.chunks.append(chunk_data)
        
        print(f"Created {len(self.chunks)} chunks from {len(scraped_data)} pages")
        
    def create_embeddings(self):
        """Create embeddings for all chunks"""
        print("Creating embeddings...")
        
        texts = [chunk['text'] for chunk in self.chunks]
        self.embeddings = self.model.encode(
            texts, 
            normalize_embeddings=True,
            show_progress_bar=True
        )
        self.embeddings = np.array(self.embeddings, dtype=np.float32)
        
    def build_faiss_index(self):
        """Build FAISS index for fast similarity search"""
        print("Building FAISS index...")
        
        dimension = self.embeddings.shape[1]
        
        # Use IndexFlatIP for cosine similarity with normalized vectors
        self.index = faiss.IndexFlatIP(dimension)
        self.index.add(self.embeddings)
        
        print(f"Built FAISS index with {self.index.ntotal} vectors")
        
    def save_index(self, index_dir='database'):
        """Save FAISS index and metadata"""
        os.makedirs(index_dir, exist_ok=True)
        
        # Save FAISS index
        faiss.write_index(self.index, f'{index_dir}/faiss.index')
        
        # Save metadata
        with open(f'{index_dir}/chunks_metadata.json', 'w', encoding='utf-8') as f:
            json.dump(self.chunks, f, ensure_ascii=False, indent=2)
        
        # Save embeddings shape info
        info = {
            'dimension': self.embeddings.shape[1],
            'num_vectors': self.embeddings.shape[0],
            'model_name': self.model._modules['0'].auto_model.config._name_or_path
        }
        
        with open(f'{index_dir}/index_info.json', 'w') as f:
            json.dump(info, f, indent=2)
            
        print(f"Saved index and metadata to {index_dir}/")
    
    def search(self, query, top_k=5):
        """Search for similar chunks"""
        if not self.index:
            print("Index not built yet!")
            return []
        
        # Create query embedding
        query_embedding = self.model.encode([query], normalize_embeddings=True)
        query_embedding = np.array(query_embedding, dtype=np.float32)
        
        # Search
        scores, indices = self.index.search(query_embedding, top_k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx != -1:  # Valid result
                result = {
                    'text': self.chunks[idx]['text'],
                    'url': self.chunks[idx]['url'],
                    'title': self.chunks[idx]['title'],
                    'page_type': self.chunks[idx]['page_type'],
                    'score': float(score),
                    'product_info': self.chunks[idx].get('product_info', {})
                }
                results.append(result)
        
        return results

# Usage
if __name__ == "__main__":
    indexer = DataIndexer()
    
    # Process the scraped data
    indexer.process_scraped_data()
    
    # Create embeddings and build index
    indexer.create_embeddings()
    indexer.build_faiss_index()
    
    # Save everything
    indexer.save_index()
    
    # Test search
    results = indexer.search("What is the price of the blue shirt?", top_k=3)
    for result in results:
        print(f"Score: {result['score']:.3f}")
        print(f"Title: {result['title']}")
        print(f"Text: {result['text'][:200]}...")
        print(f"URL: {result['url']}\n")
