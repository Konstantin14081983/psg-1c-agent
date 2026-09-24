"""Shared scanned-application baseline. Vision verifies; it cannot overwrite it."""
import copy
import re
import tempfile
import subprocess
from pathlib import Path

FIELDS = ('fio_nom', 'fio_dat', 'snils', 'birth_date', 'position', 'program', 'study_dates')


def canonical(value, field):
    text = str(value or '')
    if field == 'snils':
        return re.sub(r'\D', '', text)
    return ' '.join(text.casefold().split())


def compare_vision(baseline, response):
    """Keep every baseline row, including duplicates. Unmatched AI rows remain review candidates."""
    result = copy.deepcopy(baseline)
    result['recognition_issues'] = []
    result['ai_candidates'] = []
    if not response.get('success'):
        result['ai_error'] = response.get('error') or 'ИИ не вернул результат проверки'
        return result
    candidates = []
    for student in response.get('students', []):
        row = dict(student)
        row['fio_nom'] = row.get('fio_nom') or row.get('fio') or ''
        row['program'] = row.get('program') or '; '.join(row.get('programs') or [])
        candidates.append(row)
    used = set()
    for number, row in enumerate(result.get('students', []), 1):
        # Exact full name or exact identifier only; never fuzzy identity matching.
        matches = [i for i, candidate in enumerate(candidates) if i not in used and any(
            canonical(row.get(field), field) and canonical(row.get(field), field) == canonical(candidate.get(field), field)
            for field in ('fio_nom', 'snils'))]
        if len(matches) != 1:
            result['recognition_issues'].append({'row': number, 'fields': [], 'reason': 'ИИ не подтвердил строку однозначно. Исходная строка сохранена.'})
            continue
        index = matches[0]
        used.add(index)
        changed = [field for field in FIELDS if canonical(row.get(field), field) != canonical(candidates[index].get(field), field)]
        if changed:
            result['recognition_issues'].append({'row': number, 'fields': changed, 'reason': 'Расхождение с ИИ: ' + ', '.join(changed) + '. Данные локального распознавания сохранены; сверьте с оригиналом.'})
    for index, row in enumerate(candidates):
        if index not in used:
            result['ai_candidates'].append(row)
    if result['ai_candidates']:
        result['recognition_issues'].append({'row': None, 'fields': [], 'reason': f'Неподтверждённых строк ИИ: {len(result["ai_candidates"])}. Они сохранены в отчёте для ручной сверки и не включены автоматически в заявку.'})
    result['engine'] = baseline.get('engine', 'Локальный OCR') + ' + сверка Vision'
    return result


def orientation_score(text):
    from doc_reader import is_patronymic
    words = re.findall(r'[А-Яа-яЁё]{3,}', text)
    return (sum(is_patronymic(w) for w in words) * 30
            + len(re.findall(r'\b\d{2}\.\d{2}\.\d{4}\b', text)) * 10
            + sum(word.lower() in ('оказание', 'помощи', 'обучение', 'пострадавшим', 'снилс') for word in words) * 10
            + len(words))


def detect_rotation(image):
    from document_vision import get_tesseract_binary
    with tempfile.TemporaryDirectory(prefix='psg-orientation-') as scratch:
        path = str(Path(scratch) / 'page.png')
        image.save(path)
        try:
            process = subprocess.run([get_tesseract_binary(), path, 'stdout', '--psm', '0'], capture_output=True, text=True, timeout=25)
            angle = re.search(r'Rotate: (\d+)', process.stdout)
            confidence = re.search(r'Orientation confidence: ([\d.]+)', process.stdout)
            if process.returncode == 0 and angle and confidence and float(confidence.group(1)) >= 10:
                return (-int(angle.group(1))) % 360
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def orient_page(image):
    from document_vision import run_tesseract_on_pil
    detected = detect_rotation(image)
    if detected is not None:
        normalized = image if detected == 0 else image.rotate(detected, expand=True)
        text = run_tesseract_on_pil(normalized)
        if orientation_score(text) > 30:
            return normalized, text, detected
    variants = []
    for angle in (0, 90, 180, 270):
        candidate = image if angle == 0 else image.rotate(angle, expand=True)
        text = run_tesseract_on_pil(candidate)
        variants.append((orientation_score(text), angle, text))
    _, angle, text = max(variants, key=lambda item: item[0])
    return (image if angle == 0 else image.rotate(angle, expand=True)), text, angle


def parse_scan(file_path, use_ai=False, api_key=None, verify_applications_only=False):
    import fitz
    from PIL import Image, ImageOps
    from doc_reader import parse_raw_text_application
    pages = []
    paths = []
    with tempfile.TemporaryDirectory(prefix='psg-scan-') as scratch:
        if Path(file_path).suffix.lower() == '.pdf':
            with fitz.open(file_path) as document:
                for page in document:
                    pix = page.get_pixmap(dpi=300, colorspace=fitz.csRGB, alpha=False)
                    image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                    normalized, text, rotation = orient_page(image)
                    path = str(Path(scratch) / f'page-{len(pages)+1}.png')
                    normalized.save(path)
                    paths.append(path)
                    pages.append({'page': len(pages)+1, 'rotation': rotation, 'text': text})
        else:
            with Image.open(file_path) as source:
                # Includes every frame of a multipage TIFF, and camera EXIF orientation.
                for index in range(getattr(source, 'n_frames', 1)):
                    source.seek(index)
                    normalized, text, rotation = orient_page(ImageOps.exif_transpose(source).convert('RGB'))
                    path = str(Path(scratch) / f'page-{index+1}.png')
                    normalized.save(path)
                    paths.append(path)
                    pages.append({'page': index+1, 'rotation': rotation, 'text': text})
        result = parse_raw_text_application('\n'.join(page['text'] for page in pages))
        for row in result.get('students', []):
            row['preserve_identity'] = True
        result['engine'] = 'Локальный Tesseract OCR (единый разбор страниц)'
        result['page_orientations'] = [{'page': p['page'], 'rotation': p['rotation']} for p in pages]
        if not result.get('students'):
            result['recognition_issues'] = [{'row': None, 'fields': [], 'reason': 'Не удалось уверенно выделить слушателей. Требуется ручная сверка оригинала.'}]
        application = len(result.get('students', [])) >= 2 or any(s.get('program') for s in result.get('students', []))
        if use_ai and (application or not verify_applications_only):
            import ai_vision
            try:
                response = ai_vision.analyze_multi_page_document_with_ai(paths, api_key=api_key)
            except Exception:
                response = {'success': False, 'error': 'Не удалось выполнить сверку Vision'}
            issues = result.get('recognition_issues', [])
            result = compare_vision(result, response)
            result['recognition_issues'] = issues + result.get('recognition_issues', [])
        return result
