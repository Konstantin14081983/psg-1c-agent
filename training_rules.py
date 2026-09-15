"""
Training Rules and Validation Engine for PSG 1C Application Agent.
Enforces:
1. Training category classification (ОТ, Рабочие профессии, ПК/ДПП, Допуски, Высота/ОЗП).
2. Date restrictions (Backdating limits: Рабочие профессии <= 3 days, ПК/ДПП <= 30 days).
3. Sequence and overlap checks (ОТ strictly sequential; Высота/ОЗП groups cannot overlap).
4. Mandatory document package verification per category.
5. Job position normalization, typo correction, and abbreviation expansion.
"""

import re
import datetime
from typing import Dict, Any, List, Optional, Tuple

# Categories
CAT_OT = "ОТ (Охрана труда)"
CAT_WORKER = "Рабочие профессии"
CAT_PK_DPP = "ПК / ДПП"
CAT_HEIGHT_OZP = "Высота и ОЗП"
CAT_PERMITS_EXAM = "Допуски и проверка знаний"

# Position abbreviation dictionary
POSITION_ABBREVIATIONS = [
    (r'\bм/к\b', 'металлоконструкций'),
    (r'\bж/б\b', 'железобетонных конструкций'),
    (r'\bт/р\b', 'технологических трубопроводов'),
    (r'\bэ/г\b', 'электрогазосварщик'),
    (r'\bпом\.\s*', 'Помощник '),
    (r'\bнач\.\s*', 'Начальник '),
    (r'\bвед\.\s*', 'Ведущий '),
    (r'\bинж\.\s*', 'Инженер '),
    (r'\bрук\.\s*', 'Руководитель '),
    (r'\bспец\.\s*', 'Специалист '),
    (r'\bмаш\.\s*', 'Машинист '),
    (r'\bэлектромонт\.\s*', 'Электромонтер '),
    (r'\bэл\.\s*', 'Электромонтер '),
    (r'\bопер\.\s*', 'Оператор '),
    (r'\bаппаратч\.\s*', 'Аппаратчик '),
    (r'\bа/м\b', 'автомобиля'),
]

# Position typo corrections
POSITION_TYPOS = [
    (r'\bелектрогазосварщик\b', 'электрогазосварщик'),
    (r'\bелектрик\b', 'электрик'),
    (r'\bелектромонтер\b', 'электромонтёр'),
    (r'\bсваарщик\b', 'сварщик'),
    (r'\bсварщикк\b', 'сварщик'),
    (r'\bсваршик\b', 'сварщик'),
    (r'\bмошинист\b', 'машинист'),
    (r'\bмашинст\b', 'машинист'),
    (r'\bмашинисст\b', 'машинист'),
    (r'\bкранна\b', 'крана'),
    (r'\bавтомобильногого\b', 'автомобильного'),
    (r'\bавтомобилного\b', 'автомобильного'),
    (r'\bслесарьь\b', 'слесарь'),
    (r'\bслесар\b', 'слесарь'),
    (r'\bслесаррь\b', 'слесарь'),
    (r'\bстропалщик\b', 'стропальщик'),
    (r'\bстропальшик\b', 'стропальщик'),
    (r'\bстропаалщик\b', 'стропальщик'),
    (r'\bмантажник\b', 'монтажник'),
    (r'\bмонтжник\b', 'монтажник'),
    (r'\bмонтажик\b', 'монтажник'),
    (r'\bмонтажнник\b', 'монтажник'),
    (r'\bводител\b', 'водитель'),
    (r'\bводиитель\b', 'водитель'),
    (r'\bинжинер\b', 'инженер'),
    (r'\bинжинерр\b', 'инженер'),
    (r'\bподсобный рабочии\b', 'подсобный рабочий'),
]

def normalize_position(position_raw: Optional[str]) -> Tuple[str, Optional[str], bool]:
    """
    Normalizes a job position:
    - Strips garbage prefixes (должность:, профессия:) and quotes
    - Capitalizes first letter
    - Corrects common typos and letter doubling (e.g. 'електрогазосварщик', 'сваарщик')
    - Expands standard industry abbreviations (м/к, пом., э/г, и т.д.)
    Returns (cleaned_position, warning_message, had_issues).
    """
    if not position_raw or not position_raw.strip():
        return "", "Должность не указана", True
        
    text = position_raw.strip()
    # Strip garbage prefixes
    text = re.sub(r'^(?:должность|профессия|долж\.|проф\.)[:\s]*', '', text, flags=re.IGNORECASE).strip()
    # Strip quotes and brackets
    text = re.sub(r'^[\"\'«\(\[\{]+|[\"\'»\)\]\}]+$', '', text).strip()
    # Strip trailing punctuation
    text = text.rstrip(' .,;!?-')
    text = re.sub(r'\s+', ' ', text)
    
    had_corrections = False
    had_typos = False
    
    # Check typos
    for pattern, replacement in POSITION_TYPOS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            had_typos = True
            
    # Check abbreviations
    for pattern, replacement in POSITION_ABBREVIATIONS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            had_corrections = True
            
    # Deduplicate tripled letters
    text_dedup = re.sub(r'([а-яА-ЯёЁa-zA-Z])\1{2,}', r'\1', text)
    # Deduplicate accidental doubled vowels (e.g. сваарщик -> сварщик, водиитель -> водитель)
    text_dedup = re.sub(r'([аиоуыэюя])\1+', r'\1', text_dedup, flags=re.IGNORECASE)
    # Deduplicate initial doubled consonants (e.g. Вводитель -> Водитель)
    text_dedup = re.sub(r'\b([бвгджзклмнпрстфхцчшщ])\1', r'\1', text_dedup, flags=re.IGNORECASE)
    # Deduplicate non-legitimate double consonants in position words
    legit_pos_roots = ('кассир', 'программ', 'ассист', 'иллюстр', 'коррект', 'пресс', 'стюардесс', 'аккумул', 'компресс', 'аппарат', 'массаж', 'групп', 'колл', 'тонн', 'баллон')
    def _sub_pos_cons(m):
        w = m.group(0)
        if any(r in w.lower() for r in legit_pos_roots):
            return w
        return re.sub(r'([бвгджзклмнпрстфхцчшщ])\1+', r'\1', w, flags=re.IGNORECASE)
    text_dedup = re.sub(r'[а-яА-ЯёЁa-zA-Z\-]+', _sub_pos_cons, text_dedup)
    if text_dedup != text:
        text = text_dedup
        had_typos = True

    # Capitalize the first letter properly
    if text:
        text = text[0].upper() + text[1:]
        
    warning = None
    if had_typos:
        warning = f"Обнаружены и исправлены опечатки в должности: '{position_raw}' -> '{text}'"
    elif had_corrections:
        warning = f"Сокращение в должности автоматически раскрыто: '{text}'"
    elif len(text) < 3:
        warning = f"Слишком короткое название должности: '{text}'"
        
    return text, warning, (had_typos or had_corrections or len(text) < 3)

def classify_program(program_name: str) -> str:
    """Determines the training category for a given program name."""
    p_lower = program_name.lower()
    
    if 'высот' in p_lower or 'озп' in p_lower or 'ограниченных и замкнутых' in p_lower:
        return CAT_HEIGHT_OZP
        
    if any(k in p_lower for k in [
        'безопасным методам и приемам', 'вредных и (или) опасных',
        'первой помощи', 'средств индивидуальной защиты', 'повышенной опасности',
        'охрана труда', 'охраны труда', 'охране труда', 'охраной труда', 'от (',
        'программа а', 'программа б', 'программа в', 'общим вопросам охраны труда'
    ]) or ('охран' in p_lower and 'труд' in p_lower and not any(dp in p_lower for dp in ['переподготовка', '256'])):
        return CAT_OT
        
    if any(k in p_lower for k in [
        'допуск', 'ежегодн', 'проверка знаний', 'водител', 'бдд', 'электроустановк', 'правила работы в электро'
    ]):
        return CAT_PERMITS_EXAM
        
    if any(k in p_lower for k in [
        'дпп', 'пк', 'повышение квалификации', 'переподготовка', 'пожарн', 'пб',
        'экологическ', 'специалист по'
    ]):
        return CAT_PK_DPP
        
    if any(k in p_lower for k in [
        'профессия', 'професси', 'подготовка по профессии', 'машинист', 'стропальщик',
        'сварщик', 'слесарь', 'монтажник', 'вышкомонтажник', 'оператор'
    ]):
        return CAT_WORKER
        
    return CAT_PK_DPP

def is_weekend(d: datetime.date) -> bool:
    return d.weekday() >= 5  # 5=Saturday, 6=Sunday

def next_working_day(d: datetime.date) -> datetime.date:
    """Advances to next working day (Monday-Friday)."""
    curr = d + datetime.timedelta(days=1)
    while is_weekend(curr):
        curr += datetime.timedelta(days=1)
    return curr

def prev_working_day(d: datetime.date) -> datetime.date:
    """Rewinds to previous working day (Monday-Friday)."""
    curr = d - datetime.timedelta(days=1)
    while is_weekend(curr):
        curr -= datetime.timedelta(days=1)
    return curr

def add_working_days(start_d: datetime.date, num_days: int) -> datetime.date:
    """Adds num_days working days starting from start_d (inclusive)."""
    curr = start_d
    while is_weekend(curr):
        curr += datetime.timedelta(days=1)
    days_left = max(num_days - 1, 0)
    while days_left > 0:
        curr = next_working_day(curr)
        days_left -= 1
    return curr

def subtract_working_days(end_d: datetime.date, num_days: int) -> datetime.date:
    """Subtracts num_days working days ending on end_d (inclusive)."""
    curr = end_d
    while is_weekend(curr):
        curr -= datetime.timedelta(days=1)
    days_left = max(num_days - 1, 0)
    while days_left > 0:
        curr = prev_working_day(curr)
        days_left -= 1
    return curr

def get_program_duration_info(program_name: str, category: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns official training duration (hours, days, whether calendar or working days).
    - ОТ (А, Б, В, СИЗ, ПП): 16 hours (2 working days)
    - Высота и ОЗП: 24 hours (3 working days)
    - Рабочие профессии: 240 hours (30 calendar days)
    - ПК (пожарная, экология 112ч, и т.д.): 72 hours (9 calendar days)
    - ДПП: 250 hours (32 calendar days)
    - Ежегодная проверка знаний: 16 hours (2 working days)
    - Допуски (электроустановки): 24 hours (3 working days)
    - БДД: 20 hours (3 working days)
    """
    if not category:
        category = classify_program(program_name)
    p_low = program_name.lower()
    if 'дпп' in p_low or 'переподготовка' in p_low:
        return {'hours': 250, 'days': 32, 'calendar': True}
    elif 'эколог' in p_low:
        return {'hours': 112, 'days': 14, 'calendar': True}
    elif 'бдд' in p_low or 'водител' in p_low:
        return {'hours': 20, 'days': 3, 'calendar': False}
    elif category == CAT_OT:
        return {'hours': 16, 'days': 2, 'calendar': False}
    elif category == CAT_HEIGHT_OZP:
        return {'hours': 24, 'days': 3, 'calendar': False}
    elif category == CAT_WORKER:
        return {'hours': 240, 'days': 30, 'calendar': True}
    elif category == CAT_PK_DPP:
        return {'hours': 72, 'days': 9, 'calendar': True}
    elif category == CAT_PERMITS_EXAM:
        if 'ежегодн' in p_low or 'проверка' in p_low:
            return {'hours': 16, 'days': 2, 'calendar': False}
        return {'hours': 24, 'days': 3, 'calendar': False}
    return {'hours': 16, 'days': 2, 'calendar': False}

def calculate_start_date_for_category(
    category: str,
    end_date: datetime.date,
    num_sequential_programs: int = 1,
    program_name: str = ""
) -> datetime.date:
    """
    Calculates appropriate start date leading up to end_date when start date is not specified.
    Respects working days (skips weekends) for OT and Height.
    """
    info = get_program_duration_info(program_name, category)
    total_days = info['days'] * max(num_sequential_programs, 1)
    if info['calendar']:
        return end_date - datetime.timedelta(days=total_days - 1)
    else:
        return subtract_working_days(end_date, total_days)

def parse_date_range(dates_str: Optional[str]) -> Tuple[Optional[datetime.date], Optional[datetime.date], Optional[str]]:
    """Parses start and end dates from string like '25.12.2025 - 16.01.2026' or single date '11.09.2026'."""
    if not dates_str or not str(dates_str).strip():
        return None, None, "Сроки обучения не указаны"
        
    cleaned = str(dates_str).strip()
    # 0. Clean OCR spaces inside numeric dates (e.g. '11.09.202 6', '11 . 09 . 2026')
    cleaned = re.sub(r'(\d)\s*([./\-])\s*(\d)', r'\1\2\3', cleaned)
    cleaned = re.sub(r'(\d)\s*([./\-])\s*(\d)', r'\1\2\3', cleaned)
    for _ in range(3):
        cleaned = re.sub(r'(\d{1,2}[./\-]\d{1,2}[./\-]\d{1,3})\s+(\d{1,3})', r'\1\2', cleaned)
    # Autocorrect 3-digit year like '202' -> '2026'
    cleaned = re.sub(r'\b(\d{1,2}[./\-]\d{1,2}[./\-])202\b', r'\g<1>2026', cleaned)
    
    date_matches = re.findall(r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})', cleaned)
    
    parsed_dates = []
    for d, m, y in date_matches:
        try:
            day, month, year = int(d), int(m), int(y)
            if year == 202:
                year = 2026
            elif year < 100:
                year += 1900 if year > 30 else 2000
            parsed_dates.append(datetime.date(year, month, day))
        except Exception:
            pass
            
    if len(parsed_dates) >= 2:
        start_d, end_d = parsed_dates[0], parsed_dates[1]
        if start_d > end_d:
            return end_d, start_d, "Дата начала позже даты окончания"
        return start_d, end_d, None
    elif len(parsed_dates) == 1:
        # Check if text specifies start date (e.g. 'от 18.08', 'трудоустройства 18.08', 'с 18.08', 'начало 18.08')
        is_start = bool(re.search(r'\b(?:трудоустройств[а-я]*|нач[а-я]*|от|с)\b', cleaned, re.I))
        is_end = bool(re.search(r'\b(?:окончан[а-я]*|до|по|заверш[а-я]*)\b', cleaned, re.I))
        if is_start and not is_end:
            return parsed_dates[0], None, None
        else:
            return None, parsed_dates[0], None
        
    return None, None, f"Не удалось распознать даты обучения: '{cleaned}'"

def validate_dates_and_category(
    program_name: str,
    dates_str: Optional[str],
    current_date: Optional[datetime.date] = None
) -> Dict[str, Any]:
    """
    Validates training dates against category rules:
    - Worker professions: end date <= current_date and maximum 3 days back.
    - PK / DPP: end date <= current_date and maximum 30 days back.
    - OT, Height, Permits: no date limits.
    """
    if current_date is None:
        current_date = datetime.date.today()
        
    cat = classify_program(program_name)
    start_d, end_d, date_warn = parse_date_range(dates_str)
    
    warnings = []
    if date_warn:
        warnings.append(date_warn)
        
    if end_d:
        days_ago = (current_date - end_d).days
        
        if cat == CAT_WORKER:
            if days_ago > 3:
                warnings.append(
                    f"Рабочие профессии: окончание обучения ({end_d.strftime('%d.%m.%Y')}) "
                    f"старше допустимых 3 дней от текущей даты (прошло {days_ago} дн.)"
                )
        elif cat == CAT_PK_DPP:
            if days_ago > 30:
                warnings.append(
                    f"ПК / ДПП: окончание обучения ({end_d.strftime('%d.%m.%Y')}) "
                    f"старше допустимых 30 календарных дней (прошло {days_ago} дн.)"
                )
                
    return {
        "category": cat,
        "start_date": start_d,
        "end_date": end_d,
        "warnings": warnings,
        "has_error": len(warnings) > 0
    }

def validate_document_package(
    category: str,
    student_data: Dict[str, Any],
    manager_docs: Optional[Dict[str, bool]] = None
) -> List[str]:
    docs = manager_docs or {}
    fio = student_data.get('fio_nom', '').strip()
    birth_date = student_data.get('birth_date', '').strip()
    snils = student_data.get('snils', '').strip()
    position = student_data.get('position', '').strip()
    
    warnings = []
    
    if not fio:
        warnings.append("Отсутствует ФИО слушателя")
    if not birth_date:
        warnings.append("Отсутствует дата рождения")
        
    if category in (CAT_PK_DPP, CAT_WORKER, CAT_OT):
        if not snils:
            warnings.append("Отсутствует СНИЛС (обязателен для ФИС ФРДО)")
            
    if category in (CAT_OT, CAT_HEIGHT_OZP):
        if not position:
            warnings.append("Отсутствует должность (обязательна для охраны труда / высоты)")
            
    if category == CAT_PK_DPP:
        if not docs.get('has_diploma', False):
            warnings.append("Требуется скан диплома об образовании (ПК/ДПП)")
            
    elif category == CAT_WORKER:
        if not docs.get('has_photo', False):
            warnings.append("Требуется фото 3х4 для удостоверения рабочей профессии")
            
    elif category == CAT_HEIGHT_OZP:
        if not docs.get('has_photo', False):
            warnings.append("Требуется фото 3х4 для удостоверения по высоте / ОЗП")
            
    elif category == CAT_PERMITS_EXAM:
        if 'проверка' in category.lower() or 'ежегодн' in str(student_data.get('program', '')).lower():
            if not docs.get('has_certificate', False):
                warnings.append("Требуется скан или номер предыдущего удостоверения для ежегодной проверки знаний")
                
    return warnings

def audit_student_program_overlaps(
    student_enrollments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    issues = []
    if len(student_enrollments) < 2:
        return issues
        
    for i in range(len(student_enrollments)):
        for j in range(i + 1, len(student_enrollments)):
            e1 = student_enrollments[i]
            e2 = student_enrollments[j]
            
            p1_name = e1.get('program', '')
            p2_name = e2.get('program', '')
            cat1 = classify_program(p1_name)
            cat2 = classify_program(p2_name)
            
            d1_start, d1_end = e1.get('start_date'), e1.get('end_date')
            d2_start, d2_end = e2.get('start_date'), e2.get('end_date')
            
            if d1_start and d1_end and d2_start and d2_end:
                overlaps = max(d1_start, d2_start) <= min(d1_end, d2_end)
                if overlaps:
                    if cat1 == CAT_OT and cat2 == CAT_OT:
                        issues.append({
                            'type': 'OT_OVERLAP_ERROR',
                            'message': f"Обучение по охране труда должно быть СТРОГО последовательным! Пересекаются программы '{p1_name[:35]}...' и '{p2_name[:35]}...'",
                            'programs': [p1_name, p2_name]
                        })
                    elif cat1 == CAT_HEIGHT_OZP and cat2 == CAT_HEIGHT_OZP:
                        issues.append({
                            'type': 'HEIGHT_OVERLAP_ERROR',
                            'message': f"Программы по высоте / ОЗП не могут пересекаться между собой! Пересекаются '{p1_name[:35]}...' и '{p2_name[:35]}...'",
                            'programs': [p1_name, p2_name]
                        })
                        
    return issues

def assign_sequential_dates(
    matched_programs: List[Dict[str, Any]],
    dates_raw: Optional[str],
    default_end_date: Optional[datetime.date] = None
) -> List[Tuple[Dict[str, Any], str, bool]]:
    """
    Distributes dates across matched programs.
    - If manager passed semicolon-separated date ranges: assigns each directly.
    - If a single START date was specified (e.g. 'Дата трудоустройства 18.08.2026' or 'от 18.08.2026'):
      schedules each program sequentially FORWARD starting from that date,
      respecting working days for OT/Height (skipping weekends).
    - If a single END date was specified (e.g. '11.09.2026' or 'окончание 11.09.2026'):
      schedules each program sequentially BACKWARD so the entire sequence concludes on end date!
    - If a date range [start, end] was specified:
      schedules programs sequentially within the window.
    """
    if not matched_programs:
        return []
        
    cleaned_dates = str(dates_raw).strip() if dates_raw else ""
    
    # 1. Semicolon-separated ranges
    if ';' in cleaned_dates:
        parts = [p.strip() for p in cleaned_dates.split(';') if p.strip()]
        if len(parts) == len(matched_programs):
            return [(matched_programs[i], parts[i], False) for i in range(len(matched_programs))]
            
    start_d, end_d, warn = parse_date_range(cleaned_dates) if cleaned_dates else (None, None, None)
    if not start_d and not end_d and default_end_date:
        end_d = default_end_date
    elif not start_d and not end_d and not cleaned_dates:
        return [(p, "", False) for p in matched_programs]
        
    n = len(matched_programs)
    prog_dates = {}
    was_split = n > 1
    
    # Case A: Only START date is known (e.g. 'Дата трудоустройства 18.08.2026' or 'от 18.08.2026')
    if start_d and not end_d:
        curr = start_d
        for idx, p in enumerate(matched_programs):
            cat = classify_program(p.get('name', ''))
            info = get_program_duration_info(p.get('name', ''), cat)
            if info['calendar']:
                p_start = curr
                p_end = p_start + datetime.timedelta(days=info['days'] - 1)
                prog_dates[idx] = f"{p_start.strftime('%d.%m.%Y')} - {p_end.strftime('%d.%m.%Y')}"
                curr = p_end + datetime.timedelta(days=1)
            else:
                while is_weekend(curr):
                    curr += datetime.timedelta(days=1)
                p_start = curr
                p_end = add_working_days(p_start, info['days'])
                prog_dates[idx] = f"{p_start.strftime('%d.%m.%Y')} - {p_end.strftime('%d.%m.%Y')}"
                curr = next_working_day(p_end)

    # Case B: Only END date is known (e.g. 'окончание 11.09.2026' or default date)
    elif end_d and not start_d:
        # Schedule BACKWARDS from end_d
        scheduled = []
        curr_end = end_d
        for idx in reversed(range(n)):
            p = matched_programs[idx]
            cat = classify_program(p.get('name', ''))
            info = get_program_duration_info(p.get('name', ''), cat)
            if info['calendar']:
                p_end = curr_end
                p_start = p_end - datetime.timedelta(days=info['days'] - 1)
                scheduled.append((idx, f"{p_start.strftime('%d.%m.%Y')} - {p_end.strftime('%d.%m.%Y')}"))
                curr_end = p_start - datetime.timedelta(days=1)
            else:
                while is_weekend(curr_end):
                    curr_end -= datetime.timedelta(days=1)
                p_end = curr_end
                p_start = subtract_working_days(p_end, info['days'])
                scheduled.append((idx, f"{p_start.strftime('%d.%m.%Y')} - {p_end.strftime('%d.%m.%Y')}"))
                curr_end = prev_working_day(p_start)
        for idx, date_str in scheduled:
            prog_dates[idx] = date_str

    # Case C: Both start_d and end_d are known (e.g. '01.09.2026 - 15.09.2026')
    else:
        if n == 1:
            prog_dates[0] = f"{start_d.strftime('%d.%m.%Y')} - {end_d.strftime('%d.%m.%Y')}"
        else:
            total_req_days = sum(get_program_duration_info(p['name'], classify_program(p['name']))['days'] for p in matched_programs)
            window_days = (end_d - start_d).days + 1
            if window_days >= total_req_days:
                curr = start_d
                for idx, p in enumerate(matched_programs):
                    cat = classify_program(p.get('name', ''))
                    info = get_program_duration_info(p.get('name', ''), cat)
                    if info['calendar']:
                        p_start = curr
                        p_end = p_start + datetime.timedelta(days=info['days'] - 1)
                        prog_dates[idx] = f"{p_start.strftime('%d.%m.%Y')} - {p_end.strftime('%d.%m.%Y')}"
                        curr = p_end + datetime.timedelta(days=1)
                    else:
                        while is_weekend(curr):
                            curr += datetime.timedelta(days=1)
                        p_start = curr
                        p_end = add_working_days(p_start, info['days'])
                        prog_dates[idx] = f"{p_start.strftime('%d.%m.%Y')} - {p_end.strftime('%d.%m.%Y')}"
                        curr = next_working_day(p_end)
            else:
                base = max(window_days // n, 1)
                rem = window_days % n
                curr = start_d
                for idx in range(n):
                    p_days = base + (1 if idx < rem else 0)
                    p_start = curr
                    p_end = min(curr + datetime.timedelta(days=p_days - 1), end_d)
                    prog_dates[idx] = f"{p_start.strftime('%d.%m.%Y')} - {p_end.strftime('%d.%m.%Y')}"
                    curr = p_end + datetime.timedelta(days=1)
                    
    return [(matched_programs[i], prog_dates[i], was_split) for i in range(len(matched_programs))]

