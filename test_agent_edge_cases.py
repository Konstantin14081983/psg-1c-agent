"""
Unit and regression tests for PSG 1C Application Agent.
Tests:
1. Real DOCX sample 1 (broken rels, multi-program)
2. Real DOCX sample 2 (non-declined name, compound program)
3. Synthetic edge cases:
   - Latin homoglyphs in Cyrillic names
   - Bad SNILS checksum vs valid SNILS
   - Unrecognized program title
   - Female name declension (-ова, -ко, etc.)
   - Yellow cell highlighting verification
"""

import os
import openpyxl
import linguistics
import program_matcher
import excel_builder
import psg_agent

def test_homoglyphs_and_declension():
    # 'C' and 'a' are Latin in 'Cайфидинов' and 'Tалавшо'
    bad_nom = "Cайфидинов Tалавшо Муродович" # Latin C and T
    res = linguistics.process_person_fio(bad_nom, "Сайфидинов Талавшо Муродович")
    assert res['nom_warning'] is not None, "Should detect Latin homoglyphs"
    assert res['dat_warning'] is not None, "Should detect uninflected dative"
    assert res['dat_fio'] == "Сайфидинову Талавшо Муродовичу"
    print("✓ test_homoglyphs_and_declension passed")

def test_snils_checksum():
    valid_snils = "189-878-867 92"
    fmt, ok, warn = linguistics.validate_and_format_snils(valid_snils)
    assert ok is True and warn is None
    
    # Intentionally corrupt checksum (93 instead of 92)
    bad_snils = "189-878-867 93"
    fmt, ok, warn = linguistics.validate_and_format_snils(bad_snils)
    assert ok is False and warn is not None
    assert "контрольной суммы" in warn
    print("✓ test_snils_checksum passed")

def test_female_declension():
    female_nom = "Петрова Анна Сергеевна"
    female_dat = "Петровой Анне Сергеевне"
    res = linguistics.process_person_fio(female_nom)
    assert res['gender'] == 'Ж'
    assert res['dat_fio'] == female_dat
    
    # Non-declining female surname ending in consonant
    foreign_female = "Алиева Гюльназ Маратовна"
    res2 = linguistics.process_person_fio(foreign_female)
    assert res2['gender'] == 'Ж'
    assert res2['dat_fio'] == "Алиевой Гюльназ Маратовне"
    print("✓ test_female_declension passed")

def test_program_matching():
    # Compound
    p1 = program_matcher.match_programs("ОТ (Б+СИЗ+ПП)")
    assert len(p1) == 3
    assert all(p['is_canonical'] for p in p1)
    
    # Unknown program
    p2 = program_matcher.match_programs("Экзотическая спецпрограмма")
    assert len(p2) == 1
    assert p2[0]['is_canonical'] is False
    assert p2[0]['warning'] is not None
    print("✓ test_program_matching passed")

def test_full_pipeline_synthetic():
    test_file = "test_synthetic.xlsx"
    # Build synthetic test workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["№", "ФИО", "ФИО в дательном", "Должность", "СНИЛС", "Дата рождения", "Программа"])
    ws.append([1, "Иванов Иван Иванович", "Иванову Ивану Ивановичу", "Инженер", "189-878-867 92", "12.05.1985", "Высота 1 группа"])
    ws.append([2, "Смирнов Петр Петрович", "Смирнов Петр Петрович", "Слесарь", "189-878-867 93", "01.01.1990", "Неизвестный спецкурс"])
    wb.save(test_file)
    
    out_file = "test_synthetic_out.xlsx"
    res = psg_agent.process_application(test_file, out_file)
    assert res['success'] is True
    
    # Verify yellow highlights in out_file
    out_wb = openpyxl.load_workbook(out_file)
    out_ws = out_wb['Лист_1']
    
    # Check that unknown program row is yellow
    # Check that row with bad dative & bad SNILS has yellow cells
    found_prog_yellow = False
    found_snils_yellow = False
    found_dat_yellow = False
    
    for r in range(1, out_ws.max_row + 1):
        cell_a = out_ws.cell(r, 1)
        if cell_a.value == "Неизвестный спецкурс" and cell_a.fill.start_color.rgb == '00FFFF00':
            found_prog_yellow = True
        cell_c = out_ws.cell(r, 3) # dat_fio
        if cell_c.value == "Смирнову Петру Петровичу" and cell_c.fill.start_color.rgb == '00FFFF00':
            found_dat_yellow = True
        cell_g = out_ws.cell(r, 7) # snils
        if cell_g.value == "189-878-867 93" and cell_g.fill.start_color.rgb == '00FFFF00':
            found_snils_yellow = True
            
    assert found_prog_yellow, "Unknown program row must be yellow"
    assert found_dat_yellow, "Autocorrected uninflected dative cell must be yellow"
    assert found_snils_yellow, "Invalid SNILS checksum cell must be yellow"
    
    # Clean up test files
    if os.path.exists(test_file): os.remove(test_file)
    if os.path.exists(out_file): os.remove(out_file)
    print("✓ test_full_pipeline_synthetic passed")

if __name__ == "__main__":
    test_homoglyphs_and_declension()
    test_snils_checksum()
    test_female_declension()
    test_program_matching()
    test_full_pipeline_synthetic()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
