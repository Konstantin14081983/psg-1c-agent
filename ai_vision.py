"""
AI Vision and Multimodal Recognition module for PSG 1C Application Agent.
Uses OpenAI Vision (GPT-4o-mini / GPT-4o) or any OpenAI-compatible API endpoint
to extract high-precision structured data from photos and scans of:
- SNILS cards (green laminate, modern ADI-REG form)
- Passports (Russian Federation, CIS: Tajikistan, Uzbekistan, Azerbaijan, etc.)
- Labor Patents (MVD RF)
- Green Fingerprint Cards (MVD RF)
- Diplomas & Certificates
- Messy / blurry smartphone photos taken at an angle
"""

import os
import re
import json
import base64
import mimetypes
import socket
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List, Tuple

try:
    import requests
except ImportError:
    requests = None

class SimpleHTTPResponse:
    """Lightweight response wrapper mimicking requests.Response for zero-dependency standard library fallback."""
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
    def json(self):
        return json.loads(self.text)

def _http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 8):
    if requests is not None:
        return requests.get(url, headers=headers, timeout=timeout)
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
            return SimpleHTTPResponse(status, body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return SimpleHTTPResponse(e.code, body)
    except (urllib.error.URLError, socket.timeout) as e:
        if (hasattr(e, "reason") and isinstance(e.reason, socket.timeout)) or isinstance(e, socket.timeout):
            raise TimeoutError(f"Таймаут соединения с {url}")
        raise ConnectionError(f"Сетевая ошибка: {e}")

def _http_post(url: str, headers: Optional[Dict[str, str]] = None, json_data: Optional[Dict[str, Any]] = None, timeout: int = 30):
    if requests is not None:
        return requests.post(url, headers=headers, json=json_data, timeout=timeout)
    h = dict(headers or {})
    data = None
    if json_data is not None:
        data = json.dumps(json_data).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
            return SimpleHTTPResponse(status, body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return SimpleHTTPResponse(e.code, body)
    except (urllib.error.URLError, socket.timeout) as e:
        if (hasattr(e, "reason") and isinstance(e.reason, socket.timeout)) or isinstance(e, socket.timeout):
            raise TimeoutError(f"Таймаут соединения с {url}")
        raise ConnectionError(f"Сетевая ошибка: {e}")

from PIL import Image

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

DOCUMENT_EXTRACTION_SYSTEM_PROMPT = """Ты главный эксперт учебного центра ЧОУ ДПО ЦЕНТР «ПСГ» по оптическому распознаванию входящих заявок и документов на обучение.
Твоя задача — внимательно проанализировать изображение/скан/фото и извлечь структурированные данные.

ТИПЫ ДОКУМЕНТОВ:
1. Заявка на обучение со списком сотрудников (таблица, список, скан письма, приказ).
2. Письмо-заявка от предприятия (где программы обучения перечислены в тексте письма, а сотрудники — в таблице или списке ниже).
3. Одиночные документы сотрудника (СНИЛС, паспорт РФ или иностранный, патент МВД, зеленая дактилоскопическая карта, диплом).

КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ИЗВЛЕЧЕНИЯ:
1. КТО ЯВЛЯЕТСЯ СЛУШАТЕЛЕМ:
   - Извлекай ВСЕХ направляемых на обучение сотрудников (строки таблицы, пункты списка). Если в таблице 4, 10 или 20 человек — извлеки КАЖДОГО в массив students!
   - НЕ извлекай адресата в шапке («Директору...», «Генеральному директору...»).
   - НЕ извлекай подписантов в подвале («Главный инженер...», «Исполнитель...»).
   - НЕ путай наименование организации («ГОУП Мурманскводоканал», «АО Элмек») с ФИО человека!

2. ПОЛЯ КАЖДОГО СЛУШАТЕЛЯ:
   - fio: ФИО строго на русском языке в именительном падеже (кириллицей).
   - position: Должность или рабочая профессия (например, «Ведущий специалист по ОТиПБ», «Начальник цеха», «Техник сервиса»).
   - birth_date: Дата рождения строго в числовом формате ДД.ММ.ГГГГ (например, 14.10.1967).
   - gender: Пол «М» или «Ж».
   - snils: СНИЛС в формате XXX-XXX-XXX YY (11 цифр).
   - programs: Список программ обучения для этого слушателя (массив строк). Если в графе написано «Программа: А, Б, В (№ 5, 8, 9, 10, 15, 27) Оказание первой помощи, Применение СИЗ» — разбей на отдельные программы: ["Охрана труда А", "Охрана труда Б", "Охрана труда В", "Оказание первой помощи", "Применение СИЗ"].
   - study_dates: Сроки обучения если указаны (например, 01.09.2026 - 15.09.2026).
   - contacts: Телефон или email если указаны.

3. ЕСЛИ ПРОГРАММЫ УКАЗАНЫ ОБЩИМИ В ТЕКСТЕ ПИСЬМА НАД ТАБЛИЦЕЙ:
   - Помести их в массив "common_programs" и продублируй в programs каждого слушателя!

4. ЕСЛИ ЭТО ОДИНОЧНЫЙ ДОКУМЕНТ (паспорт, СНИЛС, патент):
   - Помести данные владельца в массив students как единственный элемент.

СХЕМА ОТВЕТА (СТРОГО ВАЛИДНЫЙ JSON):
{
  "doc_type": "application_table" | "letter_order" | "single_document",
  "application_title": "Заголовок заявки если есть",
  "organization": "Наименование организации",
  "common_programs": ["Программа 1", "Программа 2"],
  "students": [
    {
      "fio": "Фамилия Имя Отчество",
      "position": "Должность",
      "birth_date": "ДД.ММ.ГГГГ",
      "gender": "М" | "Ж",
      "snils": "XXX-XXX-XXX YY",
      "programs": ["Программа 1", "Программа 2"],
      "study_dates": "",
      "contacts": ""
    }
  ]
}
Верни ТОЛЬКО валидный JSON-объект без markdown-разметки и пояснений!"""

TEXT_MESSAGE_EXTRACTION_SYSTEM_PROMPT = """Ты аналитик входящих заявок на обучение учебного центра ЧОУ ДПО ЦЕНТР 'ПСГ'.
Твоя задача — извлечь список слушателей и параметры обучения из неструктурированного текста (сообщение WhatsApp, Telegram, Email).

Выдели по каждому слушателю:
- ФИО (в именительном падеже)
- Должность / профессию (например, 'Монтажник', 'Бетонщик')
- Дату рождения (ДД.ММ.ГГГГ)
- Пол ('М' или 'Ж')
- СНИЛС (XXX-XXX-XXX YY)
- Сроки обучения (например, '01.09.2026 - 15.09.2026')
- Контакты (телефон, email)
- Программу обучения (если указана индивидуально)

Верни СТРОГО JSON:
{
  "students": [
    {
      "fio": "Фамилия Имя Отчество",
      "position": "Должность",
      "birth_date": "ДД.ММ.ГГГГ",
      "gender": "М" | "Ж",
      "snils": "XXX-XXX-XXX YY",
      "study_dates": "Сроки",
      "contacts": "Контакты",
      "program": "Программа"
    }
  ],
  "common_params": {
    "program": "Общая программа для всех если есть",
    "study_dates": "Общие сроки если есть",
    "position": "Общая должность если есть"
  }
}
"""

PLACEHOLDER_KEYS = {
    "sk-proj-your-api-key-here",
    "your-api-key-here",
    "your_key",
    "sk-your-key-here"
}

def load_env_config() -> Dict[str, str]:
    """
    Robustly reads configuration from .env looking in standard locations:
    1. Directory of current file
    2. Current working directory
    3. /opt/psg-1c-agent/.env
    Handles export prefix, quotes, trailing comments, CRLF, and spaces.
    """
    env_vars: Dict[str, str] = {}
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.getcwd(), ".env"),
        "/opt/psg-1c-agent/.env"
    ]
    seen = set()
    pat = re.compile(r'^\s*(?:export\s+)?(OPENAI_API_KEY|OPENAI_BASE_URL)\s*=\s*[\"\']?([^\"\'#\r\n]+?)[\"\']?\s*(?:#.*)?$', re.I)

    for c_path in candidates:
        if c_path in seen:
            continue
        seen.add(c_path)
        if os.path.isfile(c_path):
            try:
                with open(c_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        m = pat.match(line)
                        if m:
                            k = m.group(1).upper()
                            v = m.group(2).strip()
                            if k not in env_vars and v and v not in PLACEHOLDER_KEYS:
                                env_vars[k] = v
            except Exception:
                pass
    return env_vars

def get_api_key(passed_key: Optional[str] = None) -> Optional[str]:
    """Resolves OpenAI API key from argument, environment, or .env file."""
    if passed_key and str(passed_key).strip():
        k = str(passed_key).strip()
        if k not in PLACEHOLDER_KEYS:
            return k
            
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key and env_key.strip():
        k = env_key.strip()
        if k not in PLACEHOLDER_KEYS:
            return k
        
    cfg = load_env_config()
    k = cfg.get("OPENAI_API_KEY")
    if k and k not in PLACEHOLDER_KEYS:
        return k
    return None

def get_base_url() -> str:
    """Returns OpenAI Base URL (supports custom proxies / gateways from environment or .env)."""
    env_url = os.environ.get("OPENAI_BASE_URL")
    if env_url and env_url.strip():
        return env_url.strip().rstrip("/")
    cfg = load_env_config()
    url = cfg.get("OPENAI_BASE_URL")
    if url and url.strip():
        return url.strip().rstrip("/")
    return DEFAULT_BASE_URL.rstrip("/")

def check_ai_connection(api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Performs comprehensive real-time diagnostics of OpenAI API connection.
    Tests: key detection, .env file presence, base URL, and live API connectivity.
    """
    resolved_key = get_api_key(api_key)
    base_url = get_base_url()
    
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.getcwd(), ".env"),
        "/opt/psg-1c-agent/.env"
    ]
    found_env_path = next((p for p in candidates if os.path.isfile(p)), None)
    
    if not resolved_key:
        return {
            "ok": False,
            "code": "NO_KEY",
            "message": "API-ключ не найден. Заполните OPENAI_API_KEY в файле /opt/psg-1c-agent/.env на сервере.",
            "env_file_found": bool(found_env_path),
            "env_file_path": found_env_path or "Не найден",
            "base_url": base_url
        }

    masked_key = (resolved_key[:7] + "..." + resolved_key[-4:]) if len(resolved_key) > 12 else "***"

    try:
        endpoint = f"{base_url}/models"
        headers = {"Authorization": f"Bearer {resolved_key}"}
        resp = _http_get(endpoint, headers=headers, timeout=8)

        if resp.status_code == 200:
            return {
                "ok": True,
                "code": "OK",
                "message": "Подключение к OpenAI успешно! ИИ активен и готов к распознаванию.",
                "masked_key": masked_key,
                "base_url": base_url,
                "env_file_path": found_env_path
            }
        elif resp.status_code == 401:
            return {
                "ok": False,
                "code": "INVALID_KEY",
                "message": "Ошибка 401: Неверный API-ключ OpenAI. Проверьте правильность ключа в .env",
                "masked_key": masked_key,
                "base_url": base_url
            }
        elif resp.status_code == 403 or "unsupported_country_region_territory" in resp.text:
            return {
                "ok": False,
                "code": "GEOBLOCK_403",
                "message": "Ошибка 403: Доступ к api.openai.com заблокирован из РФ. Добавьте в .env: OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1 (или VseGPT).",
                "masked_key": masked_key,
                "base_url": base_url
            }
        elif resp.status_code == 429:
            return {
                "ok": False,
                "code": "QUOTA_EXCEEDED",
                "message": "Ошибка 429: Превышен лимит запросов или на балансе OpenAI закончились средства ($0.00).",
                "masked_key": masked_key,
                "base_url": base_url
            }
        else:
            return {
                "ok": False,
                "code": f"HTTP_{resp.status_code}",
                "message": f"Ошибка OpenAI API ({resp.status_code}): {resp.text[:180]}",
                "masked_key": masked_key,
                "base_url": base_url
            }
    except (getattr(requests.exceptions, 'Timeout', TimeoutError) if requests else TimeoutError, TimeoutError):
        return {
            "ok": False,
            "code": "TIMEOUT",
            "message": f"Таймаут: сервер {base_url} не ответил за 8 секунд. Проверьте интернет или настройки сети.",
            "masked_key": masked_key,
            "base_url": base_url
        }
    except Exception as e:
        return {
            "ok": False,
            "code": "CONNECTION_ERROR",
            "message": f"Сетевая ошибка при обращении к {base_url}: {str(e)}",
            "masked_key": masked_key,
            "base_url": base_url
        }

def encode_image_to_base64(image_path: str, max_dimension: int = 2048) -> Tuple[str, str]:
    """
    Compresses and encodes image to base64 Data URL.
    Ensures image fits within reasonable resolution for optimal speed and cost.
    Returns (base64_data_url, mime_type).
    """
    # Auto-convert HEIC if needed
    ext = os.path.splitext(image_path)[1].lower()
    if ext == ".heic":
        import doc_reader
        conv = doc_reader.convert_heic_to_jpeg(image_path)
        if conv:
            image_path = conv
            ext = ".jpg"

    with Image.open(image_path) as img:
        # Auto-orient using EXIF
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
        
        # Convert RGBA to RGB if needed
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            
        # Resize if dimensions exceed max_dimension
        w, h = img.size
        if max(w, h) > max_dimension:
            scale = max_dimension / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
        import io
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=88)
        img_bytes = buffer.getvalue()

    mime_type = "image/jpeg"
    b64_str = base64.b64encode(img_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64_str}"
    return data_url, mime_type

def analyze_document_with_ai(
    image_path: str,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Analyzes document photo/scan with OpenAI Vision (GPT-4o-mini).
    Returns normalized dictionary ready for 1C student record.
    """
    resolved_key = get_api_key(api_key)
    if not resolved_key:
        return {
            "success": False,
            "error": "API-ключ OpenAI не найден. Укажите ключ в настройках или файле .env"
        }

    try:
        data_url, _ = encode_image_to_base64(image_path)
        base_url = get_base_url()
        endpoint = f"{base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {resolved_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": DOCUMENT_EXTRACTION_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Распознай этот документ и верни результат строго в JSON."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 1000
        }

        resp = _http_post(endpoint, headers=headers, json_data=payload, timeout=timeout)
        if resp.status_code != 200:
            err_msg = f"Ошибка OpenAI API ({resp.status_code}): {resp.text[:200]}"
            if resp.status_code == 403 or "unsupported_country_region_territory" in resp.text:
                err_msg = (
                    "Ошибка 403 (Доступ к api.openai.com заблокирован из РФ). "
                    "Укажите в файле .env шлюз: OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1 (или https://api.vsegpt.ru/v1)"
                )
            elif resp.status_code == 401:
                err_msg = "Ошибка 401: Неверный API-ключ OpenAI. Проверьте правильность ключа в файле .env"
            elif resp.status_code == 429:
                err_msg = "Ошибка 429: Превышен лимит запросов или на балансе OpenAI закончились средства ($0.00)"
            return {
                "success": False,
                "error": err_msg
            }

        res_json = resp.json()
        raw_content = res_json["choices"][0]["message"]["content"]
        extracted = json.loads(raw_content)

        # Extract and normalize students array
        raw_students = extracted.get("students", [])
        if not raw_students and (extracted.get("fio") or extracted.get("snils")):
            raw_students = [{
                "fio": extracted.get("fio", ""),
                "birth_date": extracted.get("birth_date", ""),
                "gender": extracted.get("gender", ""),
                "snils": extracted.get("snils", ""),
                "position": extracted.get("position", ""),
                "programs": extracted.get("programs", []),
                "study_dates": extracted.get("study_dates", ""),
                "contacts": extracted.get("contacts", "")
            }]

        common_progs = extracted.get("common_programs", [])
        if isinstance(common_progs, str):
            common_progs = [p.strip() for p in re.split(r'[;\n]+', common_progs) if p.strip()]

        normalized_students = []
        import linguistics
        for s in raw_students:
            s_fio = str(s.get("fio", "")).strip()
            # Ignore headers/signers/organizations mistakenly captured as FIO
            if not s_fio or any(ign in s_fio.lower() for ign in ['директор', 'главный инженер', 'исполнитель', 'организаци', 'предприяти', 'таблица']):
                if not s_fio and (s.get("snils") or s.get("position")):
                    s_fio = "Слушатель (данные из документа)"
                else:
                    continue

            s_birth = str(s.get("birth_date", "")).strip()
            if s_birth:
                norm_d, d_ok, _ = linguistics.normalize_date(s_birth)
                if d_ok:
                    s_birth = norm_d

            s_snils = str(s.get("snils", "")).strip()
            if s_snils:
                norm_s, s_ok, _ = linguistics.validate_and_format_snils(s_snils)
                if s_ok:
                    s_snils = norm_s

            s_gender = str(s.get("gender", "")).strip().upper()
            if s_gender not in ("М", "Ж"):
                s_gender = ""

            s_progs = s.get("programs", [])
            if isinstance(s_progs, str):
                s_progs = [p.strip() for p in re.split(r'[;\n]+', s_progs) if p.strip()]
            if not s_progs and common_progs:
                s_progs = list(common_progs)

            prog_str = "; ".join(s_progs) if isinstance(s_progs, list) else str(s_progs)

            normalized_students.append({
                "fio": s_fio,
                "position": str(s.get("position", "")).strip(),
                "birth_date": s_birth,
                "gender": s_gender,
                "snils": s_snils,
                "programs": s_progs,
                "program": prog_str,
                "study_dates": str(s.get("study_dates", "")).strip(),
                "contacts": str(s.get("contacts", "")).strip()
            })

        first_stud = normalized_students[0] if normalized_students else {}

        return {
            "success": True,
            "doc_type": extracted.get("doc_type", "document"),
            "application_title": extracted.get("application_title", ""),
            "organization": extracted.get("organization", ""),
            "common_programs": common_progs,
            "students": normalized_students,
            # Backward-compatible single student properties:
            "fio": first_stud.get("fio", ""),
            "position": first_stud.get("position", ""),
            "birth_date": first_stud.get("birth_date", ""),
            "gender": first_stud.get("gender", ""),
            "snils": first_stud.get("snils", ""),
            "program": first_stud.get("program", ""),
            "inn": extracted.get("inn", ""),
            "doc_number": extracted.get("doc_number", ""),
            "citizenship": extracted.get("citizenship", ""),
            "engine": f"OpenAI Vision ({model})"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Исключение при вызове OpenAI Vision: {str(e)}"
        }

def analyze_text_message_with_ai(
    raw_text: str,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    timeout: int = 25
) -> Dict[str, Any]:
    """
    Deep semantic extraction of complex text messages from managers/clients using GPT-4o-mini.
    """
    resolved_key = get_api_key(api_key)
    if not resolved_key:
        return {"success": False, "students": [], "error": "No API key"}

    try:
        base_url = get_base_url()
        endpoint = f"{base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {resolved_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": TEXT_MESSAGE_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": raw_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 1500
        }

        resp = _http_post(endpoint, headers=headers, json_data=payload, timeout=timeout)
        if resp.status_code != 200:
            err_msg = f"Ошибка OpenAI API ({resp.status_code}): {resp.text[:200]}"
            if resp.status_code == 403 or "unsupported_country_region_territory" in resp.text:
                err_msg = (
                    "Ошибка 403 (Доступ к api.openai.com заблокирован из РФ). "
                    "Укажите в файле .env шлюз: OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1 (или https://api.vsegpt.ru/v1)"
                )
            elif resp.status_code == 401:
                err_msg = "Ошибка 401: Неверный API-ключ OpenAI. Проверьте правильность ключа в файле .env"
            elif resp.status_code == 429:
                err_msg = "Ошибка 429: Превышен лимит запросов или на балансе OpenAI закончились средства ($0.00)"
            return {"success": False, "students": [], "error": err_msg}

        data = json.loads(resp.json()["choices"][0]["message"]["content"])
        return {
            "success": True,
            "students": data.get("students", []),
            "common_params": data.get("common_params", {}),
            "engine": f"OpenAI ({model})"
        }
    except Exception as e:
        return {"success": False, "students": [], "error": str(e)}
