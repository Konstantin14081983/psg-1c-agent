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
import linguistics

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

    def test_ocr_date_space_and_split_patronymic_autocorrection(self):
        # 1. Test normalize_date autocorrects OCR spaces in dates directly into valid dates
        date_cases = [
            ("26.07.198 2", "26.07.1982"),
            ("26.07.19 82", "26.07.1982"),
            ("26.07.1 9 8 2", "26.07.1982"),
            ("26 . 07 . 1982", "26.07.1982"),
            ("2 6.07.1982", "26.07.1982"),
            ("26.0 7.1982", "26.07.1982"),
            (" 26.07.198 2 г.", "26.07.1982"),
        ]
        for inp, expected in date_cases:
            d_norm, ok, warn = linguistics.normalize_date(inp)
            self.assertTrue(ok, f"Failed on {inp}: {warn}")
            self.assertEqual(d_norm, expected)

        # 2. Test split patronymic rejoining and declension
        fio_inp = "Черняков Сергей Александрови Ч"
        fio_res = linguistics.process_person_fio(fio_inp)
        self.assertEqual(fio_res["nom_fio"], "Черняков Сергей Александрович")
        self.assertEqual(fio_res["dat_fio"], "Чернякову Сергею Александровичу")
        self.assertEqual(fio_res["gender"], "М")
        self.assertEqual(fio_res["surname"], "Черняков")
        self.assertEqual(fio_res["firstname"], "Сергей")
        self.assertEqual(fio_res["patronymic"], "Александрович")

        # 3. Test parse_student_line end-to-end with this exact focus group line
        line = "Черняков Сергей Александрови Ч, 26.07.198 2, 146-782-121 80, Монтажник, Охрана труда"
        student = doc_reader.parse_student_line(line)
        self.assertIsNotNone(student)
        self.assertEqual(student["fio_nom"], "Черняков Сергей Александрович")
        self.assertEqual(student["birth_date"], "26.07.1982")
        self.assertEqual(student["position"], "Монтажник")
        self.assertEqual(student["snils"], "146-782-121 80")

        # 4. Test psg_agent processing row directly: birth_date must be clean and have no yellow flag
        out = psg_agent.process_application(raw_text=line)
        self.assertTrue(out["success"])
        students_out = list(out["grouped_data"].values())[0]["students"]
        self.assertEqual(len(students_out), 1)
        s0 = students_out[0]
        self.assertEqual(s0["birth_date"], "26.07.1982")
        self.assertNotIn("birth_date", s0["yellow_flags"], "birth_date must NOT have error/warning flag")

    def test_user_excel_table_parsing(self):
        excel_path = "Файлы и ошибки/Заявка на обучения по ОТ от 17.08.2026 Гигант (1).xlsx"
        if not os.path.exists(excel_path):
            self.skipTest("Excel test file not found")
        res = psg_agent.process_application(input_file=excel_path)
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["unique_students"], 18)
        # Check first student is Akobyan Grant Ashotovich with valid birth_date and position
        found_akobyan = False
        for prog, data in res["grouped_data"].items():
            for s in data["students"]:
                if "Акобян" in s["fio_nom"]:
                    found_akobyan = True
                    self.assertEqual(s["fio_nom"], "Акобян Грант Ашотович")
                    self.assertEqual(s["birth_date"], "02.01.1969")
                    self.assertEqual(s["position"], "Монтажник")
        self.assertTrue(found_akobyan, "Акобян Грант Ашотович must be parsed correctly from Excel")

    def test_yarovoy_dative_declension_and_backward_dates(self):
        # 1. Linguistics: Yarovoy Pavel Aleksandrovich dative declension and typo rejoining
        res_with_cust = linguistics.process_person_fio("Яровой Павел Александрович", "Яровому Павлу Александрови Чу")
        self.assertEqual(res_with_cust["nom_fio"], "Яровой Павел Александрович")
        self.assertEqual(res_with_cust["dat_fio"], "Яровому Павлу Александровичу")
        self.assertFalse(res_with_cust["has_yellow_flag"], "Must NOT produce yellow flag for customer typo 'Александрови Чу'")
        self.assertIsNone(res_with_cust["dat_warning"])

        # Auto-declension without customer dative
        res_auto = linguistics.process_person_fio("Яровой Павел Александрович")
        self.assertEqual(res_auto["dat_fio"], "Яровому Павлу Александровичу")
        self.assertFalse(res_auto["has_yellow_flag"])

        # 2. Date distribution backwards leading up to target end date 11.09.2026
        import training_rules
        matched = program_matcher.match_programs("Охрана труда А, Охрана труда Б, Первая помощь, Применение СИЗ")
        self.assertEqual(len(matched), 4)
        seq = training_rules.assign_sequential_dates(matched, "11.09.2026")
        assigned_dates = [s[1] for s in seq]
        self.assertEqual(assigned_dates, [
            "08.09.2026 - 08.09.2026",
            "09.09.2026 - 09.09.2026",
            "10.09.2026 - 10.09.2026",
            "11.09.2026 - 11.09.2026"
        ])
        # Ensure final program concludes on 11.09.2026 and none overflow to 12.09, 13.09, 14.09
        self.assertTrue(all("2026" in d and "202" not in d.replace("2026", "") for d in assigned_dates))

        # Single worker profession leading up to 11.09.2026
        matched_worker = program_matcher.match_programs("Сварщик")
        seq_w = training_rules.assign_sequential_dates(matched_worker, "11.09.2026")
        self.assertEqual(seq_w[0][1], "21.08.2026 - 11.09.2026")

        # 3. End-to-end processing of application
        text_input = """1. Яровой Павел Александрович, Яровому Павлу Александрови Чу, 26.07.1982, Монтажник, 11.09.2026
Программы: Охрана труда А, Охрана труда Б, Первая помощь, Применение СИЗ"""
        out = psg_agent.process_application(raw_text=text_input)
        self.assertTrue(out["success"])
        self.assertEqual(out["unique_students"], 1)
        self.assertEqual(out["total_enrollments"], 4)
        
        stud_summary = out["students_summary"][0]
        self.assertEqual(stud_summary["fio"], "Яровой Павел Александрович")
        self.assertEqual(stud_summary["fio_dat"], "Яровому Павлу Александровичу")
        self.assertEqual(stud_summary["birth_date"], "26.07.1982")
        self.assertEqual(stud_summary["position"], "Монтажник")
        self.assertNotIn("dat_fio", stud_summary["flags"])
        self.assertNotIn("birth_date", stud_summary["flags"])

if __name__ == "__main__":
    unittest.main()
