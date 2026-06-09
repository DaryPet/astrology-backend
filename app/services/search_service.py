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
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


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
    chart_data: Optional[Dict[str, Any]] = None,
    house: Optional[int] = None,
    book_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Поиск чанков - используем гибридный поиск (BM25 + Vector)
    """
    return await search_chunks_hybrid(query, top_k=top_k, book_id=book_id)


async def search_chunks_hybrid(
    query: str,
    top_k: int = 20,
    book_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Гибридный поиск: BM25 + Vector через Supabase RPC"""
    from app.services.supabase_async import run_sync_in_thread
    
    supabase = get_supabase()
    if not supabase:
        return []
    
    # Генерируем эмбеддинг для запроса
    query_embedding = generate_embedding(query)
    
    try:
        # Оборачиваем синхронный вызов в async executor чтобы не блокировать event loop
        rpc_call = supabase.rpc("hybrid_search", {
            "query_embedding": query_embedding,
            "query_text": query,
            "match_count": top_k,
            "book_id_filter": book_id
        })
        response = await run_sync_in_thread(rpc_call.execute)
        
        print(f"[HYBRID SEARCH] Query: {query}")
        if book_id:
            print(f"[HYBRID SEARCH] Book ID filter: {book_id}")
        print(f"[HYBRID SEARCH] Found: {len(response.data) if response.data else 0} chunks")
        return response.data if response.data else []
    except Exception as e:
        print(f"[HYBRID SEARCH] Error: {e}")
        return []


# async def search_chunks_by_query(
#     query: str,
#     top_k: int = 20,
#     chart_data: Optional[Dict[str, Any]] = None,
#     house: Optional[int] = None
# ) -> List[Dict[str, Any]]:
#     """
#     Поиск чанков по запросу - с приоритетом текстового поиска
    
#     1. СНАЧАЛА текстовый поиск (ILIKE)
#     2. ПОТОМ эмбеддинг поиск как fallback
#     """
#     supabase = get_supabase()
#     if not supabase:
#         return []

#     query_lower = query.lower()
    
#     # Извлекаем ключевые слова из запроса (ТОЛЬКО АНГЛИЙСКИЙ)
#     planet = None
#     house_num = None
#     sign = None
    
#     # Ищем планету (ТОЛЬКО английские названия)
#     english_planets = PLANET_NAMES['en']
#     for name in english_planets:
#         if name in query_lower:
#             planet = name
#             break
    
#     # Ищем номер дома (ищем английские слова first, second... и цифры)
#     house_words = {
#         1: ['first', '1st', '1', 'house 1', '1st house', 'i', 'i house', 'first house'],
#         2: ['second', '2nd', '2', 'house 2', '2nd house', 'ii', 'ii house', 'second house'],
#         3: ['third', '3rd', '3', 'house 3', '3rd house', 'iii', 'iii house', 'third house'],
#         4: ['fourth', '4th', '4', 'house 4', '4th house', 'iv', 'iv house', 'fourth house'],
#         5: ['fifth', '5th', '5', 'house 5', '5th house', 'v', 'v house', 'fifth house'],
#         6: ['sixth', '6th', '6', 'house 6', '6th house', 'vi', 'vi house', 'sixth house'],
#         7: ['seventh', '7th', '7', 'house 7', '7th house', 'in the seventh', 'vii', 'vii house', 'seventh house'],
#         8: ['eighth', '8th', '8', 'house 8', '8th house', 'viii', 'viii house', 'eighth house'],
#         9: ['ninth', '9th', '9', 'house 9', '9th house', 'ix', 'ix house', 'ninth house'],
#         10: ['tenth', '10th', '10', 'house 10', '10th house', 'x', 'x house', 'tenth house'],
#         11: ['eleventh', '11th', '11', 'house 11', '11th house', 'xi', 'xi house', 'eleventh house'],
#         12: ['twelfth', '12th', '12', 'house 12', '12th house', 'xii', 'xii house', 'twelfth house'],
#     }
    
#     for house_key, patterns in house_words.items():
#         for pattern in patterns:
#             if pattern in query_lower:
#                 house_num = house_key
#                 break
#         if house_num:
#             break
    
#     # Ищем знак (ТОЛЬКО английские названия)
#     english_signs = ZODIAC_SIGNS['en']
#     for name in english_signs:
#         if name in query_lower:
#             sign = name
#             break
    
#     print(f"[SEARCH] Query: {query}, planet: {planet}, house: {house_num}, sign: {sign}")
    
#     # Шаг 1: Текстовый поиск (ПРИОРИТЕТ)
#     chunks = await search_chunks_text(planet, house_num, sign, top_k=top_k)
#     print(f"[SEARCH] Text search found: {len(chunks)} chunks")
    
#     # Шаг 2: Если пусто - пробуем эмбеддинги
#     if not chunks:
#         print("[SEARCH] Trying embedding search...")
#         chunks = await search_chunks_embedding(query, top_k=top_k)
#         print(f"[SEARCH] Embedding search found: {len(chunks)} chunks")
    
#     return chunks


# async def search_chunks_text(
#     planet: Optional[str] = None,
#     house: Optional[int] = None,
#     sign: Optional[str] = None,
#     top_k: int = 50
# ) -> List[Dict[str, Any]]:
#     """Текстовый поиск через ILIKE в БД (СТАРЫЙ КОД - не используется)"""
#     supabase = get_supabase()
#     if not supabase:
#         return []
    
#     conditions = []
    
#     if planet:
#         # Ищем ТОЛЬКО эту планету (pluto, saturn, etc.)
#         conditions.append(f"text ILIKE '%{planet}%'")
    
#     if house:
#         house_words = {
#             1: ['first', '1st', 'i'],
#             2: ['second', '2nd', 'ii'],
#             3: ['third', '3rd', 'iii'],
#             4: ['fourth', '4th', 'iv'],
#             5: ['fifth', '5th', 'v'],
#             6: ['sixth', '6th', 'vi'],
#             7: ['seventh', '7th', 'vii'],
#             8: ['eighth', '8th', 'viii'],
#             9: ['ninth', '9th', 'ix'],
#             10: ['tenth', '10th', 'x'],
#             11: ['eleventh', '11th', 'xi'],
#             12: ['twelfth', '12th', 'xii'],
#         }
#         patterns = house_words.get(house, [str(house)])
#         house_conditions = [f"text ILIKE '%{p}%'" for p in patterns]
#         conditions.append(f"({' OR '.join(house_conditions)})")
    
#     if sign:
#         # Ищем ТОЛЬКО этот знак (libra, scorpio, etc.)
#         conditions.append(f"text ILIKE '%{sign}%'")
    
#     if not conditions:
#         return []
    
#     where_clause = " AND ".join(conditions)
#     sql = f"""
#         SELECT id, book_id, text, chunk_index, word_count
#         FROM book_chunks
#         WHERE {where_clause}
#         LIMIT {top_k}
#     """
    
#     try:
#         response = supabase.rpc("execute_sql", {"query": sql}).execute()
#         print(f"[TEXT SEARCH] SQL: {sql[:100]}...")
#         print(f"[TEXT SEARCH] Found: {len(response.data) if response.data else 0} chunks")
#         return response.data if response.data else []
#     except Exception as e:
#         # Fallback через supabase client
#         try:
#             query_builder = supabase.table("book_chunks").select("id, book_id, text, chunk_index, word_count")
            
#             if planet:
#                 query_builder = query_builder.ilike("text", f"%{planet}%")
            
#             if house:
#                 house_words = {
#                     7: ['seventh', '7th', 'vii'],
#                     1: ['first', '1st', 'i'],
#                     2: ['second', '2nd', 'ii'],
#                     3: ['third', '3rd', 'iii'],
#                     4: ['fourth', '4th', 'iv'],
#                     5: ['fifth', '5th', 'v'],
#                     6: ['sixth', '6th', 'vi'],
#                     8: ['eighth', '8th', 'viii'],
#                     9: ['ninth', '9th', 'ix'],
#                     10: ['tenth', '10th', 'x'],
#                     11: ['eleventh', '11th', 'xi'],
#                     12: ['twelfth', '12th', 'xii'],
#                 }
#                 patterns = house_words.get(house, [str(house)])
#                 for w in patterns:
#                     query_builder = query_builder.or_(f"text.ilike.%{w}%")
            
#             if sign:
#                 query_builder = query_builder.ilike("text", f"%{sign}%")
            
#             response = query_builder.limit(top_k).execute()
#             print(f"[TEXT SEARCH] Fallback found: {len(response.data) if response.data else 0} chunks")
#             return response.data if response.data else []
#         except Exception as e2:
#             print(f"[TEXT SEARCH] Fallback error: {e2}")
#             return []


# async def search_chunks_text(
#     planet: Optional[str] = None,
#     house: Optional[int] = None,
#     sign: Optional[str] = None,
#     top_k: int = 50
# ) -> List[Dict[str, Any]]:
#     """Текстовый поиск чанков по ключевым словам (ILIKE)"""
#     supabase = get_supabase()
#     if not supabase:
#         return []
#     
#     # Собираем все чанки (ограничим для производительности)
#     try:
#         response = supabase.table("book_chunks").select(
#             "id, book_id, text, chunk_index, word_count"
#         ).limit(1000).execute()
#         
#         if not response.data:
#             return []
#         
#         matching_chunks = []
#         
#         for chunk in response.data:
#             text_lower = chunk.get('text', '').lower()
#             
#             # Проверяем совпадение по планете (ТОЛЬКО АНГЛИЙСКИЙ)
#             if planet:
#                 planet_found = False
#                 english_planets = PLANET_NAMES['en']  # ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune', 'pluto', ...]
#                 for name in english_planets:
#                     if name in text_lower:
#                         planet_found = True
#                         break
#                 if not planet_found:
#                     continue
#             
#             # Проверяем совпадение по дому (ТОЛЬКО АНГЛИЙСКИЙ)
#             if house:
#                 house_found = False
#                 # Маппинг чисел на слова (для английского), включая римские цифры
#                 house_words = {
#                     1: ['first', '1st', '1', 'i', ' house i', 'first house'],
#                     2: ['second', '2nd', '2', 'ii', ' house ii', 'second house'],
#                     3: ['third', '3rd', '3', 'iii', ' house iii', 'third house'],
#                     4: ['fourth', '4th', '4', 'iv', ' house iv', 'fourth house'],
#                     5: ['fifth', '5th', '5', 'v', ' house v', 'fifth house'],
#                     6: ['sixth', '6th', '6', 'vi', ' house vi', 'sixth house'],
#                     7: ['seventh', '7th', '7', 'vii', ' house vii', 'seventh house'],
#                     8: ['eighth', '8th', '8', 'viii', ' house viii', 'eighth house'],
#                     9: ['ninth', '9th', '9', 'ix', ' house ix', 'ninth house'],
#                     10: ['tenth', '10th', '10', 'x', ' house x', 'tenth house'],
#                     11: ['eleventh', '11th', '11', 'xi', ' house xi', 'eleventh house'],
#                     12: ['twelfth', '12th', '12', 'xii', ' house xii', 'twelfth house'],
#                 }
#                 house_patterns = house_words.get(house, [])
#                 
#                 for pattern in house_patterns:
#                     if pattern in text_lower:
#                         house_found = True
#                         break
#                 if not house_found:
#                     continue
#             
#             # Проверяем совпадение по знаку (ТОЛЬКО АНГЛИЙСКИЙ)
#             if sign:
#                 sign_found = False
#                 english_signs = ZODIAC_SIGNS['en']  # ['aries', 'taurus', 'gemini', 'cancer', 'leo', 'virgo', 'libra', ...]
#                 for name in english_signs:
#                     if name in text_lower:
#                         sign_found = True
#                         break
#                 if not sign_found:
#                     continue
#             
#             matching_chunks.append({
#                 'id': chunk['id'],
#                 'book_id': chunk['book_id'],
#                 'text': chunk.get('text'),
#                 'chunk_index': chunk.get('chunk_index'),
#                 'word_count': chunk.get('word_count'),
#                 'similarity_score': 1.0,
#             })
#         
#         print(f"[TEXT SEARCH] Total matching: {len(matching_chunks)}")
#         return matching_chunks[:top_k]
#         
#     except Exception as e:
#         print(f"Text search error: {e}")
#         return []


# async def search_chunks_embedding(
#     query: str,
#     top_k: int = 20
# ) -> List[Dict[str, Any]]:
#     """Эмбеддинг поиск через Supabase RPC (СТАРЫЙ КОД - не используется)"""
#     supabase = get_supabase()
#     if not supabase:
#         return []

#     query_embedding = generate_embedding(query)

#     try:
#         response = supabase.rpc("match_book_chunks", {
#             "query_embedding": query_embedding,
#             "match_count": top_k
#         }).execute()

#         if not response.data:
#             return []

#         return response.data

#     except Exception as e:
#         print(f"Embedding search error: {e}")
#         return []

# async def search_chunks_by_query(
#     query: str,
#     top_k: int = 20,
#     chart_data: Optional[Dict[str, Any]] = None,
#     house: Optional[int] = None
# ) -> List[Dict[str, Any]]:
#     supabase = get_supabase()
#     if not supabase:
#         return []

#     query_embedding = generate_embedding(query)

#     try:
#         response = supabase.rpc("match_book_chunks", {
#             "query_embedding": query_embedding,
#             "match_count": top_k
#         }).execute()

#         if not response.data:
#             return []

#         return response.data

#     except Exception as e:
#         print(f"Search error: {e}")
#         return []

async def search_chunks_simple(
    query: str,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """Простой текстовый поиск без эмбеддингов"""
    from app.services.supabase_async import run_sync_in_thread
    
    supabase = get_supabase()
    if not supabase:
        return []
    
    query_lower = query.lower()
    
    try:
        # Оборачиваем синхронный вызов в async executor чтобы не блокировать event loop
        table_call = supabase.table("book_chunks").select("id, book_id, text, chunk_index, word_count")
        response = await run_sync_in_thread(table_call.execute)
        
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