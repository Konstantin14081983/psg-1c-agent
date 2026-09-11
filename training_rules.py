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

def calculate_start_date_for_category(
    category: str,
    end_date: datetime.date,
    num_sequential_programs: int = 1
) -> datetime.date:
    """
    Calculates appropriate start date leading up to end_date when start date is not specified.
    - Worker professions: ~21 calendar days (3 weeks) prior.
    - PK / DPP: ~10 calendar days prior.
    - Height / OZP: 3 calendar days prior (or num_sequential_programs).
    - OT: num_sequential_programs calendar days prior (concluding on end_date).
    - Permits / Exams: 1-2 days prior.
    """
    if category == CAT_WORKER:
        return end_date - datetime.timedelta(days=21)
    elif category == CAT_PK_DPP:
        return end_date - datetime.timedelta(days=10)
    elif category == CAT_HEIGHT_OZP:
        return end_date - datetime.timedelta(days=max(num_sequential_programs, 3))
    elif category == CAT_OT:
        return end_date - datetime.timedelta(days=max(num_sequential_programs - 1, 1))
    elif category == CAT_PERMITS_EXAM:
        return end_date - datetime.timedelta(days=max(num_sequential_programs - 1, 1))
    return end_date - datetime.timedelta(days=max(num_sequential_programs - 1, 1))

def parse_date_range(dates_str: Optional[str]) -> Tuple[Optional[datetime.date], Optional[datetime.date], Optional[str]]:
    """Parses start and end dates from string like '25.12.2025 - 16.01.2026' or single end date '11.09.2026'."""
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
        # Only one date specified: this is the target end date!
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
    If multiple programs belong to a category requiring sequential scheduling
    (e.g. CAT_OT or CAT_HEIGHT_OZP) and a single overall date range is provided,
    splits the overall range into consecutive non-overlapping sub-periods.
    If only an end date is provided (e.g. '11.09.2026'), calculates appropriate start dates
    leading up to end date so that training concludes on or before the end date.
    Supports semicolon-delimited date ranges if provided by manager.
    Returns list of (prog_dict, assigned_date_str, was_split).
    """
    if not matched_programs:
        return []
        
    cleaned_dates = str(dates_raw).strip() if dates_raw else ""
    
    # Check if multiple semicolon-separated date ranges were passed
    if ';' in cleaned_dates:
        parts = [p.strip() for p in cleaned_dates.split(';') if p.strip()]
        if len(parts) == len(matched_programs):
            return [(matched_programs[i], parts[i], False) for i in range(len(matched_programs))]
            
    # Parse overall start and end date
    start_d, end_d, warn = parse_date_range(cleaned_dates) if cleaned_dates else (None, None, None)
    if not end_d and default_end_date:
        end_d = default_end_date
    elif not end_d and not start_d and not cleaned_dates:
        return [(p, "", False) for p in matched_programs]
        
    if not end_d and start_d:
        end_d = start_d
        start_d = None

    # Check if there are multiple programs requiring sequential training (e.g. OT or Height)
    ot_progs = []
    height_progs = []
    for idx, p in enumerate(matched_programs):
        cat = classify_program(p.get('name', ''))
        if cat == CAT_OT:
            ot_progs.append(idx)
        elif cat == CAT_HEIGHT_OZP:
            height_progs.append(idx)
            
    # Initial dates mapping for all programs
    prog_dates = {}
    was_split = False
    
    for idx, p in enumerate(matched_programs):
        cat = classify_program(p.get('name', ''))
        if end_d:
            if start_d is None or start_d == end_d:
                p_start = calculate_start_date_for_category(cat, end_d, 1)
                prog_dates[idx] = f"{p_start.strftime('%d.%m.%Y')} - {end_d.strftime('%d.%m.%Y')}"
            else:
                prog_dates[idx] = f"{start_d.strftime('%d.%m.%Y')} - {end_d.strftime('%d.%m.%Y')}"
        else:
            prog_dates[idx] = cleaned_dates
    
    # Sequential partition helper for indices
    def partition_indices(indices: List[int]):
        nonlocal was_split
        if not indices or not end_d:
            return
        k = len(indices)
        if k < 2:
            p_idx = indices[0]
            cat = classify_program(matched_programs[p_idx].get('name', ''))
            if start_d is None or start_d == end_d:
                p_start = calculate_start_date_for_category(cat, end_d, 1)
                prog_dates[p_idx] = f"{p_start.strftime('%d.%m.%Y')} - {end_d.strftime('%d.%m.%Y')}"
            return
            
        was_split = True
        total_days = (end_d - start_d).days + 1 if start_d else 0
        if start_d and total_days >= k:
            base = total_days // k
            rem = total_days % k
            curr = start_d
            for i, p_idx in enumerate(indices):
                days = base + (1 if i < rem else 0)
                p_start = curr
                p_end = curr + datetime.timedelta(days=days - 1)
                prog_dates[p_idx] = f"{p_start.strftime('%d.%m.%Y')} - {p_end.strftime('%d.%m.%Y')}"
                curr = p_end + datetime.timedelta(days=1)
        else:
            # Training sequence concludes on end_d!
            # Pick start date backwards so programs finish on or before end_d:
            seq_start = end_d - datetime.timedelta(days=k - 1)
            curr = seq_start
            for p_idx in indices:
                prog_dates[p_idx] = f"{curr.strftime('%d.%m.%Y')} - {curr.strftime('%d.%m.%Y')}"
                curr = curr + datetime.timedelta(days=1)
                
    partition_indices(ot_progs)
    partition_indices(height_progs)
    
    return [(matched_programs[i], prog_dates[i], was_split and (i in ot_progs or i in height_progs)) for i in range(len(matched_programs))]

