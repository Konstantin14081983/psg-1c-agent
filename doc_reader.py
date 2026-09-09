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
    Extracts application header, tables, and paragraphs from DOCX using direct XML parsing.
    """
    with zipfile.ZipFile(docx_path) as z:
        xml_content = z.read('word/document.xml')
        
    root = ET.fromstring(xml_content)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    body = root.find('w:body', ns)
    
    app_title = None
    paragraphs = []
    tables = []
    
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
        str_vals = [' '.join(str(v).split()) if v is not None else '' for v in row_vals]
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
    """
    import fitz
    doc = fitz.open(pdf_path)
    paragraphs = []
    app_title = None
    
    for page in doc:
        text = page.get_text()
        for line in text.split('\n'):
            line_clean = line.strip()
            if line_clean:
                paragraphs.append(line_clean)
                if not app_title and 'заявка на обучение' in line_clean.lower():
                    app_title = line_clean
                    
    return {
        "title": app_title,
        "paragraphs": paragraphs,
        "tables": []
    }

def identify_columns(header_row: List[str]) -> Dict[str, int]:
    """
    Identifies column indices for standard 1C fields from a header row.
    """
    col_map = {}
    for idx, col in enumerate(header_row):
        c = col.lower()
        if 'фио' in c or 'слушател' in c or 'сотрудник' in c or 'работник' in c:
            if 'дат' in c:
                col_map['fio_dat'] = idx
            else:
                col_map['fio_nom'] = idx
        elif 'должност' in c or 'професси' in c:
            col_map['position'] = idx
        elif 'пол' in c and len(c) <= 5:
            col_map['gender'] = idx
        elif 'рожд' in c:
            col_map['birth_date'] = idx
        elif 'снилс' in c or 'страхов' in c:
            col_map['snils'] = idx
        elif 'срок' in c or 'период' in c or 'окончан' in c or 'сроки обучен' in c:
            col_map['study_dates'] = idx
        elif 'почт' in c or 'телефон' in c or 'email' in c or 'контакт' in c:
            col_map['contacts'] = idx
        elif 'программ' in c or 'направлен' in c or 'курс' in c:
            col_map['program'] = idx
            
    return col_map

PATRONYMIC_ENDINGS = (
    'ович', 'евич', 'ич', 'ыч',
    'овна', 'евна', 'ична', 'инична', 'ычна',
    'оглы', 'угли', 'улы', 'кызы', 'гызы'
)

def is_patronymic(word: str) -> bool:
    """Checks if word has typical Russian or Central Asian patronymic ending."""
    w = word.strip().lower()
    return any(w.endswith(end) for end in PATRONYMIC_ENDINGS)

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
        
    # 3. Catalog matching fallback
    matched = program_matcher.match_programs(part)
    if matched:
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
        
    # Strip leading list markers: '1.', '1)', '1 -', '*', '-'
    line = re.sub(r'^\s*(?:\d+[\.\)\-:]|\([0-9]+\)|\*|\-)\s*', '', line).strip()
    
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
    position = ""
    program = current_program or ""
    
    # 1. Extract study dates range (e.g. 01.09.2026 - 15.09.2026 or 01.09.2026 по 15.09.2026)
    m_dates = re.search(r'(?:(?:сроки|период|даты(?:\s+обучения)?)[:\s]+)?\b(\d{2}\.\d{2}\.\d{4}\s*(?:[-—–]|по)\s*\d{2}\.\d{2}\.\d{4})\b', line, re.I)
    if m_dates:
        dates = m_dates.group(1).strip()
        line = line[:m_dates.start()] + ' , ' + line[m_dates.end():]
        
    # 2. Extract SNILS (including optional 'СНИЛС:' prefix)
    m_snils = re.search(r'(?:снилс[:\s]+)?\b(\d{3}[\s\-]\d{3}[\s\-]\d{3}[\s\-]?\d{2}|\d{11})\b', line, re.I)
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
        # 4b. Numeric date
        m_ndate = re.search(r'(?:(?:д\.?р\.?|рожд\.?|дата\s+рождения)[:\s]+)?\b(\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4})\b', line, re.I)
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
        parts.append(p_clean)
        
    if not fio:
        for i, part in enumerate(parts):
            words = part.split()
            # 3 words with patronymic at index 2
            if len(words) == 3 and is_patronymic(words[2]) and all(w[0].isupper() for w in words if w.isalpha()):
                fio = part
                parts.pop(i)
                break
            # 2 words capitalized
            elif len(words) == 2 and all(w[0].isupper() for w in words if w.isalpha()):
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
        
    # If gender not specified, infer from FIO
    if not gender and fio:
        f_words = fio.split()
        if len(f_words) >= 2:
            gender = linguistics.infer_gender(f_words[0], f_words[1], f_words[2] if len(f_words) > 2 else "")
            
    return {
        "fio_nom": fio,
        "fio_dat": "",
        "position": position,
        "gender": gender,
        "birth_date": birth_date,
        "snils": snils,
        "study_dates": dates,
        "contacts": contacts,
        "program": program or current_program or ""
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
        is_student_row = (',' in line and len(line.split(',')) >= 2) or ('\t' in line) or bool(re.search(r'\d{3}[\s\-]\d{3}[\s\-]\d{3}', line))
        if not is_student_row and any(kw in line_lower for kw in ['программа', 'направление', 'курс', 'обучение по', 'охрана труда']) and len(line.split()) < 25:
            clean_prog = re.sub(r'^(программа|направление|курс)[:\s\-]*', '', line, flags=re.IGNORECASE).strip()
            if clean_prog:
                current_program = clean_prog
                continue
                
        stud = parse_student_line(line, current_program)
        if stud:
            students.append(stud)
            
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
    
    if ext in ('.docx', '.doc'):
        data = extract_docx_data(file_path)
        extracted_title = data.get('title')
        tables = data.get('tables', [])
    elif ext in ('.xlsx', '.xls'):
        data = extract_xlsx_data(file_path)
        extracted_title = data.get('title')
        tables = data.get('tables', [])
    elif ext == '.pdf':
        data = extract_pdf_data(file_path)
        extracted_title = data.get('title')
        # If PDF has plain text lines, try raw text parsing
        if data.get('paragraphs'):
            pdf_text = '\n'.join(data['paragraphs'])
            txt_res = parse_raw_text_application(pdf_text)
            if txt_res['students']:
                return txt_res

        # If scanned PDF without selectable text, render page 1 to image and analyze
        try:
            import fitz
            doc_pdf = fitz.open(file_path)
            if len(doc_pdf) > 0:
                page = doc_pdf[0]
                pix = page.get_pixmap(dpi=200)
                temp_img = os.path.join(os.path.dirname(file_path), f"temp_pdf_{os.path.basename(file_path)}.png")
                pix.save(temp_img)
                import document_vision
                vision_res = document_vision.parse_document_image(temp_img, use_ai=use_ai, openai_api_key=openai_api_key)
                if os.path.exists(temp_img):
                    try:
                        os.remove(temp_img)
                    except Exception:
                        pass
                if vision_res.get('success'):
                    return {
                        "title": extracted_title or f"ЗАЯВКА НА ОБУЧЕНИЕ от {datetime.date.today().strftime('%d.%m.%Y')} г.",
                        "students": [{
                            "fio_nom": vision_res.get('fio') or "Слушатель (по PDF документу)",
                            "fio_dat": "",
                            "position": vision_res.get('position') or "",
                            "gender": vision_res.get('gender') or "",
                            "birth_date": vision_res.get('birth_date') or "",
                            "snils": vision_res.get('snils') or "",
                            "study_dates": "",
                            "contacts": "",
                            "program": "",
                            "engine": vision_res.get('engine', '')
                        }],
                        "engine": vision_res.get('engine', '')
                    }
        except Exception:
            pass
    elif ext in ('.png', '.jpg', '.jpeg', '.heic', '.webp', '.bmp', '.tiff'):
        import document_vision
        vision_res = document_vision.parse_document_image(file_path, use_ai=use_ai, openai_api_key=openai_api_key)
        students = []
        if vision_res.get('success'):
            students.append({
                "fio_nom": vision_res.get('fio') or "Слушатель (по фото документа)",
                "fio_dat": "",
                "position": vision_res.get('position') or "",
                "gender": vision_res.get('gender') or "",
                "birth_date": vision_res.get('birth_date') or "",
                "snils": vision_res.get('snils') or "",
                "study_dates": "",
                "contacts": "",
                "program": "",
                "engine": vision_res.get('engine', '')
            })
        return {
            "title": f"ЗАЯВКА НА ОБУЧЕНИЕ от {datetime.date.today().strftime('%d.%m.%Y')} г.",
            "students": students,
            "engine": vision_res.get('engine', '')
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
            row_str = ' '.join(row).lower()
            if 'фио' in row_str or ('снилс' in row_str and ('должност' in row_str or 'рожд' in row_str)):
                header_idx = r_idx
                col_map = identify_columns(row)
                break
                
        if header_idx == -1:
            continue
            
        current_program = None
        
        for r_idx in range(header_idx + 1, len(tbl)):
            row = tbl[r_idx]
            non_empty = [c for c in row if c.strip()]
            if not non_empty:
                continue
                
            first_cell = row[0].strip().lower()
            if any(term in first_cell for term in ['директор', 'руководител', 'м.п.', 'согласие', 'подпись']):
                break
                
            if len(non_empty) == 1 and not row[0].isdigit():
                current_program = non_empty[0]
                continue
            elif len(non_empty) <= 2 and ('программа' in ' '.join(non_empty).lower() or 'обучение' in ' '.join(non_empty).lower()):
                current_program = ' '.join(non_empty)
                continue
                
            fio_val = row[col_map['fio_nom']].strip() if 'fio_nom' in col_map and col_map['fio_nom'] < len(row) else ''
            if not fio_val:
                continue
                
            if 'фио' in fio_val.lower() or 'подпись' in fio_val.lower():
                continue
                
            fio_dat_val = row[col_map['fio_dat']].strip() if 'fio_dat' in col_map and col_map['fio_dat'] < len(row) else ''
            position_val = row[col_map['position']].strip() if 'position' in col_map and col_map['position'] < len(row) else ''
            gender_val = row[col_map['gender']].strip() if 'gender' in col_map and col_map['gender'] < len(row) else ''
            birth_date_val = row[col_map['birth_date']].strip() if 'birth_date' in col_map and col_map['birth_date'] < len(row) else ''
            snils_val = row[col_map['snils']].strip() if 'snils' in col_map and col_map['snils'] < len(row) else ''
            study_dates_val = row[col_map['study_dates']].strip() if 'study_dates' in col_map and col_map['study_dates'] < len(row) else ''
            contacts_val = row[col_map['contacts']].strip() if 'contacts' in col_map and col_map['contacts'] < len(row) else ''
            
            prog_val = None
            if 'program' in col_map and col_map['program'] < len(row) and row[col_map['program']].strip():
                prog_val = row[col_map['program']].strip()
            elif current_program:
                prog_val = current_program
                
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
            
    return {
        "title": extracted_title,
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
            res['position'] = t
            
    # 2. Program extraction
    m_prog = re.search(r'(?:программ[аы]|направлени[ея]|курс)[:\s]+([^\n;]+)', t, re.I)
    if m_prog:
        res['program'] = m_prog.group(1).strip()
        
    # 3. Dates extraction
    m_dates = re.search(r'(\d{2}\.\d{2}\.\d{4}\s*[-—–]\s*\d{2}\.\d{2}\.\d{4})', t)
    if m_dates:
        res['study_dates'] = m_dates.group(1).strip()
        
    return res

