"""
Program matching and catalog engine for PSG 1C Application Agent.
Maps customer shorthand / abbreviations to canonical 1C educational programs.
Includes fire safety, ecology (112h), height/OZP, OHS, and worker professions.
"""

import re
from typing import List, Tuple, Dict, Any, Optional

# ---------------------------------------------------------------------------
# Semantic core: aliases / abbreviations → canonical program index
# Each key is a lowercase alias; value is the index in CANONICAL_PROGRAMS.
# Used by match_single_program() BEFORE fuzzy matching.
# ---------------------------------------------------------------------------
PROGRAM_ALIASES: Dict[str, int] = {}

def _register_aliases(idx: int, aliases: List[str]):
    for a in aliases:
        PROGRAM_ALIASES[a.lower().strip()] = idx

CANONICAL_PROGRAMS = [
    # Worker professions
    "Профессиональная подготовка по профессии Машинист крана автомобильного 7 разряд",
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

# Register aliases for all canonical programs
_register_aliases(0, ["машинист крана", "машинист крана автомобильного", "машинист автокрана", "автокран", "кран автомобильный", "кран"])
_register_aliases(1, ["стропальщик", "стропаль", "стропальные работы"])
_register_aliases(2, ["вышкомонтажник"])
_register_aliases(3, ["вышкомонтажник-сварщик"])
_register_aliases(4, ["сварщик", "электрогазосварщик", "газоэлектросварщик", "э/г"])

_register_aliases(5, ["б", "от б", "от (б)", "бм", "программа б", "безопасные методы", "безопасным методам", "безопасным методам и приемам", "вредные производственные факторы", "вредные факторы", "соут", "б."])
_register_aliases(6, ["в", "от в", "от (в)", "программа в", "повышенная опасность", "повышенной опасности", "работы повышенной опасности", "дополнительные требования", "допопасность", "в."])
_register_aliases(7, ["пп", "первая помощь", "первой помощи", "оказание первой помощи", "оказание первой помощи пострадавшим", "первая медицинская", "оказанию первой помощи", "оказание первой помощи пострадавшим на производстве"])
_register_aliases(8, ["сиз", "применение сиз", "использование сиз", "средств индивидуальной защиты", "средства индивидуальной защиты", "средства защиты"])
_register_aliases(9, ["а", "от а", "от (а)", "программа а", "охрана труда а", "общие вопросы охраны труда", "общим вопросам охраны труда", "суот", "система управления от", "общие вопросы", "а."])

_register_aliases(10, ["водители", "бдд", "ежегодные занятия с водителями", "безопасность дорожного движения", "занятия с водителями", "бдд 20 часов", "бдд 20ч"])
_register_aliases(11, ["электробезопасность", "электро", "электробез", "электроустановки", "нормы и правила в электроустановках", "нормы и правила работы в электроустановках", "эб", "допуск по электробезопасности"])

_register_aliases(12, ["высота", "высота 1", "высота 1 группа", "1 группа высоты", "высота 1 гр", "высота 1гр", "работы на высоте", "работы на высоте 1 группа", "работы на высоте 1 гр", "высотные работы", "верхолазные работы", "верхолаз", "высота i группа", "высота 1-я группа"])
_register_aliases(13, ["высота 2", "высота 2 группа", "2 группа высоты", "высота 2 гр", "высота 2гр", "работы на высоте 2 группа", "работы на высоте 2 гр", "высота ii группа", "работы на высоте 2", "высота 2-я группа"])
_register_aliases(14, ["высота 3", "высота 3 группа", "3 группа высоты", "высота 3 гр", "высота 3гр", "работы на высоте 3 группа", "работы на высоте 3 гр", "высота iii группа", "работы на высоте 3", "высота 3-я группа"])
_register_aliases(15, ["озп", "замкнутые пространства", "ограниченные пространства", "ограниченные и замкнутые пространства", "работы в озп"])
_register_aliases(16, ["ручной инструмент", "пиротехнический инструмент", "инструмент", "инструменты"])

_register_aliases(17, ["специалист по пожарной профилактике", "пожарная профилактика", "дпп пожарная", "дпп специалист по пожарной профилактике"])
_register_aliases(18, ["птм", "пожарка", "пожарная безопасность", "пб", "пожарно-технический минимум", "повышение квалификации пожарная", "ответственный за пожарную безопасность"])

_register_aliases(19, ["экология отходы", "опасные отходы", "обращение с опасными отходами", "обращение с отходами i-iv", "отходы 1-4"])
_register_aliases(20, ["экология", "экологическая безопасность", "экология руководители", "экология 112 часов", "экология 112ч", "экология 112"])
_register_aliases(21, ["экологические службы", "экологический контроль"])

def split_compound_program_text(raw_text: Any) -> List[str]:
    """
    Splits complex or multi-program string into separate program tokens.
    Handles:
    - Semicolons and newlines: 'ОТ; Высота'
    - Numbered lists: '1. Охрана труда ... 2. Работы на высоте ...'
    - Composite phrases: 'Квалификационное Высота' -> ['Квалификационное', 'Высота']
    """
    if not raw_text:
        return []
    if isinstance(raw_text, list):
        raw_list = [str(x).strip() for x in raw_text if str(x).strip()]
    else:
        raw_list = [str(raw_text).strip()]

    result = []
    for item in raw_list:
        chunks = [c.strip() for c in re.split(r'[;\n]+', item) if c.strip()]
        for chunk in chunks:
            clean_chunk = re.sub(r'^\s*\d+[\.\)]\s*', '', chunk)
            sub_parts = re.split(r'\s+(?=\d+[\.\)]\s+)', clean_chunk)
            for sp in sub_parts:
                sp_clean = re.sub(r'^\s*\d+[\.\)]\s*', '', sp).strip(' ,.')
                split_composite = re.split(r'(?<=[,\s\.])(?=(?:[Рр]аботы\s+на\s+высоте|[Вв]ысота\b))', sp_clean)
                for sc in split_composite:
                    sc_clean = sc.strip(' ,.')
                    if sc_clean:
                        result.append(sc_clean)
    return result

def match_programs(raw_text: Any, position: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Parses customer's program string (or list) into one or more canonical programs.
    Supports MULTIPLE programs separated by ';', '\n', numbers, or composite phrases.
    Supports 'квалификационное' rule by inferring worker profession from student's position.
    E.g. 'ОТ (Б+СИЗ+ПП); Высота 1 группа' -> matches all selected programs.
    """
    if not raw_text:
        if position:
            clean_pos = position.strip()
            clean_pos = re.sub(r'/[^/]+/', '', clean_pos).strip()
            clean_pos = re.sub(r'\(.*?\)', '', clean_pos).strip()
            if clean_pos and any(w in clean_pos.lower() for w in ['слесар', 'монтаж', 'свар', 'кран', 'стропаль', 'техник', 'водитель', 'электрик', 'бетонщик', 'токарь', 'плотник']):
                return match_single_program("квалификационное", position=position)
        return [{
            'name': 'Программа не указана',
            'is_canonical': False,
            'warning': 'В заявке заказчика не указано наименование программы обучения'
        }]

    items = split_compound_program_text(raw_text)
    if not items:
        return [{
            'name': 'Программа не указана',
            'is_canonical': False,
            'warning': 'В заявке заказчика не указано наименование программы обучения'
        }]

    all_results = []
    for it in items:
        sub = match_single_program(it, position=position)
        for s in sub:
            if not any(existing['name'] == s['name'] for existing in all_results):
                all_results.append(s)

    return all_results if all_results else match_single_program(items[0], position=position)

def match_single_program(raw_text: str, position: Optional[str] = None) -> List[Dict[str, Any]]:
    text = raw_text.strip()
    text_clean = re.sub(r'\s+', ' ', text)
    t_lower = text_clean.lower()

    # 0. Fast alias lookup in semantic core dictionary
    t_key = re.sub(r'^\s*(?:программ[аы]?\s*[:\-]?\s*|направлени[ея]?\s*[:\-]?\s*|курс[ы]?\s*[:\-]?\s*)', '', t_lower).strip(' .,;:')
    if t_key in PROGRAM_ALIASES:
        canon_idx = PROGRAM_ALIASES[t_key]
        return [{'name': CANONICAL_PROGRAMS[canon_idx], 'is_canonical': True, 'warning': None}]

    # 1. Check 'квалификационное' / повышение квалификации rule -> worker profession from position
    is_qualif = any(q in t_lower for q in [
        'квалификационн', 'квалификаци', 'повышение квалификации', 
        'присвоение квалификации', 'проверка знаний', 'аттестаци'
    ])
    if is_qualif and position:
        clean_pos = position.strip()
        clean_pos = re.sub(r'/[^/]+/', '', clean_pos).strip()
        clean_pos = re.sub(r'\(.*?\)', '', clean_pos).strip()
        if clean_pos:
            clean_pos = clean_pos[0].upper() + clean_pos[1:]
        pos_low = clean_pos.lower()
        if clean_pos:
            if 'манипулятор' in pos_low:
                return [{'name': 'Профессиональная подготовка по профессии Машинист крана-манипулятора', 'is_canonical': True, 'warning': None}]
            elif 'кран' in pos_low and 'башенн' not in pos_low and 'мостов' not in pos_low:
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

    # 2. Exact match with catalog
    for canon in CANONICAL_PROGRAMS:
        if canon.lower() == t_lower:
            return [{'name': canon, 'is_canonical': True, 'warning': None}]

    # 3. Fire safety abbreviations: Пожарка, ПТМ, ПБ инструктажи, пожарно-технический минимум
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

    # 4. 112-hour Ecology programs
    if 'эколог' in t_lower:
        if 'отход' in t_lower or 'опасными отходами' in t_lower or 'i-iv' in t_lower:
            return [{'name': PROG_ECO_WASTE, 'is_canonical': True, 'warning': None}]
        elif 'служб' in t_lower or 'систем экологического контроля' in t_lower:
            return [{'name': PROG_ECO_SERVICE, 'is_canonical': True, 'warning': None}]
        else:
            return [{'name': PROG_ECO_MGMT, 'is_canonical': True, 'warning': None}]

    # 5. Check compound OHRANA TRUDA shorthand: e.g. "ОТ (Б+СИЗ+ПП)", "Б+СИЗ+ПП", "ОТ (А+Б+СИЗ+ПП)", "Б, В (номера)"
    has_a = bool(re.search(r'\(а\)|«а»|"а"|„а“|\bпрограмм[а-я]*\s*[«"„(]?а[»"“)]?|\b(?:от|охрана\s*труда)\s*[«"„(]?а[»"“)]?\b|общим вопросам|функционирования системы управления|(?<=[,\s\+])а(?=[,\s\+\)\(]|$)', t_lower))
    has_b = bool(re.search(r'\(б\)|«б»|"б"|„б“|\bпрограмм[а-я]*\s*[«"„(]?б[»"“)]?|\b(?:от|охрана\s*труда)\s*[«"„(]?б[»"“)]?\b|вредных|опасных производственных факторов|(?<=[,\s\+])б(?=[,\s\+\)\(]|$)', t_lower))
    has_v = bool(re.search(r'\(в\)|«в»|"в"|„в“|\bпрограмм[а-я]*\s*[«"„(]?в[»"“)]?|\b(?:от|охрана\s*труда)\s*[«"„(]?в[»"“)]?\b|повышенн[а-я\s]*опасн|(?<=[,\s\+])в(?=[,\s\+\)\(]|$)', t_lower))
    has_siz = bool(re.search(r'сиз|средств[а-я\s]*индивидуальной', t_lower))
    has_pp = bool(re.search(r'\bпп\b|перв[а-я\s]*помо[щш]', t_lower))

    ot_results = []
    if ('от' in t_lower or 'охрана труда' in t_lower or has_b or has_siz or has_pp or has_a or has_v) and (has_b or has_siz or has_pp or has_a or has_v):
        if has_a:
            ot_results.append({'name': PROG_A, 'is_canonical': True, 'warning': None})
        if has_b:
            ot_results.append({'name': PROG_B, 'is_canonical': True, 'warning': None})
        if has_v:
            ot_results.append({'name': PROG_V, 'is_canonical': True, 'warning': None})
        if has_pp:
            ot_results.append({'name': PROG_FIRST_AID, 'is_canonical': True, 'warning': None})
        if has_siz:
            ot_results.append({'name': PROG_PPE, 'is_canonical': True, 'warning': None})

    # Also check if Height / OZP / Tools are embedded in the same phrase
    extra_results = []
    if 'высот' in t_lower:
        if '2' in t_lower or 'ii' in t_lower:
            extra_results.append({'name': PROG_HEIGHT_2, 'is_canonical': True, 'warning': None})
        elif '3' in t_lower or 'iii' in t_lower:
            extra_results.append({'name': PROG_HEIGHT_3, 'is_canonical': True, 'warning': None})
        else:
            extra_results.append({'name': PROG_HEIGHT_1, 'is_canonical': True, 'warning': None})

    if 'озп' in t_lower or 'замкнут' in t_lower:
        extra_results.append({'name': PROG_OZP, 'is_canonical': True, 'warning': None})

    if 'электробезопасн' in t_lower or 'электроустанов' in t_lower or ('электро' in t_lower and not any(prof in t_lower for prof in ['монтер', 'монтёр', 'сварщик', 'слесарь', 'механик', 'привод'])):
        extra_results.append({'name': PROG_ELECTRO, 'is_canonical': True, 'warning': None})

    combined = ot_results + extra_results
    if combined:
        return combined

    # 6. Standalone First Aid / PPE checks
    if any(k in t_lower for k in ['перв', 'помощ', 'помош']) and ('пострадавш' in t_lower or 'производств' in t_lower or 'оказани' in t_lower):
        return [{'name': PROG_FIRST_AID, 'is_canonical': True, 'warning': None}]
    if 'сиз' in t_lower or 'индивидуальной защит' in t_lower or 'средств защиты' in t_lower:
        return [{'name': PROG_PPE, 'is_canonical': True, 'warning': None}]

    # 7. Drivers (Водители / БДД 20 часов)
    if 'водител' in t_lower or 'автотранспорт' in t_lower or 'бдд' in t_lower:
        return [{'name': PROG_DRIVERS, 'is_canonical': True, 'warning': None}]

    # 8. Crane operator (Машинист крана)
    if 'кран' in t_lower:
        if 'манипулятор' in t_lower:
            return [{'name': 'Профессиональная подготовка по профессии Машинист крана-манипулятора', 'is_canonical': True, 'warning': None}]
        return [{'name': CANONICAL_PROGRAMS[0], 'is_canonical': True, 'warning': None}]

    # 9. Slinger (Стропальщик)
    if 'стропальщик' in t_lower or 'стропаль' in t_lower:
        return [{'name': CANONICAL_PROGRAMS[1], 'is_canonical': True, 'warning': None}]

    # 10. Welder (Сварщик)
    if 'сварщик' in t_lower or 'электрогазосварщик' in t_lower:
        return [{'name': CANONICAL_PROGRAMS[4], 'is_canonical': True, 'warning': None}]

    # 11. Hand / Pyrotechnic tools (Ручной инструмент)
    if 'инструмент' in t_lower or 'пиротехническ' in t_lower:
        return [{'name': PROG_TOOL, 'is_canonical': True, 'warning': None}]

    # 12. Fuzzy / Partial matching against full canonical names
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

    return [{
        'name': text_clean,
        'is_canonical': False,
        'warning': f'Нестандартное наименование программы: "{text_clean}" (требует проверки менеджером)'
    }]
