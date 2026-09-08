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
    (r'\bмошинист\b', 'Машинист'),
    (r'\bкранна\b', 'крана'),
    (r'\bавтомобильногого\b', 'автомобильного'),
    (r'\bавтомобилного\b', 'автомобильного'),
    (r'\bслесарьь\b', 'слесарь'),
    (r'\bсварщикк\b', 'сварщик'),
    (r'\bстропалщик\b', 'стропальщик'),
    (r'\bмантажник\b', 'монтажник'),
    (r'\bмонтжник\b', 'монтажник'),
]

def normalize_position(position_raw: Optional[str]) -> Tuple[str, Optional[str], bool]:
    """
    Normalizes a job position:
    - Capitalizes first letter
    - Corrects common typos (e.g. 'мошинист кранна', 'автомобильногого')
    - Expands standard industry abbreviations (м/к, пом., э/г, и т.д.)
    Returns (cleaned_position, warning_message, had_issues).
    """
    if not position_raw or not position_raw.strip():
        return "", "Должность не указана", True
        
    text = position_raw.strip()
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
        'охрана труда', 'от (б+сиз+пп)', 'программа а', 'программа б', 'программа в'
    ]):
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

def parse_date_range(dates_str: Optional[str]) -> Tuple[Optional[datetime.date], Optional[datetime.date], Optional[str]]:
    """Parses start and end dates from string like '25.12.2025 - 16.01.2026'."""
    if not dates_str or not dates_str.strip():
        return None, None, "Сроки обучения не указаны"
        
    cleaned = dates_str.strip()
    date_matches = re.findall(r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})', cleaned)
    
    parsed_dates = []
    for d, m, y in date_matches:
        try:
            day, month, year = int(d), int(m), int(y)
            if year < 100:
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
        return parsed_dates[0], parsed_dates[0], None
        
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
