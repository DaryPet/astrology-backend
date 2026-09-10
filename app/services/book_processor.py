import os
import io
from typing import List, Dict
from supabase import create_client
from app.core.config import settings
from app.services.book_parser import parse_file
from app.services.chunker import chunk_text

supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

_model = None

def get_embedding_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _model

def generate_embeddings(texts: List[str]) -> List[List[float]]:
    model = get_embedding_model()
    embeddings = model.encode(texts)
    return embeddings.tolist()

def download_from_storage(filename: str) -> io.BytesIO:
    data = supabase.storage.from_("AstroBooks").download(filename)
    return io.BytesIO(data)

async def process_book_async(filename: str) -> Dict:
    # Download from Supabase Storage
    file_data = download_from_storage(filename)

    # Save to a temp file
    temp_path = f"/tmp/{filename}"
    with open(temp_path, "wb") as f:
        f.write(file_data.getvalue())

    # Parse
    parsed = parse_file(temp_path)
    print(f"Text length: {len(parsed['text'])}")
    text = parsed["text"]
    os.unlink(temp_path)

    # Chunk it
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    chunk_texts = [c["text"] for c in chunks]
    embeddings = generate_embeddings(chunk_texts)

    # Save the book to Supabase
    book_result = supabase.table("books").insert({
        "title": os.path.basename(filename).rsplit(".", 1)[0],
        "content": text,
        "format": parsed["format"],
        "language": parsed["language"]
    }).execute()

    book_id = book_result.data[0]["id"]

    # Save the chunks
    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        supabase.table("book_chunks").insert({
            "book_id": book_id,
            "chunk_index": idx,
            "text": chunk["text"],
            "word_count": chunk["word_count"],
            "embedding": emb
        }).execute()

    return {
        "book_id": book_id,
        "filename": filename,
        "chunks_count": len(chunks)
    }