"""Deterministic schedules: inclusive days, eight teaching hours/day, no compression."""
import re, math
from datetime import date,timedelta
from production_calendar import roll,span,CalendarUnavailable

def parse_dates(value, role='auto'):
    text=str(value or '').strip().lower().replace('ё','е')
    if not text:return None,None,'Сроки обучения не указаны'
    found=re.findall(r'(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)',text)
    if not found or len(found)>2:return None,None,'Формат или количество дат не определены — требуется уточнение'
    try:dates=[date(int(y),int(m),int(d)) for d,m,y in found]
    except ValueError:return None,None,'Несуществующая календарная дата — требуется уточнение'
    if len(dates)==2:
        if dates[0]>dates[1]:return None,None,'Начало позже окончания — требуется уточнение'
        return *dates,None
    start=role=='start' or (role=='auto' and (re.search(r'прием|принят|трудоустройств|выход.*работ|начал|^с\s',text) or re.search(r'\d\s*[-–—]\s*$',text)))
    end=role=='end' or (role=='auto' and re.search(r'окончан|заверш|^до\s|^по\s',text))
    if start and not end:return dates[0],None,None
    if end and not start:return None,dates[0],None
    return None,None,'Укажите, является дата началом или окончанием обучения'

def schedule(programs, raw, role='auto', hours_overrides=None):
    start,end,error=parse_dates(raw,role)
    programs=[dict(p) for p in programs]
    hours_overrides=hours_overrides or {}
    for p in programs:
        override=hours_overrides.get(p.get('id'),hours_overrides.get(p['name']))
        if override is not None:
            if isinstance(override,bool) or not isinstance(override,int) or not 1<=override<=2000:
                error='Некорректное число часов'
            elif p.get('hours_options') and override not in p['hours_options']:
                error=f"Недопустимый вариант часов для {p['name']}"
            else:p.update(hours=override,hours_source='Выбор оператора')
        if not p.get('is_canonical') or not p.get('hours'):
            error=error or 'Программа или длительность не подтверждены — требуется уточнение'
    def failed(msg):
        return [(dict(p,schedule_warning=msg),'',False) for p in programs]
    if error:return failed(error)
    try:
        cursor=roll(start,1) if start else roll(end,-1)
        moved=cursor!=(start or end)
        scheduled=[]
        iterable=programs if start else list(reversed(programs))
        for p in iterable:
            days=math.ceil(p['hours']/8)
            if start:
                first=roll(cursor);last=span(first,days);cursor=last+timedelta(days=1)
            else:
                last=roll(cursor,-1);first=span(last,days,-1);cursor=first-timedelta(days=1)
            p.update(days=days,calendar='РФ, производственный',date_source=role,schedule_warning='Опорная дата перенесена на рабочий день' if moved else None)
            scheduled.append((p,f'{first:%d.%m.%Y} - {last:%d.%m.%Y}',len(programs)>1))
        if not start:scheduled.reverse()
        if start and end and last>end:return failed('В заданном интервале недостаточно рабочих дней; измените сроки. Длительность не сокращена')
        return scheduled
    except CalendarUnavailable as e:return failed(str(e))
