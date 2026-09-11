"""
Linguistic and validation engine for PSG 1C Application Agent.
Handles:
- Cyrillic / Latin homoglyph cleanup
- Punctuation & whitespace normalization
- Application Title cleaning (removing stray !, fixing years like 2026в, joining split numbers)
- FIO parsing (Surname, Name, Patronymic)
- FIO anomaly and typo detection (key mashing, irregular endings)
- Nominative to Dative case declension for Russian, Ukrainian, and Central Asian names
- Gender inference (М / Ж)
- SNILS formatting and checksum validation
- Birthdate standardization (DD.MM.YYYY)
- Contacts (Email & Phone) cleaning, garbage stripping, and validation
"""

import re
from typing import Tuple, Optional, Dict, Any, List

HOMOGLYPHS = {
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'M': 'М',
    'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'a': 'а', 'c': 'с', 'e': 'е',
    'o': 'о', 'p': 'р', 'x': 'х', 'y': 'у', 'k': 'к',
}

def clean_homoglyphs(text: str) -> Tuple[str, bool]:
    """Replace Latin characters with their Cyrillic counterparts in Russian words."""
    if not text:
        return "", False
    
    had_replacements = False
    cleaned_chars = []
    
    for char in text:
        if char in HOMOGLYPHS:
            cleaned_chars.append(HOMOGLYPHS[char])
            had_replacements = True
        else:
            cleaned_chars.append(char)
            
    return "".join(cleaned_chars), had_replacements

def clean_text(text: Optional[str]) -> str:
    """Normalize whitespace, non-breaking spaces, and trim."""
    if text is None:
        return ""
    text = str(text)
    text = text.replace('\xa0', ' ').replace('\t', ' ').replace('\r', ' ')
    text = re.sub(r' +', ' ', text)
    return text.strip()

def clean_application_title(title: Optional[str]) -> Tuple[str, List[str]]:
    """
    Cleans typos, stray punctuation, and accidental spaces in application title.
    E.g. 'ЗАЯВКА НА ОБУЧЕНИЕ № ИЖ-25-0000000009 0 от 16 декабря 2026в г.!' ->
         'ЗАЯВКА НА ОБУЧЕНИЕ № ИЖ-25-00000000090 от 16 декабря 2026 г.'
    """
    if not title:
        return "", []
        
    t = clean_text(title)
    # Strip quotes if the entire title is enclosed
    if (t.startswith('"') and t.endswith('"')) or (t.startswith('«') and t.endswith('»')):
        t = t[1:-1].strip()

    warnings = []
    
    # 1. Remove unwanted exclamation marks, asterisks, question marks, hashes, etc.
    if re.search(r'[!?;\*#~]+', t):
        t = re.sub(r'[!?;\*#~]+', '', t).strip()
        warnings.append("Удалены недопустимые лишние знаки (восклицательный знак и др.) из заголовка заявки")
    
    # 2. Fix stray letters in years (e.g. '2026в г.' -> '2026 г.')
    m_year = re.search(r'(\d{4})[а-яА-Яa-zA-Z]+\s*г', t)
    if m_year:
        t = re.sub(r'(\d{4})[а-яА-Яa-zA-Z]+\s*(г\.?)', r'\1 \2', t)
        warnings.append("Исправлена опечатка в годе (удалены лишние буквы)")
        
    # 3. Fix accidental spaces inside registration number after № (e.g. '№ ИЖ-25-0000000009 0' -> '№ ИЖ-25-00000000090')
    m_num = re.search(r'(№\s*[А-Яа-яA-Za-z0-9\-]+)\s+(\d+)(\s+от\b)', t)
    if m_num:
        t = re.sub(r'(№\s*[А-Яа-яA-Za-z0-9\-]+)\s+(\d+)(\s+от\b)', r'\1\2\3', t)
        warnings.append("Удален случайный пробел в номере заявки")
        
    # 4. Normalize spaces
    t = re.sub(r'\s+', ' ', t).strip()
    
    # Ensure ends with 'г.'
    if not t.endswith('г.') and not t.endswith('года'):
        if t.endswith('г'):
            t += '.'
        elif re.search(r'\d{4}$', t):
            t += ' г.'
            
    return t, warnings


def validate_and_format_snils(snils_input: Optional[str]) -> Tuple[str, bool, Optional[str]]:
    """Validates and formats SNILS: XXX-XXX-XXX YY."""
    if not snils_input:
        return "", False, "СНИЛС отсутствует"
    
    cleaned = clean_text(snils_input)
    # Strip leading markers like 'СНИЛС:', 'страховой номер', '№'
    cleaned = re.sub(r'^(?:снилс|snils|страховой|номер|№)[:\s#№]*', '', cleaned, flags=re.I).strip()
    
    # OCR homoglyph fix for digits: O/o/О/о -> 0, l/I/i -> 1
    for ch, d in [("O", "0"), ("o", "0"), ("О", "0"), ("о", "0"), ("l", "1"), ("I", "1"), ("i", "1")]:
        cleaned = cleaned.replace(ch, d)
        
    digits = re.sub(r'\D', '', cleaned)
    
    if len(digits) != 11:
        return cleaned, False, f"Некорректная длина СНИЛС ({len(digits)} цифр вместо 11)"
    
    formatted = f"{digits[:3]}-{digits[3:6]}-{digits[6:9]} {digits[9:]}"
    num_part = digits[:9]
    check_part = int(digits[9:])
    
    if num_part in [c * 9 for c in '0123456789']:
        return formatted, False, "Некорректный номер СНИЛС (все цифры одинаковые)"
    
    s = sum(int(num_part[i]) * (9 - i) for i in range(9))
    if s < 100:
        c = s
    elif s in (100, 101):
        c = 0
    else:
        c = s % 101
        if c == 100 or c == 101:
            c = 0
            
    if c == check_part:
        return formatted, True, None
    else:
        return formatted, False, f"Ошибка контрольной суммы СНИЛС (ожидалось {c:02d}, введено {check_part:02d})"

MONTHS_RU = {
    'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4,
    'мая': 5, 'май': 5,
    'июн': 6, 'июл': 7,
    'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
}

def normalize_date(date_input: Optional[str]) -> Tuple[str, bool, Optional[str]]:
    """
    Normalizes date to DD.MM.YYYY.
    Supports both numeric (DD.MM.YYYY) and verbal Russian formats
    (e.g. '22 АВГУСТА 2005 ГОДА Г. НОВОСИБИРСК', '22 августа 2005 г.').
    """
    if not date_input:
        return "", False, "Дата отсутствует"
    
    cleaned = clean_text(date_input)
    cleaned, _ = clean_homoglyphs(cleaned)
    # Strip leading markers like 'д.р.:', 'дата рождения:', 'г.р.'
    cleaned = re.sub(r'^(?:(?:д\.?р\.?|рожд\.?|дата(?:\s+рождения)?|г\.?р\.?)[:\s]+)', '', cleaned, flags=re.I).strip()
    # Strip trailing year markers like 'г.', 'г', 'года'
    cleaned = re.sub(r'\s*г(?:ода|\.)?$', '', cleaned, flags=re.I).strip()
    
    # 0. Pre-clean OCR spaces inside numeric dates:
    # 0a. Spaces around separators: e.g. '26 . 07 . 1982' -> '26.07.1982'
    cleaned = re.sub(r'(\d)\s*([./\-])\s*(\d)', r'\1\2\3', cleaned)
    cleaned = re.sub(r'(\d)\s*([./\-])\s*(\d)', r'\1\2\3', cleaned)
    # 0b. Spaces inside year: e.g. '26.07.198 2', '26.07.19 82', '26.07.1 9 8 2'
    for _ in range(3):
        cleaned = re.sub(r'(\d{1,2}[./\-]\d{1,2}[./\-]\d{1,3})\s+(\d{1,3})', r'\1\2', cleaned)
    # 0c. Spaces inside day: e.g. '2 6.07.1982'
    cleaned = re.sub(r'\b(\d)\s+(\d[./\-])', r'\1\2', cleaned)
    # 0d. Spaces inside month: e.g. '26.0 7.1982'
    cleaned = re.sub(r'([./\-])(\d)\s+(\d[./\-])', r'\1\2\3', cleaned)
    
    # 1. Verbal Russian format: e.g. '22 АВГУСТА 2005 ГОДА Г. НОВОСИБИРСК'
    m_verbal = re.search(r'\b(\d{1,2})\s+([а-яА-ЯёЁ]{3,12})\s+(\d{4})(?:\s*г(?:ода|\.)?)?\b', cleaned, flags=re.I)
    if m_verbal:
        day = int(m_verbal.group(1))
        month_str = m_verbal.group(2).lower()
        year = int(m_verbal.group(3))
        
        month_num = None
        for prefix, num in MONTHS_RU.items():
            if month_str.startswith(prefix):
                month_num = num
                break
                
        if month_num and 1 <= day <= 31 and 1930 <= year <= 2035:
            formatted = f"{day:02d}.{month_num:02d}.{year}"
            return formatted, True, None

    # 1b. ISO date format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (common in Excel exports)
    m_iso = re.search(r'\b(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})(?:[ T]\d{2}:\d{2}:\d{2})?\b', cleaned)
    if m_iso:
        year, month, day = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if 1930 <= year <= 2035 and 1 <= month <= 12 and 1 <= day <= 31:
            formatted = f"{day:02d}.{month:02d}.{year}"
            return formatted, True, None

    # 2. Numeric format: DD.MM.YYYY or DD/MM/YYYY or DD-MM-YYYY or single-digit D.M.YYYY (supports trailing 'г', 'г.', 'года')
    m = re.search(r'\b(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})(?:\s*г(?:ода|\.)?)?(?!\d)', cleaned, flags=re.I)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 1900 if year > 30 else 2000
        if 1 <= day <= 31 and 1 <= month <= 12 and 1930 <= year <= 2035:
            formatted = f"{day:02d}.{month:02d}.{year}"
            warn = None
            if int(m.group(3)) < 100:
                warn = f"2-значный год преобразован в {year}"
            return formatted, True, warn
        else:
            return cleaned, False, f"Недопустимые значения даты: {cleaned}"
    
    return cleaned, False, f"Не удалось распознать формат даты: {cleaned}"

def clean_and_validate_contacts(contacts_raw: Optional[str]) -> Tuple[str, bool, Optional[str]]:
    """
    Cleans and validates email and phone.
    - Strips garbage (e.g. 'uuuuu', '111111', '-', 'нет') without highlighting yellow.
    - Validates email format and phone numbers.
    - If valid, formats as 'email, +7 (XXX) XXX-XX-XX'.
    - If user attempted an email or phone but made syntax errors, flags yellow.
    Returns (cleaned_text, has_yellow_flag, warning_message).
    """
    if not contacts_raw or not str(contacts_raw).strip():
        return "", False, None
        
    s = clean_text(contacts_raw)
    
    # 1. Pure garbage checks
    if re.fullmatch(r'([a-zA-Zа-яА-Я0-9])\1{2,}', s):
        return "", False, None
    if s.lower() in ['нет', 'отсутствует', '-', '--', 'б/н', 'none', 'null', 'nan', 'н/д']:
        return "", False, None
    if re.fullmatch(r'\d{1,7}', s):
        return "", False, None

    # 2. Extract valid emails
    emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', s)
    
    # 3. Extract and format valid Russian phones
    phone_formatted = None
    phone_candidates = re.findall(r'(?:\+7|8|7)?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', s)
    for cand in phone_candidates:
        c_digits = re.sub(r'\D', '', cand)
        if len(c_digits) == 11 and c_digits[0] in ('7', '8'):
            phone_formatted = f"+7 ({c_digits[1:4]}) {c_digits[4:7]}-{c_digits[7:9]}-{c_digits[9:]}"
            break
        elif len(c_digits) == 10 and c_digits[0] == '9':
            phone_formatted = f"+7 ({c_digits[0:3]}) {c_digits[3:6]}-{c_digits[6:8]}-{c_digits[8:]}"
            break
            
    valid_parts = []
    if emails:
        valid_parts.append(emails[0].lower())
    if phone_formatted:
        valid_parts.append(phone_formatted)
        
    if valid_parts:
        return ", ".join(valid_parts), False, None
        
    # 4. Check for broken email or phone attempts
    if '@' in s:
        return s, True, f"Некорректный адрес электронной почты: '{s}'"
        
    digits_seq = re.sub(r'\D', '', s)
    if '+' in s or (len(digits_seq) >= 7 and len(digits_seq) <= 12):
        return s, True, f"Неполный или некорректный номер телефона: '{s}'"
        
    return "", False, None

def infer_gender(last_name: str, first_name: str, patronymic: str) -> str:
    p_lower = patronymic.lower()
    if p_lower.endswith(('вич', 'ич', 'оглы', 'угли', 'улы')):
        return 'М'
    if p_lower.endswith(('вна', 'чна', 'инична', 'кызы', 'гызы')):
        return 'Ж'
    
    ln_lower = last_name.lower()
    if ln_lower.endswith(('ова', 'ева', 'ина', 'ына', 'ая', 'яя')):
        return 'Ж'
    if ln_lower.endswith(('ов', 'ев', 'ин', 'ын', 'ий', 'ый')):
        return 'М'
    
    fn_lower = first_name.lower()
    female_vowels = ('а', 'я', 'ия')
    male_a_names = {'илья', 'никита', 'данила', 'лука', 'фома', 'кузьма', 'савва', 'миша', 'саша', 'дима'}
    if fn_lower in male_a_names:
        return 'М'
    if fn_lower.endswith(female_vowels):
        return 'Ж'
    
    return 'М'

def decline_surname_dative(surname: str, gender: str) -> Tuple[str, bool]:
    s = surname.strip()
    if not s:
        return "", True
    s_lower = s.lower()
    
    if s_lower.endswith(('ко', 'их', 'ых', 'о', 'е', 'и', 'у', 'э', 'ю')):
        return s, True
    
    if gender == 'Ж':
        if s_lower.endswith(('ова', 'ева', 'ина', 'ына')):
            return s[:-1] + 'ой', True
        if s_lower.endswith('ая'):
            return s[:-2] + 'ой', True
        if s_lower.endswith('яя'):
            return s[:-2] + 'ей', True
        return s, True
    else:
        if s_lower.endswith(('ов', 'ев', 'ин', 'ын')):
            return s + 'у', True
        if s_lower.endswith(('ский', 'цкий', 'ской', 'цкой')):
            return s[:-2] + 'ому', True
        if s_lower.endswith(('ый', 'ой')):
            return s[:-2] + 'ому', True
        if s_lower.endswith('ий'):
            return s[:-2] + 'ему', True
        if s_lower.endswith('ец'):
            return s + 'у', False
        if s_lower.endswith(('б', 'в', 'г', 'д', 'ж', 'з', 'к', 'л', 'м', 'н', 'п', 'р', 'с', 'т', 'ф', 'х', 'ц', 'ч', 'ш', 'щ')):
            return s + 'у', True
        if s_lower.endswith('ь'):
            return s[:-1] + 'ю', True
        if s_lower.endswith('й'):
            return s[:-1] + 'ю', True
            
    return s, False

def decline_firstname_dative(firstname: str, gender: str) -> Tuple[str, bool]:
    fn = firstname.strip()
    if not fn:
        return "", True
    fn_lower = fn.lower()
    
    if fn_lower.endswith(('о', 'у', 'и', 'э', 'ю')):
        return fn, True
    if fn_lower.endswith(('а', 'я')):
        if fn_lower.endswith('ия'):
            return fn[:-1] + 'и', True
        return fn[:-1] + 'е', True
        
    if gender == 'М':
        if fn_lower == 'павел':
            return fn[:-2] + 'лу', True
        if fn_lower == 'лев':
            return fn[:-2] + 'ьву', True
        if fn_lower in ('пётр', 'петр'):
            return fn[:-1] + 'ру', True
        if fn_lower.endswith('ь'):
            return fn[:-1] + 'ю', True
        if fn_lower.endswith('й'):
            return fn[:-1] + 'ю', True
        if fn_lower[-1] in 'бвгджзклмнпрстфхцчшщ':
            return fn + 'у', True
            
    if gender == 'Ж':
        if fn_lower.endswith('ь'):
            return fn[:-1] + 'и', True
        return fn, True
        
    return fn, False

def decline_patronymic_dative(patronymic: str, gender: str) -> Tuple[str, bool]:
    p = patronymic.strip()
    if not p:
        return "", True
    p_lower = p.lower()
    
    if p_lower.endswith(('вич', 'ич')):
        return p + 'у', True
    if p_lower.endswith(('вна', 'чна', 'инична')):
        return p[:-1] + 'е', True
    if any(p_lower.endswith(s) for s in ['оглы', 'угли', 'улы', 'кызы', 'гызы', 'заде']):
        return p, True
        
    return p, False

LEGITIMATE_DOUBLE_CONSONANTS = (
    "геннад", "кирилл", "филипп", "илларион", "савв", "иннокент",
    "анн", "инн", "алл", "римм", "эмм", "жанн", "белл", "стелл", "нонн", "сусанн",
    "аполлон", "диграмм", "программ", "масс", "росс"
)

PATRONYMIC_TYPO_FIXES = {
    r"алексадрович\b": "Александрович",
    r"алексадровна\b": "Александровна",
    r"вячеславоич\b": "Вячеславович",
    r"станиславоич\b": "Станиславович",
    r"ярославоич\b": "Ярославович",
    r"ростиславоич\b": "Ростиславович",
    r"святославоич\b": "Святославович",
    r"владиславоич\b": "Владиславович",
    r"сергевич\b": "Сергеевич",
    r"дмитривич\b": "Дмитриевич",
    r"андревич\b": "Андреевич",
    r"алексевич\b": "Алексеевич",
    r"николаич\b": "Николаевич",
    r"михалович\b": "Михайлович",
    r"василевич\b": "Васильевич",
    r"анатолевич\b": "Анатольевич",
    r"владимрович\b": "Владимирович",
    r"владмирович\b": "Владимирович",
    r"контантинович\b": "Константинович",
    r"евгеневич\b": "Евгеньевич",
    r"валеревич\b": "Валерьевич",
    r"юревич\b": "Юрьевич",
    r"сергевна\b": "Сергеевна",
    r"дмитривна\b": "Дмитриевна",
    r"андревна\b": "Андреевна",
    r"алексевна\b": "Алексеевна",
    r"михаловна\b": "Михайловна",
    r"василевна\b": "Васильевна",
    r"анатолевна\b": "Анатольевна",
    r"владимровна\b": "Владимировна",
}

NAME_TYPO_FIXES = {
    r"\bалексадр\b": "Александр",
    r"\bвладмир\b": "Владимир",
    r"\bдмирий\b": "Дмитрий",
    r"\bконтантин\b": "Константин",
    r"\bвячелав\b": "Вячеслав",
    r"\bстанилав\b": "Станислав",
    r"\bгенадий\b": "Геннадий",
    r"\bкирил\b": "Кирилл",
    r"\bфилип\b": "Филипп",
    r"\bмихаилл\b": "Михаил",
}

PATRONYMIC_ENDINGS = ("ович", "евич", "ич", "ыч", "овна", "евна", "ична", "инична", "ычна", "оглы", "угли", "улы", "кызы", "гызы")

def clean_fio_word(w: str, word_idx: int = 0, total_words: int = 3) -> Tuple[str, List[str]]:
    """
    Cleans and corrects a single word of FIO:
    - Removes garbage characters
    - Fixes casing (Title Case)
    - Deduplicates accidental double vowels & consonants
    - Restores missing letters in standard names/patronymics
    """
    warnings = []
    orig = w
    
    # Strip garbage punctuation, quotes, numbers
    w_clean = re.sub(r'[^а-яА-ЯёЁa-zA-Z\-]', '', w)
    if not w_clean:
        return "", []
        
    w_clean, _ = clean_homoglyphs(w_clean)
    w_lower = w_clean.lower()
    is_pat = any(w_lower.endswith(end) for end in PATRONYMIC_ENDINGS)
    is_name = (word_idx == 1 and total_words >= 2)
    
    # Strip stray tail garbage after patronymics (e.g. 'Фанильевичывсвы' -> 'Фанильевич', 'Ивановичв' -> 'Иванович')
    # BUT preserve legitimate Russian case inflections:
    # -у (dative male: Александровичу), -е (dative female: Александровне),
    # -а (genitive: Александровича), -ем (instrumental: Александровичем),
    # -ей / -ой (instrumental female: Александровной), and surnames in -енко
    m_pat_tail = re.match(r'^([а-яА-ЯёЁ]{3,}(?:ович|евич|овна|евна|ична|ычна))([а-яА-ЯёЁ]{1,8})$', w_clean, flags=re.I)
    if m_pat_tail:
        stem_pat = m_pat_tail.group(1)
        tail = m_pat_tail.group(2)
        if tail.lower() not in ('у', 'е', 'а', 'ем', 'ей', 'ой', 'енко', 'ев', 'ева', 'ский', 'ская'):
            w_clean = stem_pat
            warnings.append(f"Удален мусорный хвост в отчестве: '{orig}' -> '{w_clean}'")
            w_lower = w_clean.lower()
            is_pat = True
            
    # 1. Check known missing letter dictionaries
    corrected_from_dict = False
    for pattern, repl in PATRONYMIC_TYPO_FIXES.items():
        if re.search(pattern, w_lower):
            w_clean = repl
            warnings.append(f"Восстановлена пропущенная буква в отчестве: '{orig}' -> '{repl}'")
            corrected_from_dict = True
            break
            
    if not corrected_from_dict:
        for pattern, repl in NAME_TYPO_FIXES.items():
            if re.search(pattern, w_lower):
                w_clean = repl
                warnings.append(f"Восстановлена пропущенная буква в имени: '{orig}' -> '{repl}'")
                corrected_from_dict = True
                break
                
    if not corrected_from_dict:
        # 2. Tripled letter deduplication: e.g. Ивааанович -> Иванович
        w_dedup = re.sub(r'([а-яА-ЯёЁa-zA-Z])\1{2,}', r'\1', w_clean)
        
        # 3. Accidental doubled vowels: protect "еевич" / "еевна", deduplicate other double vowels
        w_vowels = re.sub(r'([аиоуыэюя])\1+', r'\1', w_dedup, flags=re.IGNORECASE)
        w_vowels = re.sub(r'е{3,}(вич|вна)', r'ее\1', w_vowels, flags=re.IGNORECASE)
        w_vowels = re.sub(r'е{2,}(?!вич|вна)', r'е', w_vowels, flags=re.IGNORECASE)
        
        # 4. Accidental doubled consonants
        # Deduplicate initial doubled consonants (e.g. Ппетров -> Петров)
        w_cons = re.sub(r'^([бвгджзклмнпрстфхцчшщ])\1', r'\1', w_vowels, flags=re.IGNORECASE)
        # For patronymics and first names, deduplicate non-legitimate double consonants
        if is_pat or is_name:
            is_legit = any(root in w_cons.lower() for root in LEGITIMATE_DOUBLE_CONSONANTS)
            if not is_legit:
                w_cons = re.sub(r'([бвгджзклмнпрстфхцчшщ])\1+', r'\1', w_cons, flags=re.IGNORECASE)
            
        if w_cons.lower() != w_clean.lower():
            warnings.append(f"Устранено ошибочное задвоение букв: '{orig}' -> '{w_cons}'")
            
        w_clean = w_cons

    # Proper Title Casing (handles hyphenated names like Мамин-Сибиряк)
    w_title = "-".join([part.capitalize() for part in w_clean.split('-')])
    
    if orig != w_title and not warnings:
        if orig.islower():
            warnings.append(f"Исправлен регистр: '{orig}' -> '{w_title}'")
        elif orig != w_title:
            warnings.append(f"Скорректирован регистр: '{orig}' -> '{w_title}'")
            
    return w_title, warnings

def correct_fio_typos(raw_fio: str) -> Tuple[str, List[str]]:
    """
    Normalizes and cleans full FIO string:
    - Strips leading numbering (1., 1), №), bullets, quotes
    - Corrects each word (casing, double letters, missing letters)
    - Returns (clean_fio, warnings)
    """
    if not raw_fio:
        return "", []
        
    warnings = []
    t = clean_text(raw_fio)
    
    # Strip leading list markers: '1.', '1)', '1 -', '№1'
    t_clean = re.sub(r'^\s*(?:\d+[\.\)\-:]|№\s*\d+|\([0-9]+\)|\*|\-)\s*', '', t).strip()
    # Strip quotes and brackets
    t_clean = re.sub(r'^[\"\'«\(\[\{]+|[\"\'»\)\]\}]+$', '', t_clean).strip()
    
    # Rejoin patronymics split by space (OCR/typing typo, e.g. 'Александрови Ч' -> 'Александрович', 'Александрови Чу' -> 'Александровичу')
    m_split_ch = re.search(r'\b([а-яА-ЯёЁ]{3,}(?:ови|еви|ини|ыч|и))\s+([чЧ][уУеЕаАыЫ]?|[чЧ])\b', t_clean)
    if m_split_ch:
        orig_match = m_split_ch.group(0)
        rejoined = f"{m_split_ch.group(1)}{m_split_ch.group(2).lower()}"
        t_clean = t_clean[:m_split_ch.start()] + rejoined + t_clean[m_split_ch.end():]
        warnings.append(f"Устранено ошибочное разделение отчества пробелом: '{orig_match}' -> '{rejoined}'")

    m_split_a = re.search(r'\b([а-яА-ЯёЁ]{3,}(?:овн|евн|ичн))\s+([аАеЕыЫ]?|[аА])\b', t_clean)
    if m_split_a:
        orig_match = m_split_a.group(0)
        rejoined = f"{m_split_a.group(1)}{m_split_a.group(2).lower()}"
        t_clean = t_clean[:m_split_a.start()] + rejoined + t_clean[m_split_a.end():]
        warnings.append(f"Устранено ошибочное разделение отчества пробелом: '{orig_match}' -> '{rejoined}'")

    words = t_clean.split()
    clean_words = []
    for idx, w in enumerate(words):
        cw, w_warns = clean_fio_word(w, word_idx=idx, total_words=len(words))
        if cw:
            clean_words.append(cw)
            warnings.extend(w_warns)
            
    return " ".join(clean_words), warnings

def check_fio_anomalies(surname: str, firstname: str, patronymic: str) -> List[str]:
    warnings = []
    
    m = re.search(r'(вич|вна|овна|евна|ич|инична)([а-яa-z]+)', patronymic, flags=re.IGNORECASE)
    if m:
        warnings.append(f"Опечатка в отчестве: после суффикса '{m.group(1)}' обнаружены лишние символы '{m.group(2)}'")

    for part, label in [(surname, 'фамилии'), (firstname, 'имени'), (patronymic, 'отчестве')]:
        if re.search(r'([а-яА-Яa-zA-Z])\1{2,}', part):
            warnings.append(f"Подозрительное повторение букв в {label}: '{part}'")

    for part, label in [(surname, 'фамилии'), (firstname, 'имени'), (patronymic, 'отчестве')]:
        if any(seq in part.lower() for seq in ['ывс', 'фыва', 'йцук', 'asdf', 'qwer', 'zxcv']):
            warnings.append(f"Подозрительная комбинация символов в {label}: '{part}'")

    return warnings

def process_person_fio(
    raw_nominative: str,
    raw_dative: Optional[str] = None,
    explicit_gender: Optional[str] = None
) -> Dict[str, Any]:
    clean_nom, nom_corrections = correct_fio_typos(raw_nominative)
    nom_clean, nom_homoglyphs = clean_homoglyphs(clean_nom)
    
    if raw_dative:
        clean_dat, dat_corrections = correct_fio_typos(raw_dative)
        dat_clean, dat_homoglyphs = clean_homoglyphs(clean_dat)
    else:
        dat_clean, dat_homoglyphs = "", False
        dat_corrections = []
    
    nom_parts = [p.capitalize() for p in nom_clean.split()]
    
    if len(nom_parts) >= 3:
        surname, firstname, patronymic = nom_parts[0], nom_parts[1], " ".join(nom_parts[2:])
    elif len(nom_parts) == 2:
        surname, firstname, patronymic = nom_parts[0], nom_parts[1], ""
    elif len(nom_parts) == 1:
        surname, firstname, patronymic = nom_parts[0], "", ""
    else:
        return {
            "nom_fio": raw_nominative,
            "dat_fio": raw_dative or raw_nominative,
            "gender": explicit_gender or "М",
            "nom_warning": "Пустое или некорректное ФИО",
            "dat_warning": "Не удалось определить дательный падеж",
            "patronymic_warning": None,
            "has_yellow_flag": True,
            "yellow_columns": ["nom_fio", "dat_fio"]
        }
        
    gender = explicit_gender.upper() if explicit_gender in ('М', 'Ж') else infer_gender(surname, firstname, patronymic)
    
    anomalies = check_fio_anomalies(surname, firstname, patronymic)
    anomalies.extend(nom_corrections)
    
    s_dat, s_cert = decline_surname_dative(surname, gender)
    fn_dat, fn_cert = decline_firstname_dative(firstname, gender)
    p_dat, p_cert = decline_patronymic_dative(patronymic, gender)
    
    auto_dat_parts = [p for p in [s_dat, fn_dat, p_dat] if p]
    auto_dat_fio = " ".join(auto_dat_parts)
    
    dat_warning = None
    has_yellow_flag = False
    yellow_columns = []
    final_dat_fio = auto_dat_fio
    
    if dat_clean:
        if dat_clean.lower() == nom_clean.lower():
            final_dat_fio = auto_dat_fio
            dat_warning = "Заказчик не просклонял ФИО в дательном падеже; выполнено автоматическое склонение"
            has_yellow_flag = True
            yellow_columns.append("dat_fio")
        elif dat_clean.lower() != auto_dat_fio.lower():
            final_dat_fio = auto_dat_fio
            dat_warning = f"Расхождение в дательном падеже (заказчик: '{dat_clean}', авто: '{auto_dat_fio}')"
            has_yellow_flag = True
            yellow_columns.append("dat_fio")
        else:
            final_dat_fio = dat_clean
    else:
        final_dat_fio = auto_dat_fio
        if not (s_cert and fn_cert and p_cert):
            dat_warning = "Нестандартное окончание имени или фамилии при автосклонении"
            has_yellow_flag = True
            yellow_columns.append("dat_fio")
            
    patronymic_warning = None
    if patronymic:
        p_lower = patronymic.lower()
        if not (p_lower.endswith(('вич', 'ич', 'вна', 'чна', 'инична', 'оглы', 'угли', 'кызы', 'заде'))):
            patronymic_warning = f"Нетипичное окончание отчества: '{patronymic}'"
            has_yellow_flag = True
            if "nom_fio" not in yellow_columns:
                yellow_columns.append("nom_fio")
            if "dat_fio" not in yellow_columns:
                yellow_columns.append("dat_fio")
                
    nom_warning = None
    if anomalies:
        nom_warning = "; ".join(anomalies)
        has_yellow_flag = True
        if "nom_fio" not in yellow_columns:
            yellow_columns.append("nom_fio")
        if "dat_fio" not in yellow_columns:
            yellow_columns.append("dat_fio")
            
    if nom_homoglyphs:
        nom_warning = (nom_warning + "; " if nom_warning else "") + "Обнаружены и исправлены латинские символы в ФИО"
        has_yellow_flag = True
        if "nom_fio" not in yellow_columns:
            yellow_columns.append("nom_fio")

    return {
        "nom_fio": " ".join(nom_parts),
        "dat_fio": final_dat_fio,
        "surname": surname,
        "firstname": firstname,
        "patronymic": patronymic,
        "gender": gender,
        "nom_warning": nom_warning,
        "dat_warning": dat_warning,
        "patronymic_warning": patronymic_warning,
        "corrections": nom_corrections,
        "has_yellow_flag": has_yellow_flag,
        "yellow_columns": yellow_columns
    }
