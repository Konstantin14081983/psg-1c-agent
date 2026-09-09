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
from typing import Dict, Any, Optional, List, Tuple
import requests

from PIL import Image

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

DOCUMENT_EXTRACTION_SYSTEM_PROMPT = """Ты высококвалифицированный эксперт по оптическому распознаванию документов для кадровой системы 1С учебного центра.
Твоя задача — внимательно проанализировать изображение официального документа и извлечь точные персональные данные.

Возможные типы документов:
- СНИЛС (зеленое страховое свидетельство или бланк АДИ-РЕГ)
- Паспорт гражданина РФ или иностранный паспорт (Таджикистан, Узбекистан, Азербайджан, Кыргызстан, Казахстан и др.)
- Патент на работу иностранного гражданина (МВД РФ)
- Дактилоскопическая карта иностранного гражданина (зеленая карта МВД РФ)
- Диплом / аттестат об образовании
- Прочие документы, удостоверяющие личность

ПРАВИЛА ИЗВЛЕЧЕНИЯ:
1. ФИО: верни Фамилию Имя Отчество на чистом русском языке в именительном падеже (кириллицей). Если в иностранном паспорте имя на латинице (например, NAIMOV ESIN), используй русское написание из документа (НАИМОВ ЕСИН АБДУКОДИРОВИЧ).
2. Дата рождения: строго в формате ДД.ММ.ГГГГ (например, 12.03.1983 или 01.06.1996). Если в документе месяц написан прописью (например, '12 апреля 1983 года'), переведи в числовой формат '12.04.1983'.
3. Пол: 'М' или 'Ж'.
4. СНИЛС: если в документе есть СНИЛС, отформатируй его как XXX-XXX-XXX YY (11 цифр).
5. Должность / профессия: если в документе указана специальность или профессия (например, в патенте строка 'Профессия (специальность...): Подсобный рабочий'), обязательно извлеки ее в поле position.
6. Гражданство и номер документа: извлеки, если они присутствуют.

Верни результат СТРОГО в виде JSON-объекта по следующей схеме:
{
  "success": true,
  "doc_type": "snils" | "passport_rf" | "passport_foreign" | "patent" | "fingerprint_card" | "diploma" | "other",
  "fio": "Фамилия Имя Отчество",
  "birth_date": "ДД.ММ.ГГГГ",
  "gender": "М" | "Ж",
  "snils": "XXX-XXX-XXX YY",
  "inn": "ИНН если указан",
  "doc_number": "Серия и номер",
  "citizenship": "Гражданство",
  "position": "Профессия/Должность если указана"
}
Если какое-либо поле отсутствует на документе, укажи для него пустую строку "".
НЕ ДОБАВЛЯЙ никаких пояснений или markdown-тегов вне JSON. Ответ должен быть только валидным JSON-объектом!
"""

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

def get_api_key(passed_key: Optional[str] = None) -> Optional[str]:
    """Resolves OpenAI API key from argument, environment, or .env file."""
    if passed_key and str(passed_key).strip():
        return str(passed_key).strip()
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
        
    # Check .env file in workspace
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OPENAI_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except Exception:
            pass
    return None

def get_base_url() -> str:
    """Returns OpenAI Base URL (supports custom proxies / gateways)."""
    return os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

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

        resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"Ошибка OpenAI API ({resp.status_code}): {resp.text}"
            }

        res_json = resp.json()
        raw_content = res_json["choices"][0]["message"]["content"]
        extracted = json.loads(raw_content)

        # Post-process and normalize fields
        fio_clean = extracted.get("fio", "").strip()
        birth_clean = extracted.get("birth_date", "").strip()
        snils_clean = extracted.get("snils", "").strip()
        gender_clean = extracted.get("gender", "").strip().upper()
        pos_clean = extracted.get("position", "").strip()

        # Sanitize birth date format
        if birth_clean:
            import linguistics
            norm_date, d_ok, _ = linguistics.normalize_date(birth_clean)
            if d_ok:
                birth_clean = norm_date

        # Sanitize SNILS format
        if snils_clean:
            import linguistics
            norm_snils, s_ok, _ = linguistics.validate_and_format_snils(snils_clean)
            if s_ok:
                snils_clean = norm_snils

        return {
            "success": True,
            "fio": fio_clean,
            "birth_date": birth_clean,
            "gender": gender_clean if gender_clean in ("М", "Ж") else "",
            "snils": snils_clean,
            "position": pos_clean,
            "inn": extracted.get("inn", ""),
            "doc_type": extracted.get("doc_type", "document"),
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

        resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            return {"success": False, "students": [], "error": resp.text}

        data = json.loads(resp.json()["choices"][0]["message"]["content"])
        return {
            "success": True,
            "students": data.get("students", []),
            "common_params": data.get("common_params", {}),
            "engine": f"OpenAI ({model})"
        }
    except Exception as e:
        return {"success": False, "students": [], "error": str(e)}
