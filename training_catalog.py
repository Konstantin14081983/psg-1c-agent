"""Source-backed course resolution. Suggestions never silently become enrollments."""
import json, re
from pathlib import Path
from difflib import SequenceMatcher
from functools import lru_cache

def norm(text):
    return re.sub(r'[^а-яa-z0-9]+',' ',str(text).lower().replace('ё','е')).strip()

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'data/training_catalog.json').read_text())

def result(record):
    warning=None
    if record['status']!='offered':warning='Программа не доступна для обучения: '+record['status']
    elif not record['hours']:warning='Часы не указаны в источнике — требуется уточнение'
    return dict(record,is_canonical=record['status']=='offered',warning=warning,hours_options=record['hours'],hours=record['hours'][0] if record['hours'] else None)

def unresolved(text, candidates=()):
    return dict(name=text or 'Программа не указана',is_canonical=False,hours=None,hours_options=[],status='review',warning='Программа или вариант не определены — требуется уточнение',candidates=[{'id':r['id'],'name':r['name'],'hours':r['hours'],'status':r['status']} for r in candidates])

def select_source(source,group=None):
    return [r for r in catalog()['programs'] if r['source']==source and (group is None or r.get('group')==group)]

def resolve(text):
    key=norm(text)
    key=re.sub(r'^охрана труда ([абв])$', r'от \1', key)
    records=catalog()['programs']
    if key in ('ежегодная проверка знаний', 'переаттестация'):
        return dict(id='policy-annual', name='Ежегодная проверка знаний', category='permit', status='offered', source='Согласованные правила центра, 23.09.2026', hours=16, hours_options=[16], is_canonical=True, warning='Уточните предмет проверки знаний и предыдущее удостоверение')
    exact=[r for r in records if norm(r['name'])==key or r['id']==text]
    if len(exact)==1:return result(exact[0])
    if len(exact)>1:
        # Same spelling with conflicting durations remains a choice.
        if len({(tuple(r['hours']),r['status'],r['category']) for r in exact})==1:return result(exact[0])
        return unresolved(text,exact)
    aliases={'а':4,'от а':4,'программа а':4,'б':5,'от б':5,'программа б':5,'в':6,'от в':6,'программа в':6,'сиз':7,'пп':8,'первая помощь':8}
    if key in aliases:return result(select_source(f'Охрана труда!B{aliases[key]}')[0])
    # Group must be explicit. Do not confuse the 8h OT-V work types with 24h group training.
    if re.fullmatch(r'(?:высота|высоте|озп)\s*[123]\s*(?:группа|группы|гр)?',key):
        g=int(re.search('[123]',key)[0]); row=11 if key.startswith('озп') else 10
        return result(select_source(f'Охрана труда!B{row}',g)[0])
    from program_matcher import PROGRAM_ALIASES, CANONICAL_PROGRAMS
    old_key = str(text).lower().strip()
    old_idx = PROGRAM_ALIASES.get(old_key)
    if old_idx is None:
        old_idx = next((i for i, n in enumerate(CANONICAL_PROGRAMS) if norm(n) == key), None)
    source_map = {5:'Охрана труда!B5', 6:'Охрана труда!B6', 7:'Охрана труда!B8', 8:'Охрана труда!B7', 9:'Охрана труда!B4', 19:'Экологическая безопасность!B5', 20:'Экологическая безопасность!B6'}
    if old_idx in source_map:
        return result(select_source(source_map[old_idx])[0])
    if old_idx in (12,13,14) and re.search(r'[123]', key):
        return result(select_source('Охрана труда!B10', old_idx-11)[0])
    # Removing punctuation/prefix does not erase the PK vs DPP distinction.
    cleaned = re.sub(r'^пк ', '', key)
    matches = [r for r in records if re.sub(r'^пк ', '', norm(r['name'])) == cleaned]
    if len(matches) == 1: return result(matches[0])
    # Strip only explicit course prefixes; retain type/rank to avoid cross-type matches.
    worker=re.sub(r'^профессиональная подготовка по профессии\s*','',key)
    worker=re.sub(r'\s+(\d+)\s+разряда?$',r' \1 разряд',worker)
    candidates=[r for r in records if r['category']=='worker' and norm(r['name'])==worker]
    if len(candidates)==1:return result(candidates[0])
    ranked=sorted(records,key=lambda r:SequenceMatcher(None,key,norm(r['name'])).ratio(),reverse=True)[:5] if key else []
    missing=unresolved(text,ranked)
    occupations=[o for o in catalog()['occupations'] if norm(o['name'])==key]
    if occupations:
        missing['occupation_reference']=occupations
        missing['warning']='Профессия есть в приказе №534, но программа центра и часы не подтверждены — требуется уточнение'
    return missing

def resolve_many(raw, position=None):
    if not raw:return [unresolved('')]
    parts=raw if isinstance(raw,list) else re.split(r';|\n',str(raw))
    # Split comma lists only when every item independently resolves.
    flattened=[]
    for part in parts:
        chunks=str(part).split(',')
        if len(chunks)>1 and all(resolve(c.strip())['status']!='review' for c in chunks):flattened.extend(chunks)
        else:flattened.append(part)
    parts=flattened
    results=[]
    for part in parts:
        part=str(part).strip()
        if not part:continue
        # A selected catalog name is atomic, even if it contains punctuation/conjunctions.
        direct=resolve(part)
        if direct['status']!='review':expanded=[direct]
        else:
            groups=list(re.finditer(r'(?:высот[аеуы]?|озп)\s*([123])\s*(?:групп[аы]?|гр\.?)?',part,re.I))
            if groups and re.fullmatch(r'[\s,;+и.]*',re.sub(r'(?:высот[аеуы]?|озп)\s*[123]\s*(?:групп[аы]?|гр\.?)?','',part,flags=re.I)):
                expanded=[resolve(('ОЗП ' if 'озп' in m[0].lower() else 'Высота ')+m[1]+' группа') for m in groups]
            elif re.search(r'[«"(][абв][»")]|перво[йя] помо[щш]и',part,re.I) and not re.search(r'пк|дпп|инструктор',part,re.I):
                expanded=[]
                for token,row in [('а',4),('б',5),('в',6)]:
                    if re.search(r'[«"(]'+token+r'[»")]',part,re.I):expanded.append(result(select_source(f'Охрана труда!B{row}')[0]))
                if re.search(r'перв[^,;]*помо[щш]',part,re.I):expanded.append(result(select_source('Охрана труда!B8')[0]))
                if re.search(r'сиз|индивидуальн',part,re.I):expanded.append(result(select_source('Охрана труда!B7')[0]))
                if not expanded:expanded=[direct]
            elif re.fullmatch(r'(?:ОТ\s*)?\(?\s*(?:А|Б|В|СИЗ|ПП)(?:\s*[+,]\s*(?:А|Б|В|СИЗ|ПП))*\s*\)?',part,re.I):
                expanded=[resolve(t) for t in re.findall(r'СИЗ|ПП|[АБВ]',part.upper().replace('ОТ',''))]
            else:expanded=[direct]
        for r in expanded:
            if not any(x.get('id',x['name'])==r.get('id',r['name']) for x in results):results.append(r)
    return results or [unresolved('')]
