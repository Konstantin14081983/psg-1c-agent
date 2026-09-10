"""
PSG 1C Application Agent - Web Interface.
FastAPI web application with Swiss B2B Engineering design,
Lucide SVG icons, GSAP 3 animations, and corporate branding (ЧОУ ДПО ЦЕНТР "ПСГ").
Supports:
- Multi-file upload with '➕ Добавить еще файл(ы)' button
- Smart auto-fill for training dates in manual parameters
- Turquoise (#DCFFDD) program divider fills matching reference 1C template
- Separate dedicated audit & error panel
- Real-time 1C table preview with interactive yellow highlighting
- Clean removal of garbage contacts ('uuuuu', '111111') without yellow highlighting
- AI Vision toggle (OpenAI GPT-4o-mini) and fallback to local Tesseract OCR
- Instant 1C Excel download
"""

import os
import shutil
import base64
import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

import psg_agent
import document_vision
import doc_reader

app = FastAPI(title="ЧОУ ДПО ЦЕНТР ПСГ — Агент 1С")

# Mount static files and directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "index.html")

os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "uploads"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "output_1c"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Load logo as base64 for embedding
LOGO_B64 = ""
logo_file = os.path.join(BASE_DIR, "static", "psg_logo.png")
if os.path.exists(logo_file):
    with open(logo_file, "rb") as f:
        LOGO_B64 = base64.b64encode(f.read()).decode("utf-8")

TASKS: Dict[str, str] = {}

def get_html_content() -> str:
    """Reads HTML template and injects dynamic base64 logo."""
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return content.replace("{LOGO_B64}", LOGO_B64)
    return f"<h1>Ошибка: Шаблон {TEMPLATE_PATH} не найден</h1>"

HTML_TEMPLATE = get_html_content()

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=get_html_content())

@app.get("/api/ai-status")
async def get_ai_status():
    """Returns OpenAI connection status, key presence, and diagnostics."""
    import ai_vision
    status = ai_vision.check_ai_connection()
    return JSONResponse(content=status)

@app.post("/api/process")
async def process_api(
    files: Optional[List[UploadFile]] = File(None),
    raw_text: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    program: Optional[str] = Form(None),
    study_dates: Optional[str] = Form(None),
    position: Optional[str] = Form(None),
    has_diploma: Optional[bool] = Form(False),
    has_photo: Optional[bool] = Form(False),
    has_certificate: Optional[bool] = Form(False),
    use_ai: Optional[Any] = Form(False),
    openai_api_key: Optional[str] = Form(None)
):
    saved_file_paths = []
    
    try:
        if files:
            for file in files:
                if file and file.filename:
                    temp_path = os.path.join("uploads", file.filename)
                    with open(temp_path, "wb") as f:
                        shutil.copyfileobj(file.file, f)
                    saved_file_paths.append(temp_path)

        manual_overrides = {
            "category": category if category else None,
            "program": program if program else None,
            "study_dates": study_dates if study_dates else None,
            "position": position if position else None,
            "documents": {
                "has_diploma": has_diploma,
                "has_photo": has_photo,
                "has_certificate": has_certificate
            }
        }

        is_ai_enabled = str(use_ai).strip().lower() in ("true", "1", "yes", "on") if use_ai is not None else False

        result = psg_agent.process_application(
            input_file=saved_file_paths if saved_file_paths else None,
            raw_text=raw_text if raw_text else None,
            output_file=None,
            manual_overrides=manual_overrides,
            use_ai=is_ai_enabled,
            openai_api_key=openai_api_key if openai_api_key else None
        )

        if result.get("success") and result.get("output_file"):
            dest_out = os.path.join("output_1c", result["output_filename"])
            shutil.copy(result["output_file"], dest_out)
            TASKS[result["output_filename"]] = dest_out

        return JSONResponse(content=result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join("output_1c", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Запуск веб-сервера Агента 1С ПСГ: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
