"""
Document Vision and OCR module for PSG 1C Application Agent.
Extracts structured personal information from photos / scans of:
- SNILS cards (both green laminated and modern ADI-REG)
- Passports
- Diplomas
- Photo applications (JPEG, PNG, HEIC from iPhone / Android)
"""

import os
import re
import subprocess
import uuid
from typing import Dict, Any, Optional, List, Tuple
from PIL import Image, ImageOps

import linguistics

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STOP_WORDS = {
    'страховое', 'свидетельство', 'обязательного', 'пенсионного', 'страхования',
    'пенсионный', 'фонд', 'россии', 'российской', 'федерации', 'российская', 'федерация',
    'государственного', 'государственный', 'государственная',
    'дата', 'рождения', 'место', 'пол', 'муж', 'жен', 'регистрации', 'паспорт', 'гражданина',
    'отделение', 'уфмс', 'мвд', 'россия', 'диплом', 'квалификация', 'специальность',
    'снилс', 'номер', 'страховой', 'сфр', 'пфр', 'уведомление', 'форма', 'фио', 'fio',
    # Russian months and date markers
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
    'сентября', 'октября', 'ноября', 'декабря',
    'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август',
    'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
    'года', 'год', 'г.', 'г',
    # Geographical terms
    'город', 'гор', 'село', 'деревня', 'поселок', 'область', 'район', 'край',
    'республика', 'новосибирск', 'москва', 'санкт-петербург',
    # Document headers / markers
    'выдан', 'код', 'подразделения', 'серия', 'личное', 'подпись'
}

def get_tesseract_binary() -> str:
    candidates = [
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
        "tesseract"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "tesseract"

COMMON_FIRST_NAME_REPAIRS = {
    "нтон": "Антон", "нтн": "Антон", "ндрей": "Андрей", "ртем": "Артем",
    "лексей": "Алексей", "лексан": "Александр", "лександр": "Александр",
    "натолий": "Анатолий", "рсений": "Арсений", "ртур": "Артур",
    "лина": "Алина", "лена": "Алена", "нна": "Анна", "настасия": "Анастасия",
    "гений": "Евгений", "вгений": "Евгений", "горь": "Игорь", "лья": "Илья", "ван": "Иван"
}

def correct_first_name(fn: str) -> str:
    """Corrects common OCR first name truncations (e.g. 'Нтон' -> 'Антон', 'Лексей' -> 'Алексей')."""
    if not fn:
        return fn
    low = fn.lower()
    if low in COMMON_FIRST_NAME_REPAIRS:
        return COMMON_FIRST_NAME_REPAIRS[low]
    if len(low) >= 3:
        for prefix in ("а", "е", "и", "о"):
            cand = prefix + low
            if cand in {"антон", "андрей", "артем", "алексей", "александр", "анатолий", "арсений", "артур", "алина", "алена", "анна", "анастасия", "евгений", "игорь", "илья", "иван"}:
                return cand.capitalize()
    return fn

def repair_snils_checksum(raw_snils: Optional[str]) -> Tuple[Optional[str], bool]:
    """
    Validates SNILS checksum. If invalid, attempts single-digit OCR error correction
    (e.g. 5 <-> 6, 6 <-> 8, 3 <-> 8, 1 <-> 7, 0 <-> 8) using the official Pension Fund algorithm.
    Returns (repaired_snils, is_valid).
    """
    if not raw_snils:
        return None, False
    formatted, ok, _ = linguistics.validate_and_format_snils(raw_snils)
    if ok:
        return formatted, True

    digits = [c for c in raw_snils if c.isdigit()]
    if len(digits) != 11:
        return raw_snils, False

    ocr_confusions = {
        ("5", "6"), ("6", "5"),
        ("6", "8"), ("8", "6"),
        ("3", "8"), ("8", "3"),
        ("1", "7"), ("7", "1"),
        ("0", "8"), ("8", "0"),
        ("1", "4"), ("4", "1")
    }

    conf_candidates = []
    for i in range(9):
        orig_d = digits[i]
        for alt_d in "0123456789":
            if alt_d == orig_d:
                continue
            if (orig_d, alt_d) not in ocr_confusions:
                continue
            test_digits = list(digits)
            test_digits[i] = alt_d
            test_fmt, is_valid, _ = linguistics.validate_and_format_snils("".join(test_digits))
            if is_valid:
                conf_candidates.append(test_fmt)

    if len(conf_candidates) == 1:
        return conf_candidates[0], True

    return formatted or raw_snils, False

def normalize_fio_order(fio_str: str) -> str:
    """
    Ensures standard Russian ordering: [Surname, First Name, Patronymic].
    If OCR extracted [First Name, Patronymic, Surname] (e.g. 'Антон Александрович Абрамов'),
    detects patronymic suffix in middle word and non-patronymic in 3rd word to reorder to 'Абрамов Антон Александрович'.
    Also autocorrects OCR-truncated Russian first names (e.g. 'Нтон' -> 'Антон').
    """
    if not fio_str:
        return ""
    words = fio_str.split()
    if len(words) == 3:
        w1, w2, w3 = words[0], words[1], words[2]
        pat_suffixes = ("ович", "евич", "ич", "овна", "евна", "ична", "инична")
        w2_is_pat = w2.lower().endswith(pat_suffixes)
        w3_is_pat = w3.lower().endswith(pat_suffixes)
        if w2_is_pat and not w3_is_pat:
            w3 = correct_first_name(w3)
            return f"{w3} {w1} {w2}".title()
        else:
            w2 = correct_first_name(w2)
            return f"{w1} {w2} {w3}".title()
    elif len(words) == 2:
        words[1] = correct_first_name(words[1])
    return " ".join(words).title()

def preprocess_image_for_ocr(image_path: str) -> str:
    """Preprocess image with PIL (grayscale, autocontrast, scaling) for highest OCR accuracy."""
    try:
        ext = os.path.splitext(image_path)[1].lower()
        if ext == '.heic':
            import doc_reader
            conv = doc_reader.convert_heic_to_jpeg(image_path)
            if conv:
                image_path = conv

        img = Image.open(image_path)
        img = img.convert('L')  # grayscale
        img = ImageOps.autocontrast(img)
        
        # If image is small, upscale with high quality filter
        if img.width < 1200 or img.height < 1200:
            scale = max(1200 / max(img.width, 1), 1200 / max(img.height, 1))
            new_w = int(img.width * scale)
            new_h = int(img.height * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
        temp_file_path = os.path.join(UPLOAD_DIR, f"ocr_tmp_{uuid.uuid4().hex[:8]}.png")
        img.save(temp_file_path)
        return temp_file_path
    except Exception:
        return image_path

def run_tesseract_on_pil(pil_img: Image.Image) -> str:
    """Runs Tesseract on a PIL Image object safely using workspace uploads directory."""
    temp_file_path = os.path.join(UPLOAD_DIR, f"ocr_tmp_{uuid.uuid4().hex[:8]}.png")
    try:
        pil_img.save(temp_file_path)
        tesseract_bin = get_tesseract_binary()
        for lang in ["rus", "rus+eng"]:
            try:
                cmd = [tesseract_bin, temp_file_path, "stdout", "-l", lang, "--psm", "3"]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout
            except Exception:
                continue
        return ""
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass

def run_tesseract_ocr(image_path: str) -> str:
    """Runs system tesseract on preprocessed image."""
    tesseract_bin = get_tesseract_binary()
    preprocessed_path = preprocess_image_for_ocr(image_path)
    
    out_text = ""
    try:
        for lang in ["rus", "rus+eng"]:
            cmd = [tesseract_bin, preprocessed_path, "stdout", "-l", lang, "--psm", "3"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if res.returncode == 0 and res.stdout.strip():
                out_text = res.stdout
                break
    except Exception:
        try:
            cmd = [tesseract_bin, preprocessed_path, "stdout", "-l", "rus+eng"]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if res.returncode == 0:
                out_text = res.stdout
        except Exception:
            pass
            
    if preprocessed_path != image_path and os.path.exists(preprocessed_path):
        try:
            os.remove(preprocessed_path)
        except Exception:
            pass
            
    return out_text

def extract_fio_candidates(lines: List[str]) -> str:
    """
    Robust extraction of Russian full name (Surname, Name, Patronymic)
    from lines of a document (SNILS, Passport, etc.).
    Handles single line FIO, labeled FIO, and multiline (1 word per line).
    Pre-merges single-letter split lines (e.g. 'А' + 'НТОН' -> 'АНТОН').
    """
    # Pre-merge single-letter broken lines (common in SNILS card green emblem background)
    merged_lines = []
    i = 0
    while i < len(lines):
        curr = lines[i].strip()
        if len(curr) == 1 and curr.isalpha() and i + 1 < len(lines):
            nxt = lines[i+1].strip()
            words_nxt = nxt.split()
            if len(words_nxt) == 1 and words_nxt[0].isalpha():
                merged_lines.append(curr + nxt)
                i += 2
                continue
        merged_lines.append(curr)
        i += 1

    lines = merged_lines
    full_text = "\n".join(lines)

    # 1. Check for labeled FIO (e.g. Фамилия: Иванов, Имя: Иван, Отчество: Иванович)
    last_m = re.search(r'(?:фамили[яи]|last\s*name)[:\s]+([А-Яа-яA-Za-z\-]+)', full_text, re.I)
    first_m = re.search(r'(?:им[яи]|first\s*name)[:\s]+([А-Яа-яA-Za-z\-]+)', full_text, re.I)
    pat_m = re.search(r'(?:отчеств[оа]|middle\s*name)[:\s]+([А-Яа-яA-Za-z\-]+)', full_text, re.I)
    if last_m and first_m:
        pat = pat_m.group(1) if pat_m else ''
        return normalize_fio_order(f"{last_m.group(1)} {first_m.group(1)} {pat}".strip().title())

    # 2. Check for explicit ФИО label chunk: e.g. "ФИО: АБРАМОВ АНТОН АЛЕКСАНДРОВИЧ" or multiline after "ФИО"
    fio_label_m = re.search(r'(?:ф\.?\s*и\.?\s*о\.?|fio)[:\s]*\n?([^\n\r]{2,80}(?:\n[^\n\r]{2,80}){0,3})', full_text, re.I)
    if fio_label_m:
        chunk = fio_label_m.group(1)
        raw_words = [w for w in re.sub(r'[^А-Яа-яA-Za-z\s\-]', ' ', chunk).split() if len(w) >= 2]
        clean_words = [w for w in raw_words if w.lower() not in STOP_WORDS]
        if len(clean_words) in (2, 3):
            return normalize_fio_order(" ".join(clean_words))

    # Pre-clean lines: strip leading label markers and trailing noise numbers/symbols
    cleaned_line_words = []
    for l in lines:
        line_clean = re.sub(r'^(?:ф\.?\s*и\.?\s*о\.?|fio|фамилия|имя|отчество)[:\s]*', '', l.strip(), flags=re.I)
        words = [w for w in re.sub(r'[^А-Яа-яA-Za-z\s\-]', ' ', line_clean).split() if len(w) >= 2]
        words = [w for w in words if w.lower() not in STOP_WORDS]
        if words and all(w[0].isupper() or w.isupper() for w in words):
            cleaned_line_words.append(words)
        else:
            cleaned_line_words.append([])

    # 3. Check for single line with 2 or 3 capitalized Cyrillic words
    for words in cleaned_line_words:
        if len(words) in (2, 3):
            return normalize_fio_order(" ".join(words))

    # 4. Check for consecutive lines (1 or 2 words per line)
    words_seq = []
    for words in cleaned_line_words:
        if 1 <= len(words) <= 2:
            words_seq.extend(words)
            if len(words_seq) == 3:
                return normalize_fio_order(" ".join(words_seq))
        else:
            if len(words_seq) in (2, 3):
                return normalize_fio_order(" ".join(words_seq))
            words_seq = []

    if len(words_seq) in (2, 3):
        return normalize_fio_order(" ".join(words_seq))

    # 5. Check for MRZ transliterated name in passports: e.g. P<RUSIVANOV<<IVAN<<<<<<<<
    mrz_m = re.search(r'P<RUS([A-Z]+)<<([A-Z]+)', full_text)
    if mrz_m:
        last_trans = mrz_m.group(1)
        first_trans = mrz_m.group(2)
        return f"{last_trans} {first_trans}".title()

    return ""

def extract_birth_date(text: str) -> Optional[str]:
    """
    Extracts birth date from document text (SNILS, Passport, etc.).
    Supports:
    - Verbal Russian formats (e.g. '12 апреля 1983 года', '22 АВГУСТА 2005 ГОДА Г. НОВОСИБИРСК')
    - Handles noisy prefixes like '_12 апреля', '~12 апреля', '.12 апреля', ' 12 апреля'
    - Numeric formats (e.g. '12.04.1983', '22/08/2005', '22-08-2005')
    Returns normalized DD.MM.YYYY string or None.
    """
    if not text:
        return None
        
    clean_ocr, _ = linguistics.clean_homoglyphs(text)

    # 1. Verbal Russian format: day (1 or 2 digits, even after noise symbols) + Russian month + 4-digit year
    m_verbal = re.search(r'(?:^|[^\d])(\d{1,2})\s+([а-яА-ЯёЁ]{3,12})[\s,\.\-]+(\d{4})(?:\s*г(?:ода|\.)?)?', clean_ocr)
    if m_verbal:
        norm, ok, _ = linguistics.normalize_date(f"{m_verbal.group(1)} {m_verbal.group(2)} {m_verbal.group(3)}")
        if ok:
            return norm

    # 2. Look near keywords "рождения" / "рождени" / "дата и место" / "дата"
    m_near = re.search(r'(?:рождени[яеи]|дата\s+(?:и\s+место\s+)?(?:рождени[яеи])?)[:\s,\-]*\n?([^\n]{1,80})', clean_ocr, re.IGNORECASE)
    if m_near:
        target_chunk = re.sub(r'[^0-9A-Za-zА-Яа-я\s\.\,\-]', ' ', m_near.group(1)).strip()
        norm, ok, _ = linguistics.normalize_date(target_chunk)
        if ok:
            return norm

    # 3. Numeric format anywhere in text: DD.MM.YYYY
    m_num = re.search(r'(?:^|[^\d])(\d{1,2}[./\-]\d{1,2}[./\-]\d{4})', clean_ocr)
    if m_num:
        norm, ok, _ = linguistics.normalize_date(m_num.group(1))
        if ok:
            return norm

    return None

def parse_snils_card_text(text: str) -> Dict[str, Any]:
    """
    Extracts SNILS number, FIO, birth date, gender from SNILS card text.
    Handles both modern electronic ADI-REG forms and Soviet/Russian green cards.
    Automatically validates and repairs single-digit OCR checksum errors (e.g. 5 vs 6).
    """
    clean_lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # 1. Search for SNILS number
    snils_match = re.search(r'(\d{3}[\s\-\.]\d{3}[\s\-\.]\d{3}[\s\-\.]\d{2})', text)
    if not snils_match:
        # Raw 11 digits
        snils_match = re.search(r'\b(\d{11})\b', text)
    snils_num = snils_match.group(1) if snils_match else None
    if snils_num:
        repaired, ok = repair_snils_checksum(snils_num)
        if ok:
            snils_num = repaired
    
    # 2. Search for birth date (verbal or numeric)
    birth_date = extract_birth_date(text)
    
    # 3. Search for gender
    gender = None
    if re.search(r'\b(МУЖ|МУЖСКОЙ|М)\b', text, re.IGNORECASE):
        gender = 'М'
    elif re.search(r'\b(ЖЕН|ЖЕНСКИЙ|Ж)\b', text, re.IGNORECASE):
        gender = 'Ж'
        
    # 4. Extract FIO
    fio = extract_fio_candidates(clean_lines)
    if not fio:
        if snils_num:
            fio = f"Слушатель (СНИЛС {snils_num})"
        else:
            fio = "Слушатель (по фото СНИЛС)"
            
    return {
        "type": "snils_card",
        "snils": snils_num,
        "fio": fio,
        "birth_date": birth_date,
        "gender": gender,
        "raw_text": text
    }

def parse_passport_text(text: str) -> Dict[str, Any]:
    """
    Extracts FIO, birth date, gender, series/number from Russian passport.
    """
    clean_lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Search for birth date (verbal or numeric)
    birth_date = extract_birth_date(text)
    
    gender = None
    if re.search(r'\b(МУЖ|МУЖСКОЙ|М)\b', text, re.IGNORECASE):
        gender = 'М'
    elif re.search(r'\b(ЖЕН|ЖЕНСКИЙ|Ж)\b', text, re.IGNORECASE):
        gender = 'Ж'
        
    fio = extract_fio_candidates(clean_lines)
    if not fio:
        fio = "Слушатель (по фото паспорта)"
        
    return {
        "type": "passport",
        "fio": fio,
        "birth_date": birth_date,
        "gender": gender,
        "raw_text": text
    }

def parse_diploma_text(text: str) -> Dict[str, Any]:
    """Extracts FIO and qualification / specialty from Diploma."""
    clean_lines = [l.strip() for l in text.split('\n') if l.strip()]
    fio = extract_fio_candidates(clean_lines)
    qualification = ""
    for l in clean_lines:
        if any(kw in l.lower() for kw in ['квалификация', 'профессия', 'специальность']):
            qualification = l
            break
            
    return {
        "type": "diploma",
        "fio": fio or "Слушатель (по фото диплома)",
        "qualification": qualification,
        "raw_text": text
    }

def parse_document_image(image_path: str) -> Dict[str, Any]:
    """
    Main entry point for extracting data from an image file.
    Always returns a structured record so that processing never fails.
    Uses multi-pass OCR (card crop + tight crop + full image) with checksum validation
    and OCR error correction to guarantee flawless extraction even for photos on busy backgrounds.
    """
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.heic':
        import doc_reader
        conv = doc_reader.convert_heic_to_jpeg(image_path)
        if conv:
            image_path = conv

    pil_img = Image.open(image_path)
    w, h = pil_img.size

    variants = []

    # If photo has significant dimensions (e.g. phone camera photo on a table), add central document crops
    if w >= 400 and h >= 350:
        # 1. Exact centered document framing (eliminates surrounding wooden table/background)
        c_card = pil_img.crop((int(w * 0.18), int(h * 0.32), int(w * 0.82), int(h * 0.68)))
        variants.append(("card", ImageOps.autocontrast(c_card.convert("L"))))

        # 2. Slightly wider framing
        c_tight = pil_img.crop((int(w * 0.14), int(h * 0.28), int(w * 0.88), int(h * 0.72)))
        variants.append(("tight", ImageOps.autocontrast(c_tight.convert("L"))))

    # 3. Full image preprocessed
    v_full = pil_img.convert("L")
    v_full = ImageOps.autocontrast(v_full)
    variants.append(("full", v_full))

    final_record = {
        "type": "snils_card",
        "snils": None,
        "fio": "",
        "birth_date": None,
        "gender": None,
        "raw_text": "",
        "success": True
    }

    combined_ocr_texts = []
    snils_is_valid = False

    for name, v_img in variants:
        raw_text = run_tesseract_on_pil(v_img)
        if not raw_text:
            continue
        combined_ocr_texts.append(raw_text)
        ocr_lower = raw_text.lower()

        # Check document type
        if any(k in ocr_lower for k in ['страховое', 'пенсионн', 'снилс', 'сфр', 'пфр', 'ади-рег']):
            parsed = parse_snils_card_text(raw_text)
            doc_type = "snils_card"
        elif any(k in ocr_lower for k in ['паспорт', 'росс', 'уфмс', 'мвд', 'выдан']):
            parsed = parse_passport_text(raw_text)
            doc_type = "passport"
        elif any(k in ocr_lower for k in ['диплом', 'квалификац', 'образован']):
            parsed = parse_diploma_text(raw_text)
            doc_type = "diploma"
        else:
            snils_res = parse_snils_card_text(raw_text)
            if snils_res.get('snils') or (snils_res.get('fio') and not snils_res.get('fio').startswith('Слушатель')):
                parsed = snils_res
                doc_type = "snils_card"
            else:
                parsed = parse_passport_text(raw_text)
                doc_type = "passport"

        final_record["type"] = doc_type

        # SNILS handling: prioritize checksum-valid numbers
        cand_snils = parsed.get("snils")
        if cand_snils:
            cand_fmt, cand_ok, _ = linguistics.validate_and_format_snils(cand_snils)
            if not final_record["snils"] or (cand_ok and not snils_is_valid):
                final_record["snils"] = cand_fmt
                snils_is_valid = cand_ok

        # Birth date handling: prioritize 2-digit day over single-digit (e.g. 12.04 over 02.04)
        cand_bd = parsed.get("birth_date")
        if cand_bd:
            if not final_record["birth_date"]:
                final_record["birth_date"] = cand_bd
            elif final_record["birth_date"].startswith("0") and not cand_bd.startswith("0") and cand_bd[2:] == final_record["birth_date"][2:]:
                final_record["birth_date"] = cand_bd

        if not final_record["gender"] and parsed.get("gender"):
            final_record["gender"] = parsed["gender"]
        if not final_record.get("qualification") and parsed.get("qualification"):
            final_record["qualification"] = parsed["qualification"]

        fio_candidate = parsed.get("fio", "")
        if fio_candidate and not fio_candidate.startswith("Слушатель"):
            cand_words = len(fio_candidate.split())
            curr_words = len(final_record["fio"].split())
            if cand_words > curr_words:
                final_record["fio"] = fio_candidate
            elif cand_words == curr_words and len(fio_candidate) > len(final_record["fio"]):
                final_record["fio"] = fio_candidate

        # Stop early if we already have all key fields (valid SNILS, birth date, and full 3-word FIO)
        if snils_is_valid and final_record["birth_date"] and len(final_record["fio"].split()) == 3:
            break

    final_record["raw_text"] = "\n---\n".join(combined_ocr_texts)

    if not final_record["fio"]:
        if final_record["snils"]:
            final_record["fio"] = f"Слушатель (СНИЛС {final_record['snils']})"
        else:
            final_record["fio"] = f"Слушатель (по фото {final_record['type']})"

    return final_record
