# import os
# import io
# from typing import List, Dict
# from supabase import create_client
# from app.core.config import settings
# from app.services.book_parser import parse_file
# from app.services.chunker import chunk_text

# supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

# _model = None


# def get_embedding_model():
#     global _model
#     if _model is None:
#         from sentence_transformers import SentenceTransformer
#         _model = SentenceTransformer("all-MiniLM-L6-v2")
#     return _model


# def generate_embeddings(texts: List[str]) -> List[List[float]]:
#     model = get_embedding_model()
#     embeddings = model.encode(texts)
#     return embeddings.tolist()


# def download_from_storage(filename: str) -> io.BytesIO:
#     data = supabase.storage.from_("AstroBooks").download(filename)
#     return io.BytesIO(data)


# async def process_book_async(db, filename: str) -> Dict:
#     """Обработать книгу: скачать из Supabase -> парсить PDF -> нарезать на чанки -> сохранить в БД"""
#     source = os.path.splitext(filename)[1].lower()
    
#     # Скачиваем из Supabase Storage
#     file_data = download_from_storage(filename)
    
#     # Сохраняем во временный файл
#     temp_path = f"/tmp/{filename}"
#     with open(temp_path, "wb") as f:
#         f.write(file_data.getvalue())
    
#     # Парсим PDF
#     parsed = parse_file(temp_path)
#     text = parsed["text"]  # Извлекаем текст из словаря
#     os.unlink(temp_path)
    
#     chunks = chunk_text(text, chunk_size=500, overlap=50)
#     chunk_texts = [c["text"] for c in chunks]
    
#     embeddings = generate_embeddings(chunk_texts)
    
#     from app.models.models import Book, BookChunk
#     from datetime import datetime
    
#     book = Book(
#         title=os.path.basename(filename).rsplit(".", 1)[0],
#         content=text[:500],
#         format=parsed["format"],
#         language=parsed["language"],
#         created_at=datetime.utcnow()
#     )
#     db.add(book)
#     await db.flush()
    
#     for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
#         book_chunk = BookChunk(
#             book_id=book.id,
#             chunk_index=idx,
#             text=chunk["text"],
#             word_count=chunk["word_count"],
#             embedding=emb
#         )
#         db.add(book_chunk)
    
#     await db.commit()
#     await db.refresh(book)
    
#     return {
#         "book_id": book.id,
#         "filename": filename,
#         "chunks_count": len(chunks)
#     }

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
    # Скачиваем из Supabase Storage
    file_data = download_from_storage(filename)

    # Сохраняем во временный файл
    temp_path = f"/tmp/{filename}"
    with open(temp_path, "wb") as f:
        f.write(file_data.getvalue())

    # Парсим
    parsed = parse_file(temp_path)
    print(f"ДЛИНА ТЕКСТА: {len(parsed['text'])}")
    text = parsed["text"]
    os.unlink(temp_path)

    # Нарезаем на куски
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    chunk_texts = [c["text"] for c in chunks]
    embeddings = generate_embeddings(chunk_texts)

    # Сохраняем книгу в Supabase
    book_result = supabase.table("books").insert({
        "title": os.path.basename(filename).rsplit(".", 1)[0],
        "content": text[:500],
        "format": parsed["format"],
        "language": parsed["language"]
    }).execute()

    book_id = book_result.data[0]["id"]

    # Сохраняем куски
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