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
import time
import asyncio
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
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

# Load logo and favicon as base64 for embedding
LOGO_B64 = ""
logo_file = os.path.join(BASE_DIR, "static", "psg_logo.png")
if os.path.exists(logo_file):
    with open(logo_file, "rb") as f:
        LOGO_B64 = base64.b64encode(f.read()).decode("utf-8")

FAVICON_B64 = ""
fav_file = os.path.join(BASE_DIR, "static", "favicon-32x32.png")
if not os.path.exists(fav_file):
    fav_file = os.path.join(BASE_DIR, "favicon.ico")
if os.path.exists(fav_file):
    with open(fav_file, "rb") as f:
        FAVICON_B64 = base64.b64encode(f.read()).decode("utf-8")

TASKS: Dict[str, str] = {}
TASK_UPLOADS: Dict[str, List[str]] = {}
CLEANUP_DELAY_SECONDS = int(os.environ.get("CLEANUP_DELAY_SECONDS", 5))

def cleanup_stale_files(max_age_seconds: int = 1800):
    """Removes orphan files older than max_age_seconds from uploads/ and output_1c/."""
    now = time.time()
    for folder in ("uploads", "output_1c"):
        dir_path = os.path.join(BASE_DIR, folder)
        if not os.path.exists(dir_path):
            continue
        try:
            for entry in os.scandir(dir_path):
                if entry.is_file() and not entry.name.startswith("."):
                    try:
                        if now - entry.stat().st_mtime > max_age_seconds:
                            os.remove(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass

def _remove_task_files(output_filename: str):
    """Safely removes the generated output file and all associated upload files."""
    if not output_filename:
        return
    safe_name = os.path.basename(output_filename)
    if not safe_name:
        return

    # 1. Purge output file from output_1c/
    out_path = os.path.join(BASE_DIR, "output_1c", safe_name)
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass

    # 2. Purge associated uploaded files from uploads/
    associated_uploads = TASK_UPLOADS.pop(safe_name, [])
    for up_path in associated_uploads:
        full_up_path = os.path.abspath(up_path)
        if full_up_path.startswith(os.path.join(BASE_DIR, "uploads")) and os.path.exists(full_up_path):
            try:
                os.remove(full_up_path)
            except OSError:
                pass

    # 3. Clean from TASKS
    TASKS.pop(safe_name, None)

async def delayed_cleanup(output_filename: str, delay_seconds: Optional[int] = None):
    """Wait for delay_seconds to let download complete, then purge task files."""
    if delay_seconds is None:
        delay_seconds = CLEANUP_DELAY_SECONDS
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    _remove_task_files(output_filename)

def get_html_content() -> str:
    """Reads HTML template and injects dynamic base64 logo and favicon."""
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return content.replace("{LOGO_B64}", LOGO_B64).replace("{FAVICON_B64}", FAVICON_B64)
    return f"<h1>Ошибка: Шаблон {TEMPLATE_PATH} не найден</h1>"

HTML_TEMPLATE = get_html_content()

@app.on_event("startup")
async def on_startup():
    cleanup_stale_files(max_age_seconds=1800)

@app.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    favicon_path = os.path.join(BASE_DIR, "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(
            favicon_path,
            media_type="image/x-icon",
            headers={"Cache-Control": "public, max-age=3600"}
        )
    raise HTTPException(status_code=404, detail="Favicon not found")

@app.get("/", response_class=HTMLResponse)
async def index():
    cleanup_stale_files(max_age_seconds=1800)
    return HTMLResponse(content=get_html_content())

@app.get("/api/ai-status")
async def get_ai_status():
    """Returns OpenAI connection status, key presence, and diagnostics."""
    try:
        import ai_vision
        status = ai_vision.check_ai_connection()
        return JSONResponse(content=status)
    except Exception as e:
        return JSONResponse(
            content={
                "ok": False,
                "code": "SERVER_ERROR",
                "message": f"Ошибка проверки подключения к ИИ: {str(e)}"
            }
        )

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
            dest_out = os.path.join(BASE_DIR, "output_1c", result["output_filename"])
            orig_out = os.path.abspath(result["output_file"])
            dest_abs = os.path.abspath(dest_out)
            if orig_out != dest_abs:
                shutil.copy(orig_out, dest_out)
                if os.path.exists(orig_out):
                    try:
                        os.remove(orig_out)
                    except OSError:
                        pass
            TASKS[result["output_filename"]] = dest_out
            TASK_UPLOADS[result["output_filename"]] = list(saved_file_paths)
            result["output_file"] = dest_out
        else:
            for up_path in saved_file_paths:
                if os.path.exists(up_path):
                    try:
                        os.remove(up_path)
                    except OSError:
                        pass

        return JSONResponse(content=result)

    except Exception as e:
        for up_path in saved_file_paths:
            if os.path.exists(up_path):
                try:
                    os.remove(up_path)
                except OSError:
                    pass
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(BASE_DIR, "output_1c", safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден или срок его хранения истек")
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=safe_name,
        background=BackgroundTask(delayed_cleanup, safe_name)
    )

@app.post("/api/cleanup")
async def cleanup_endpoint(request: Request):
    """Endpoint for instant file purge (called on browser refresh, tab close, or reset)."""
    filename = None
    try:
        data = await request.json()
        if isinstance(data, dict):
            filename = data.get("filename")
    except Exception:
        pass

    if not filename:
        try:
            form = await request.form()
            filename = form.get("filename")
        except Exception:
            pass

    if not filename:
        filename = request.query_params.get("filename")

    if not filename:
        try:
            body = (await request.body()).decode("utf-8").strip()
            if body.startswith("{") and body.endswith("}"):
                import json
                filename = json.loads(body).get("filename")
            elif body:
                filename = body
        except Exception:
            pass

    if filename:
        _remove_task_files(filename)
        return JSONResponse({"ok": True, "cleaned": filename})
    return JSONResponse({"ok": False, "message": "Имя файла не указано"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Запуск веб-сервера Агента 1С ПСГ: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
