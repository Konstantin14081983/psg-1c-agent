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

def parse_raw_text_application(raw_text: str) -> Dict[str, Any]:
    """
    Parses plain text messages (e.g. from WhatsApp, Telegram, Email, copy-pasted blocks).
    Supports:
    - Tab-delimited rows (from Excel)
    - Comma / semicolon delimited rows
    - Numbered lists: '1. Иванов Иван Иванович, 12.05.1985, 123-456-789 00, монтажник...'
    - Block format: ФИО: ..., СНИЛС: ..., Должность: ...
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
        if any(kw in line_lower for kw in ['программа', 'направление', 'курс', 'обучение по', 'охрана труда']) and len(line.split()) < 25:
            # Looks like a program header
            clean_prog = re.sub(r'^(программа|направление|курс)[:\s\-]*', '', line, flags=re.IGNORECASE).strip()
            if clean_prog:
                current_program = clean_prog
                continue
                
        # Try tab separation
        if '\t' in line:
            parts = [p.strip() for p in line.split('\t')]
        elif ';' in line:
            parts = [p.strip() for p in line.split(';')]
        else:
            # Try comma separation if contains commas and multiple parts
            comma_parts = [p.strip() for p in line.split(',')]
            if len(comma_parts) >= 3:
                parts = comma_parts
            else:
                parts = [line]
                
        # Extract fields from parts
        fio = ""
        fio_dat = ""
        snils = ""
        birth_date = ""
        position = ""
        prog = current_program
        dates = ""
        contacts = ""
        
        # Strip leading numbers: e.g. "1. Иванов" or "1)"
        if parts and re.match(r'^\d+[\.\)\s]', parts[0]):
            parts[0] = re.sub(r'^\d+[\.\)\s]+', '', parts[0]).strip()
            
        for part in parts:
            p_clean = part.strip()
            # Check for SNILS
            if re.search(r'\d{3}[\s\-]\d{3}[\s\-]\d{3}[\s\-]\d{2}|\d{11}', p_clean):
                snils = p_clean
            # Check for Date
            elif re.search(r'\b\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}\b', p_clean):
                if not birth_date:
                    birth_date = p_clean
                else:
                    dates = p_clean
            # Check for email or phone
            elif '@' in p_clean or re.search(r'\+7|\b8\d{10}\b', p_clean):
                contacts = p_clean
            # Check for FIO: 2-3 Cyrillic words
            elif not fio and len(p_clean.split()) in (2, 3, 4) and all(w[0].isupper() for w in p_clean.split() if w.isalpha()):
                fio = p_clean
            # Otherwise could be position or program
            elif not position and len(p_clean.split()) <= 6:
                position = p_clean
            elif not prog:
                prog = p_clean
                
        if fio:
            students.append({
                "fio_nom": fio,
                "fio_dat": fio_dat,
                "position": position,
                "gender": "",
                "birth_date": birth_date,
                "snils": snils,
                "study_dates": dates,
                "contacts": contacts,
                "program": prog or current_program
            })
            
    return {
        "title": app_title,
        "students": students
    }

def parse_incoming_application(file_path: str) -> Dict[str, Any]:
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
    elif ext in ('.png', '.jpg', '.jpeg', '.heic', '.webp', '.bmp', '.tiff'):
        import document_vision
        vision_res = document_vision.parse_document_image(file_path)
        students = []
        if vision_res.get('success'):
            students.append({
                "fio_nom": vision_res.get('fio') or "Слушатель (по фото документа)",
                "fio_dat": "",
                "position": "",
                "gender": vision_res.get('gender') or "",
                "birth_date": vision_res.get('birth_date') or "",
                "snils": vision_res.get('snils') or "",
                "study_dates": "",
                "contacts": "",
                "program": ""
            })
        return {
            "title": f"ЗАЯВКА НА ОБУЧЕНИЕ от {datetime.date.today().strftime('%d.%m.%Y')} г.",
            "students": students
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

