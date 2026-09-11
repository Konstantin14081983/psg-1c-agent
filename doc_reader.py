"""
Universal document reader for PSG 1C Application Agent.
Supports:
- DOCX (robust XML-based extractor resilient to broken/mismatched media rels)
- XLSX / XLS (via openpyxl)
- PDF (via PyMuPDF / fitz)
- Images (JPEG, PNG, HEIC via macOS sips conversion)
- Raw text input (messages from WhatsApp, Telegram, Email, copy-pasted blocks)
"""

import os
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET
import datetime
import uuid
from typing import List, Dict, Any, Optional, Tuple

import openpyxl
import linguistics
import program_matcher

def convert_heic_to_jpeg(heic_path: str) -> Optional[str]:
    """
    Converts iPhone HEIC image to standard JPEG.
    Uses pillow_heif (cross-platform Linux/Docker/Render) or native macOS sips utility.
    """
    if not os.path.exists(heic_path):
        return None
        
    out_path = os.path.splitext(heic_path)[0] + "_converted.jpg"
    
    # 1. Try pillow_heif (cross-platform, works in Docker on Render)
    try:
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        image = Image.open(heic_path)
        image.convert('RGB').save(out_path, format="JPEG")
        if os.path.exists(out_path):
            return out_path
    except Exception:
        pass

    # 2. Fallback to macOS native sips utility
    try:
        subprocess.run(['sips', '-s', 'format', 'jpeg', heic_path, '--out', out_path],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(out_path):
            return out_path
    except Exception as e:
        print(f"Error converting HEIC with sips: {e}")
    return None

def extract_docx_data(docx_path: str) -> Dict[str, Any]:
    """
    Extracts application header, tables, and paragraphs from DOCX/DOC files.
    Employs 3-tier resilient extraction:
    1. python-docx (high-level DOM extraction)
    2. Direct ZIP XML extraction (resilient to media/relation corruption)
    3. Binary / plaintext fallback (resilient to old Word 97-2003 .doc / RTF)
    """
    app_title = None
    paragraphs = []
    tables = []

    # Tier 1: python-docx
    try:
        import docx
        doc = docx.Document(docx_path)
        for p in doc.paragraphs:
            txt = ' '.join(p.text.split())
            if txt:
                paragraphs.append(txt)
                if not app_title and 'заявка на обучение' in txt.lower():
                    app_title = txt
        for t in doc.tables:
            tbl_rows = []
            for row in t.rows:
                row_cells = [' '.join(cell.text.split()) for cell in row.cells]
                if any(row_cells):
                    tbl_rows.append(row_cells)
            if tbl_rows:
                tables.append(tbl_rows)
        if tables or paragraphs:
            return {
                "title": app_title,
                "paragraphs": paragraphs,
                "tables": tables
            }
    except Exception as e:
        print(f"python-docx extraction fallback triggered: {e}")

    # Tier 2: Direct XML zipfile extraction
    if zipfile.is_zipfile(docx_path):
        try:
            with zipfile.ZipFile(docx_path) as z:
                if 'word/document.xml' in z.namelist():
                    xml_content = z.read('word/document.xml')
                    root = ET.fromstring(xml_content)
                    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                    body = root.find('w:body', ns)
                    if body is not None:
                        for elem in body:
                            tag = elem.tag.split('}')[-1]
                            if tag == 'p':
                                text = ' '.join(''.join(elem.itertext()).split())
                                if text:
                                    paragraphs.append(text)
                                    if not app_title and 'заявка на обучение' in text.lower():
                                        app_title = text
                            elif tag == 'tbl':
                                tbl_rows = []
                                for tr in elem.findall('w:tr', ns):
                                    row_cells = []
                                    for tc in tr.findall('w:tc', ns):
                                        cell_text = ' '.join(''.join(tc.itertext()).split())
                                        row_cells.append(cell_text)
                                        if not app_title and 'заявка на обучение' in cell_text.lower():
                                            app_title = cell_text
                                    if any(row_cells):
                                        tbl_rows.append(row_cells)
                                if tbl_rows:
                                    tables.append(tbl_rows)
            if tables or paragraphs:
                return {
                    "title": app_title,
                    "paragraphs": paragraphs,
                    "tables": tables
                }
        except Exception as e:
            print(f"ZIP XML extraction fallback triggered: {e}")

    # Tier 3: Binary string / plaintext fallback (e.g. legacy .doc or RTF)
    try:
        with open(docx_path, 'rb') as f:
            raw_bytes = f.read()
        chunks = re.findall(rb'[\x20-\x7E\x80-\xFF]{4,}', raw_bytes)
        for chunk in chunks:
            for enc in ('utf-8', 'cp1251', 'latin-1'):
                try:
                    dec = chunk.decode(enc).strip()
                    if len(dec) >= 5 and any('\u0400' <= ch <= '\u04ff' for ch in dec):
                        clean_txt = ' '.join(dec.split())
                        if clean_txt and clean_txt not in paragraphs:
                            paragraphs.append(clean_txt)
                            if not app_title and 'заявка на обучение' in clean_txt.lower():
                                app_title = clean_txt
                        break
                except Exception:
                    continue
    except Exception as e:
        print(f"Binary string fallback error: {e}")

    return {
        "title": app_title,
        "paragraphs": paragraphs,
        "tables": tables
    }

def extract_xlsx_data(xlsx_path: str) -> Dict[str, Any]:
    """
    Extracts raw rows from an Excel file.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = []
    app_title = None
    
    for r in range(1, ws.max_row + 1):
        row_vals = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
        str_vals = []
        for v in row_vals:
            if v is None:
                str_vals.append('')
            elif isinstance(v, (datetime.datetime, datetime.date)):
                str_vals.append(v.strftime('%d.%m.%Y'))
            else:
                str_vals.append(' '.join(str(v).split()))
        if any(str_vals):
            rows.append(str_vals)
            first_val = str_vals[0] if str_vals else ''
            if not app_title and 'заявка на обучение' in first_val.lower():
                app_title = first_val
                
    return {
        "title": app_title,
        "tables": [rows]
    }

def extract_pdf_data(pdf_path: str) -> Dict[str, Any]:
    """
    Extracts text and table rows from PDF using PyMuPDF (fitz).
    Uses find_tables() to detect structured vector tables.
    """
    import fitz
    doc = fitz.open(pdf_path)
    paragraphs = []
    tables = []
    app_title = None
    
    for page in doc:
        # Extract tables
        try:
            tab_finder = page.find_tables()
            for tab in tab_finder.tables:
                extracted = tab.extract()
                clean_table = []
                for row in extracted:
                    clean_row = [' '.join(str(cell or '').split()) for cell in row]
                    if any(clean_row):
                        clean_table.append(clean_row)
                if clean_table:
                    tables.append(clean_table)
        except Exception as e:
            print(f"PyMuPDF table extraction notice: {e}")

        # Extract plain text
        text = page.get_text()
        for line in text.split('\n'):
            line_clean = ' '.join(line.split())
            if line_clean:
                paragraphs.append(line_clean)
                if not app_title and 'заявка на обучение' in line_clean.lower():
                    app_title = line_clean
                    
    return {
        "title": app_title,
        "paragraphs": paragraphs,
        "tables": tables
    }

def extract_letter_programs(paragraphs: List[str]) -> List[str]:
    """
    Extracts list of training programs specified in a letter body above a student table.
    E.g. letter from enterprise stating 'просит провести аттестацию сотрудников: - Охрана труда (Б) - Высота 1 группа'.
    """
    progs = []
    in_prog_block = False
    
    for p in paragraphs:
        p_clean = ' '.join(p.split())
        p_low = p_clean.lower()
        
        # Check start of program block in letter
        if any(k in p_low for k in ['просит провести', 'по программам', 'на обучение по', 'просим обучить', 'по следующим программам']):
            in_prog_block = True
            continue
            
        # Check end of program block (e.g. table header or payment guarantee or signature)
        if any(k in p_low for k in ['фамилия', '№ п/п', 'оплату гарантируем', 'главный инженер', 'директор', 'руководитель']):
            in_prog_block = False
            
        is_bullet = bool(re.match(r'^(?:[-–—•\*]|\d+[\.\)]|[-–—]?\d+\s+)\s*', p_clean))
        has_prog_kw = any(k in p_low for k in [
            'безопасные методы', 'охрана труда', 'перв', 'помощ', 'помош', 'сиз',
            'средств индивидуальной защиты', 'высот', 'электроустанов', 'тепловых',
            'пожарн', 'птм', 'эколог', 'бдд', 'правила безопасности', 'озп'
        ])
        
        if (in_prog_block or is_bullet) and has_prog_kw:
            clean_item = re.sub(r'^[\s\-–—•\*\d\.\)]+\s*', '', p_clean).strip()
            if len(clean_item) > 5 and clean_item not in progs:
                progs.append(clean_item)
                
    return progs

def identify_columns(header_row: List[str]) -> Dict[str, int]:
    """
    Identifies column indices for standard 1C fields from a header row.
    Resilient to diverse Russian enterprise phrasing and OCR abbreviations.
    """
    col_map = {}
    for idx, col in enumerate(header_row):
        c = ' '.join(str(col).split()).lower()
        if not c:
            continue
            
        # 1. Contacts (email, phone - check before learner keyword to handle 'почта обучающегося')
        if any(kw in c for kw in ['почт', 'телефон', 'email', 'e-mail', 'контакт', 'тел.']):
            col_map['contacts'] = idx
            
        # 2. Study dates
        elif any(kw in c for kw in ['срок', 'период', 'окончан', 'сроки обучен', 'даты']):
            col_map['study_dates'] = idx

        # 3. FIO
        elif any(kw in c for kw in ['дат. падеж', 'дательный', 'в дательном']) or ('дат' in c and any(kw in c for kw in ['фио', 'ф.и.о.', 'слушател', 'сотрудник', 'падеж'])):
            col_map['fio_dat'] = idx
        elif any(kw in c for kw in ['фио', 'ф.и.о.', 'ф.и.о', 'слушател', 'сотрудник', 'работник', 'фамили', 'обучающ']):
            if 'дат' in c:
                col_map['fio_dat'] = idx
            else:
                col_map['fio_nom'] = idx
                
        # 4. Position / Profession
        elif any(kw in c for kw in ['должност', 'професси', 'проф.', 'долж.']):
            col_map['position'] = idx
            
        # 5. Gender
        elif any(kw in c for kw in ['пол', 'gender']) and len(c) <= 6:
            col_map['gender'] = idx
            
        # 6. Birth date
        elif any(kw in c for kw in ['рожд', 'д.р.', 'дата р', 'г.р.', 'год рожд']):
            col_map['birth_date'] = idx
            
        # 7. SNILS
        elif any(kw in c for kw in ['снилс', 'страхов', 'snils']):
            col_map['snils'] = idx
            
        # 8. Training Program / "На кого обучаем" / "Вид обучения" / "Квалификация"
        elif any(kw in c for kw in [
            'программ', 'направлен', 'курс', 'на кого обучаем', 'кого обучаем', 
            'вид обучен', 'вид подготовки', 'наименование программы', 'квалификац', 'аттестац'
        ]):
            col_map['program'] = idx
            
        # 9. Organization name (marked to avoid misinterpreting as FIO)
        elif any(kw in c for kw in ['организац', 'предприяти', 'заказчик', 'компани']):
            col_map['organization'] = idx
            
        # 10. Education
        elif any(kw in c for kw in ['образован']):
            col_map['education'] = idx
            
    return col_map

PATRONYMIC_ENDINGS = (
    'ович', 'евич', 'ич', 'ыч',
    'овна', 'евна', 'ична', 'инична', 'ычна',
    'оглы', 'угли', 'улы', 'кызы', 'гызы'
)

PATRONYMIC_DATIVE_ENDINGS = (
    'овичу', 'евичу', 'ичу', 'ычу',
    'овне', 'евне', 'ичне', 'иничне', 'ычне',
    'оглы', 'угли', 'улы', 'кызы', 'гызы'
)

def is_patronymic(word: str) -> bool:
    """Checks if word has typical Russian or Central Asian patronymic ending (or typo/tail garbage)."""
    w = word.strip().lower()
    if any(w.endswith(end) for end in PATRONYMIC_ENDINGS):
        return True
    if re.search(r'[а-яё]{3,}(?:ович|евич|овна|евна|ична|ычна)[а-яё]{1,8}$', w):
        return True
    return False

def is_dative_patronymic(word: str) -> bool:
    """Checks if word is a patronymic in dative case (e.g. Александровичу, Павловне)."""
    w = word.strip().lower()
    if any(w.endswith(end) for end in PATRONYMIC_DATIVE_ENDINGS):
        return True
    if re.search(r'[а-яё]{3,}(?:овичу|евичу|овне|евне|ичне|ычне)[а-яё]{0,5}$', w):
        return True
    return False

def is_dative_fio_phrase(phrase: str) -> bool:
    """Checks if phrase is a full name in dative case (e.g. 'Яровому Павлу Александровичу')."""
    words = phrase.strip().split()
    if len(words) in (2, 3):
        if not all(re.match(r'^[а-яА-ЯёЁ\-]+$', w) for w in words):
            return False
        if is_dative_patronymic(words[-1]):
            return True
        w0_low = words[0].lower()
        w1_low = words[1].lower()
        if (w0_low.endswith(('ому', 'ему', 'овой', 'евой')) and w1_low.endswith(('у', 'ю', 'е', 'и'))):
            return True
    return False

def classify_text_part(part: str) -> str:
    """Classifies an isolated phrase as 'program', 'position', or 'unknown'."""
    p_lower = part.lower().strip()
    
    # 1. Definite program indicators
    if any(prog_kw in p_lower for prog_kw in [
        'охрана труда', 'охране труда', 'от (', 'пожар', 'птм', 'высот', 'озп', 
        'эколог', 'бдд', 'перв', 'помощ', 'сиз', 'правила работы', 'минимум', 'дпп', 'пк '
    ]):
        return 'program'
        
    # 2. Definite profession / position indicators
    if any(p_lower.endswith(suf) for suf in ['ник', 'щик', 'чик', 'тель', 'ер', 'арь', 'ист']) or any(kw in p_lower for kw in [
        'монтаж', 'бетон', 'свар', 'строп', 'водител', 'слесар', 'инженер', 'мастер', 
        'буриль', 'кранов', 'машинист', 'директор', 'начальник', 'специалист', 'рабоч', 'электрик', 'токарь'
    ]):
        return 'position'
        
    # 3. Catalog matching fallback (only if matched to an actual catalog/canonical program)
    matched = program_matcher.match_programs(part)
    if matched and any(m.get('is_canonical') for m in matched):
        return 'program'
        
    return 'unknown'

def parse_student_line(raw_line: str, current_program: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Parses a single line (or comma/tab/dash separated chunk) into structured student fields:
    FIO, Position, Gender, Birth Date, SNILS, Study Dates, Contacts, Program.
    """
    line = raw_line.strip()
    if not line:
        return None
        
    # Strip leading list markers: '1.', '1)', '1 -', '*', '-' (ensure not stripping dates like 22.12.1978 or 1.5.1990)
    line = re.sub(r'^\s*(?:\d{1,4}(?:[\)\:]|\s*[-–—]|\.(?!\d))|\([0-9]+\)|\*|[-–—])\s*', '', line).strip()
    
    # Check if line is purely program header / general text
    line_lower = line.lower()
    if any(line_lower.startswith(p) for p in ['программа', 'направление', 'курс', 'обучение по', 'охрана труда']) and len(line.split()) < 25 and not re.search(r'\d{3}[\s\-]\d{3}', line):
        return None
        
    dates = ""
    snils = ""
    birth_date = ""
    gender = ""
    contacts = ""
    fio = ""
    fio_dat = ""
    position = ""
    program = current_program or ""
    
    # 1. Extract study dates range (e.g. 01.09.2026 - 15.09.2026) or labeled end date (e.g. окончание: 11.09.2026, даты: 11.09.2026)
    m_dates = re.search(r'(?:(?:сроки|период|даты(?:\s+обучения)?|окончани[ея](?:\s+обучения)?)[:\s]+)\b(\d{2}\.\d{2}\.\d{4}\s*(?:[-—–]|по)\s*\d{2}\.\d{2}\.\d{4}|\d{2}\.\d{2}\.\d{4})\b', line, re.I)
    if not m_dates:
        m_dates = re.search(r'\b(\d{2}\.\d{2}\.\d{4}\s*(?:[-—–]|по)\s*\d{2}\.\d{2}\.\d{4})\b', line, re.I)
    if m_dates:
        dates = m_dates.group(1).strip()
        line = line[:m_dates.start()] + ' , ' + line[m_dates.end():]
        
    # 2. Extract SNILS (including optional 'СНИЛС:' prefix and OCR letters)
    m_snils = re.search(r'(?:снилс[:\s#№]+)?\b([0-9ОоoOlI]{3}[\s\-][0-9ОоoOlI]{3}[\s\-][0-9ОоoOlI]{3}[\s\-]?[0-9ОоoOlI]{2}|[0-9ОоoOlI]{11})\b', line, re.I)
    if m_snils:
        snils_cand = m_snils.group(1).strip()
        snils_clean, ok, _ = linguistics.validate_and_format_snils(snils_cand)
        snils = snils_clean if ok else snils_cand
        line = line[:m_snils.start()] + ' , ' + line[m_snils.end():]
        
    # 3. Extract Contacts (email, phone)
    m_email = re.search(r'(?:(?:email|e-mail|почта)[:\s]+)?\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b', line, re.I)
    if m_email:
        email = m_email.group(1).strip()
        contacts = email
        line = line[:m_email.start()] + ' , ' + line[m_email.end():]
        
    m_phone = re.search(r'(?:(?:тел(?:ефон)?|тел\.)[:\s]+)?((?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2})\b', line, re.I)
    if m_phone:
        phone = m_phone.group(1).strip()
        contacts = f'{contacts}, {phone}'.strip(', ') if contacts else phone
        line = line[:m_phone.start()] + ' , ' + line[m_phone.end():]
        
    # 4. Extract Birth Date
    # 4a. Verbal Russian date with optional place of birth: e.g. 22 АВГУСТА 2005 ГОДА Г. НОВОСИБИРСК
    m_vdate = re.search(r'(?:(?:д\.?р\.?|рожд\.?|дата\s+рождения)[:\s]+)?\b(\d{1,2}\s+[а-яА-ЯёЁ]{3,12}\s+\d{4}(?:\s*г(?:ода|\.)?)?(?:\s*г(?:ород|\.)?\s+[а-яА-ЯёЁ\-]+)?)\b', line, re.I)
    if m_vdate:
        d_norm, ok, _ = linguistics.normalize_date(m_vdate.group(1))
        birth_date = d_norm if ok else m_vdate.group(1)
        line = line[:m_vdate.start()] + ' , ' + line[m_vdate.end():]
    else:
        # 4b. Numeric date (supports OCR spaces and trailing 'г', 'г.', 'года')
        m_ndate = re.search(r'(?:(?:д\.?р\.?|рожд\.?|дата\s+рождения|г\.?р\.?)[:\s]+)?\b(\d{1,2}\s*[./\-]\s*\d{1,2}\s*[./\-]\s*(?:\d[\d\s]{0,3}\d|\d{2,4})(?:\s*г(?:ода|\.)?)?)\b', line, re.I)
        if m_ndate:
            d_norm, ok, _ = linguistics.normalize_date(m_ndate.group(1))
            birth_date = d_norm if ok else m_ndate.group(1)
            line = line[:m_ndate.start()] + ' , ' + line[m_ndate.end():]
            
    # 5. Extract Gender
    m_gender = re.search(r'(?:пол[:\s]+)?\b(муж(?:ской)?|жен(?:ский)?)\b', line, re.I)
    if m_gender:
        g_val = m_gender.group(1).lower()
        gender = 'М' if 'муж' in g_val else 'Ж'
        line = line[:m_gender.start()] + ' , ' + line[m_gender.end():]
    else:
        m_gshort = re.search(r'(?:^|[\,\;])\s*(?:пол[:\s]+)?([мж])\s*(?:$|[\,\;])', line, re.I)
        if m_gshort:
            gender = m_gshort.group(1).upper()
            line = line[:m_gshort.start()] + ' , ' + line[m_gshort.end():]
            
    # 6. Check explicit labeled fields
    m_pos_label = re.search(r'(?:должност[ьи]|професси[яи]|долж\.|проф\.)[:\s]+([^,;\n]+)', line, re.I)
    if m_pos_label:
        position = m_pos_label.group(1).strip()
        line = line[:m_pos_label.start()] + ' , ' + line[m_pos_label.end():]
        
    m_fiodat_label = re.search(r'(?:фио\s*(?:обучающегося\s*)?в\s*дат(?:ельном)?(?:\s*падеже)?|в\s*дат(?:ельном)?(?:\s*падеже)?|дат(?:ельный)?\s*падеж|фио\s*дат\.?)[:\s]+([^,;\n]+)', line, re.I)
    if m_fiodat_label:
        fio_dat = m_fiodat_label.group(1).strip()
        line = line[:m_fiodat_label.start()] + ' , ' + line[m_fiodat_label.end():]

    m_fio_label = re.search(r'(?:фио|слушатель|работник|сотрудник)[:\s]+([^,;\n]+)', line, re.I)
    if m_fio_label:
        fio = m_fio_label.group(1).strip()
        line = line[:m_fio_label.start()] + ' , ' + line[m_fio_label.end():]
        
    m_prog_label = re.search(r'(?:программ[аы]|направлени[ея]|курс)[:\s]+([^,;\n]+)', line, re.I)
    if m_prog_label:
        program = m_prog_label.group(1).strip()
        line = line[:m_prog_label.start()] + ' , ' + line[m_prog_label.end():]
        
    # 7. Analyze remaining parts
    line = re.sub(r'[,;\t|]+', ',', line)
    raw_parts = [p.strip() for p in re.split(r',|(?:\s+[-—–]\s+)', line) if p.strip()]
    
    parts = []
    for p in raw_parts:
        p_clean = p.strip(' ,;.')
        if not p_clean:
            continue
        # Remove stray label residues or city markers
        if re.match(r'^(?:г\.|город)\s+[а-яА-ЯёЁ\-]+$', p_clean, re.I):
            continue
        if re.match(r'^(?:снилс|пол|тел|email|почта|д\.?р\.?|рожд\.?)[:\s]*$', p_clean, re.I):
            continue
        # Rejoin split patronymics in parts so word splitting recognizes 3 words (e.g. 'Александрови Ч' -> 'Александрович', 'Александрови Чу' -> 'Александровичу')
        p_clean = re.sub(r'\b([а-яА-ЯёЁ]{3,}(?:ови|еви|ини|ыч|и))\s+([чЧ][уУеЕаАыЫ]?|[чЧ])\b', lambda m: f"{m.group(1)}{m.group(2).lower()}", p_clean)
        p_clean = re.sub(r'\b([а-яА-ЯёЁ]{3,}(?:овн|евн|ичн))\s+([аАеЕыЫ]?|[аА])\b', lambda m: f"{m.group(1)}{m.group(2).lower()}", p_clean)
        parts.append(p_clean)
        
    # If dative FIO is present in parts (e.g. from table or comma list), extract it before FIO or position
    if not fio_dat:
        for i, part in enumerate(parts):
            if is_dative_fio_phrase(part):
                fio_dat = part
                parts.pop(i)
                break
        
    if not fio:
        for i, part in enumerate(parts):
            if classify_text_part(part) == 'program':
                continue
            words = part.split()
            # 3 words with patronymic at index 2 (case-insensitive, supports typos)
            if len(words) == 3 and is_patronymic(words[2]):
                fio = part
                parts.pop(i)
                break
            # 3 words where 3rd word is a profession: e.g. 'Иванов Иван сварщик'
            elif len(words) == 3 and classify_text_part(words[2]) == 'position':
                fio = ' '.join(words[:2])
                if not position:
                    position = words[2]
                parts.pop(i)
                break
            # 3 words all alphabetic (Cyrillic or Latin names)
            elif len(words) == 3 and all(re.match(r'^[а-яА-ЯёЁa-zA-Z\-]+$', w) for w in words):
                # Ensure none of the words are common organization or letter-header terms
                p_low = part.lower()
                if not any(np in p_low for np in ['директор', 'генеральн', 'инженер', 'исполнитель', 'акционерн', 'общество', 'учебн', 'центр', 'заявк', 'договор', 'просим', 'руковод']):
                    fio = part
                    parts.pop(i)
                    break
            # 2 words (Surname + First name): e.g. 'Петров Геннадий'
            elif len(words) == 2 and all(re.match(r'^[а-яА-ЯёЁa-zA-Z\-]+$', w) for w in words):
                p_low = part.lower()
                if not any(np in p_low for np in ['директор', 'генеральн', 'инженер', 'исполнитель', 'акционерн', 'общество', 'учебн', 'центр', 'заявк', 'договор', 'просим', 'руковод']):
                    fio = part
                    parts.pop(i)
                    break
            # 4+ words in single part without separators: e.g. 'Абрамов Антон Александрович Монтажник'
            elif len(words) >= 4:
                pat_idx = -1
                for w_i, w in enumerate(words):
                    if is_patronymic(w):
                        pat_idx = w_i
                        break
                if pat_idx in (1, 2):
                    fio = ' '.join(words[:pat_idx+1])
                    remainder_pos = ' '.join(words[pat_idx+1:])
                    if remainder_pos and not position:
                        position = remainder_pos
                    parts.pop(i)
                    break
                elif pat_idx > 2 and pat_idx == len(words) - 1:
                    fio = ' '.join(words[pat_idx-2:pat_idx+1])
                    remainder_pos = ' '.join(words[:pat_idx-2])
                    if remainder_pos and not position:
                        position = remainder_pos
                    parts.pop(i)
                    break
                else:
                    # Check if position starts after 2 or 3 words
                    if classify_text_part(' '.join(words[2:])) == 'position':
                        fio = ' '.join(words[:2])
                        if not position:
                            position = ' '.join(words[2:])
                        parts.pop(i)
                        break
                    elif len(words) >= 4 and classify_text_part(' '.join(words[3:])) == 'position':
                        fio = ' '.join(words[:3])
                        if not position:
                            position = ' '.join(words[3:])
                        parts.pop(i)
                        break
                    
    # Check if any remaining part is a date (e.g. target study date 11.09.2026)
    for i in range(len(parts) - 1, -1, -1):
        p_str = parts[i].strip()
        if re.match(r'^\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}$', p_str):
            d_norm, d_ok, _ = linguistics.normalize_date(p_str)
            if not dates:
                dates = d_norm if d_ok else p_str
            parts.pop(i)

    # Assign remaining parts to position or program
    for part in parts:
        c = classify_text_part(part)
        if c == 'program' and not program:
            program = part
        elif c == 'position' and not position:
            position = part
        elif not position:
            position = part
        elif not program:
            program = part
            
    if not fio:
        return None
        
    # Clean FIO and correct typos (casing, double letters, missing letters)
    fio_clean, fio_warns = linguistics.correct_fio_typos(fio)
    fio_final = fio_clean or fio
        
    # If gender not specified, infer from FIO
    if not gender and fio_final:
        f_words = fio_final.split()
        if len(f_words) >= 2:
            gender = linguistics.infer_gender(f_words[0], f_words[1], f_words[2] if len(f_words) > 2 else "")
            
    fio_dat_clean, _ = linguistics.correct_fio_typos(fio_dat) if fio_dat else ("", [])
    fio_dat_final = fio_dat_clean or fio_dat
            
    return {
        "fio_nom": fio_final,
        "raw_fio": fio,
        "fio_dat": fio_dat_final,
        "position": position,
        "gender": gender,
        "birth_date": birth_date,
        "snils": snils,
        "study_dates": dates,
        "contacts": contacts,
        "program": program or current_program or "",
        "fio_corrections": fio_warns
    }

def parse_raw_text_application(raw_text: str) -> Dict[str, Any]:
    """
    Parses plain text messages (e.g. from WhatsApp, Telegram, Email, copy-pasted blocks).
    Supports:
    - Numbered lists: '1. Абрамов Антон Александрович, Монтажник'
    - Separated rows: FIO, Position, Birth date, SNILS, Dates, Contacts
    - Multi-line block format: ФИО: ..., Должность: ...
    """
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    if not lines:
        return {"title": None, "students": []}
        
    app_title = None
    students = []
    current_program = None
    
    # Check for title in the first 3 lines
    for line in lines[:3]:
        if 'заявка' in line.lower() or 'договор' in line.lower():
            app_title = line
            break
            
    for line in lines:
        if line == app_title:
            continue
            
        # Check if line indicates a program header
        line_lower = line.lower()
        is_explicit_prog = any(line_lower.startswith(kw) for kw in ['программа:', 'программы:', 'программа ', 'программы ', 'курс:', 'курсы:', 'направление:'])
        is_student_row = (not is_explicit_prog) and (((',' in line and len(line.split(',')) >= 3) or ('\t' in line) or bool(re.search(r'\d{3}[\s\-]\d{3}[\s\-]\d{3}', line))))
        if is_explicit_prog or (not is_student_row and any(kw in line_lower for kw in ['программа', 'направление', 'курс', 'обучение по', 'охрана труда']) and len(line.split()) < 30):
            clean_prog = re.sub(r'^(программ[аы]|направлени[ея]|курс[ы]?|обучение\s+по)[:\s\-]*', '', line, flags=re.IGNORECASE).strip()
            if clean_prog:
                current_program = clean_prog
                continue
                
        stud = parse_student_line(line, current_program)
        if stud:
            students.append(stud)
            
    if current_program:
        for s in students:
            if not s.get('program'):
                s['program'] = current_program
            
    return {
        "title": app_title,
        "students": students
    }

def reconcile_student_records(file_students: List[Dict[str, Any]], text_students: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Reconciles and merges student records from uploaded files (e.g. SNILS photos, scans)
    with student records from text messages (e.g. FIO, Position).
    Avoids duplicate rows and enriches verified file data with manager text instructions.
    """
    if not file_students:
        return list(text_students)
    if not text_students:
        return list(file_students)
        
    merged = [dict(s) for s in file_students]
    matched_file_indices = set()
    unmatched_text_students = []
    
    for t_stud in text_students:
        t_fio = (t_stud.get('fio_nom') or '').strip().lower()
        t_snils = re.sub(r'\D', '', t_stud.get('snils') or '')
        t_words = [w for w in t_fio.split() if len(w) > 1]
        
        matched_idx = -1
        # 1. Match by SNILS if both have SNILS
        if t_snils and len(t_snils) >= 9:
            for idx, f_stud in enumerate(merged):
                if idx in matched_file_indices:
                    continue
                f_snils = re.sub(r'\D', '', f_stud.get('snils') or '')
                if f_snils and f_snils == t_snils:
                    matched_idx = idx
                    break
                    
        # 2. Match by exact normalized FIO
        if matched_idx == -1 and t_fio and 'слушатель' not in t_fio:
            for idx, f_stud in enumerate(merged):
                if idx in matched_file_indices:
                    continue
                f_fio = (f_stud.get('fio_nom') or '').strip().lower()
                if f_fio and f_fio == t_fio:
                    matched_idx = idx
                    break
                    
        # 3. Match by Surname + First Name (first 2 words)
        if matched_idx == -1 and len(t_words) >= 2:
            for idx, f_stud in enumerate(merged):
                if idx in matched_file_indices:
                    continue
                f_fio = (f_stud.get('fio_nom') or '').strip().lower()
                f_words = [w for w in f_fio.split() if len(w) > 1]
                if len(f_words) >= 2 and t_words[0] == f_words[0] and t_words[1] == f_words[1]:
                    matched_idx = idx
                    break
                    
        # 4. Match by Surname if only one student with this surname exists in files
        if matched_idx == -1 and len(t_words) >= 1:
            matching_surnames = []
            for idx, f_stud in enumerate(merged):
                if idx in matched_file_indices:
                    continue
                f_fio = (f_stud.get('fio_nom') or '').strip().lower()
                f_words = [w for w in f_fio.split() if len(w) > 1]
                if f_words and f_words[0] == t_words[0]:
                    matching_surnames.append(idx)
            if len(matching_surnames) == 1:
                matched_idx = matching_surnames[0]
                
        # 5. If exactly 1 file student with generic placeholder FIO
        if matched_idx == -1 and len(merged) == 1:
            f_fio = (merged[0].get('fio_nom') or '').strip().lower()
            if 'слушатель' in f_fio:
                matched_idx = 0
                
        if matched_idx != -1:
            matched_file_indices.add(matched_idx)
            target = merged[matched_idx]
            # Position: text message position is explicitly entered by manager, takes precedence
            if t_stud.get('position'):
                target['position'] = t_stud['position']
            # If target has generic FIO or shorter FIO and text has full FIO, update FIO
            if ('слушатель' in (target.get('fio_nom') or '').lower() or len(target.get('fio_nom', '').split()) < len(t_stud.get('fio_nom', '').split())) and t_stud.get('fio_nom'):
                target['fio_nom'] = t_stud['fio_nom']
            # Enrich other missing fields
            if not target.get('snils') and t_stud.get('snils'):
                target['snils'] = t_stud['snils']
            if not target.get('birth_date') and t_stud.get('birth_date'):
                target['birth_date'] = t_stud['birth_date']
            if not target.get('gender') and t_stud.get('gender'):
                target['gender'] = t_stud['gender']
            if not target.get('program') and t_stud.get('program'):
                target['program'] = t_stud['program']
            if not target.get('study_dates') and t_stud.get('study_dates'):
                target['study_dates'] = t_stud['study_dates']
            if not target.get('fio_dat') and t_stud.get('fio_dat'):
                target['fio_dat'] = t_stud['fio_dat']
            if not target.get('contacts') and t_stud.get('contacts'):
                target['contacts'] = t_stud['contacts']
        else:
            unmatched_text_students.append(t_stud)
            
    # Phase 2: Match remaining unmatched text students with remaining placeholder file students
    still_unmatched = []
    for t_stud in unmatched_text_students:
        matched_placeholder_idx = -1
        for idx, f_stud in enumerate(merged):
            if idx not in matched_file_indices and 'слушатель' in (f_stud.get('fio_nom') or '').lower():
                matched_placeholder_idx = idx
                break
        if matched_placeholder_idx != -1:
            matched_file_indices.add(matched_placeholder_idx)
            target = merged[matched_placeholder_idx]
            if t_stud.get('fio_nom'):
                target['fio_nom'] = t_stud['fio_nom']
            if t_stud.get('position'):
                target['position'] = t_stud['position']
            if not target.get('snils') and t_stud.get('snils'):
                target['snils'] = t_stud['snils']
            if not target.get('birth_date') and t_stud.get('birth_date'):
                target['birth_date'] = t_stud['birth_date']
            if not target.get('gender') and t_stud.get('gender'):
                target['gender'] = t_stud['gender']
            if not target.get('program') and t_stud.get('program'):
                target['program'] = t_stud['program']
            if not target.get('study_dates') and t_stud.get('study_dates'):
                target['study_dates'] = t_stud['study_dates']
            if not target.get('contacts') and t_stud.get('contacts'):
                target['contacts'] = t_stud['contacts']
        else:
            still_unmatched.append(t_stud)
            
    merged.extend(still_unmatched)

    return merged


def parse_incoming_application(
    file_path: str,
    use_ai: bool = False,
    openai_api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parses any incoming application file (DOCX, XLSX, PDF, Image)
    and returns normalized records ready for 1C processing.
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.heic':
        conv = convert_heic_to_jpeg(file_path)
        if conv:
            file_path = conv
            ext = '.jpg'
            
    extracted_title = None
    tables = []
    letter_progs = []
    pdf_paragraphs = []
    
    if ext in ('.docx', '.doc'):
        data = extract_docx_data(file_path)
        extracted_title = data.get('title')
        tables = data.get('tables', [])
        docx_paragraphs = data.get('paragraphs', [])
        letter_progs = extract_letter_programs(docx_paragraphs)
    elif ext in ('.xlsx', '.xls'):
        data = extract_xlsx_data(file_path)
        extracted_title = data.get('title')
        tables = data.get('tables', [])
    elif ext == '.pdf':
        # If AI Vision requested and available, use AI multimodal on PDF first
        if use_ai:
            try:
                import fitz
                import uuid
                doc_pdf = fitz.open(file_path)
                if len(doc_pdf) > 0:
                    page = doc_pdf[0]
                    pix = page.get_pixmap(dpi=200)
                    temp_img = os.path.join(os.path.dirname(file_path), f"temp_pdf_{uuid.uuid4().hex[:8]}.png")
                    pix.save(temp_img)
                    import document_vision
                    vision_res = document_vision.parse_document_image(temp_img, use_ai=True, openai_api_key=openai_api_key)
                    if os.path.exists(temp_img):
                        try:
                            os.remove(temp_img)
                        except Exception:
                            pass
                    if vision_res.get('success'):
                        students = []
                        if vision_res.get('students'):
                            for s in vision_res['students']:
                                prog = s.get('program') or ("; ".join(s.get('programs', [])) if isinstance(s.get('programs'), list) else "")
                                students.append({
                                    "fio_nom": s.get('fio') or s.get('fio_nom') or "Слушатель",
                                    "fio_dat": s.get('fio_dat') or "",
                                    "position": s.get('position') or "",
                                    "gender": s.get('gender') or "",
                                    "birth_date": s.get('birth_date') or "",
                                    "snils": s.get('snils') or "",
                                    "study_dates": s.get('study_dates') or "",
                                    "contacts": s.get('contacts') or "",
                                    "program": prog,
                                    "engine": vision_res.get('engine', '')
                                })
                        elif vision_res.get('fio'):
                            prog = vision_res.get('program') or ("; ".join(vision_res.get('programs', [])) if isinstance(vision_res.get('programs'), list) else "")
                            students.append({
                                "fio_nom": vision_res.get('fio'),
                                "fio_dat": "",
                                "position": vision_res.get('position') or "",
                                "gender": vision_res.get('gender') or "",
                                "birth_date": vision_res.get('birth_date') or "",
                                "snils": vision_res.get('snils') or "",
                                "study_dates": "",
                                "contacts": "",
                                "program": prog,
                                "engine": vision_res.get('engine', '')
                            })
                        if students:
                            return {
                                "title": vision_res.get('application_title') or extracted_title or f"ЗАЯВКА НА ОБУЧЕНИЕ от {datetime.date.today().strftime('%d.%m.%Y')} г.",
                                "students": students,
                                "engine": vision_res.get('engine', '')
                            }
            except Exception as e:
                print(f"PDF AI Vision fallback notice: {e}")

        # Standard PDF scanner (Vector table extraction + letter program extraction)
        data = extract_pdf_data(file_path)
        extracted_title = data.get('title')
        tables = data.get('tables', [])
        pdf_paragraphs = data.get('paragraphs', [])
        letter_progs = extract_letter_programs(pdf_paragraphs)

    elif ext in ('.png', '.jpg', '.jpeg', '.heic', '.webp', '.bmp', '.tiff'):
        import document_vision
        vision_res = document_vision.parse_document_image(file_path, use_ai=use_ai, openai_api_key=openai_api_key)
        students = []
        if vision_res.get('success'):
            if vision_res.get('students'):
                for s in vision_res['students']:
                    prog = s.get('program') or ("; ".join(s.get('programs', [])) if isinstance(s.get('programs'), list) else "")
                    students.append({
                        "fio_nom": s.get('fio') or s.get('fio_nom') or "Слушатель (по фото документа)",
                        "fio_dat": s.get('fio_dat') or "",
                        "position": s.get('position') or "",
                        "gender": s.get('gender') or "",
                        "birth_date": s.get('birth_date') or "",
                        "snils": s.get('snils') or "",
                        "study_dates": s.get('study_dates') or "",
                        "contacts": s.get('contacts') or "",
                        "program": prog,
                        "engine": vision_res.get('engine', '')
                    })
            elif vision_res.get('fio'):
                prog = vision_res.get('program') or ("; ".join(vision_res.get('programs', [])) if isinstance(vision_res.get('programs'), list) else "")
                students.append({
                    "fio_nom": vision_res.get('fio') or "Слушатель (по фото документа)",
                    "fio_dat": "",
                    "position": vision_res.get('position') or "",
                    "gender": vision_res.get('gender') or "",
                    "birth_date": vision_res.get('birth_date') or "",
                    "snils": vision_res.get('snils') or "",
                    "study_dates": "",
                    "contacts": "",
                    "program": prog,
                    "engine": vision_res.get('engine', '')
                })

            is_single_card = vision_res.get('type') in ('snils_card', 'passport', 'diploma')
            if not is_single_card and len(students) <= 1 and vision_res.get('raw_text') and not use_ai:
                txt_cand = parse_raw_text_application(vision_res['raw_text'])
                if len(txt_cand.get('students', [])) > len(students):
                    students = txt_cand['students']

            if students:
                return {
                    "title": vision_res.get('application_title') or f"ЗАЯВКА НА ОБУЧЕНИЕ от {datetime.date.today().strftime('%d.%m.%Y')} г.",
                    "students": students,
                    "engine": vision_res.get('engine', ''),
                    "ai_error": vision_res.get('ai_error')
                }
    else:
        # Check if text file
        if ext in ('.txt', '.csv'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return parse_raw_text_application(f.read())
        tables = []
        
    students_raw = []
    
    for tbl in tables:
        header_idx = -1
        col_map = {}
        for r_idx, row in enumerate(tbl):
            non_empty_cells = [c for c in row if str(c).strip()]
            if len(non_empty_cells) < 2:
                continue
            row_str = ' '.join(str(c) for c in row).lower()
            if any(kw in row_str for kw in ['фио', 'ф.и.о', 'фамили', 'слушател', 'сотрудник', 'работник', 'обучающ']) or ('снилс' in row_str and ('должност' in row_str or 'рожд' in row_str or 'професси' in row_str)):
                cand_map = identify_columns(row)
                if 'fio_nom' in cand_map and (len(cand_map) >= 2 or any(k in row_str for k in ['фио', 'фамил'])):
                    header_idx = r_idx
                    col_map = cand_map
                    break
                
        if header_idx == -1:
            continue
            
        current_program = None
        
        for r_idx in range(header_idx + 1, len(tbl)):
            row = tbl[r_idx]
            non_empty = [c for c in row if str(c).strip()]
            if not non_empty:
                continue
                
            first_cell = str(row[0]).strip().lower()
            if any(term in first_cell for term in ['директор', 'руководител', 'м.п.', 'согласие', 'подпись', 'исполнитель', 'оплату гарантируем', 'главный инженер']):
                break
                
            if len(non_empty) == 1 and not str(row[0]).strip().isdigit():
                current_program = non_empty[0].strip()
                continue
            elif len(non_empty) <= 2 and ('программа' in ' '.join(str(c) for c in non_empty).lower() or 'обучение' in ' '.join(str(c) for c in non_empty).lower()):
                current_program = ' '.join(str(c) for c in non_empty).strip()
                continue
                
            fio_val = str(row[col_map['fio_nom']]).strip() if 'fio_nom' in col_map and col_map['fio_nom'] < len(row) else ''
            if not fio_val:
                continue
                
            if any(term in fio_val.lower() for term in ['фио', 'ф.и.о', 'фамилия', 'подпись', 'слушатель', 'сотрудник', 'директор', 'главный инженер', 'исполнитель']):
                continue
                
            fio_dat_val = str(row[col_map['fio_dat']]).strip() if 'fio_dat' in col_map and col_map['fio_dat'] < len(row) else ''
            position_val = str(row[col_map['position']]).strip() if 'position' in col_map and col_map['position'] < len(row) else ''
            gender_val = str(row[col_map['gender']]).strip() if 'gender' in col_map and col_map['gender'] < len(row) else ''
            birth_date_val = str(row[col_map['birth_date']]).strip() if 'birth_date' in col_map and col_map['birth_date'] < len(row) else ''
            snils_val = str(row[col_map['snils']]).strip() if 'snils' in col_map and col_map['snils'] < len(row) else ''
            study_dates_val = str(row[col_map['study_dates']]).strip() if 'study_dates' in col_map and col_map['study_dates'] < len(row) else ''
            contacts_val = str(row[col_map['contacts']]).strip() if 'contacts' in col_map and col_map['contacts'] < len(row) else ''
            
            prog_val = None
            if 'program' in col_map and col_map['program'] < len(row) and str(row[col_map['program']]).strip():
                prog_val = str(row[col_map['program']]).strip()
            elif current_program:
                prog_val = current_program
            elif letter_progs:
                prog_val = "; ".join(letter_progs)
                
            students_raw.append({
                "fio_nom": fio_val,
                "fio_dat": fio_dat_val,
                "position": position_val,
                "gender": gender_val,
                "birth_date": birth_date_val,
                "snils": snils_val,
                "study_dates": study_dates_val,
                "contacts": contacts_val,
                "program": prog_val
            })
            
    if students_raw:
        return {
            "title": extracted_title or f"ЗАЯВКА НА ОБУЧЕНИЕ от {datetime.date.today().strftime('%d.%m.%Y')} г.",
            "students": students_raw
        }

    # If PDF had no tables (or 0 students extracted from tables), fallback to text or OCR
    if ext == '.pdf':
        if pdf_paragraphs:
            pdf_text = '\n'.join(pdf_paragraphs)
            txt_res = parse_raw_text_application(pdf_text)
            if txt_res.get('students'):
                return txt_res

        # Fallback for scanned PDF without text
        try:
            import fitz
            import uuid
            doc_pdf = fitz.open(file_path)
            if len(doc_pdf) > 0:
                page = doc_pdf[0]
                pix = page.get_pixmap(dpi=200)
                temp_img = os.path.join(os.path.dirname(file_path), f"temp_pdf_{uuid.uuid4().hex[:8]}.png")
                pix.save(temp_img)
                import document_vision
                vision_res = document_vision.parse_document_image(temp_img, use_ai=use_ai, openai_api_key=openai_api_key)
                if os.path.exists(temp_img):
                    try:
                        os.remove(temp_img)
                    except Exception:
                        pass
                if vision_res.get('success'):
                    students = []
                    if vision_res.get('students'):
                        for s in vision_res['students']:
                            prog = s.get('program') or ("; ".join(s.get('programs', [])) if isinstance(s.get('programs'), list) else "")
                            students.append({
                                "fio_nom": s.get('fio') or s.get('fio_nom') or "Слушатель",
                                "fio_dat": s.get('fio_dat') or "",
                                "position": s.get('position') or "",
                                "gender": s.get('gender') or "",
                                "birth_date": s.get('birth_date') or "",
                                "snils": s.get('snils') or "",
                                "study_dates": s.get('study_dates') or "",
                                "contacts": s.get('contacts') or "",
                                "program": prog,
                                "engine": vision_res.get('engine', '')
                            })
                    elif vision_res.get('fio'):
                        prog = vision_res.get('program') or ("; ".join(vision_res.get('programs', [])) if isinstance(vision_res.get('programs'), list) else "")
                        students.append({
                            "fio_nom": vision_res.get('fio'),
                            "fio_dat": "",
                            "position": vision_res.get('position') or "",
                            "gender": vision_res.get('gender') or "",
                            "birth_date": vision_res.get('birth_date') or "",
                            "snils": vision_res.get('snils') or "",
                            "study_dates": "",
                            "contacts": "",
                            "program": prog,
                            "engine": vision_res.get('engine', '')
                        })
                    if students:
                        return {
                            "title": vision_res.get('application_title') or extracted_title or f"ЗАЯВКА НА ОБУЧЕНИЕ от {datetime.date.today().strftime('%d.%m.%Y')} г.",
                            "students": students,
                            "engine": vision_res.get('engine', '')
                        }
        except Exception:
            pass

    return {
        "title": extracted_title or f"ЗАЯВКА НА ОБУЧЕНИЕ от {datetime.date.today().strftime('%d.%m.%Y')} г.",
        "students": students_raw
    }

def extract_supplementary_instructions(text: Optional[str]) -> Dict[str, Any]:
    """
    Extracts supplementary manager parameters from unstructured text messages:
    e.g. 'должность монтажник', 'программа Охрана труда', 'сроки 01.09.2026 - 15.09.2026'
    """
    if not text:
        return {}
        
    res = {}
    t = text.strip()
    
    # 1. Position extraction
    m_pos = re.search(r'(?:должност[ьи]|професси[яи]|долж\.|проф\.)[:\s]+([^\n,;\.]+)', t, re.I)
    if m_pos:
        res['position'] = m_pos.group(1).strip()
    else:
        words = t.split()
        if 1 <= len(words) <= 4 and not re.search(r'\d', t):
            if classify_text_part(t) == 'position':
                res['position'] = t
            
    # 2. Program extraction
    m_prog = re.search(r'(?:программ[аы]|направлени[ея]|курс)[:\s]+([^\n;]+)', t, re.I)
    if m_prog:
        res['program'] = m_prog.group(1).strip()
    else:
        if classify_text_part(t) == 'program':
            res['program'] = t
        
    # 3. Dates extraction
    m_dates = re.search(r'(\d{2}\.\d{2}\.\d{4}\s*[-—–]\s*\d{2}\.\d{2}\.\d{4})', t)
    if m_dates:
        res['study_dates'] = m_dates.group(1).strip()
        
    return res

