"""
Document Vision and OCR module for PSG 1C Application Agent.
Extracts structured personal information from photos / scans of:
- SNILS cards
- Passports
- Diplomas
- Photo applications (JPEG, PNG, HEIC from iPhone / Android)
"""

import os
import re
import subprocess
from typing import Dict, Any, Optional, List

import linguistics

def run_tesseract_ocr(image_path: str) -> str:
    """Runs system tesseract on image if available."""
    tesseract_bin = "/opt/homebrew/bin/tesseract"
    if not os.path.exists(tesseract_bin):
        tesseract_bin = "tesseract"
        
    try:
        cmd = [tesseract_bin, image_path, "stdout", "-l", "rus+eng"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            return res.stdout
    except Exception:
        pass
    return ""

def parse_snils_card_text(text: str) -> Dict[str, Any]:
    """
    Extracts SNILS number, FIO, birth date, gender from SNILS card text.
    """
    clean_lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Search for SNILS number
    snils_match = re.search(r'(\d{3}[\s\-]\d{3}[\s\-]\d{3}[\s\-]\d{2})', text)
    snils_num = snils_match.group(1) if snils_match else None
    
    # Search for birth date
    date_match = re.search(r'(\d{2}[./\-]\d{2}[./\-]\d{4})', text)
    birth_date = date_match.group(1) if date_match else None
    
    # Search for gender
    gender = None
    if re.search(r'\b(МУЖ|МУЖСКОЙ|М)\b', text, re.IGNORECASE):
        gender = 'М'
    elif re.search(r'\b(ЖЕН|ЖЕНСКИЙ|Ж)\b', text, re.IGNORECASE):
        gender = 'Ж'
        
    # Search for FIO candidates (3 capitalized Cyrillic words)
    fio_candidates = []
    for line in clean_lines:
        words = line.split()
        if len(words) in (2, 3) and all(w.isalpha() and w[0].isupper() for w in words):
            # Exclude service words
            if not any(sw in line.lower() for sw in ['страховое', 'свидетельство', 'пенсионное', 'пенсионный', 'фонд', 'россии']):
                fio_candidates.append(line)
                
    fio = fio_candidates[0] if fio_candidates else ""
    
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
    Extracts FIO, birth date, gender from Russian passport spread.
    """
    # Search for birth date
    date_match = re.search(r'(\d{2}[./\-]\d{2}[./\-]\d{4})', text)
    birth_date = date_match.group(1) if date_match else None
    
    # Search for gender
    gender = None
    if re.search(r'\b(МУЖ|МУЖСКОЙ|М)\b', text, re.IGNORECASE):
        gender = 'М'
    elif re.search(r'\b(ЖЕН|ЖЕНСКИЙ|Ж)\b', text, re.IGNORECASE):
        gender = 'Ж'
        
    # FIO extraction from lines
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    fio_words = []
    for line in lines:
        if any(kw in line.lower() for kw in ['паспорт', 'россия', 'мвд', 'отделение', 'выдан', 'код']):
            continue
        words = [w for w in line.split() if w.isalpha() and w.isupper()]
        if words:
            fio_words.extend(words)
            
    fio = " ".join(fio_words[:3]).title() if fio_words else ""
    
    return {
        "type": "passport",
        "fio": fio,
        "birth_date": birth_date,
        "gender": gender,
        "raw_text": text
    }

def parse_diploma_text(text: str) -> Dict[str, Any]:
    """
    Extracts FIO and qualification / specialty from Diploma.
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    fio = ""
    qualification = ""
    
    for idx, l in enumerate(lines):
        if 'диплом' in l.lower() and idx + 1 < len(lines):
            next_l = lines[idx + 1]
            if len(next_l.split()) in (2, 3):
                fio = next_l
        if any(kw in l.lower() for kw in ['квалификация', 'профессия', 'специальность']):
            qualification = l
            
    return {
        "type": "diploma",
        "fio": fio,
        "qualification": qualification,
        "raw_text": text
    }

def parse_document_image(image_path: str) -> Dict[str, Any]:
    """
    Main entry point for extracting data from an image file.
    """
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.heic':
        import doc_reader
        conv = doc_reader.convert_heic_to_jpeg(image_path)
        if conv:
            image_path = conv
            
    raw_ocr = run_tesseract_ocr(image_path)
    if not raw_ocr:
        return {
            "success": False,
            "error": "OCR не дал результатов или tesseract rus не установлен"
        }
        
    ocr_lower = raw_ocr.lower()
    if 'страховое' in ocr_lower or 'пенсионн' in ocr_lower or 'снилс' in ocr_lower:
        parsed = parse_snils_card_text(raw_ocr)
    elif 'паспорт' in ocr_lower or 'росс' in ocr_lower or 'уфмс' in ocr_lower or 'мвд' in ocr_lower:
        parsed = parse_passport_text(raw_ocr)
    elif 'диплом' in ocr_lower or 'квалификац' in ocr_lower:
        parsed = parse_diploma_text(raw_ocr)
    else:
        # Generic text parsing
        parsed = {
            "type": "general_document",
            "raw_text": raw_ocr
        }
        
    parsed["success"] = True
    return parsed
