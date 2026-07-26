"""Event chart regression: the verdict on fixed matches must not change silently.

Doesn't measure accuracy — that's what eval_event.py is for. Its only job:
if a weight or logic change shifted match_type/diff, the test fails and shows
before/after.

Snapshot: tests/data/regression_snapshot.json. Regenerate after a deliberate
change to the method:

    ./venv/bin/python tests/test_event_regression.py --update
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.eval_event import (  # noqa: E402
    MATCHES_FILE, _load_geocode_cache, _save_geocode_cache, build_judgement,
)

SNAPSHOT_FILE = Path(__file__).parent / 'data' / 'regression_snapshot.json'


def _current() -> Dict[str, Dict[str, Any]]:
    from app.services.daily_forecast_service import _card_match_type, _card_verdict

    matches = json.loads(MATCHES_FILE.read_text(encoding='utf-8'))
    cache = _load_geocode_cache()
    out: Dict[str, Dict[str, Any]] = {}
    try:
        for match in matches:
            judgement = build_judgement(match, cache)
            card = (judgement or {}).get('significator_card')
            if not card:
                out[str(match['id'])] = {'match_type': 'ERROR', 'diff': None}
                continue
            _decisive, _winner, diff = _card_verdict(card)
            out[str(match['id'])] = {
                'match_type': _card_match_type(card),
                'diff': round(diff, 2),
            }
    finally:
        _save_geocode_cache(cache)
    return out


@pytest.mark.skipif(not SNAPSHOT_FILE.exists(),
                    reason='no snapshot — create one with --update')
def test_event_verdicts_unchanged():
    expected = json.loads(SNAPSHOT_FILE.read_text(encoding='utf-8'))
    actual = _current()

    drifted = {
        mid: (expected.get(mid), actual.get(mid))
        for mid in sorted(set(expected) | set(actual))
        if expected.get(mid) != actual.get(mid)
    }
    assert not drifted, 'verdict changed:\n' + '\n'.join(
        f"  match {mid}: was {was} -> now {now}" for mid, (was, now) in drifted.items()
    )


if __name__ == '__main__':
    if '--update' in sys.argv:
        SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_FILE.write_text(
            json.dumps(_current(), ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'snapshot updated: {SNAPSHOT_FILE}')
    else:
        print(__doc__)
