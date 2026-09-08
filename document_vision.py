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
import tempfile
from typing import Dict, Any, Optional, List
from PIL import Image, ImageOps

import linguistics

STOP_WORDS = {
    'страховое', 'свидетельство', 'обязательного', 'пенсионного', 'страхования',
    'пенсионный', 'фонд', 'россии', 'российской', 'федерации', 'дата', 'рождения',
    'место', 'пол', 'муж', 'жен', 'регистрации', 'паспорт', 'гражданина',
    'отделение', 'уфмс', 'мвд', 'россия', 'диплом', 'квалификация', 'специальность',
    'снилс', 'номер', 'страховой', 'сфр', 'пфр', 'уведомление', 'форма'
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
            
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        img.save(temp_file.name)
        temp_file.close()
        return temp_file.name
    except Exception as e:
        return image_path

def run_tesseract_ocr(image_path: str) -> str:
    """Runs system tesseract on preprocessed image."""
    tesseract_bin = get_tesseract_binary()
    preprocessed_path = preprocess_image_for_ocr(image_path)
    
    out_text = ""
    try:
        cmd = [tesseract_bin, preprocessed_path, "stdout", "-l", "rus+eng", "--psm", "3"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if res.returncode == 0:
            out_text = res.stdout
    except Exception:
        # Fallback to default PSM
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
    Handles single line FIO and multiline (1 word per line).
    """
    # 1. Check for labeled FIO (e.g. Фамилия: Иванов, Имя: Иван, Отчество: Иванович)
    full_text = "\n".join(lines)
    last_m = re.search(r'(?:фамили[яи]|last\s*name)[:\s]+([А-Яа-яA-Za-z\-]+)', full_text, re.I)
    first_m = re.search(r'(?:им[яи]|first\s*name)[:\s]+([А-Яа-яA-Za-z\-]+)', full_text, re.I)
    pat_m = re.search(r'(?:отчеств[оа]|middle\s*name)[:\s]+([А-Яа-яA-Za-z\-]+)', full_text, re.I)
    if last_m and first_m:
        pat = pat_m.group(1) if pat_m else ''
        return f"{last_m.group(1)} {first_m.group(1)} {pat}".strip().title()

    # 2. Check for single line with 2 or 3 capitalized Cyrillic words
    for l in lines:
        words = [w for w in l.split() if w.isalpha()]
        if len(words) in (2, 3) and not any(w.lower() in STOP_WORDS for w in words):
            if all(len(w) >= 2 and w[0].isupper() for w in words):
                return " ".join(words).title()

    # 3. Check for 3 consecutive lines with single capitalized words (standard green card)
    words_seq = []
    for l in lines:
        if re.search(r'\d', l):
            continue
        words = [w for w in l.split() if w.isalpha()]
        if len(words) in (1, 2) and not any(w.lower() in STOP_WORDS for w in words):
            if all(len(w) >= 2 and w[0].isupper() for w in words):
                words_seq.extend(words)
                if len(words_seq) == 3:
                    return " ".join(words_seq).title()
        else:
            if len(words_seq) in (2, 3):
                return " ".join(words_seq).title()
            words_seq = []

    if len(words_seq) in (2, 3):
        return " ".join(words_seq).title()

    # 4. Check for MRZ transliterated name in passports: e.g. P<RUSIVANOV<<IVAN<<<<<<<<
    mrz_m = re.search(r'P<RUS([A-Z]+)<<([A-Z]+)', full_text)
    if mrz_m:
        last_trans = mrz_m.group(1)
        first_trans = mrz_m.group(2)
        return f"{last_trans} {first_trans}".title()

    return ""

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
    
    # 2. Search for birth date
    date_match = re.search(r'(\d{2}[./\-]\d{2}[./\-]\d{4})', text)
    birth_date = date_match.group(1) if date_match else None
    
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
    
    date_match = re.search(r'(\d{2}[./\-]\d{2}[./\-]\d{4})', text)
    birth_date = date_match.group(1) if date_match else None
    
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
    """
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.heic':
        import doc_reader
        conv = doc_reader.convert_heic_to_jpeg(image_path)
        if conv:
            image_path = conv
            
    raw_ocr = run_tesseract_ocr(image_path)
    ocr_lower = raw_ocr.lower()
    
    if any(k in ocr_lower for k in ['страховое', 'пенсионн', 'снилс', 'сфр', 'пфр', 'ади-рег']):
        parsed = parse_snils_card_text(raw_ocr)
    elif any(k in ocr_lower for k in ['паспорт', 'росс', 'уфмс', 'мвд', 'выдан']):
        parsed = parse_passport_text(raw_ocr)
    elif any(k in ocr_lower for k in ['диплом', 'квалификац', 'образован']):
        parsed = parse_diploma_text(raw_ocr)
    else:
        # Generic image analysis: attempt SNILS then Passport
        snils_res = parse_snils_card_text(raw_ocr)
        if snils_res.get('snils') or (snils_res.get('fio') and not snils_res.get('fio').startswith('Слушатель')):
            parsed = snils_res
        else:
            parsed = parse_passport_text(raw_ocr)
            
    parsed["success"] = True
    return parsed
