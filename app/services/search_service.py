from typing import List, Dict, Any, Optional
import numpy as np
from supabase import create_client
from app.core.config import settings
from sentence_transformers import SentenceTransformer

PLANET_NAMES = {
    'ru': ['солнце', 'луна', 'меркурий', 'венера', 'марс', 'юпитер', 'сатурн', 'уран', 'нептун', 'плутон', 'раху', 'кету', 'лилит', 'хирон'],
    'en': ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune', 'pluto', 'north node', 'south node', 'lilith', 'chiron'],
    'es': ['sol', 'luna', 'mercurio', 'venus', 'marte', 'júpiter', 'saturno', 'urano', 'neptuno', 'plutón'],
    'de': ['sonne', 'mond', 'merkur', 'venus', 'mars', 'jupiter', 'saturn', 'uran', 'neptun', 'pluto'],
    'fr': ['soleil', 'lune', 'mercure', 'vénus', 'mars', 'jupiter', 'saturne', 'uranus', 'neptune', 'pluton'],
}

ZODIAC_SIGNS = {
    'ru': ['овен', 'телец', 'близнецы', 'рак', 'лев', 'дева', 'весы', 'скорпион', 'стрелец', 'козерог', 'водолей', 'рыбы'],
    'en': ['aries', 'taurus', 'gemini', 'cancer', 'leo', 'virgo', 'libra', 'scorpio', 'sagittarius', 'capricorn', 'aquarius', 'pisces'],
}

ASPECTS_RU = {
    'ru': ['соединение', 'секстиль', 'квадрат', 'тригон', 'оппозиция'],
    'en': ['conjunction', 'sextile', 'square', 'trine', 'opposition'],
}

HOUSE_NUMBERS = {
    'ru': ['первый', 'второй', 'третий', 'четвёртый', 'пятый', 'шестой', 'седьмой', 'восьмой', 'девятый', 'десятый', 'одиннадцатый', 'двенадцатый'],
    'en': ['first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth'],
}


_supabase = None
_embedding_model = None


def get_supabase():
    global _supabase
    if _supabase is None and settings.SUPABASE_URL and settings.SUPABASE_KEY:
        _supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _supabase


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _embedding_model


def detect_query_language(query: str) -> str:
    """Определить язык запроса по символам"""
    if any('\u0400' <= c <= '\u04FF' for c in query):
        return 'ru'
    elif any('\u00C0' <= c <= '\u024F' for c in query):
        return 'en'
    return 'en'


def parse_astrology_query(query: str) -> Dict[str, Any]:
    """Извлечь астрологические сущности из запроса"""
    query_lower = query.lower()
    language = detect_query_language(query)
    
    planets = []
    houses = []
    signs = []
    aspects = []
    
    for lang, names in PLANET_NAMES.items():
        for planet in names:
            if planet in query_lower:
                planets.append(planet)
                break
    
    for i in range(1, 13):
        if str(i) in query_lower:
            houses.append(i)
        for lang, names in HOUSE_NUMBERS.items():
            if i <= len(names) and names[i-1] in query_lower:
                houses.append(i)
                break
    
    for lang, names in ZODIAC_SIGNS.items():
        for sign in names:
            if sign in query_lower:
                signs.append(sign)
                break
    
    for lang, names in ASPECTS_RU.items():
        for aspect in names:
            if aspect in query_lower:
                aspects.append(aspect)
                break
    
    return {
        'language': language,
        'planets': planets,
        'houses': houses,
        'signs': signs,
        'aspects': aspects,
    }


def generate_embedding(text: str) -> List[float]:
    """Сгенерировать эмбеддинг для текста"""
    model = get_embedding_model()
    embedding = model.encode(text)
    return embedding.tolist()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Вычислить косинусное сходство"""
    a = np.array(a)
    b = np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# async def search_chunks_by_query(
#     query: str,
#     top_k: int = 5,
#     chart_data: Optional[Dict[str, Any]] = None
# ) -> List[Dict[str, Any]]:
#     """Поиск релевантных чанков по запросу"""
#     supabase = get_supabase()
#     if not supabase:
#         return []
    
#     parsed_query = parse_astrology_query(query)
#     query_lang = parsed_query['language']
    
#     query_embedding = generate_embedding(query)
    
#     try:
#         response = supabase.table("book_chunks").select("id, book_id, text, chunk_index, word_count, embedding").execute()
        
#         if not response.data:
#             return []
        
#         chunks_with_scores = []
#         for chunk in response.data:
#             if chunk.get('embedding'):
#                 sim = cosine_similarity(query_embedding, chunk['embedding'])
#                 chunk_text = chunk.get('text', '')
#                 chunk_lower = chunk_text.lower()
                
#                 boost = 0.0
#                 for planet in parsed_query['planets']:
#                     if planet in chunk_lower:
#                         boost += 0.1
#                 for house in parsed_query['houses']:
#                     if f"дом {house}" in chunk_lower or f"house {house}" in chunk_lower or f"{house} дом" in chunk_lower:
#                         boost += 0.1
                
#                 final_score = sim + boost
#                 chunks_with_scores.append({
#                     'id': chunk['id'],
#                     'book_id': chunk['book_id'],
#                     'text': chunk_text,
#                     'chunk_index': chunk.get('chunk_index'),
#                     'word_count': chunk.get('word_count'),
#                     'similarity_score': final_score,
#                 })
        
#         chunks_with_scores.sort(key=lambda x: x['similarity_score'], reverse=True)
#         return chunks_with_scores[:top_k]
        
#     except Exception as e:
#         print(f"Search error: {e}")
#         return []


async def search_chunks_by_query(
    query: str,
    top_k: int = 20,
    chart_data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    supabase = get_supabase()
    if not supabase:
        return []

    query_embedding = generate_embedding(query)

    try:
        response = supabase.rpc("match_book_chunks", {
            "query_embedding": query_embedding,
            "match_count": top_k
        }).execute()

        if not response.data:
            return []

        return response.data

    except Exception as e:
        print(f"Search error: {e}")
        return []

async def search_chunks_simple(
    query: str,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """Простой текстовый поиск без эмбеддингов"""
    supabase = get_supabase()
    if not supabase:
        return []
    
    query_lower = query.lower()
    
    try:
        response = supabase.table("book_chunks").select("id, book_id, text, chunk_index, word_count").execute()
        
        if not response.data:
            return []
        
        matching_chunks = []
        for chunk in response.data:
            chunk_text = chunk.get('text', '').lower()
            if query_lower in chunk_text:
                matching_chunks.append({
                    'id': chunk['id'],
                    'book_id': chunk['book_id'],
                    'text': chunk.get('text'),
                    'chunk_index': chunk.get('chunk_index'),
                    'word_count': chunk.get('word_count'),
                    'similarity_score': 1.0,
                })
        
        return matching_chunks[:top_k]
        
    except Exception as e:
        print(f"Simple search error: {e}")
        return []


def build_search_context(
    chart_data: Optional[Dict[str, Any]],
    chunks: List[Dict[str, Any]]
) -> str:
    """Построить контекст для LLM из данных карты и чанков"""
    context_parts = []
    
    if chart_data:
        context_parts.append("=== НАТАЛЬНАЯ КАРТА ===")
        
        planets = chart_data.get('planets', {})
        for planet_name, planet_data in planets.items():
            sign = planet_data.get('sign', 'Unknown')
            degree = planet_data.get('degree', 0)
            house = planet_data.get('house', '?')
            context_parts.append(f"{planet_name}: {sign} {degree}° (дом {house})")
        
        houses = chart_data.get('houses', {})
        for house_num in range(1, 13):
            if house_num in houses:
                house_data = houses[house_num]
                cusp = house_data.get('cusp_longitude', 0)
                sign = house_data.get('sign', 'Unknown')
                context_parts.append(f"Дом {house_num}: {sign} {cusp:.1f}°")
    
    if chunks:
        context_parts.append("\n=== НАЙДЕННЫЕ ФРАГМЕНТЫ ИЗ КНИГ ===")
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get('text', '')[:500]
            context_parts.append(f"\n[Фрагмент {i}]:\n{text}...")
    
    return "\n".join(context_parts)