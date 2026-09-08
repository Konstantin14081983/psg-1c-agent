"""
Excel Generator for PSG 1C Application Agent.
Creates 1C-compatible Excel spreadsheets strictly conforming to the reference template:
- Sheet: Лист_1
- Fonts: Arial 8pt (data) and Arial 9pt bold (headers)
- Row heights: 23.25 (title), 24.0 (header), 11.25 (program), 22.5 (data)
- Column widths: A=5.75, B=29.25, C=30.25, D=29.25, E=5.75, F=11.75, G=15.25, H=19.75, I=25.75
- Program divider rows: merged A:I, fill #DCFFDD (LIGHT MINT/GREEN как в эталоне 1С)
- Yellow highlighting (#FFFF00) for suspicious / disputed items (WITHOUT cell comments in Excel per manager requirement)
"""

import datetime
from typing import List, Dict, Any, Optional
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from linguistics import clean_application_title

COLUMN_WIDTHS = {
    'A': 5.75,
    'B': 29.25,
    'C': 30.25,
    'D': 29.25,
    'E': 5.75,
    'F': 11.75,
    'G': 15.25,
    'H': 19.75,
    'I': 25.75
}

HEADER_TITLES = [
    '№ п/п',
    'ФИО\n(в именит. падеже)',
    'ФИО\n(в дат. падеже)',
    'Должность',
    'Пол',
    'Дата рождения',
    'СНИЛС',
    'Предполагаемые сроки обучения',
    'Электронная почта и телефон обучающегося'
]

# Style definitions
FONT_TITLE = Font(name='Arial', size=9.0, bold=True)
FONT_HEADER = Font(name='Arial', size=9.0, bold=True)
FONT_DATA = Font(name='Arial', size=8.0, bold=False)
FONT_PROGRAM = Font(name='Arial', size=8.0, bold=False)

# LIGHT MINT / GREEN (#DCFFDD / RGB 220, 255, 221) matching reference 1C template
FILL_PROGRAM_STANDARD = PatternFill(fill_type='solid', start_color='DCFFDD', end_color='DCFFDD')
FILL_YELLOW = PatternFill(fill_type='solid', start_color='FFFF00', end_color='FFFF00')

BORDER_THIN = Side(border_style='thin', color='000000')
BORDER_ALL_THIN = Border(top=BORDER_THIN, bottom=BORDER_THIN, left=BORDER_THIN, right=BORDER_THIN)

BORDER_PROGRAM_LEFT = Border(top=BORDER_THIN, bottom=BORDER_THIN, left=BORDER_THIN, right=None)
BORDER_PROGRAM_MID = Border(top=BORDER_THIN, bottom=BORDER_THIN, left=None, right=None)
BORDER_PROGRAM_RIGHT = Border(top=BORDER_THIN, bottom=BORDER_THIN, left=None, right=BORDER_THIN)

ALIGN_CENTER_CENTER_WRAP = Alignment(horizontal='center', vertical='center', wrap_text=True)
ALIGN_CENTER_CENTER = Alignment(horizontal='center', vertical='center')
ALIGN_RIGHT_TOP = Alignment(horizontal='right', vertical='top')
ALIGN_LEFT_TOP_WRAP = Alignment(horizontal='left', vertical='top', wrap_text=True)
ALIGN_CENTER_TOP = Alignment(horizontal='center', vertical='top')
ALIGN_LEFT_TOP = Alignment(horizontal='left', vertical='top')

def create_1c_application_workbook(
    application_title: Optional[str],
    grouped_programs: Dict[str, Dict[str, Any]]
) -> openpyxl.Workbook:
    """
    Builds the 1C application workbook.
    No cell comments are written to Excel; suspicious cells are highlighted with solid YELLOW fill (#FFFF00).
    Program rows have solid LIGHT MINT/GREEN fill (#DCFFDD).
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Лист_1"
    
    for col_letter, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[col_letter].width = width
        
    # Row 1: Application Title
    ws.row_dimensions[1].height = 23.25
    if application_title:
        application_title, _ = clean_application_title(application_title)
    else:
        today_str = datetime.date.today().strftime("%d.%m.%Y")
        application_title = f"ЗАЯВКА НА ОБУЧЕНИЕ от {today_str} г."
        
    ws.cell(1, 1, application_title)
    ws.merge_cells("A1:I1")
    cell_a1 = ws.cell(1, 1)
    cell_a1.font = FONT_TITLE
    cell_a1.alignment = ALIGN_CENTER_CENTER
    
    # Row 2: Table Header
    ws.row_dimensions[2].height = 24.0
    for col_idx, title in enumerate(HEADER_TITLES, start=1):
        cell = ws.cell(2, col_idx, title)
        cell.font = FONT_HEADER
        cell.alignment = ALIGN_CENTER_CENTER_WRAP
        cell.border = BORDER_ALL_THIN
        
    current_row = 3
    
    for prog_name, prog_info in grouped_programs.items():
        students = prog_info.get('students', [])
        if not students:
            continue
            
        # Program divider row
        ws.row_dimensions[current_row].height = 11.25
        prog_cell = ws.cell(current_row, 1, prog_name)
        prog_cell.font = FONT_PROGRAM
        prog_cell.alignment = ALIGN_LEFT_TOP
        
        is_canonical = prog_info.get('is_canonical', True)
        prog_warning = prog_info.get('warning')
        
        # Apply fill to program row (Yellow if unrecognized, else turquoise #CCFFFF)
        prog_fill = FILL_YELLOW if (not is_canonical or prog_warning) else FILL_PROGRAM_STANDARD
        
        for c in range(1, 10):
            c_cell = ws.cell(current_row, c)
            c_cell.fill = prog_fill
            if c == 1:
                c_cell.border = BORDER_PROGRAM_LEFT
            elif c == 9:
                c_cell.border = BORDER_PROGRAM_RIGHT
            else:
                c_cell.border = BORDER_PROGRAM_MID
                
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=9)
        current_row += 1
        
        # Student rows under this program
        for s_idx, student in enumerate(students, start=1):
            ws.row_dimensions[current_row].height = 22.5
            flags = student.get('yellow_flags', {})
            
            # Col 1 (A): № п/п
            c1 = ws.cell(current_row, 1, s_idx)
            c1.font = FONT_DATA
            c1.alignment = ALIGN_RIGHT_TOP
            c1.border = BORDER_ALL_THIN
            
            # Col 2 (B): ФИО им.
            c2 = ws.cell(current_row, 2, student.get('fio_nom', ''))
            c2.font = FONT_DATA
            c2.alignment = ALIGN_LEFT_TOP_WRAP
            c2.border = BORDER_ALL_THIN
            if 'nom_fio' in flags:
                c2.fill = FILL_YELLOW
                
            # Col 3 (C): ФИО дат.
            c3 = ws.cell(current_row, 3, student.get('fio_dat', ''))
            c3.font = FONT_DATA
            c3.alignment = ALIGN_LEFT_TOP_WRAP
            c3.border = BORDER_ALL_THIN
            if 'dat_fio' in flags:
                c3.fill = FILL_YELLOW
                
            # Col 4 (D): Должность
            c4 = ws.cell(current_row, 4, student.get('position', ''))
            c4.font = FONT_DATA
            c4.alignment = ALIGN_LEFT_TOP_WRAP
            c4.border = BORDER_ALL_THIN
            if 'position' in flags:
                c4.fill = FILL_YELLOW
                
            # Col 5 (E): Пол
            c5 = ws.cell(current_row, 5, student.get('gender', ''))
            c5.font = FONT_DATA
            c5.alignment = ALIGN_CENTER_TOP
            c5.border = BORDER_ALL_THIN
            if 'gender' in flags:
                c5.fill = FILL_YELLOW
                
            # Col 6 (F): Дата рождения
            c6 = ws.cell(current_row, 6, student.get('birth_date', ''))
            c6.font = FONT_DATA
            c6.alignment = ALIGN_LEFT_TOP
            c6.border = BORDER_ALL_THIN
            if 'birth_date' in flags:
                c6.fill = FILL_YELLOW
                
            # Col 7 (G): СНИЛС
            c7 = ws.cell(current_row, 7, student.get('snils', ''))
            c7.font = FONT_DATA
            c7.alignment = ALIGN_LEFT_TOP
            c7.border = BORDER_ALL_THIN
            if 'snils' in flags:
                c7.fill = FILL_YELLOW
                
            # Col 8 (H): Предполагаемые сроки обучения
            c8 = ws.cell(current_row, 8, student.get('study_dates', ''))
            c8.font = FONT_DATA
            c8.alignment = ALIGN_LEFT_TOP_WRAP
            c8.border = BORDER_ALL_THIN
            if 'study_dates' in flags:
                c8.fill = FILL_YELLOW
                
            # Col 9 (I): Электронная почта и телефон обучающегося
            c9 = ws.cell(current_row, 9, student.get('contacts', ''))
            c9.font = FONT_DATA
            c9.alignment = ALIGN_LEFT_TOP_WRAP
            c9.border = BORDER_ALL_THIN
            if 'contacts' in flags:
                c9.fill = FILL_YELLOW
                
            current_row += 1
            
    return wb
