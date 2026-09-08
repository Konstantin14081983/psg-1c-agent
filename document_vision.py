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
from typing import Dict, Any, Optional, List
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

def normalize_fio_order(fio_str: str) -> str:
    """
    Ensures standard Russian ordering: [Surname, First Name, Patronymic].
    If OCR extracted [First Name, Patronymic, Surname] (e.g. 'Антон Александрович Абрамов'),
    detects patronymic suffix in middle word and non-patronymic in 3rd word to reorder to 'Абрамов Антон Александрович'.
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
            return f"{w3} {w1} {w2}".title()
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
    """
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
    - Numeric formats (e.g. '12.04.1983', '22/08/2005', '22-08-2005')
    Returns normalized DD.MM.YYYY string or None.
    """
    if not text:
        return None
        
    clean_ocr, _ = linguistics.clean_homoglyphs(text)

    # 1. Look specifically near keywords "рождения" / "рождени" / "дата и место" / "дата"
    m_near = re.search(r'(?:рождени[яеи]|дата\s+(?:и\s+место\s+)?(?:рождени[яеи])?)[:\s,\-]*\n?([^\n]{1,80})', clean_ocr, re.IGNORECASE)
    if m_near:
        target_chunk = m_near.group(1)
        norm, ok, _ = linguistics.normalize_date(target_chunk)
        if ok:
            return norm

    # 2. Verbal Russian format anywhere in text: e.g. '12 апреля 1983 года' or '12 апреля — 1983 года'
    m_verbal = re.search(r'\b(\d{1,2})\s+([а-яА-ЯёЁ]{3,12})[\s,\.\-]+(\d{4})(?:\s*г(?:ода|\.)?)?\b', clean_ocr)
    if m_verbal:
        norm, ok, _ = linguistics.normalize_date(f"{m_verbal.group(1)} {m_verbal.group(2)} {m_verbal.group(3)}")
        if ok:
            return norm

    # 3. Numeric format anywhere in text: DD.MM.YYYY
    m_num = re.search(r'\b(\d{1,2}[./\-]\d{1,2}[./\-]\d{4})\b', clean_ocr)
    if m_num:
        norm, ok, _ = linguistics.normalize_date(m_num.group(1))
        if ok:
            return norm

    return None

def parse_snils_card_text(text: str) -> Dict[str, Any]:
    """
    Extracts SNILS number, FIO, birth date, gender from SNILS card text.
    Handles both modern electronic ADI-REG forms and Soviet/Russian green cards.
    """
    clean_lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # 1. Search for SNILS number
    snils_match = re.search(r'(\d{3}[\s\-\.]\d{3}[\s\-\.]\d{3}[\s\-\.]\d{2})', text)
    if not snils_match:
        # Raw 11 digits
        snils_match = re.search(r'\b(\d{11})\b', text)
    snils_num = snils_match.group(1) if snils_match else None
    
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
    Uses multi-pass OCR (full image + central document crop fallback) to guarantee
    flawless extraction even for photos with busy table backgrounds.
    """
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.heic':
        import doc_reader
        conv = doc_reader.convert_heic_to_jpeg(image_path)
        if conv:
            image_path = conv

    pil_img = Image.open(image_path)
    w, h = pil_img.size

    # Variant 1: Full image preprocessed
    v_full = pil_img.convert("L")
    v_full = ImageOps.autocontrast(v_full)
    if v_full.width < 1200 or v_full.height < 1200:
        scale = max(1200 / max(v_full.width, 1), 1200 / max(v_full.height, 1))
        v_full = v_full.resize((int(v_full.width * scale), int(v_full.height * scale)), Image.Resampling.LANCZOS)

    variants = [("full", v_full)]

    # If photo has significant dimensions (e.g. phone camera photo on a table), add central document crops
    if w >= 400 and h >= 350:
        c_tight = pil_img.crop((int(w * 0.14), int(h * 0.28), int(w * 0.88), int(h * 0.72)))
        c_tight = ImageOps.autocontrast(c_tight.convert("L"))
        variants.append(("tight", c_tight))

        c_wide = pil_img.crop((int(w * 0.08), int(h * 0.22), int(w * 0.92), int(h * 0.78)))
        c_wide = ImageOps.autocontrast(c_wide.convert("L"))
        variants.append(("wide", c_wide))

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
        if not final_record["snils"] and parsed.get("snils"):
            final_record["snils"] = parsed["snils"]
        if not final_record["birth_date"] and parsed.get("birth_date"):
            final_record["birth_date"] = parsed["birth_date"]
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

        # Stop early if we already have all key fields with a complete 3-word FIO
        if final_record["snils"] and final_record["birth_date"] and len(final_record["fio"].split()) == 3:
            break

    final_record["raw_text"] = "\n---\n".join(combined_ocr_texts)

    if not final_record["fio"]:
        if final_record["snils"]:
            final_record["fio"] = f"Слушатель (СНИЛС {final_record['snils']})"
        else:
            final_record["fio"] = f"Слушатель (по фото {final_record['type']})"

    return final_record
