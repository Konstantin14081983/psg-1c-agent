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
    (r'\bбетоннщик\b', 'бетонщик'),
    (r'\bплоттник\b', 'плотник'),
    # Fix true orthographic errors (missing double letters in legitimate Russian words)
    (r'\bпроизводствен([ыоае][а-я]*)\b', r'производственн\1'),
    (r'\bэлектроборудован', 'электрооборудован'),
    (r'\bгазоборудован', 'газооборудован'),
    (r'\bответствен([ыоае][а-я]*)\b', r'ответственн\1'),
    (r'\bквалификацион([ыоае][а-я]*)\b', r'квалификационн\1'),
    (r'\bакумулятор', 'аккумулятор'),
    (r'\bапаратчик', 'аппаратчик'),
]

def normalize_position(position_raw: Optional[str]) -> Tuple[str, Optional[str], bool]:
    """
    Normalizes a job position:
    - Strips garbage prefixes (должность:, профессия:) and quotes
    - Capitalizes first letter
    - Corrects specific orthographic errors and typos without stripping legitimate double letters
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
    
    # Check typos and orthographic corrections
    for pattern, replacement in POSITION_TYPOS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            had_typos = True
            
    # Check abbreviations
    for pattern, replacement in POSITION_ABBREVIATIONS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            had_corrections = True

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
    from training_catalog import resolve
    record = resolve(program_name)
    category_map = {'ot': CAT_OT, 'worker': CAT_WORKER, 'pk': CAT_PK_DPP, 'dpp': CAT_PK_DPP, 'height_ozp': CAT_HEIGHT_OZP, 'permit': CAT_PERMITS_EXAM}
    if record.get('is_canonical') and record.get('category') in category_map:
        return category_map[record['category']]
    p_lower = program_name.lower()
    if p_lower.startswith(('пк ', 'дпп ')) or 'переподготовка' in p_lower or 'повышение квалификации' in p_lower:
        return CAT_PK_DPP
    
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
    from production_calendar import is_working_day
    return not is_working_day(d)

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

def get_program_duration_info(program_name, category=None):
    from training_catalog import resolve
    import math
    p = resolve(program_name)
    hours = p.get('hours')
    return {'hours': hours, 'days': math.ceil(hours / 8) if hours else None, 'calendar': False}

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
    if not info['days']:
        raise ValueError('Программа или длительность не подтверждены — требуется уточнение')
    total_days = info['days'] * max(num_sequential_programs, 1)
    if info['calendar']:
        return end_date - datetime.timedelta(days=total_days - 1)
    else:
        return subtract_working_days(end_date, total_days)

def parse_date_range(dates_str):
    from scheduling import parse_dates
    return parse_dates(dates_str)

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

def assign_sequential_dates(matched_programs, dates_raw, default_end_date=None, date_role='auto', hours_overrides=None):
    from scheduling import schedule
    # The document issue date is not an enrollment start/end date.
    return schedule(matched_programs, dates_raw, date_role, hours_overrides)
