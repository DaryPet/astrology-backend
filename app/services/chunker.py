from typing import List, Dict


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, any]]:
    """
    Split text into chunks of specified word count with overlap.
    
    Args:
        text: Input text
        chunk_size: Number of words per chunk (default: 500)
        overlap: Number of overlapping words between chunks (default: 50)
    
    Returns:
        List of dicts: [{"text": "...", "word_count": N}, ...]
    """
    words = text.split()
    
    if len(words) <= chunk_size:
        return [{"text": text, "word_count": len(words)}]
    
    step = chunk_size - overlap
    chunks = []
    
    for i in range(0, len(words), step):
        chunk_words = words[i:i + chunk_size]
        chunk_text_val = " ".join(chunk_words)
        chunks.append({
            "text": chunk_text_val,
            "word_count": len(chunk_words)
        })
        
        if i + chunk_size >= len(words):
            break
    
    return chunks