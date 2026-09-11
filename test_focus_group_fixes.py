"""
Comprehensive test suite verifying focus group remediation:
1. Vector PDF table extraction + letter body program extraction (e.g. АО «Элмек»).
2. Exclusion of header recipients ("Директору...") and signatories ("Главный инженер...") from student records.
3. "Квалификационное" / "повышение квалификации" rule mapping to worker profession from position.
4. "На кого обучаем" column mapping to program + complex multi-program text parsing (A, B, V, First Aid typo, PPE).
5. Multimodal AI Vision multi-student table unpacking into 1C spreadsheet.
6. DOCX / DOC resilient multi-tier extraction.
"""

import os
import unittest
from unittest.mock import patch, MagicMock
import openpyxl

import doc_reader
import program_matcher
import psg_agent
import ai_vision

class TestFocusGroupFixes(unittest.TestCase):

    def test_pdf_vector_table_and_letter_programs(self):
        pdf_path = "/Users/konstantinageev/.gemini/antigravity/brain/d535fd35-9aa2-4cfd-b984-22e3861d2f34/.user_uploaded/media_1789105022769.pdf"
        if not os.path.exists(pdf_path):
            self.skipTest("Uploaded focus group PDF not found on disk")

        # 1. Standard scanner (no AI)
        res = doc_reader.parse_incoming_application(pdf_path, use_ai=False)
        students = res.get("students", [])
        self.assertEqual(len(students), 1, "Exactly 1 student should be found in vector table")
        s = students[0]
        self.assertEqual(s["fio_nom"], "Вакин Константин Павлович")
        self.assertEqual(s["position"], "Техник сервиса")
        self.assertEqual(s["birth_date"], "28.01.1980")
        self.assertEqual(s["snils"], "146-782-121 80")
        
        # Verify no header/signatory false positives
        fios = [stud["fio_nom"] for stud in students]
        self.assertFalse(any("директор" in f.lower() for f in fios))
        self.assertFalse(any("элмек" in f.lower() for f in fios))
        self.assertFalse(any("гусевской" in f.lower() for f in fios))
        self.assertFalse(any("михайличенко" in f.lower() for f in fios))

        # 2. End-to-end 1C pipeline
        out = psg_agent.process_application(input_file=pdf_path, use_ai=False)
        self.assertTrue(out["success"])
        self.assertEqual(out["unique_students"], 1)
        self.assertEqual(out["total_enrollments"], 6, "All 6 programs from letter must be enrolled")
        self.assertTrue(os.path.exists(out["output_file"]))

    def test_kvalifikatsionnoe_worker_profession_mapping(self):
        cases = [
            ("квалификационное", "Слесарь-ремонтник 4 разряда", "Профессиональная подготовка по профессии Слесарь-ремонтник 4 разряда"),
            ("квалификационное удостоверение", "Электрогазосварщик 5 разряда", "Профессиональная подготовка по профессии Электрогазосварщик"),
            ("повышение квалификации", "Машинист крана автомобильного", "Профессиональная подготовка по профессии Машинист крана автомобильного 8 разряд"),
            ("присвоение квалификации", "Стропальщик 3 разряда", "Профессиональная подготовка по профессии Стропальщик"),
            ("аттестация", "Монтажник стальных конструкций", "Профессиональная подготовка по профессии Монтажник стальных конструкций")
        ]
        for prog_input, pos, expected_canonical in cases:
            matched = program_matcher.match_programs(prog_input, position=pos)
            self.assertTrue(len(matched) >= 1)
            self.assertEqual(matched[0]["name"], expected_canonical)

    def test_image_column_mapping_and_multi_programs(self):
        # 1. Header mapping
        header = ["ФИО", "Должность/профессия", "СНИЛС", "На кого обучаем", "Наименование организации", "Дата рождения", "Пол"]
        col_map = doc_reader.identify_columns(header)
        self.assertEqual(col_map.get("fio_nom"), 0)
        self.assertEqual(col_map.get("position"), 1)
        self.assertEqual(col_map.get("snils"), 2)
        self.assertEqual(col_map.get("program"), 3, "'На кого обучаем' must map to program column")
        self.assertEqual(col_map.get("organization"), 4)
        self.assertEqual(col_map.get("birth_date"), 5)
        self.assertEqual(col_map.get("gender"), 6)

        # 2. Multi-program text with OCR typo 'помоши'
        prog_text = "Программа: «А», «Б», «В» (№5,8,9, 10, 15,27) Оказание первой помоши, Применение СИЗ"
        matched = program_matcher.match_programs(prog_text)
        self.assertEqual(len(matched), 5, "Must match all 5 distinct programs: A, B, V, First Aid, PPE")
        names = [m["name"] for m in matched]
        self.assertTrue(any("общим вопросам охраны труда" in n.lower() for n in names))
        self.assertTrue(any("вредных и (или) опасных" in n.lower() for n in names))
        self.assertTrue(any("повышенной опасности" in n.lower() for n in names))
        self.assertTrue(any("первой помощи" in n.lower() for n in names))
        self.assertTrue(any("средств индивидуальной защиты" in n.lower() for n in names))

    @patch("ai_vision._http_post")
    def test_ai_vision_multi_student_extraction(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '''{
                            "doc_type": "application_table",
                            "application_title": "Заявка на обучение АО Тест",
                            "common_programs": ["Оказание первой помощи"],
                            "students": [
                                {
                                    "fio": "Иванов Иван Иванович",
                                    "position": "Монтажник",
                                    "birth_date": "10.05.1988",
                                    "gender": "М",
                                    "snils": "111-222-333 44",
                                    "programs": ["Охрана труда Б"]
                                },
                                {
                                    "fio": "Петрова Анна Сергеевна",
                                    "position": "Инженер",
                                    "birth_date": "15.08.1992",
                                    "gender": "Ж",
                                    "snils": "555-666-777 88",
                                    "programs": ["Охрана труда А", "Охрана труда Б"]
                                }
                            ]
                        }'''
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # Use any dummy image
        sample_img = "Исходники/snils_photo_sample.jpg"
        ai_res = ai_vision.analyze_document_with_ai(sample_img, api_key="sk-test-key")
        self.assertTrue(ai_res["success"])
        students = ai_res["students"]
        self.assertEqual(len(students), 2, "AI Vision must extract all students in table")
        self.assertEqual(students[0]["fio"], "Иванов Иван Иванович")
        self.assertEqual(students[0]["gender"], "М")
        self.assertEqual(students[1]["fio"], "Петрова Анна Сергеевна")
        self.assertEqual(students[1]["gender"], "Ж")

    def test_word_doc_robustness(self):
        # Verify extract_docx_data handles arbitrary binary files without crashing
        test_file = "uploads/test_corrupted.doc"
        with open(test_file, "wb") as f:
            f.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100) # OLE2 header
        try:
            res = doc_reader.extract_docx_data(test_file)
            self.assertIn("tables", res)
            self.assertIn("paragraphs", res)
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
