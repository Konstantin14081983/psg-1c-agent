"""
PSG 1C Application Agent (Main Orchestrator).
Processes incoming client applications in DOCX, XLSX, PDF, images, or plain text,
enforces training rules, normalizes data, and generates 1C-compliant Excel files.
Supports multi-file batches and intelligent contact cleaning.
"""

import os
import sys
import argparse
import datetime
from typing import Dict, Any, List, Optional, Union
from collections import OrderedDict

import linguistics
import program_matcher
import training_rules
import doc_reader
import excel_builder

def process_application(
    input_file: Optional[Union[str, List[str]]] = None,
    raw_text: Optional[str] = None,
    output_file: Optional[str] = None,
    manual_overrides: Optional[Dict[str, Any]] = None,
    use_ai: bool = False,
    openai_api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Processes an incoming application file(s) or text and generates 1C Excel spreadsheet.
    Supports AI Vision (OpenAI GPT-4o-mini) or local Tesseract OCR.
    """
    manual_overrides = manual_overrides or {}
    engines_used = set()
    
    input_files_list = []
    if isinstance(input_file, list):
        input_files_list = input_file
    elif isinstance(input_file, str):
        input_files_list = [input_file]
        
    raw_students = []
    detected_title = None
    input_source_name = "Заявка"
    
    # 1. Parse raw inputs (both files and text can be provided together)
    names = []
    ai_errors = []
    if input_files_list:
        for fpath in input_files_list:
            if not os.path.exists(fpath):
                continue
            names.append(os.path.basename(fpath))
            parsed = doc_reader.parse_incoming_application(fpath, use_ai=use_ai, openai_api_key=openai_api_key)
            if parsed.get('engine'):
                engines_used.add(parsed['engine'])
            if parsed.get('ai_error'):
                ai_errors.append(f"{os.path.basename(fpath)}: {parsed['ai_error']}")
            if not detected_title and parsed.get('title'):
                detected_title = parsed.get('title')
            raw_students.extend(parsed.get('students', []))
        input_source_name = ", ".join(names) if names else "Файлы"

    if raw_text:
        # Check if raw_text contains student rows or supplementary manager instructions
        # If use_ai=True, attempt deep semantic extraction with OpenAI first
        text_parsed_by_ai = False
        if use_ai:
            try:
                import ai_vision
                ai_text_res = ai_vision.analyze_text_message_with_ai(raw_text, api_key=openai_api_key)
                if ai_text_res.get("success") and ai_text_res.get("students"):
                    text_parsed_by_ai = True
                    engines_used.add(ai_text_res.get("engine", "OpenAI (GPT-4o-mini)"))
                    ai_studs = []
                    for s in ai_text_res["students"]:
                        ai_studs.append({
                            "fio_nom": s.get("fio", ""),
                            "position": s.get("position", ""),
                            "birth_date": s.get("birth_date", ""),
                            "gender": s.get("gender", ""),
                            "snils": s.get("snils", ""),
                            "study_dates": s.get("study_dates", ""),
                            "contacts": s.get("contacts", ""),
                            "program": s.get("program", "")
                        })
                    if raw_students:
                        raw_students = doc_reader.reconcile_student_records(raw_students, ai_studs)
                    else:
                        raw_students.extend(ai_studs)
                    c_params = ai_text_res.get("common_params", {})
                    if c_params.get("position") and not manual_overrides.get("position"):
                        manual_overrides["position"] = c_params["position"]
                    if c_params.get("program") and not manual_overrides.get("program"):
                        manual_overrides["program"] = c_params["program"]
                    if c_params.get("study_dates") and not manual_overrides.get("study_dates"):
                        manual_overrides["study_dates"] = c_params["study_dates"]
                else:
                    if ai_text_res.get("error"):
                        ai_errors.append(f"Текстовое сообщение: {ai_text_res['error']}")
            except Exception as e:
                ai_errors.append(f"Текстовое сообщение: {str(e)}")

        if not text_parsed_by_ai:
            parsed_raw = doc_reader.parse_raw_text_application(raw_text)
            text_students = parsed_raw.get('students', [])
            if text_students:
                if not detected_title and parsed_raw.get('title'):
                    detected_title = parsed_raw.get('title')
                if raw_students:
                    raw_students = doc_reader.reconcile_student_records(raw_students, text_students)
                else:
                    raw_students.extend(text_students)
            if not input_files_list:
                input_source_name = "Текстовое сообщение"
                
        # Also check for supplementary manager instructions (position, program, dates)
        supp = doc_reader.extract_supplementary_instructions(raw_text)
        if supp.get('position') and not manual_overrides.get('position'):
            manual_overrides['position'] = supp['position']
        if supp.get('program') and not manual_overrides.get('program'):
            manual_overrides['program'] = supp['program']
        if supp.get('study_dates') and not manual_overrides.get('study_dates'):
            manual_overrides['study_dates'] = supp['study_dates']

    if not input_files_list and not raw_text:
        raise ValueError("Необходимо указать input_file или raw_text")
        
    app_title = manual_overrides.get('application_title') or detected_title
    
    # If still no students, create a fallback student from file/input context
    if not raw_students and (input_files_list or raw_text):
        fallback_fio = "Слушатель (данные из входящего документа)"
        fallback_pos = manual_overrides.get('position') or "Слушатель"
        raw_students.append({
            "fio_nom": fallback_fio,
            "fio_dat": "",
            "position": fallback_pos,
            "gender": "",
            "birth_date": "",
            "snils": "",
            "study_dates": manual_overrides.get('study_dates') or "",
            "contacts": "",
            "program": manual_overrides.get('program') or ""
        })
        
    base_name = os.path.splitext(input_source_name.split(',')[0])[0].strip()
    if not output_file:
        output_dir = os.path.dirname(input_files_list[0]) if input_files_list else "."
        today_clean = datetime.date.today().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(output_dir or ".", f"Заявка_1С_{base_name}_{today_clean}.xlsx")
        
    grouped_programs: Dict[str, Dict[str, Any]] = OrderedDict()
    all_warnings = []
    rule_violations = []
    document_issues = []
    student_audit_cards = []
    
    if app_title:
        clean_title, title_warnings = linguistics.clean_application_title(app_title)
        app_title = clean_title
        for tw in title_warnings:
            all_warnings.append({
                'type': 'Заголовок заявки',
                'student': 'Шапка документа',
                'field': 'application_title',
                'reason': tw,
                'message': tw
            })
            
    student_enrollment_tracker: Dict[str, List[Dict[str, Any]]] = {}
    
    # 2. Process each student
    for s_idx, raw_s in enumerate(raw_students, start=1):
        fio_nom_raw = raw_s.get('raw_fio') or raw_s.get('fio_nom', '')
        fio_dat_raw = raw_s.get('fio_dat', '')
        gender_raw = raw_s.get('gender', '')
        birth_raw = raw_s.get('birth_date', '')
        snils_raw = raw_s.get('snils', '')
        pos_raw = raw_s.get('position') or manual_overrides.get('position') or ''
        prog_raw = raw_s.get('program') or manual_overrides.get('programs') or manual_overrides.get('program') or ''
        dates_raw = raw_s.get('study_dates') or manual_overrides.get('study_dates') or ''
        contacts_raw = raw_s.get('contacts', '')
        
        # Linguistic & FIO processing (with anomaly and patronymic typo check)
        fio_res = linguistics.process_person_fio(fio_nom_raw, fio_dat_raw, gender_raw)
        if raw_s.get('fio_corrections'):
            for c in raw_s['fio_corrections']:
                if c not in fio_res.get('corrections', []):
                    fio_res.setdefault('corrections', []).append(c)
            if 'nom_fio' not in fio_res.setdefault('yellow_columns', []):
                fio_res['yellow_columns'].append('nom_fio')
            fio_res['has_yellow_flag'] = True
            fio_res['nom_warning'] = "; ".join(fio_res['corrections'])
        
        # SNILS validation
        snils_formatted, snils_valid, snils_warn = linguistics.validate_and_format_snils(snils_raw)
        
        # Date validation
        birth_formatted, birth_valid, birth_warn = linguistics.normalize_date(birth_raw) if birth_raw else ("", True, None)
        
        # Position normalization & typo corrections
        pos_clean, pos_warn, pos_had_issues = training_rules.normalize_position(pos_raw)
        pos_clean, pos_homo = linguistics.clean_homoglyphs(pos_clean)
        
        # Contacts cleaning & validation:
        # Garbage like 'uuuuu' or '111111' is cleaned to "" without yellow highlight!
        contacts_clean, contacts_yellow, contacts_warn = linguistics.clean_and_validate_contacts(contacts_raw)
        
        # Yellow flags compiler
        yellow_flags = {}
        for col in fio_res.get('yellow_columns', []):
            if col == 'nom_fio':
                yellow_flags['nom_fio'] = fio_res.get('nom_warning') or "Подозрительные символы или опечатка в ФИО"
            elif col == 'dat_fio':
                yellow_flags['dat_fio'] = fio_res.get('dat_warning') or fio_res.get('patronymic_warning') or "Проверьте окончание дательного падежа"
                
        if not snils_valid:
            yellow_flags['snils'] = snils_warn or "Некорректный номер СНИЛС"
            
        if not birth_valid and birth_raw:
            yellow_flags['birth_date'] = birth_warn or "Некорректный формат даты рождения"
        elif not birth_raw:
            yellow_flags['birth_date'] = "Дата рождения не указана"
            
        if pos_had_issues:
            yellow_flags['position'] = pos_warn or "Проверьте написание должности"
            
        if contacts_yellow:
            yellow_flags['contacts'] = contacts_warn or "Некорректный формат контактов"
            
        # Program matching & expansion
        matched_progs = program_matcher.match_programs(prog_raw, position=pos_clean)
        progs_with_dates = training_rules.assign_sequential_dates(matched_progs, dates_raw)
        
        student_key = fio_res['nom_fio']
        if student_key not in student_enrollment_tracker:
            student_enrollment_tracker[student_key] = []
            
        for prog, p_dates, was_split in progs_with_dates:
            p_name = prog['name']
            prog_yellow_flags = dict(yellow_flags)
            
            # Category and date auditing
            date_audit = training_rules.validate_dates_and_category(p_name, p_dates)
            if date_audit['has_error']:
                for dw in date_audit['warnings']:
                    rule_violations.append({
                        'student': fio_res['nom_fio'],
                        'program': p_name,
                        'message': dw
                    })
                    prog_yellow_flags['study_dates'] = dw
            elif was_split:
                all_warnings.append({
                    'type': 'Сроки обучения',
                    'student': fio_res['nom_fio'],
                    'field': 'study_dates',
                    'reason': f"Сроки для '{p_name[:35]}...' автоматически распределены последовательно: {p_dates}"
                })
                    
            # Document package checklist
            doc_flags = manual_overrides.get('documents') or {}
            doc_warns = training_rules.validate_document_package(
                date_audit['category'],
                {
                    'fio_nom': fio_res['nom_fio'],
                    'birth_date': birth_formatted,
                    'snils': snils_formatted,
                    'position': pos_clean,
                    'program': p_name
                },
                doc_flags
            )
            for dw in doc_warns:
                document_issues.append({
                    'student': fio_res['nom_fio'],
                    'category': date_audit['category'],
                    'message': dw
                })
                
            student_record = {
                'fio_nom': fio_res['nom_fio'],
                'fio_dat': fio_res['dat_fio'],
                'position': pos_clean,
                'gender': fio_res['gender'],
                'birth_date': birth_formatted,
                'snils': snils_formatted,
                'study_dates': linguistics.clean_text(p_dates),
                'contacts': contacts_clean,
                'yellow_flags': prog_yellow_flags
            }
            
            student_enrollment_tracker[student_key].append({
                'program': p_name,
                'category': date_audit['category'],
                'start_date': date_audit['start_date'],
                'end_date': date_audit['end_date']
            })
            
            if p_name not in grouped_programs:
                grouped_programs[p_name] = {
                    'is_canonical': prog['is_canonical'],
                    'warning': prog['warning'],
                    'category': date_audit['category'],
                    'students': []
                }
                if prog['warning']:
                    all_warnings.append({
                        'program': p_name,
                        'reason': prog['warning']
                    })
                    
            grouped_programs[p_name]['students'].append(student_record)
            
        for col_name, reason in yellow_flags.items():
            all_warnings.append({
                'student': fio_res['nom_fio'],
                'field': col_name,
                'reason': reason
            })
            
        student_audit_cards.append({
            'fio': fio_res['nom_fio'],
            'fio_dat': fio_res['dat_fio'],
            'gender': fio_res['gender'],
            'snils': snils_formatted,
            'birth_date': birth_formatted,
            'position': pos_clean,
            'contacts': contacts_clean,
            'flags_count': len(yellow_flags),
            'flags': yellow_flags
        })
        
    # Multi-program overlap check
    for s_name, enrollments in student_enrollment_tracker.items():
        overlap_issues = training_rules.audit_student_program_overlaps(enrollments)
        for issue in overlap_issues:
            rule_violations.append({
                'student': s_name,
                'program': "Совмещение программ",
                'message': issue['message']
            })
            
    # Record any AI errors to audit warnings
    if ai_errors:
        for a_err in ai_errors:
            all_warnings.append({
                'type': 'Статус ИИ (Vision)',
                'student': 'Оптическое распознавание ИИ',
                'field': 'use_ai',
                'reason': f"⚠️ {a_err}. Выполнен автоматический откат на локальные алгоритмы / Tesseract OCR."
            })

    # Build Excel spreadsheet with turquoise fills and no comments
    wb = excel_builder.create_1c_application_workbook(app_title, grouped_programs)
    wb.save(output_file)
    
    total_enrollments = sum(len(p['students']) for p in grouped_programs.values())
    ocr_engine_label = "OpenAI Vision (GPT-4o-mini)" if any("OpenAI" in str(e) for e in engines_used) else "Локальный Tesseract OCR"
    
    return {
        "success": True,
        "input_source": input_source_name,
        "output_file": output_file,
        "output_filename": os.path.basename(output_file),
        "application_title": app_title,
        "ocr_engine": ocr_engine_label,
        "unique_students": len(raw_students),
        "total_enrollments": total_enrollments,
        "programs_count": len(grouped_programs),
        "programs": list(grouped_programs.keys()),
        "grouped_data": grouped_programs,
        "students_summary": student_audit_cards,
        "audit": {
            "warnings_count": len(all_warnings),
            "warnings": all_warnings,
            "rule_violations": rule_violations,
            "document_issues": document_issues,
            "ai_errors": ai_errors
        }
    }

def print_report(result: Dict[str, Any]):
    print("=" * 70)
    print("      ОТЧЕТ АГЕНТА: ОБРАБОТКА ЗАЯВКИ ДЛЯ 1С")
    print("=" * 70)
    if not result.get("success"):
        print(f"❌ Ошибка обработки: {result.get('error')}")
        return
        
    print(f"📁 Источник:          {result['input_source']}")
    print(f"💾 Создан файл 1С:    {result['output_file']}")
    print(f"📋 Заголовок заявки:  {result['application_title'] or 'Сформирован по умолчанию'}")
    print(f"👥 Слушателей всего:  {result['unique_students']}")
    print(f"🎓 Программ обучения: {result['programs_count']}")
    print(f"📊 Записей в 1С:      {result['total_enrollments']}")
    print("-" * 70)
    print("Программы обучения в заявке:")
    for idx, p in enumerate(result['programs'], 1):
        print(f"  {idx}. {p}")
        
    audit = result.get('audit', {})
    rule_violations = audit.get('rule_violations', [])
    doc_issues = audit.get('document_issues', [])
    warnings = audit.get('warnings', [])
    
    if rule_violations:
        print("\n🚫 НАРУШЕНИЯ РЕГЛАМЕНТА ОБУЧЕНИЯ (ДАТЫ / ПОСЛЕДОВАТЕЛЬНОСТЬ):")
        for rv in rule_violations:
            print(f"  • [{rv.get('student')}] {rv.get('message')}")
            
    if doc_issues:
        print("\n📄 ЗАМЕЧАНИЯ ПО ПАКЕТУ ДОКУМЕНТОВ:")
        for di in doc_issues:
            print(f"  • [{di.get('student')}] ({di.get('category')}): {di.get('message')}")
            
    if warnings:
        print(f"\n⚠️  СПОРНЫЕ МОМЕНТЫ (подсвечены ЖЕЛТЫМ в файле 1С): {len(warnings)}")
        for i, w in enumerate(warnings, 1):
            msg = w.get('reason') or w.get('message', '')
            if 'student' in w:
                print(f"  [{i}] {w['student']} | Поле: {w.get('field', '-')} -> {msg}")
            elif 'program' in w:
                print(f"  [{i}] Программа: {w['program']} -> {msg}")
            else:
                print(f"  [{i}] {msg}")
    else:
        print("\n✅ Все данные выверены. Спорных моментов и орфографических ошибок не обнаружено.")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Агент обработки заявок на обучение для 1С (ПСГ)")
    parser.add_argument("--input", "-i", nargs="+", help="Путь к входящей заявке (docx, xlsx, pdf, jpeg, png, heic)")
    parser.add_argument("--text", "-t", help="Сырой текст сообщения заявки")
    parser.add_argument("--output", "-o", help="Путь к результирующему файлу Excel для 1С")
    args = parser.parse_args()
    
    if not args.input and not args.text:
        print("Укажите --input <файл...> или --text '<текст заявки>'", file=sys.stderr)
        sys.exit(1)
        
    try:
        res = process_application(input_file=args.input, raw_text=args.text, output_file=args.output)
        print_report(res)
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
