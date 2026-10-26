"""One bilingual catalog and filter contract for UI, tools and persistence."""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).resolve().parents[1]/'assets/music_styles.v1.json').read_text(encoding='utf-8'))


def genre_ids(values):
    if not isinstance(values, list) or len(values)>12:
        raise ValueError('風格請使用最多 12 項的 ID 清單。')
    known={s['id'] for s in catalog()['styles']}
    if any(not isinstance(v,str) or v not in known for v in values):
        raise ValueError('未知風格；請先查詢 styles。')
    return list(dict.fromkeys(values))


def filter_tracks(tracks, selected=(), match='any', query='', unclassified=False):
    if match not in ('any','all'):
        raise ValueError('genre_match 只能是 any 或 all。')
    selected=set(genre_ids(list(selected)))
    query=str(query).strip().casefold()
    styles={s['id']:s for s in catalog()['styles']}
    result=[]
    for track in tracks:
        actual=set(track.get('genre_ids',[]))
        if unclassified and actual:
            continue
        if selected and not (bool(actual & selected) if match=='any' else selected<=actual):
            continue
        haystack=' '.join([track.get('title',''),track.get('style_notes',''),*track.get('tags',[]),
                          *[' '.join([styles[g]['zh'],styles[g]['en'],*styles[g].get('aliases',[])])
                            for g in actual if g in styles]])
        if query and query not in haystack.casefold():
            continue
        result.append(track)
    return result
