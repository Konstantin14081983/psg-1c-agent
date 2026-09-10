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
    # Item 4: AI Mode Switch & key drawer
    assert "useAiToggle" in response.text
    assert "aiModeCard" in response.text
    assert "aiStatusBadge" in response.text
    assert "openaiApiKeyInput" in response.text
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

def test_verbal_birth_date():
    import linguistics
    import document_vision
    import psg_agent
    
    # 1. Test linguistics normalize_date directly
    res, ok, warn = linguistics.normalize_date("22 АВГУСТА 2005 ГОДА Г. НОВОСИБИРСК")
    assert ok is True, f"Failed: {warn}"
    assert res == "22.08.2005", f"Expected 22.08.2005, got {res}"
    
    # 2. Test document_vision SNILS card text parsing with verbal date & multiline FIO
    ocr_text = """
    СТРАХОВОЕ СВИДЕТЕЛЬСТВО
    ОБЯЗАТЕЛЬНОГО ПЕНСИОННОГО СТРАХОВАНИЯ
    071-884-230 76
    СИДОРОВ
    АЛЕКСЕЙ
    ПЕТРОВИЧ
    Дата и место рождения
    22 АВГУСТА 2005 ГОДА Г. НОВОСИБИРСК
    Пол МУЖСКОЙ
    Дата регистрации 15.06.2010
    """
    parsed = document_vision.parse_snils_card_text(ocr_text)
    assert parsed["snils"] == "071-884-230 76"
    assert parsed["fio"] == "Сидоров Алексей Петрович"
    assert parsed["birth_date"] == "22.08.2005", f"Expected 22.08.2005, got {parsed['birth_date']}"
    assert parsed["gender"] == "М"
    
    # 3. Test full pipeline with verbal date
    raw_text = """
    1. Сидоров Алексей Петрович, 22 АВГУСТА 2005 ГОДА Г. НОВОСИБИРСК, 071-884-230 76, Электромонтажник, Охрана труда, 01.09.2026 - 15.09.2026
    """
    res_pipeline = psg_agent.process_application(
        raw_text=raw_text,
        output_file="output_1c/test_verbal.xlsx"
    )
    assert res_pipeline["unique_students"] == 1
    stud = list(res_pipeline["grouped_data"].values())[0]["students"][0]
    assert stud["birth_date"] == "22.08.2005"
    assert "birth_date" not in stud["yellow_flags"]
    print("✓ test_verbal_birth_date passed")

def test_multi_ot_sequential_no_violations():
    data = {
        "raw_text": "Федотов Илья Андреевич, монтажник, 071-884-230 76, 22.08.2005",
        "program": "ОТ (Б+СИЗ+ПП)",
        "study_dates": "01.09.2026 - 15.09.2026"
    }
    res = client.post("/api/process", data=data)
    assert res.status_code == 200
    jdata = res.json()
    assert jdata["success"] is True
    assert jdata["audit"]["rule_violations"] == [], f"Expected no violations, got: {jdata['audit']['rule_violations']}"
    # Verify sequential assignment
    dates = [pdata["students"][0]["study_dates"] for pdata in jdata["grouped_data"].values()]
    assert dates == ['01.09.2026 - 05.09.2026', '06.09.2026 - 10.09.2026', '11.09.2026 - 15.09.2026']
    print("✓ test_multi_ot_sequential_no_violations passed")

def test_real_snils_photo_ocr():
    sample_img = "Исходники/snils_photo_sample.jpg"
    assert os.path.exists(sample_img), f"Sample image {sample_img} not found"
    
    with open(sample_img, "rb") as f:
        files = [("files", ("snils_photo_sample.jpg", f, "image/jpeg"))]
        data = {
            "raw_text": "должность монтажник",
            "program": "ОТ (Б+СИЗ+ПП)",
            "study_dates": "01.09.2026 - 15.09.2026"
        }
        res = client.post("/api/process", files=files, data=data)
        
    assert res.status_code == 200, f"Error: {res.text}"
    jdata = res.json()
    assert jdata["success"] is True
    assert jdata["unique_students"] == 1
    stud = list(jdata["grouped_data"].values())[0]["students"][0]
    assert stud["fio_nom"] == "Абрамов Антон Александрович", f"Expected Абрамов Антон Александрович, got {stud['fio_nom']}"
    assert stud["snils"] == "094-314-268 64", f"Expected 094-314-268 64, got {stud['snils']}"
    assert stud["birth_date"] == "12.04.1983", f"Expected 12.04.1983, got {stud['birth_date']}"
    assert stud["gender"] == "М", f"Expected М, got {stud['gender']}"
    assert "Монтажник" in stud["position"], f"Expected Монтажник, got {stud['position']}"
    print("✓ test_real_snils_photo_ocr passed")

def test_snils_ocr_edge_cases():
    import document_vision
    
    # 1. Test single-digit checksum repair (5 -> 6)
    rep, ok = document_vision.repair_snils_checksum("094-314-258 64")
    assert ok is True, "Checksum repair failed"
    assert rep == "094-314-268 64", f"Expected 094-314-268 64, got {rep}"
    
    # 2. Test first name repair (Нтон -> Антон)
    assert document_vision.correct_first_name("Нтон") == "Антон"
    assert document_vision.correct_first_name("Нтн") == "Антон"
    
    # 3. Test broken lines FIO merging ('А' on separate line from 'НТОН')
    fio_res = document_vision.extract_fio_candidates([
        "Фио АБРАМОВ",
        "А",
        "НТОН",
        "АЛЕКСАНДРОВИЧ"
    ])
    assert fio_res == "Абрамов Антон Александрович", f"Expected Абрамов Антон Александрович, got {fio_res}"
    
    # 4. Test birth date with noisy prefix/suffix
    date_res = document_vision.extract_birth_date("ождения _12 апреля 1983 года МАИ")
    assert date_res == "12.04.1983", f"Expected 12.04.1983, got {date_res}"
    print("✓ test_snils_ocr_edge_cases passed")

def test_text_message_fio_position_parsing():
    """
    Test user request:
    1.Абрамов Антон Александрович, Монтажник
    2. Федотов Илья Андреевич, Бетонщик
    Must parse FIO cleanly without swallowing Position into FIO!
    """
    import doc_reader
    raw_text = """
    1.Абрамов Антон Александрович, Монтажник
    2. Федотов Илья Андреевич, Бетонщик
    """
    res = doc_reader.parse_raw_text_application(raw_text)
    students = res.get("students", [])
    assert len(students) == 2, f"Expected 2 students, got {len(students)}"
    
    assert students[0]["fio_nom"] == "Абрамов Антон Александрович", f"Expected Абрамов Антон Александрович, got {students[0]['fio_nom']}"
    assert students[0]["position"] == "Монтажник", f"Expected Монтажник, got {students[0]['position']}"
    assert "Монтажник" not in students[0]["fio_nom"]
    
    assert students[1]["fio_nom"] == "Федотов Илья Андреевич", f"Expected Федотов Илья Андреевич, got {students[1]['fio_nom']}"
    assert students[1]["position"] == "Бетонщик", f"Expected Бетонщик, got {students[1]['position']}"
    assert "Бетонщик" not in students[1]["fio_nom"]
    print("✓ test_text_message_fio_position_parsing passed")

def test_seven_fields_extraction():
    """
    Test extraction of all 7 fields from a raw message:
    ФИО, Должность, Пол, Дата рождения, СНИЛС, сроки обучения, контакты.
    """
    import doc_reader
    line = "1. Абрамов Антон Александрович, Монтажник, муж, 12.04.1983, 094-314-268 64, 01.09.2026 - 15.09.2026, +7 (999) 123-45-67"
    stud = doc_reader.parse_student_line(line)
    assert stud is not None
    assert stud["fio_nom"] == "Абрамов Антон Александрович"
    assert stud["position"] == "Монтажник"
    assert stud["gender"] == "М"
    assert stud["birth_date"] == "12.04.1983"
    assert stud["snils"] == "094-314-268 64"
    assert stud["study_dates"] == "01.09.2026 - 15.09.2026"
    assert "+7 (999) 123-45-67" in stud["contacts"]
    print("✓ test_seven_fields_extraction passed")

def test_file_and_text_reconciliation_no_duplicates():
    """
    Test reconciliation between uploaded document (Abramov SNILS photo) and text message:
    1.Абрамов Антон Александрович, Монтажник
    2. Федотов Илья Андреевич, Бетонщик
    Must merge Abramov's position from text with his SNILS & birth date from the document,
    and add Fedotov as the 2nd student without duplicating Abramov!
    """
    sample_img = "Исходники/snils_photo_sample.jpg"
    assert os.path.exists(sample_img), f"Sample image {sample_img} not found"
    
    with open(sample_img, "rb") as f:
        files = [("files", ("snils_photo_sample.jpg", f, "image/jpeg"))]
        data = {
            "raw_text": "1.Абрамов Антон Александрович, Монтажник\n2. Федотов Илья Андреевич, Бетонщик",
            "program": "ОТ (Б+СИЗ+ПП)",
            "study_dates": "01.09.2026 - 15.09.2026"
        }
        res = client.post("/api/process", files=files, data=data)
        
    assert res.status_code == 200, f"Error: {res.text}"
    jdata = res.json()
    assert jdata["success"] is True
    assert jdata["unique_students"] == 2, f"Expected 2 unique students, got {jdata['unique_students']}"
    
    # Check Abramov
    abramov = [s for s in jdata["students_summary"] if "Абрамов" in s["fio"]][0]
    assert abramov["position"] == "Монтажник"
    assert abramov["snils"] == "094-314-268 64"
    assert abramov["birth_date"] == "12.04.1983"
    
    # Check Fedotov
    fedotov = [s for s in jdata["students_summary"] if "Федотов" in s["fio"]][0]
    assert fedotov["position"] == "Бетонщик"
    
    # Verify Excel file contents
    out_file = os.path.join("output_1c", jdata["output_filename"])
    wb = openpyxl.load_workbook(out_file)
    ws = wb["Лист_1"]
    
    # Find rows for Abramov and Fedotov
    found_abramov = False
    found_fedotov = False
    for r in range(4, ws.max_row + 1):
        nom_fio = ws.cell(r, 2).value
        dat_fio = ws.cell(r, 3).value
        pos = ws.cell(r, 4).value
        if nom_fio == "Абрамов Антон Александрович":
            found_abramov = True
            assert pos == "Монтажник", f"Expected Монтажник in row {r}, got {pos}"
            assert dat_fio == "Абрамову Антону Александровичу"
            assert ws.cell(r, 6).value == "12.04.1983"
            assert ws.cell(r, 7).value == "094-314-268 64"
        elif nom_fio == "Федотов Илья Андреевич":
            found_fedotov = True
            assert pos == "Бетонщик", f"Expected Бетонщик in row {r}, got {pos}"
            assert dat_fio == "Федотову Илье Андреевичу"
            
    assert found_abramov is True, "Abramov row not found in Excel"
    assert found_fedotov is True, "Fedotov row not found in Excel"
    print("✓ test_file_and_text_reconciliation_no_duplicates passed")

def test_ai_toggle_and_mocked_execution():
    """
    Test POST /api/process with use_ai=True and mocked OpenAI Vision API.
    """
    from unittest.mock import patch, MagicMock
    import json
    
    mock_ai_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "fio": "Кузнецов Дмитрий Сергеевич",
                    "birth_date": "15.07.1991",
                    "gender": "М",
                    "snils": "112-233-445 95",
                    "doc_type": "СНИЛС",
                    "position": "Электрогазосварщик",
                    "citizenship": "РФ"
                })
            }
        }]
    }
    
    sample_img = "Исходники/snils_photo_sample.jpg"
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_ai_response
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp
        
        with open(sample_img, "rb") as f:
            files = [("files", ("test_ai.jpg", f, "image/jpeg"))]
            data = {
                "use_ai": "true",
                "openai_api_key": "sk-testkey12345",
                "program": "Охрана труда",
                "study_dates": "01.09.2026 - 15.09.2026"
            }
            res = client.post("/api/process", files=files, data=data)
            
        assert res.status_code == 200
        jdata = res.json()
        assert jdata["success"] is True
        assert jdata["ocr_engine"] == "OpenAI Vision (GPT-4o-mini)"
        stud = list(jdata["grouped_data"].values())[0]["students"][0]
        assert stud["fio_nom"] == "Кузнецов Дмитрий Сергеевич"
        assert stud["fio_dat"] == "Кузнецову Дмитрию Сергеевичу"
        assert stud["birth_date"] == "15.07.1991"
        assert stud["snils"] == "112-233-445 95"
        assert stud["position"] == "Электрогазосварщик"
        print("✓ test_ai_toggle_and_mocked_execution passed")

def test_ai_fallback_to_tesseract_on_api_error():
    """
    Test that if use_ai=True but OpenAI fails (e.g. 401 Unauthorized or network error),
    the system automatically and gracefully falls back to local Tesseract OCR.
    """
    from unittest.mock import patch
    import requests
    
    sample_img = "Исходники/snils_photo_sample.jpg"
    with patch("requests.post", side_effect=requests.RequestException("OpenAI API unreachable")):
        with open(sample_img, "rb") as f:
            files = [("files", ("test_fallback.jpg", f, "image/jpeg"))]
            data = {
                "use_ai": "true",
                "openai_api_key": "sk-badkey",
                "program": "ОТ (Б+СИЗ+ПП)",
                "study_dates": "01.09.2026 - 15.09.2026"
            }
            res = client.post("/api/process", files=files, data=data)
            
        assert res.status_code == 200
        jdata = res.json()
        assert jdata["success"] is True
        # Must fall back to Tesseract
        assert jdata["ocr_engine"] == "Локальный Tesseract OCR"
        stud = list(jdata["grouped_data"].values())[0]["students"][0]
        assert "Абрамов" in stud["fio_nom"]
        print("✓ test_ai_fallback_to_tesseract_on_api_error passed")

def test_text_input_nlp_autocorrection_and_audit():
    """
    Test auto-correction of typos in FIO (case, double letters, missing letters),
    positions, birth dates, and SNILS from raw text messages, and verification
    that all corrections are tracked in audit warnings and yellow flags.
    """
    # 1. Test casing and numbering removal: '1. Петров Геннадий иванович'
    res1 = client.post("/api/process", data={
        "raw_text": "1. Петров Геннадий иванович",
        "program": "Охрана труда",
        "study_dates": "01.09.2026 - 15.09.2026"
    })
    assert res1.status_code == 200
    jdata1 = res1.json()
    assert jdata1["success"] is True
    students1 = list(jdata1["grouped_data"].values())[0]["students"]
    assert len(students1) == 1
    s1 = students1[0]
    assert s1["fio_nom"] == "Петров Геннадий Иванович"
    assert s1["fio_dat"] == "Петрову Геннадию Ивановичу"
    assert bool(s1["yellow_flags"]["nom_fio"]) is True
    warnings1 = jdata1["audit"]["warnings"]
    assert any("Исправлен регистр" in w.get("reason", "") and "Иванович" in w.get("reason", "") for w in warnings1)
    print("✓ test_text_input_nlp_autocorrection_and_audit: casing & numbering passed")

    # 2. Test double letters in FIO & position, 2-digit year date, unhyphenated SNILS
    text2 = "Пеетров Сергей Иваанович, сваарщик, 15.07.91, 11223344595"
    res2 = client.post("/api/process", data={
        "raw_text": text2,
        "program": "Охрана труда",
        "study_dates": "01.09.2026 - 15.09.2026"
    })
    assert res2.status_code == 200
    jdata2 = res2.json()
    assert jdata2["success"] is True
    students2 = list(jdata2["grouped_data"].values())[0]["students"]
    assert len(students2) == 1
    s2 = students2[0]
    assert s2["fio_nom"] == "Петров Сергей Иванович"
    assert s2["position"] == "Сварщик"
    assert s2["birth_date"] == "15.07.1991"
    assert s2["snils"] == "112-233-445 95"
    assert bool(s2["yellow_flags"]["nom_fio"]) is True
    assert bool(s2["yellow_flags"]["position"]) is True
    warnings2 = jdata2["audit"]["warnings"]
    assert any("задвоение букв" in w.get("reason", "") for w in warnings2)
    assert any("опечатки в должности" in w.get("reason", "") and "Сварщик" in w.get("reason", "") for w in warnings2)
    print("✓ test_text_input_nlp_autocorrection_and_audit: double letters & formatting passed")

    # 3. Test missing letters in patronymics
    text3 = "Сидоров Александр Вячеславоич"
    res3 = client.post("/api/process", data={
        "raw_text": text3,
        "program": "Охрана труда",
        "study_dates": "01.09.2026 - 15.09.2026"
    })
    assert res3.status_code == 200
    jdata3 = res3.json()
    assert jdata3["success"] is True
    students3 = list(jdata3["grouped_data"].values())[0]["students"]
    assert len(students3) == 1
    s3 = students3[0]
    assert s3["fio_nom"] == "Сидоров Александр Вячеславович"
    assert s3["fio_dat"] == "Сидорову Александру Вячеславовичу"
    assert bool(s3["yellow_flags"]["nom_fio"]) is True
    warnings3 = jdata3["audit"]["warnings"]
    assert any("Вячеславоич" in w.get("reason", "") and "Вячеславович" in w.get("reason", "") for w in warnings3)
    print("✓ test_text_input_nlp_autocorrection_and_audit: missing letters passed")

    # 4. Test date with 'г' and patronymic with tail garbage: '22.12.1978г Хабибуллин Рустем Фанильевичывсвы'
    text4 = "22.12.1978г Хабибуллин Рустем Фанильевичывсвы"
    res4 = client.post("/api/process", data={
        "raw_text": text4,
        "program": "Охрана труда",
        "study_dates": "01.09.2026 - 15.09.2026"
    })
    assert res4.status_code == 200
    jdata4 = res4.json()
    assert jdata4["success"] is True
    students4 = list(jdata4["grouped_data"].values())[0]["students"]
    assert len(students4) == 1
    s4 = students4[0]
    assert s4["fio_nom"] == "Хабибуллин Рустем Фанильевич"
    assert s4["fio_dat"] == "Хабибуллину Рустему Фанильевичу"
    assert s4["birth_date"] == "22.12.1978"
    assert bool(s4["yellow_flags"]["nom_fio"]) is True
    warnings4 = jdata4["audit"]["warnings"]
    assert not any("Не удалось распознать формат даты" in w.get("reason", "") for w in warnings4)
    assert any("Фанильевичывсвы" in w.get("reason", "") for w in warnings4)
    print("✓ test_text_input_nlp_autocorrection_and_audit: date with 'г' and tail garbage passed")

def test_ai_status_endpoint():
    """
    Test GET /api/ai-status diagnostics under various conditions.
    """
    from unittest.mock import patch, MagicMock

    # 1. Without key
    with patch("ai_vision.get_api_key", return_value=None):
        res = client.get("/api/ai-status")
        assert res.status_code == 200
        j = res.json()
        assert j["ok"] is False
        assert j["code"] == "NO_KEY"

    # 2. With valid key and mock 200 response
    with patch("requests.get") as mock_get, patch("ai_vision.get_api_key", return_value="sk-proj-validtestkey12345"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        res = client.get("/api/ai-status")
        assert res.status_code == 200
        j = res.json()
        assert j["ok"] is True
        assert j["code"] == "OK"

    # 3. With 403 Russian geoblock
    with patch("requests.get") as mock_get, patch("ai_vision.get_api_key", return_value="sk-proj-validtestkey12345"):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "unsupported_country_region_territory"
        mock_get.return_value = mock_resp
        res = client.get("/api/ai-status")
        assert res.status_code == 200
        j = res.json()
        assert j["ok"] is False
        assert j["code"] == "GEOBLOCK_403"
        assert "OPENAI_BASE_URL" in j["message"]

    # 4. With unexpected exception in check_ai_connection
    with patch("ai_vision.check_ai_connection", side_effect=RuntimeError("Unexpected test crash")):
        res = client.get("/api/ai-status")
        assert res.status_code == 200
        j = res.json()
        assert j["ok"] is False
        assert j["code"] == "SERVER_ERROR"
        assert "Unexpected test crash" in j["message"]

    print("✓ test_ai_status_endpoint passed")

if __name__ == "__main__":
    test_homepage()
    test_errors_sample_file()
    test_process_raw_text()
    test_image_and_multi_programs()
    test_verbal_birth_date()
    test_multi_ot_sequential_no_violations()
    test_real_snils_photo_ocr()
    test_snils_ocr_edge_cases()
    test_text_message_fio_position_parsing()
    test_seven_fields_extraction()
    test_file_and_text_reconciliation_no_duplicates()
    test_ai_toggle_and_mocked_execution()
    test_ai_fallback_to_tesseract_on_api_error()
    test_text_input_nlp_autocorrection_and_audit()
    test_ai_status_endpoint()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")




