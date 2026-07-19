"""Прогон карт событий по датасету матчей + отчёты для evals.

НЕ pytest: это измеритель, а не «прошёл/упал». Запуск:

    ./venv/bin/python tests/eval_event.py
    ./venv/bin/python tests/eval_event.py --ablate dignity

Повторяет продакшен-путь event-эндпоинта (app/api/endpoints.py:2055-2108)
шаг в шаг, но без async/LLM/RAG/кэша: скоринг живёт в judge_event_chart,
она синхронная и чистая. См. plans/event-chart-tests-and-evals.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = Path(__file__).parent / 'data'
REPORT_DIR = Path(__file__).parent / 'reports'
MATCHES_FILE = DATA_DIR / 'matches.json'
# Геокодер ходит в сеть (Nominatim, ~1 запрос/сек). Кэшируем на диск: без
# этого каждый прогон — а для абляции их нужно много — заново долбит сеть.
GEOCODE_CACHE = DATA_DIR / 'geocode_cache.json'

OUTCOMES = ('favourite', 'underdog', 'draw')
# Какой реальный исход считается угаданным для каждого match_type.
MATCH_TYPE_TO_OUTCOME = {
    'comfortable_win': 'favourite',
    'advantage': 'favourite',
    'draw_likely': 'draw',
    'underdog_edge': 'underdog',
    'underdog_win_likely': 'underdog',
}


def _load_geocode_cache() -> Dict[str, List[float]]:
    if GEOCODE_CACHE.exists():
        return json.loads(GEOCODE_CACHE.read_text(encoding='utf-8'))
    return {}


def _save_geocode_cache(cache: Dict[str, List[float]]) -> None:
    GEOCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')


def resolve_coordinates(place: str, cache: Dict[str, List[float]]) -> Tuple[float, float]:
    """Тот же геокодер, что в продакшене (get_coordinates в endpoints.py),
    поверх дискового кэша по строке места."""
    key = place.lower().strip()
    if key in cache:
        lat, lon = cache[key]
        return lat, lon
    from app.api.endpoints import get_coordinates  # ленивый импорт: тянет FastAPI
    lat, lon = get_coordinates(place)
    cache[key] = [lat, lon]
    return lat, lon


def build_judgement(match: Dict[str, Any], cache: Dict[str, List[float]],
                     language: str = 'ru') -> Optional[Dict[str, Any]]:
    """Карта события на момент+место матча и суждение по ней.

    Повторяет endpoints.py:2055-2108. Натальной карты в методе нет:
    calculate_transits — общая утилита, момент матча передаётся ей и как
    birth_date, и как target_date, чтобы получить карту на один момент.
    """
    from app.utils.astrology_v2 import calculate_transits
    from app.services.daily_forecast_service import judge_event_chart

    dt = datetime.fromisoformat(match['datetime'])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(match['timezone']))

    lat, lon = resolve_coordinates(match['place'], cache)

    transits = calculate_transits(
        birth_date=dt,
        birth_place=match['place'],
        target_date=dt,
        lat=lat,
        lon=lon,
        timezone_str=match['timezone'],
        house_system='Placidus',       # карта события всегда по Плацидусу
        transit_lat=lat,
        transit_lon=lon,
        exact_time=True,               # обязателен: иначе 00:00 уедет на полдень
    )
    if not transits.get('transit_houses'):
        return None

    return judge_event_chart(
        transits['transit_houses'],
        transits.get('transit_planets', {}) or {},
        language=language,
    )


def apply_ablation(card: Dict[str, Any], kind: str) -> None:
    """Обнулить вес всех показаний данного вида — «а что если убрать это
    свидетельство». Мутирует карточку на месте; вердикт после этого
    пересчитывается заново."""
    for side_key in ('favourite', 'underdog'):
        side = card.get(side_key)
        for s in (side or {}).get('showings', []) or []:
            if s.get('kind') == kind:
                s['weight'] = 0.0
    for s in card.get('chart_wide') or []:
        if s.get('kind') == kind:
            s['weight'] = 0.0


def evaluate(matches: List[Dict[str, Any]], ablate: Optional[str] = None
             ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """-> (строки по матчам, строки по свидетельствам)."""
    from app.services.daily_forecast_service import _card_match_type, _card_verdict

    cache = _load_geocode_cache()
    results: List[Dict[str, Any]] = []
    testimony_rows: List[Dict[str, Any]] = []

    try:
        for match in matches:
            judgement = build_judgement(match, cache)
            card = (judgement or {}).get('significator_card')
            if not card:
                results.append({
                    'id': match['id'], 'place': match['place'],
                    'datetime': match['datetime'], 'match_type': 'ERROR',
                    'diff': '', 'decisive': '', 'outcome': match.get('outcome', ''),
                    'hit': '',
                })
                continue

            if ablate:
                apply_ablation(card, ablate)

            decisive, _winner, diff = _card_verdict(card)
            match_type = _card_match_type(card)
            outcome = match.get('outcome')
            hit = ''
            if outcome in OUTCOMES:
                hit = int(MATCH_TYPE_TO_OUTCOME.get(match_type) == outcome)

            results.append({
                'id': match['id'], 'place': match['place'],
                'datetime': match['datetime'], 'match_type': match_type,
                'diff': round(diff, 2), 'decisive': decisive,
                'outcome': outcome or '', 'hit': hit,
            })

            for side_key in ('favourite', 'underdog'):
                side = card.get(side_key)
                if not side:
                    continue
                for s in side.get('showings', []) or []:
                    testimony_rows.append({
                        'match_id': match['id'], 'place': match['place'],
                        'side': side_key, 'kind': s.get('kind', ''),
                        'label': s.get('label_ru', ''), 'effect': s.get('effect') or '',
                        'weight': s.get('weight', 0.0), 'source': s.get('source', ''),
                        'match_type': match_type, 'outcome': outcome or '', 'hit': hit,
                    })
            for s in card.get('chart_wide') or []:
                testimony_rows.append({
                    'match_id': match['id'], 'place': match['place'],
                    'side': 'chart_wide', 'kind': s.get('kind', ''),
                    'label': s.get('label_ru', ''), 'effect': s.get('effect') or '',
                    'weight': s.get('weight', 0.0), 'source': s.get('source', ''),
                    'match_type': match_type, 'outcome': outcome or '', 'hit': hit,
                })
    finally:
        _save_geocode_cache(cache)

    return results, testimony_rows


def _write_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def build_summary(results: List[Dict[str, Any]], testimony_rows: List[Dict[str, Any]]) -> str:
    scored = [r for r in results if r['hit'] != '']
    lines = ['# Сводка прогона', '']
    lines.append(f"Матчей в датасете: {len(results)}")
    lines.append(f"С известным исходом: {len(scored)}")

    if not scored:
        lines += ['', 'Реальных исходов нет — считается только распределение прогнозов.', '']
        dist = defaultdict(int)
        for r in results:
            dist[r['match_type']] += 1
        lines.append('| match_type | матчей |')
        lines.append('|---|---|')
        for mt, n in sorted(dist.items(), key=lambda kv: -kv[1]):
            lines.append(f'| {mt} | {n} |')
        return '\n'.join(lines) + '\n'

    hits = sum(r['hit'] for r in scored)
    # Baseline: «всегда фаворит». Без него процент метода не читается — если
    # метод не бьёт baseline, он не даёт ничего сверх ставки на фаворита.
    baseline = sum(1 for r in scored if r['outcome'] == 'favourite')
    lines += [
        '',
        f"**Точность метода: {hits}/{len(scored)} = {hits / len(scored):.1%}**",
        f"**Baseline «всегда фаворит»: {baseline}/{len(scored)} = {baseline / len(scored):.1%}**",
        '',
        '## По типу прогноза',
        '',
        '| match_type | матчей | попали | % |',
        '|---|---|---|---|',
    ]
    by_type: Dict[str, List[int]] = defaultdict(list)
    for r in scored:
        by_type[r['match_type']].append(r['hit'])
    for mt, hs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        lines.append(f'| {mt} | {len(hs)} | {sum(hs)} | {sum(hs) / len(hs):.0%} |')

    lines += ['', '## По свидетельству', '',
              '| вид | встретилось | попали | % |', '|---|---|---|---|']
    by_kind: Dict[str, List[int]] = defaultdict(list)
    for t in testimony_rows:
        if t['hit'] != '' and t['weight']:
            by_kind[t['kind']].append(t['hit'])
    for kind, hs in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        lines.append(f'| {kind} | {len(hs)} | {sum(hs)} | {sum(hs) / len(hs):.0%} |')

    lines += ['', '## По источнику', '',
              '| source | встретилось | попали | % |', '|---|---|---|---|']
    by_source: Dict[str, List[int]] = defaultdict(list)
    for t in testimony_rows:
        if t['hit'] != '' and t['weight']:
            by_source[t['source'] or '(нет)'].append(t['hit'])
    for src, hs in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        lines.append(f'| {src} | {len(hs)} | {sum(hs)} | {sum(hs) / len(hs):.0%} |')

    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='Прогон карт событий по датасету')
    parser.add_argument('--matches', default=str(MATCHES_FILE), help='JSON с матчами')
    parser.add_argument('--ablate', default=None,
                        help="обнулить вес показаний этого вида (напр. dignity, house_strength)")
    parser.add_argument('--out', default=str(REPORT_DIR), help='куда писать отчёты')
    args = parser.parse_args()

    matches_path = Path(args.matches)
    if not matches_path.exists():
        print(f"Нет файла с матчами: {matches_path}")
        return 1
    matches = json.loads(matches_path.read_text(encoding='utf-8'))
    if not matches:
        print(f"{matches_path} пуст — положи туда матчи.")
        return 1

    results, testimony_rows = evaluate(matches, ablate=args.ablate)

    out = Path(args.out)
    suffix = f'_ablate_{args.ablate}' if args.ablate else ''
    _write_csv(out / f'results{suffix}.csv', results,
               ['id', 'place', 'datetime', 'match_type', 'diff', 'decisive', 'outcome', 'hit'])
    _write_csv(out / f'testimonies{suffix}.csv', testimony_rows,
               ['match_id', 'place', 'side', 'kind', 'label', 'effect', 'weight',
                'source', 'match_type', 'outcome', 'hit'])
    summary = build_summary(results, testimony_rows)
    (out / f'summary{suffix}.md').write_text(summary, encoding='utf-8')

    print(summary)
    print(f"Отчёты: {out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
