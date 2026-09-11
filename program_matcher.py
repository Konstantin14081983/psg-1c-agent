"""
Program matching and catalog engine for PSG 1C Application Agent.
Maps customer shorthand / abbreviations to canonical 1C educational programs.
Includes fire safety, ecology (112h), height/OZP, OHS, and worker professions.
"""

import re
from typing import List, Tuple, Dict, Any, Optional

CANONICAL_PROGRAMS = [
    # Worker professions
    "Профессиональная подготовка по профессии Машинист крана автомобильного 8 разряд",
    "Профессиональная подготовка по профессии Стропальщик",
    "Профессиональная подготовка по профессии Вышкомонтажник",
    "Профессиональная подготовка по профессии Вышкомонтажник-сварщик",
    "Профессиональная подготовка по профессии Электрогазосварщик",
    
    # OHS (ОТ)
    "Программа обучения безопасным методам и приемам выполнения работ при воздействии вредных и (или) опасных производственных факторов, источников опасности, идентифицированных в рамках специальной оценки условий труда и оценки профессиональных рисков",
    "Программа обучения безопасным методам и приемам выполнения работ повышенной опасности, к которым предъявляются дополнительные требования в соответствии с нормативными правовыми актами, содержащими государственные нормативные требования охраны труда",
    "Программа обучения по оказанию первой помощи пострадавшим на производстве",
    "Программа обучения по использованию (применению) средств индивидуальной защиты",
    "Программа обучения общим вопросам охраны труда и функционирования системы управления охраной труда",
    
    # Permits & Annual checks
    "Ежегодные занятия с водителями автотранспортных средств",
    'Обучение по программе "Нормы и правила работы в электроустановках"',
    
    # Height & OZP (24h)
    "Программа обучения безопасным методам и приемам выполнения работ на высоте, 1 группа",
    "Программа обучения безопасным методам и приемам выполнения работ на высоте, 2 группа",
    "Программа обучения безопасным методам и приемам выполнения работ на высоте, 3 группа",
    "Обучение безопасным методам и приемам выполнения работ в ограниченных и замкнутых пространствах (ОЗП)",
    "Программа обучения безопасным методам и приемам работ с ручным инструментом, в том числе с пиротехническим.",
    
    # Fire safety (ДПП / ПК)
    "ДПП Специалист по пожарной профилактике",
    "ПК Повышение квалификации для руководителей организаций, лиц, назначенных ответственными за обеспечение пожарной безопасности",
    
    # Ecology 112h (ПК)
    "ПК Обеспечение экологической безопасности при работах в области обращения с опасными отходами I-IV класс опасности",
    "ПК Обеспечение экологической безопасности руководителями и специалистами общехозяйственных систем управления",
    "ПК Обеспечение экологической безопасности руководителями и специалистами экологических служб и систем экологического контроля",
    
    # Combined OHS
    "Программа обучения безопасным методам и приемам выполнения работ при воздействии вредных и (или) опасных производственных факторов, источников опасности, идентифицированных в рамках специальной оценки условий труда и оценки профессиональных рисков, включающая оказание первой помощи пострадавшим и использование (применение) средств индивидуальной защиты."
]

PROG_B = CANONICAL_PROGRAMS[5]
PROG_V = CANONICAL_PROGRAMS[6]
PROG_FIRST_AID = CANONICAL_PROGRAMS[7]
PROG_PPE = CANONICAL_PROGRAMS[8]
PROG_A = CANONICAL_PROGRAMS[9]
PROG_DRIVERS = CANONICAL_PROGRAMS[10]
PROG_ELECTRO = CANONICAL_PROGRAMS[11]
PROG_HEIGHT_1 = CANONICAL_PROGRAMS[12]
PROG_HEIGHT_2 = CANONICAL_PROGRAMS[13]
PROG_HEIGHT_3 = CANONICAL_PROGRAMS[14]
PROG_OZP = CANONICAL_PROGRAMS[15]
PROG_TOOL = CANONICAL_PROGRAMS[16]

PROG_FIRE_SPEC = CANONICAL_PROGRAMS[17]
PROG_FIRE_MGR = CANONICAL_PROGRAMS[18]

PROG_ECO_WASTE = CANONICAL_PROGRAMS[19]
PROG_ECO_MGMT = CANONICAL_PROGRAMS[20]
PROG_ECO_SERVICE = CANONICAL_PROGRAMS[21]

def match_programs(raw_text: Any, position: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Parses customer's program string (or list) into one or more canonical programs.
    Supports MULTIPLE programs separated by ';' or '\n' or passed as a list.
    Supports 'квалификационное' rule by inferring worker profession from student's position.
    E.g. 'ОТ (Б+СИЗ+ПП); Высота 1 группа' -> matches all selected programs.
    """
    if not raw_text:
        # If no program specified, check if position indicates a worker profession under qualification
        if position:
            clean_pos = position.strip()
            clean_pos = re.sub(r'/[^/]+/', '', clean_pos).strip()
            clean_pos = re.sub(r'\(.*?\)', '', clean_pos).strip()
            if clean_pos and any(w in clean_pos.lower() for w in ['слесар', 'монтаж', 'свар', 'кран', 'стропаль', 'техник', 'водитель', 'электрик', 'бетонщик', 'токарь']):
                return match_single_program("квалификационное", position=position)
        return [{
            'name': 'Программа не указана',
            'is_canonical': False,
            'warning': 'В заявке заказчика не указано наименование программы обучения'
        }]
        
    if isinstance(raw_text, list):
        items = [str(x).strip() for x in raw_text if str(x).strip()]
    else:
        items = [p.strip() for p in re.split(r'[;\n]+', str(raw_text)) if p.strip()]
        
    if len(items) > 1:
        all_results = []
        for it in items:
            sub = match_single_program(it, position=position)
            for s in sub:
                if not any(existing['name'] == s['name'] for existing in all_results):
                    all_results.append(s)
        return all_results if all_results else match_single_program(items[0], position=position)
        
    return match_single_program(items[0] if items else "", position=position)

def match_single_program(raw_text: str, position: Optional[str] = None) -> List[Dict[str, Any]]:
    text = raw_text.strip()
    text_clean = re.sub(r'\s+', ' ', text)
    t_lower = text_clean.lower()

    # 0. Check 'квалификационное' / повышение квалификации rule -> worker profession from position
    is_qualif = any(q in t_lower for q in [
        'квалификационн', 'квалификаци', 'повышение квалификации', 
        'присвоение квалификации', 'проверка знаний', 'аттестаци'
    ])
    if is_qualif and position:
        clean_pos = position.strip()
        clean_pos = re.sub(r'/[^/]+/', '', clean_pos).strip()
        clean_pos = re.sub(r'\(.*?\)', '', clean_pos).strip()
        pos_low = clean_pos.lower()
        if clean_pos:
            if 'кран' in pos_low:
                return [{'name': CANONICAL_PROGRAMS[0], 'is_canonical': True, 'warning': None}]
            elif 'стропаль' in pos_low:
                return [{'name': CANONICAL_PROGRAMS[1], 'is_canonical': True, 'warning': None}]
            elif 'вышкомонтажник-сварщик' in pos_low:
                return [{'name': CANONICAL_PROGRAMS[3], 'is_canonical': True, 'warning': None}]
            elif 'вышкомонтажник' in pos_low:
                return [{'name': CANONICAL_PROGRAMS[2], 'is_canonical': True, 'warning': None}]
            elif 'сварщик' in pos_low or 'электрогазосварщик' in pos_low:
                return [{'name': CANONICAL_PROGRAMS[4], 'is_canonical': True, 'warning': None}]
            else:
                return [{
                    'name': f"Профессиональная подготовка по профессии {clean_pos}",
                    'is_canonical': True,
                    'warning': None
                }]

    # 1. Exact match with catalog
    for canon in CANONICAL_PROGRAMS:
        if canon.lower() == t_lower:
            return [{'name': canon, 'is_canonical': True, 'warning': None}]
            
    # 2. Fire safety abbreviations: Пожарка, ПТМ, ПБ инструктажи, пожарно-технический минимум
    if any(k in t_lower for k in ['пожарк', 'птм', 'пб инструктаж', 'пожарн', 'пожарн. безоп']):
        if 'специалист' in t_lower or 'профилактик' in t_lower:
            return [{
                'name': PROG_FIRE_SPEC,
                'is_canonical': True,
                'warning': f'Неточное наименование программы "{text_clean}" автоматически приведено к официальной: "{PROG_FIRE_SPEC}"'
            }]
        else:
            return [{
                'name': PROG_FIRE_MGR,
                'is_canonical': True,
                'warning': f'Сокращение пожарной безопасности "{text_clean}" приведено к официальной программе: "{PROG_FIRE_MGR}"'
            }]
            
    # 3. 112-hour Ecology programs
    if 'эколог' in t_lower:
        if 'отход' in t_lower or 'опасными отходами' in t_lower or 'i-iv' in t_lower:
            return [{'name': PROG_ECO_WASTE, 'is_canonical': True, 'warning': None}]
        elif 'служб' in t_lower or 'систем экологического контроля' in t_lower:
            return [{'name': PROG_ECO_SERVICE, 'is_canonical': True, 'warning': None}]
        else:
            return [{'name': PROG_ECO_MGMT, 'is_canonical': True, 'warning': None}]
            
    # 4. Check compound OHRANA TRUDA shorthand: e.g. "ОТ (Б+СИЗ+ПП)", "Б+СИЗ+ПП", "ОТ (А+Б+СИЗ+ПП)"
    has_a = bool(re.search(r'\bа\b|«а»|"а"|„а“|программ[аы]\s*а', t_lower))
    has_b = bool(re.search(r'\bб\b|«б»|"б"|„б“|программ[аы]\s*б', t_lower))
    has_siz = bool(re.search(r'сиз|средств[а-я\s]*индивидуальной', t_lower))
    has_pp = bool(re.search(r'\bпп\b|перв[а-я\s]*помо[щш]', t_lower))
    has_v = bool(re.search(r'\bв\b|«в»|"в"|„в“|повышенн[а-я\s]*опасн', t_lower))
    
    if ('от' in t_lower or 'охрана труда' in t_lower or has_b or has_siz or has_pp or has_a or has_v) and (has_b or has_siz or has_pp or has_a or has_v):
        results = []
        if has_a:
            results.append({'name': PROG_A, 'is_canonical': True, 'warning': None})
        if has_b:
            results.append({'name': PROG_B, 'is_canonical': True, 'warning': None})
        if has_v:
            results.append({'name': PROG_V, 'is_canonical': True, 'warning': None})
        if has_pp:
            results.append({'name': PROG_FIRST_AID, 'is_canonical': True, 'warning': None})
        if has_siz:
            results.append({'name': PROG_PPE, 'is_canonical': True, 'warning': None})
            
        if results:
            return results

    # 4b. Standalone First Aid / PPE checks (with OCR typo tolerance)
    if any(k in t_lower for k in ['перв', 'помощ', 'помош']) and ('пострадавш' in t_lower or 'производств' in t_lower or 'оказани' in t_lower):
        return [{'name': PROG_FIRST_AID, 'is_canonical': True, 'warning': None}]
    if 'сиз' in t_lower or 'индивидуальной защит' in t_lower or 'средств защиты' in t_lower:
        return [{'name': PROG_PPE, 'is_canonical': True, 'warning': None}]

    # 5. OZP (Ограниченные и замкнутые пространства)
    if 'озп' in t_lower or 'замкнут' in t_lower:
        return [{'name': PROG_OZP, 'is_canonical': True, 'warning': None}]

    # 6. Height safety (Высота)
    if 'высот' in t_lower:
        if '2' in t_lower or 'ii' in t_lower:
            return [{'name': PROG_HEIGHT_2, 'is_canonical': True, 'warning': None}]
        elif '3' in t_lower or 'iii' in t_lower:
            return [{'name': PROG_HEIGHT_3, 'is_canonical': True, 'warning': None}]
        else:
            return [{'name': PROG_HEIGHT_1, 'is_canonical': True, 'warning': None}]
            
    # 7. Electrical safety (Электробезопасность / Нормы и правила)
    if 'электро' in t_lower or 'электроустанов' in t_lower:
        return [{'name': PROG_ELECTRO, 'is_canonical': True, 'warning': None}]
        
    # 8. Drivers (Водители / БДД 20 часов)
    if 'водител' in t_lower or 'автотранспорт' in t_lower or 'бдд' in t_lower:
        return [{'name': PROG_DRIVERS, 'is_canonical': True, 'warning': None}]
        
    # 9. Crane operator (Машинист крана)
    if 'кран' in t_lower:
        return [{'name': CANONICAL_PROGRAMS[0], 'is_canonical': True, 'warning': None}]
        
    # 10. Slinger (Стропальщик)
    if 'стропальщик' in t_lower:
        return [{'name': CANONICAL_PROGRAMS[1], 'is_canonical': True, 'warning': None}]
        
    # 11. Welder (Сварщик)
    if 'сварщик' in t_lower or 'электрогазосварщик' in t_lower:
        return [{'name': CANONICAL_PROGRAMS[4], 'is_canonical': True, 'warning': None}]
        
    # 12. Hand / Pyrotechnic tools (Ручной инструмент)
    if 'инструмент' in t_lower or 'пиротехническ' in t_lower:
        return [{'name': PROG_TOOL, 'is_canonical': True, 'warning': None}]
        
    # 13. Fuzzy / Partial matching against full canonical names
    best_match = None
    max_overlap = 0
    words = [w for w in re.split(r'[\s,\(\)]+', t_lower) if len(w) > 3]
    for canon in CANONICAL_PROGRAMS:
        c_lower = canon.lower()
        overlap = sum(1 for w in words if w in c_lower)
        if overlap > max_overlap and overlap >= 3:
            max_overlap = overlap
            best_match = canon
            
    if best_match:
        return [{'name': best_match, 'is_canonical': True, 'warning': None}]
        
    # If not recognized, keep raw text but mark for yellow highlight
    return [{
        'name': text_clean,
        'is_canonical': False,
        'warning': f'Нестандартное наименование программы: "{text_clean}" (требует проверки менеджером)'
    }]
