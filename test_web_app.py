"""
Unit tests for PSG 1C Web Application API and rules.
Tests:
- GET / (homepage with branding and logo)
- POST /api/process (with sample 2 docx)
- POST /api/process (with Ошибки в заявке.xlsx)
- Verification of yellow highlight on nom_fio for 'Хабибуллин Рустем Фанильевичывсвы'
- Verification of clean deletion of 'uuuuu' and '111111'
- Verification of turquoise program fill (#CCFFFF)
- Auto-fill dates and category rules
"""

import os
import openpyxl
from starlette.testclient import TestClient
from web_app import app
import training_rules
import datetime

client = TestClient(app)

def test_homepage():
    response = client.get("/")
    assert response.status_code == 200
    assert "ЧОУ ДПО ЦЕНТР" in response.text
    assert "«ПСГ»" in response.text
    assert "data:image/png;base64," in response.text
    assert "Добавить еще файл" in response.text
    assert "Авто-заполнение" in response.text
    # Item 1: Must NOT contain 'Заливка программ — бирюзовая'
    assert "Заливка программ — бирюзовая" not in response.text, "Text 'Заливка программ — бирюзовая' should be removed"
    # Item 2: Must contain clear manual params button
    assert "Очистить параметры" in response.text
    assert "clearManualParams" in response.text
    # Item 3: Must contain auto-mask for datesInput
    assert "datesInput" in response.text
    print("✓ test_homepage passed")

def test_errors_sample_file():
    sample_file = "Исходники/Ошибки в заявке.xlsx"
    assert os.path.exists(sample_file), f"File {sample_file} not found"
    
    with open(sample_file, "rb") as f:
        files = [("files", ("Ошибки_в_заявке.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
        res = client.post("/api/process", files=files)
        
    assert res.status_code == 200, f"Error: {res.text}"
    data = res.json()
    assert data["success"] is True
    assert data["unique_students"] == 2
    
    # Check that nom_fio is in yellow flags for Khabibullin
    khabibullin_summary = [s for s in data["students_summary"] if "Хабибуллин" in s["fio"]][0]
    assert "nom_fio" in khabibullin_summary["flags"], "nom_fio must be flagged yellow for Khabibullin"
    assert "dat_fio" in khabibullin_summary["flags"], "dat_fio must be flagged yellow for Khabibullin"
    
    # Check that contacts for both students are empty (uuuuu and 111111 stripped cleanly without flags)
    assert khabibullin_summary["contacts"] == ""
    assert "contacts" not in khabibullin_summary["flags"], "garbage contacts should NOT be flagged yellow"
    
    # Verify the generated Excel file
    out_file = os.path.join("output_1c", data["output_filename"])
    wb = openpyxl.load_workbook(out_file)
    ws = wb["Лист_1"]
    
    # Check Title in Row 1: must be sanitized without '!' and with cleaned year and joined number
    title_val = ws.cell(1, 1).value
    assert "!" not in title_val, f"Title should not contain exclamation marks: {title_val}"
    assert "2026в" not in title_val, f"Title should not contain stray year typo: {title_val}"
    assert "0000000009 0" not in title_val, f"Title should not contain split number: {title_val}"
    assert "2026 г." in title_val, f"Title should contain proper year format: {title_val}"
    
    # Check program fill: must be light mint 00DCFFDD
    prog_fill_color = ws.cell(3, 1).fill.start_color.rgb
    assert prog_fill_color == "00DCFFDD", f"Expected 00DCFFDD, got {prog_fill_color}"
    
    # Check Row 5 (Khabibullin): Cell B5 (nom_fio) must be yellow!
    cell_b5_color = ws.cell(5, 2).fill.start_color.rgb
    assert cell_b5_color == "00FFFF00", f"Cell B5 must be yellow, got {cell_b5_color}"
    
    # Check Contacts in Row 4 and Row 5: must be None / empty and not yellow
    assert ws.cell(4, 9).value is None
    assert ws.cell(5, 9).value is None
    assert ws.cell(4, 9).fill.fill_type is None or ws.cell(4, 9).fill.start_color.rgb != "00FFFF00"
    
    print("✓ test_errors_sample_file and Excel styling passed")

def test_process_raw_text():
    text_data = """
    1. Иванов Иван Иванович, 12.05.1985, 189-878-867 92, монтажник м/к, Пожарка, 01.09.2026 - 10.09.2026
    2. Петров Петр Петрович, 20.08.1990, 078-404-337 73, пом. бурильщика, Высота 1 группа, 05.09.2026 - 08.09.2026
    """
    res = client.post("/api/process", data={"raw_text": text_data})
    assert res.status_code == 200
    json_data = res.json()
    assert json_data["success"] is True
    assert json_data["unique_students"] == 2
    print("✓ test_process_raw_text passed")

def test_image_and_multi_programs():
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (600, 300), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((30, 30), 'СТРАХОВОЕ СВИДЕТЕЛЬСТВО', fill='black')
    draw.text((30, 80), '078-404-337 73', fill='black')
    draw.text((30, 130), '22.12.1978', fill='black')
    img_path = "uploads/test_snils_temp.png"
    img.save(img_path)
    
    try:
        with open(img_path, "rb") as f:
            files = [("files", ("test_snils_temp.png", f, "image/png"))]
            data = {
                "raw_text": "должность монтажник",
                "program": "ОТ (Б+СИЗ+ПП); Высота 1 группа",
                "study_dates": "01.09.2026 - 15.09.2026"
            }
            res = client.post("/api/process", files=files, data=data)
            
        assert res.status_code == 200
        jdata = res.json()
        assert jdata["success"] is True
        assert jdata["unique_students"] == 1
        assert jdata["programs_count"] == 4
        # Verify position was assigned from raw_text
        student_obj = list(jdata["grouped_data"].values())[0]["students"][0]
        assert "Монтажник" in student_obj["position"]
        print("✓ test_image_and_multi_programs passed")
    finally:
        if os.path.exists(img_path):
            os.remove(img_path)

if __name__ == "__main__":
    test_homepage()
    test_errors_sample_file()
    test_process_raw_text()
    test_image_and_multi_programs()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")

