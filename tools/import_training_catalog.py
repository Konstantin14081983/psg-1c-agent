"""Offline importer. Reads reference files, never uploads documents or stores prices/PII."""
import argparse, hashlib, json, re
from pathlib import Path
import openpyxl

def normalize(s):
    return re.sub(r'[^а-яa-z0-9]+', ' ', str(s).lower().replace('ё','е')).strip()

def build(price, dpp_text, order_text):
    records=[]
    def add(name, hours, source, category, status='offered', **extra):
        ident=hashlib.sha256((source+'|'+name).encode()).hexdigest()[:16]
        records.append(dict(id=ident,name=name,hours=hours,source=source,category=category,status=status,**extra))
    wb=openpyxl.load_workbook(price,read_only=True,data_only=True)
    for ws in wb:
        section_hours=[]
        for row in ws.iter_rows():
            vals=[c.value for c in row]
            if len(vals)<2: continue
            a,b=vals[:2]
            if not b:
                # Hours in industrial safety section banners apply to the section.
                section_hours=[int(x) for x in re.findall(r'(\d+)\s*ч',str(a or ''))]
                continue
            if not isinstance(a,(int,float)) and not (ws.title == 'Охрана труда' and re.match(r'^\d+\s*[–-]', str(b))): continue
            name=' '.join(str(b).split())
            cat={'Рабочие специальности':'worker','ДПП Профпереподготовка':'dpp','Охрана труда':'ot'}.get(ws.title,'pk')
            if re.match(r'ДПП\b',name):cat='dpp'
            elif re.match(r'ПК\b',name):cat='pk'
            status='excluded' if ws.title=='НЕ УЧИМ' or any('НЕ УЧИМ' in str(v).upper() for v in vals[2:]) else 'demo' if ws.title=='Демо' else 'offered'
            hours=[]; rank=None
            if ws.title=='Рабочие специальности':
                rank=str(vals[2] or '').strip(); raw=vals[3]
                hours=[int(raw)] if isinstance(raw,(int,float)) else []
                if rank:name+=f' — {rank} разряд'
            elif ws.title=='Промышленная безопасность':
                hours=section_hours.copy()
                if str(vals[3]).strip().lower()=='нет':status='unavailable'
            elif ws.title=='Электробезопасность':
                hours=[int(x) for x in re.findall(r'(\d+)\s*ч', name)]
                if not hours:cat='permit'
            elif ws.title not in ('Демо','НЕ УЧИМ'):
                raw=vals[2]
                if isinstance(raw,(int,float)):hours=[int(raw)]
                elif raw and re.fullmatch(r'[\d\s,]+',str(raw)):hours=[int(x) for x in re.findall(r'\d+',str(raw))]
            extra={'rank':rank} if rank else {}
            if ws.title=='Охрана труда' and row[0].row in (6,7,8):hours=[16,8]
            source=f'{ws.title}!B{row[0].row}'
            if ws.title=='Охрана труда' and row[0].row in (10,11):
                for group in (1,2,3):
                    add(re.sub(r'1, 2, 3 группы',f'{group} группа',name),hours,source,'height_ozp',group=group)
            else:add(name,hours,source,cat,status,**extra)
    text=Path(dpp_text).read_text()
    text=re.sub(r'PAGE \d+','',text)
    for idx,part in enumerate(re.split(r'(?:^|\n)o\s+',text)[1:],1):
        name=' '.join(part.split())
        exact=[r for r in records if normalize(r['name'])==normalize(name) and r['category']=='dpp']
        if exact:
            for r in exact:r['additional_source']=f'Список программ ДПП.pdf, пункт {idx}'
        else:add(name,[],f'Список программ ДПП.pdf, пункт {idx}','dpp')
    order=Path(order_text).read_text()
    occupations=[]
    entries=list(re.finditer(r'^(\d+(?:\.\d+)?(?:\(\d+\))?)\.\s*\n',order,re.M))
    for idx,m in enumerate(entries):
        block=order[m.end():entries[idx+1].start() if idx+1<len(entries) else len(order)]
        lines=[x.strip() for x in block.splitlines() if x.strip()]
        if not lines:continue
        name=lines[0]
        code=next((x for x in lines[1:] if re.fullmatch(r'\d{5}(?:,\s*\d{5})*',x)),None)
        ranks=next((x for x in lines[1:] if re.fullmatch(r'\d{1,2}(?:\s*[-–,]\s*\d{1,2})*',x)),None)
        occupations.append(dict(number=m[1],name=name,code=code,ranks=ranks))
    return dict(version='2026-09-23',sources={Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (price,dpp_text,order_text)},programs=records,occupations=occupations,occupation_version='534, редакция предоставленного файла от 25.06.2026')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('price');p.add_argument('dpp_text');p.add_argument('order_text');p.add_argument('output');a=p.parse_args()
    data=build(a.price,a.dpp_text,a.order_text)
    Path(a.output).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'programs':len(data['programs']),'occupations':len(data['occupations'])}))
