"""
PSG 1C Application Agent - Web Interface.
FastAPI web application with corporate branding (White, Black, Gray, Red, and PSG Logo).
Supports:
- Multi-file upload with '➕ Добавить еще файл(ы)' button
- Smart auto-fill for training dates in manual parameters
- Turquoise (#CCFFFF) program divider fills matching reference 1C template
- Separate dedicated audit & error panel
- Real-time 1C table preview with interactive yellow highlighting
- Clean removal of garbage contacts ('uuuuu', '111111') without yellow highlighting
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

# Mount static files
os.makedirs("static", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("output_1c", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Load logo as base64 for embedding
LOGO_B64 = ""
logo_file = os.path.join("static", "psg_logo.png")
if os.path.exists(logo_file):
    with open(logo_file, "rb") as f:
        LOGO_B64 = base64.b64encode(f.read()).decode("utf-8")

TASKS: Dict[str, str] = {}

HTML_TEMPLATE = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Агент 1С | ЧОУ ДПО ЦЕНТР "ПСГ"</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --psg-red: #E51E25;
      --psg-red-hover: #C41219;
      --psg-black: #121214;
      --psg-dark: #1E1E24;
      --psg-gray-bg: #F4F5F7;
      --psg-gray-card: #FFFFFF;
      --psg-gray-border: #E2E8F0;
      --psg-gray-text: #64748B;
      --psg-text-dark: #0F172A;
      --psg-yellow: #FEF08A;
      --psg-yellow-dark: #854D0E;
      --psg-yellow-border: #FACC15;
      --psg-cell-yellow: #FFFF00;
      --psg-1c-turquoise: #DCFFDD;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      font-family: 'Inter', sans-serif;
      background-color: var(--psg-gray-bg);
      color: var(--psg-text-dark);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}

    header {{
      background-color: var(--psg-black);
      color: #FFFFFF;
      padding: 1rem 2rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 3px solid var(--psg-red);
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }}

    .brand-container {{
      display: flex;
      align-items: center;
      gap: 1.25rem;
    }}

    .logo-img {{
      height: 52px;
      width: 52px;
      object-fit: contain;
      filter: drop-shadow(0 2px 4px rgba(0,0,0,0.4));
    }}

    .brand-text h1 {{
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}

    .brand-text h1 span {{
      color: var(--psg-red);
    }}

    .brand-text p {{
      font-size: 0.8rem;
      color: #94A3B8;
      margin-top: 0.15rem;
    }}

    .header-badge {{
      background-color: rgba(229, 30, 37, 0.15);
      border: 1px solid var(--psg-red);
      color: #FECACA;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.35rem 0.75rem;
      border-radius: 9999px;
    }}

    main {{
      flex: 1;
      max-width: 1440px;
      width: 100%;
      margin: 0 auto;
      padding: 1.5rem 2rem;
      display: grid;
      grid-template-columns: 480px 1fr;
      gap: 1.5rem;
    }}

    @media (max-width: 1024px) {{
      main {{
        grid-template-columns: 1fr;
      }}
    }}

    .card {{
      background: var(--psg-gray-card);
      border-radius: 12px;
      border: 1px solid var(--psg-gray-border);
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
      overflow: hidden;
    }}

    .card-header {{
      padding: 1rem 1.25rem;
      border-bottom: 1px solid var(--psg-gray-border);
      background-color: #FAFAFA;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}

    .card-title {{
      font-size: 0.95rem;
      font-weight: 700;
      color: var(--psg-black);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}

    .card-body {{
      padding: 1.25rem;
    }}

    .tabs-nav {{
      display: flex;
      border-bottom: 1px solid var(--psg-gray-border);
      background-color: #F8FAFC;
    }}

    .tab-btn {{
      flex: 1;
      padding: 0.75rem 1rem;
      background: none;
      border: none;
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--psg-gray-text);
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.4rem;
    }}

    .tab-btn.active {{
      color: var(--psg-red);
      background: #FFFFFF;
      border-bottom-color: var(--psg-red);
    }}

    .tab-pane {{
      display: none;
    }}

    .tab-pane.active {{
      display: block;
    }}

    .dropzone {{
      border: 2px dashed #CBD5E1;
      border-radius: 8px;
      padding: 1.75rem 1.5rem;
      text-align: center;
      background-color: #F8FAFC;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .dropzone:hover, .dropzone.dragover {{
      border-color: var(--psg-red);
      background-color: rgba(229, 30, 37, 0.03);
    }}

    .dropzone-icon {{
      font-size: 2.25rem;
      color: var(--psg-gray-text);
      margin-bottom: 0.4rem;
    }}

    .dropzone-text {{
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--psg-black);
    }}

    .dropzone-hint {{
      font-size: 0.75rem;
      color: var(--psg-gray-text);
      margin-top: 0.35rem;
    }}

    /* Multi-file List */
    .files-list-container {{
      margin-top: 0.75rem;
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
      max-height: 180px;
      overflow-y: auto;
    }}

    .file-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.45rem 0.75rem;
      background: #F1F5F9;
      border-radius: 6px;
      font-size: 0.8rem;
      border: 1px solid #E2E8F0;
    }}

    .file-item-name {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-weight: 500;
      color: #1E293B;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 340px;
    }}

    .file-remove-btn {{
      color: #EF4444;
      background: none;
      border: none;
      font-size: 1rem;
      cursor: pointer;
      padding: 0 0.25rem;
    }}

    .add-more-btn {{
      margin-top: 0.6rem;
      background-color: #F8FAFC;
      border: 1px solid #CBD5E1;
      color: #334155;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 0.45rem 0.85rem;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      transition: all 0.2s ease;
    }}

    .add-more-btn:hover {{
      background-color: #E2E8F0;
      border-color: #94A3B8;
    }}

    textarea.msg-input {{
      width: 100%;
      height: 140px;
      padding: 0.75rem;
      border-radius: 8px;
      border: 1px solid var(--psg-gray-border);
      font-family: inherit;
      font-size: 0.85rem;
      resize: vertical;
      outline: none;
    }}

    textarea.msg-input:focus {{
      border-color: var(--psg-red);
      box-shadow: 0 0 0 3px rgba(229, 30, 37, 0.1);
    }}

    .form-group {{
      margin-bottom: 0.9rem;
    }}

    .form-label {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.78rem;
      font-weight: 600;
      color: #334155;
      margin-bottom: 0.35rem;
    }}

    .form-input, .form-select {{
      width: 100%;
      padding: 0.55rem 0.75rem;
      border-radius: 6px;
      border: 1px solid var(--psg-gray-border);
      font-size: 0.825rem;
      font-family: inherit;
      outline: none;
      background-color: #FFFFFF;
    }}

    .form-input:focus, .form-select:focus {{
      border-color: var(--psg-red);
      box-shadow: 0 0 0 2px rgba(229, 30, 37, 0.1);
    }}

    /* Date presets */
    .date-presets {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      margin-top: 0.4rem;
    }}

    .preset-chip {{
      font-size: 0.68rem;
      font-weight: 600;
      padding: 0.2rem 0.5rem;
      background: #E2E8F0;
      color: #334155;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.15s ease;
      border: none;
    }}

    .preset-chip:hover {{
      background: var(--psg-red);
      color: #FFFFFF;
    }}

    .btn-clear-params {{
      background: none;
      border: 1px solid var(--psg-gray-border);
      border-radius: 4px;
      padding: 3px 8px;
      font-size: 0.72rem;
      font-weight: 500;
      color: #64748B;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.15s ease;
    }}

    .btn-clear-params:hover {{
      background: #FEE2E2;
      color: var(--psg-red);
      border-color: var(--psg-red);
    }}

    .prog-chip-label {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.73rem;
      background: #F1F5F9;
      color: #334155;
      padding: 3px 8px;
      border-radius: 6px;
      border: 1px solid var(--psg-gray-border);
      cursor: pointer;
      user-select: none;
      transition: all 0.15s ease;
    }}

    .prog-chip-label:hover {{
      background: #E2E8F0;
      border-color: #94A3B8;
    }}

    .prog-chip-label input[type="checkbox"] {{
      accent-color: var(--psg-red);
      width: 13px;
      height: 13px;
    }}

    .checkbox-group {{
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      background-color: #F8FAFC;
      padding: 0.65rem 0.75rem;
      border-radius: 6px;
      border: 1px solid var(--psg-gray-border);
    }}

    .checkbox-label {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.76rem;
      font-weight: 500;
      color: #334155;
      cursor: pointer;
    }}

    .checkbox-label input[type="checkbox"] {{
      accent-color: var(--psg-red);
      width: 14px;
      height: 14px;
    }}

    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      font-family: inherit;
      font-size: 0.875rem;
      font-weight: 600;
      padding: 0.75rem 1.25rem;
      border-radius: 8px;
      border: none;
      cursor: pointer;
      transition: all 0.2s ease;
      width: 100%;
    }}

    .btn-red {{
      background-color: var(--psg-red);
      color: #FFFFFF;
    }}

    .btn-red:hover {{
      background-color: var(--psg-red-hover);
      transform: translateY(-1px);
      box-shadow: 0 4px 10px rgba(229, 30, 37, 0.25);
    }}

    .btn-download {{
      background-color: #10B981;
      color: #FFFFFF;
      text-decoration: none;
      margin-top: 1rem;
    }}

    .btn-download:hover {{
      background-color: #059669;
    }}

    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 0.75rem;
      margin-bottom: 1.25rem;
    }}

    .stat-card {{
      background: #FFFFFF;
      border: 1px solid var(--psg-gray-border);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      text-align: center;
    }}

    .stat-value {{
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--psg-black);
    }}

    .stat-label {{
      font-size: 0.7rem;
      color: var(--psg-gray-text);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-top: 0.2rem;
    }}

    .audit-section {{
      margin-bottom: 1.25rem;
    }}

    .audit-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 0.5rem;
    }}

    .audit-category-title {{
      font-size: 0.825rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }}

    .audit-badge {{
      font-size: 0.72rem;
      padding: 0.15rem 0.5rem;
      border-radius: 999px;
      font-weight: 700;
    }}

    .badge-error {{
      background-color: #FEE2E2;
      color: #B91C1C;
    }}

    .badge-warning {{
      background-color: var(--psg-yellow);
      color: var(--psg-yellow-dark);
    }}

    .badge-doc {{
      background-color: #E0E7FF;
      color: #3730A3;
    }}

    .audit-list {{
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }}

    .audit-item {{
      padding: 0.6rem 0.85rem;
      border-radius: 6px;
      font-size: 0.8rem;
      display: flex;
      align-items: flex-start;
      gap: 0.6rem;
      line-height: 1.4;
    }}

    .audit-item-error {{
      background-color: #FEF2F2;
      border-left: 3px solid #EF4444;
      color: #991B1B;
    }}

    .audit-item-warning {{
      background-color: #FEFCE8;
      border-left: 3px solid #EAB308;
      color: #854D0E;
    }}

    .audit-item-doc {{
      background-color: #EEF2FF;
      border-left: 3px solid #6366F1;
      color: #312E81;
    }}

    .audit-item strong {{
      font-weight: 600;
    }}

    .table-container {{
      max-height: 440px;
      overflow: auto;
      border: 1px solid var(--psg-gray-border);
      border-radius: 8px;
      background-color: #FFFFFF;
    }}

    table.preview-1c {{
      width: 100%;
      border-collapse: collapse;
      font-family: Arial, sans-serif;
      font-size: 11px;
    }}

    table.preview-1c th, table.preview-1c td {{
      border: 1px solid #000000;
      padding: 4px 6px;
      vertical-align: top;
    }}

    table.preview-1c th {{
      background-color: #FFFFFF;
      font-weight: bold;
      text-align: center;
      vertical-align: middle;
      height: 32px;
    }}

    .row-title-1c {{
      text-align: center;
      font-weight: bold;
      font-size: 12px;
      height: 30px;
      vertical-align: middle !important;
      background-color: #FFFFFF;
    }}

    /* LIGHT MINT/GREEN (#DCFFDD) */
    .row-prog-1c {{
      background-color: var(--psg-1c-turquoise) !important;
      font-size: 11px;
      font-weight: normal;
      padding: 4px 8px;
      color: #000000;
    }}

    .row-prog-1c.yellow-prog {{
      background-color: var(--psg-cell-yellow) !important;
    }}

    td.cell-yellow {{
      background-color: var(--psg-cell-yellow) !important;
      position: relative;
    }}

    td.cell-yellow:hover::after {{
      content: attr(data-tooltip);
      position: absolute;
      left: 10px;
      bottom: 100%;
      background: #1E293B;
      color: #FFFFFF;
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 10px;
      white-space: nowrap;
      z-index: 50;
      box-shadow: 0 4px 6px rgba(0,0,0,0.2);
    }}

    .spinner {{
      display: none;
      width: 18px;
      height: 18px;
      border: 2px solid #FFFFFF;
      border-top-color: transparent;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }}

    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}

    .placeholder-msg {{
      padding: 3rem 2rem;
      text-align: center;
      color: var(--psg-gray-text);
      font-size: 0.9rem;
    }}
  </style>
</head>
<body>

  <!-- Header -->
  <header>
    <div class="brand-container">
      <img src="data:image/png;base64,{LOGO_B64}" alt="ПСГ Логотип" class="logo-img">
      <div class="brand-text">
        <h1>ЧОУ ДПО ЦЕНТР <span>«ПСГ»</span> | Агент 1С</h1>
        <p>Интеллектуальная обработка заявок заказчиков и подготовка эталонной выгрузки в 1С</p>
      </div>
    </div>
    <div class="header-badge">Версия 2.1 • Регламенты обучения 2026</div>
  </header>

  <!-- Main Content -->
  <main>
    
    <!-- Left Column: Input Form -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">📥 Источник входящей заявки</div>
      </div>
      
      <!-- Input Mode Tabs -->
      <div class="tabs-nav">
        <button type="button" class="tab-btn active" onclick="switchTab('file')">📁 Файлы заявки</button>
        <button type="button" class="tab-btn" onclick="switchTab('text')">✍️ Текст сообщения</button>
      </div>

      <div class="card-body">
        <form id="processForm" onsubmit="handleFormSubmit(event)">
          
          <!-- Tab 1: Multi-File Upload -->
          <div id="tabFile" class="tab-pane active">
            <div class="dropzone" id="dropzone" onclick="document.getElementById('fileInput').click()">
              <div class="dropzone-icon">📄</div>
              <div class="dropzone-text">Перетащите сюда файлы или нажмите для выбора</div>
              <div class="dropzone-hint">Word (.docx), Excel (.xlsx), PDF, фото документов (JPEG, PNG, HEIC)</div>
            </div>
            <input type="file" id="fileInput" multiple style="display: none;" onchange="handleFilesSelected(this.files)">
            
            <!-- Multi-file list -->
            <div class="files-list-container" id="filesListContainer" style="display: none;"></div>
            
            <div style="display: flex; justify-content: flex-end;">
              <button type="button" class="add-more-btn" id="addMoreBtn" style="display: none;" onclick="document.getElementById('fileInput').click()">
                ➕ Добавить еще файл(ы)
              </button>
            </div>
          </div>

          <!-- Tab 2: Raw Text -->
          <div id="tabText" class="tab-pane">
            <div class="form-group">
              <label class="form-label">Вставьте текст сообщения из WhatsApp / Telegram / Email:</label>
              <textarea class="msg-input" id="rawTextInput" placeholder="Пример:&#10;1. Иванов Иван Иванович, 12.05.1985, 189-878-867 92, монтажник м/к, Пожарка, 01.09.2026 - 15.09.2026"></textarea>
            </div>
          </div>

          <hr style="margin: 1.15rem 0; border: none; border-top: 1px solid var(--psg-gray-border);">

          <!-- Manual Overrides for Manager -->
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
            <div class="card-title" style="margin-bottom: 0; font-size: 0.85rem;">⚙️ Ручные параметры (опционально)</div>
            <button type="button" class="btn-clear-params" onclick="clearManualParams()" title="Очистить все введенные ручные параметры">
              🗑️ Очистить параметры
            </button>
          </div>

          <div class="form-group">
            <label class="form-label">Вид обучения:</label>
            <select class="form-select" id="overrideCategory" onchange="handleCategoryChange(this.value)">
              <option value="">Автоопределение по названию программы</option>
              <option value="ОТ (Охрана труда)">Охрана труда (А, Б, В, СИЗ, ПП) — строго последовательно</option>
              <option value="Рабочие профессии">Рабочие профессии (120-280 ч, окончание <= 3 дней назад)</option>
              <option value="ПК / ДПП">ПК / ДПП (окончание <= 30 дней назад, экология 112ч, пожарка)</option>
              <option value="Высота и ОЗП">Высота и ОЗП (24 ч, группы 1, 2, 3 без пересечения)</option>
              <option value="Допуски и проверка знаний">Допуски и ежегодная проверка знаний (свободные даты)</option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Программы обучения (можно выбрать несколько или ввести свои):</label>
            <div style="display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.5rem;">
              <label class="prog-chip-label"><input type="checkbox" name="progChip" value="ОТ (Б+СИЗ+ПП)" onchange="updateSelectedPrograms()"> 🛡️ Охрана труда (Б+СИЗ+ПП)</label>
              <label class="prog-chip-label"><input type="checkbox" name="progChip" value="Высота 1 группа" onchange="updateSelectedPrograms()"> 🧗 Высота 1 группа</label>
              <label class="prog-chip-label"><input type="checkbox" name="progChip" value="Высота 2 группа" onchange="updateSelectedPrograms()"> 🧗 Высота 2 группа</label>
              <label class="prog-chip-label"><input type="checkbox" name="progChip" value="ДПП Специалист по пожарной профилактике" onchange="updateSelectedPrograms()"> 🔥 Пожарная безопасность</label>
              <label class="prog-chip-label"><input type="checkbox" name="progChip" value="Обучение по программе 'Нормы и правила работы в электроустановках'" onchange="updateSelectedPrograms()"> ⚡ Электробезопасность</label>
              <label class="prog-chip-label"><input type="checkbox" name="progChip" value="Ежегодные занятия с водителями автотранспортных средств" onchange="updateSelectedPrograms()"> 🚗 Водители (БДД 20ч)</label>
            </div>
            <input type="text" class="form-input" id="overrideProgram" list="programList" placeholder="Укажите программу или несколько через точку с запятой ';'">
            <datalist id="programList">
              <option value="ОТ (Б+СИЗ+ПП)">
              <option value="Программа обучения безопасным методам и приемам выполнения работ на высоте, 1 группа">
              <option value="Профессиональная подготовка по профессии Машинист крана автомобильного 8 разряд">
              <option value="Профессиональная подготовка по профессии Стропальщик">
              <option value="Ежегодные занятия с водителями автотранспортных средств">
              <option value="Обучение по программе 'Нормы и правила работы в электроустановках'">
              <option value="ДПП Специалист по пожарной профилактике">
              <option value="ПК Обеспечение экологической безопасности при работах в области обращения с опасными отходами I-IV класс опасности">
            </datalist>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
            <div class="form-group">
              <div class="form-label">
                <span>Сроки обучения:</span>
                <span style="color: var(--psg-red); font-size: 0.7rem; cursor: pointer; text-decoration: underline;" onclick="autoFillDatesForCategory()">⚡ Авто-заполнение</span>
              </div>
              <input type="text" class="form-input" id="overrideDates" placeholder="ДД.ММ.ГГГГ - ДД.ММ.ГГГГ">
              <div class="date-presets">
                <button type="button" class="preset-chip" onclick="setDatePreset('today_14')">Сегодня +14д</button>
                <button type="button" class="preset-chip" onclick="setDatePreset('worker_3d')">Рабочие (за 2д)</button>
                <button type="button" class="preset-chip" onclick="setDatePreset('pk_15d')">ПК/ДПП (за 15д)</button>
                <button type="button" class="preset-chip" onclick="setDatePreset('ot_5d')">ОТ (+5д)</button>
              </div>
            </div>
            
            <div class="form-group">
              <div class="form-label">Должность по умолчанию:</div>
              <input type="text" class="form-input" id="overridePosition" placeholder="Например: Подсобный рабочий">
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Наличие подтверждающих документов:</label>
            <div class="checkbox-group">
              <label class="checkbox-label">
                <input type="checkbox" id="docDiploma"> Скан диплома об образовании (обязателен для ПК/ДПП)
              </label>
              <label class="checkbox-label">
                <input type="checkbox" id="docPhoto"> Фото 3х4 (обязательно для рабочих профессий и высоты)
              </label>
              <label class="checkbox-label">
                <input type="checkbox" id="docCertificate"> Скан / номер удостоверения (для ежегодной проверки)
              </label>
            </div>
          </div>

          <!-- Submit Button -->
          <button type="submit" class="btn btn-red" id="submitBtn">
            <span class="spinner" id="btnSpinner"></span>
            <span id="btnText">⚡ Обработать заявку и сформировать файл 1С</span>
          </button>

        </form>
      </div>
    </div>

    <!-- Right Column: Results, Audit & Preview -->
    <div style="display: flex; flex-direction: column; gap: 1.5rem;">
      
      <!-- Stats & Audit Card -->
      <div class="card" id="resultsCard">
        <div class="card-header">
          <div class="card-title">🔍 Отчет аудита и комментарии к заявке</div>
          <span id="statusBadge" class="audit-badge badge-warning" style="display: none;">Требуется внимание</span>
        </div>
        <div class="card-body">
          
          <div id="initialPlaceholder" class="placeholder-msg">
            👈 Загрузите файлы заявки или вставьте текст, чтобы запустить проверку и подготовку выгрузки для 1С
          </div>

          <div id="resultsContent" style="display: none;">
            <!-- Stats -->
            <div class="stats-grid">
              <div class="stat-card">
                <div class="stat-value" id="statStudents">0</div>
                <div class="stat-label">Слушателей</div>
              </div>
              <div class="stat-card">
                <div class="stat-value" id="statPrograms">0</div>
                <div class="stat-label">Программ</div>
              </div>
              <div class="stat-card">
                <div class="stat-value" id="statRows">0</div>
                <div class="stat-label">Строк в 1С</div>
              </div>
              <div class="stat-card">
                <div class="stat-value" id="statYellow" style="color: #D97706;">0</div>
                <div class="stat-label">Спорных полей</div>
              </div>
            </div>

            <!-- Audit Sections -->
            <!-- 1. Rule violations -->
            <div class="audit-section" id="secViolations" style="display: none;">
              <div class="audit-header">
                <div class="audit-category-title" style="color: #DC2626;">🚫 Нарушения регламентов обучения</div>
                <span class="audit-badge badge-error" id="badgeViolations">0</span>
              </div>
              <div class="audit-list" id="listViolations"></div>
            </div>

            <!-- 2. Document package issues -->
            <div class="audit-section" id="secDocs" style="display: none;">
              <div class="audit-header">
                <div class="audit-category-title" style="color: #4F46E5;">📄 Комплектность пакета документов</div>
                <span class="audit-badge badge-doc" id="badgeDocs">0</span>
              </div>
              <div class="audit-list" id="listDocs"></div>
            </div>

            <!-- 3. Yellow Highlighted fields -->
            <div class="audit-section" id="secYellow" style="display: none;">
              <div class="audit-header">
                <div class="audit-category-title" style="color: #B45309;">⚠️ Спорные данные (подсвечены желтым в 1С)</div>
                <span class="audit-badge badge-warning" id="badgeYellow">0</span>
              </div>
              <div class="audit-list" id="listYellow"></div>
            </div>

            <!-- Download Button -->
            <a href="#" class="btn btn-download" id="downloadBtn" target="_blank">
              📥 Скачать готовую заявку для 1С (.xlsx)
            </a>

          </div>

        </div>
      </div>

      <!-- Preview Table Card -->
      <div class="card" id="previewCard" style="display: none;">
        <div class="card-header">
          <div class="card-title">📋 Предпросмотр таблицы для 1С (Лист_1)</div>
          <span style="font-size: 0.75rem; color: var(--psg-gray-text);">Спорные ячейки — желтые</span>
        </div>
        <div class="card-body" style="padding: 0.75rem;">
          <div class="table-container" id="tablePreviewContainer"></div>
        </div>
      </div>

    </div>

  </main>

  <script>
    let activeTab = 'file';
    let selectedFiles = [];

    function switchTab(tab) {{
      activeTab = tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      if (tab === 'file') {{
        document.querySelector('.tab-btn:nth-child(1)').classList.add('active');
        document.getElementById('tabFile').classList.add('active');
      }} else {{
        document.querySelector('.tab-btn:nth-child(2)').classList.add('active');
        document.getElementById('tabText').classList.add('active');
      }}
    }}

    // Dropzone logic
    const dropzone = document.getElementById('dropzone');
    dropzone.addEventListener('dragover', (e) => {{ e.preventDefault(); dropzone.classList.add('dragover'); }});
    dropzone.addEventListener('dragleave', () => {{ dropzone.classList.remove('dragover'); }});
    dropzone.addEventListener('drop', (e) => {{
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {{
        handleFilesSelected(e.dataTransfer.files);
      }}
    }});

    function handleFilesSelected(files) {{
      if (!files || files.length === 0) return;
      
      for (let i = 0; i < files.length; i++) {{
        // Avoid duplicate files by name and size
        const f = files[i];
        if (!selectedFiles.some(item => item.name === f.name && item.size === f.size)) {{
          selectedFiles.push(f);
        }}
      }}
      renderFilesList();
    }}

    function removeFile(index) {{
      selectedFiles.splice(index, 1);
      renderFilesList();
    }}

    function renderFilesList() {{
      const container = document.getElementById('filesListContainer');
      const addMoreBtn = document.getElementById('addMoreBtn');
      
      if (selectedFiles.length === 0) {{
        container.style.display = 'none';
        addMoreBtn.style.display = 'none';
        dropzone.style.display = 'block';
        return;
      }}

      container.innerHTML = '';
      selectedFiles.forEach((file, idx) => {{
        const item = document.createElement('div');
        item.className = 'file-item';
        
        const sizeKb = (file.size / 1024).toFixed(1);
        item.innerHTML = `
          <div class="file-item-name">
            <span>📄</span>
            <span>${{file.name}} <small style="color: #64748B;">(${{sizeKb}} KB)</small></span>
          </div>
          <button type="button" class="file-remove-btn" onclick="removeFile(${{idx}})">✖</button>
        `;
        container.appendChild(item);
      }});

      container.style.display = 'flex';
      addMoreBtn.style.display = 'inline-flex';
      dropzone.style.display = 'none';
    }}

    // Date Auto-Fill Logic
    function formatDate(d) {{
      const day = String(d.getDate()).padStart(2, '0');
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const year = d.getFullYear();
      return `${{day}}.${{month}}.${{year}}`;
    }}

    function setDatePreset(type) {{
      const today = new Date();
      let startD = new Date();
      let endD = new Date();

      if (type === 'today_14') {{
        // Today to today + 14 days
        endD.setDate(today.getDate() + 14);
      }} else if (type === 'worker_3d') {{
        // Worker profession: end date must be <= 3 days ago (e.g. 2 days ago)
        endD.setDate(today.getDate() - 2);
        startD.setDate(endD.getDate() - 21); // 3 weeks
      }} else if (type === 'pk_15d') {{
        // PK / DPP: end date <= 30 days ago (e.g. 15 days ago)
        endD.setDate(today.getDate() - 15);
        startD.setDate(endD.getDate() - 10);
      }} else if (type === 'ot_5d') {{
        // OHS: sequential, e.g. current 5 days
        endD.setDate(today.getDate() + 5);
      }}
      document.getElementById('overrideDates').value = `${{formatDate(startD)}} - ${{formatDate(endD)}}`;
    }}

    function handleCategoryChange(cat) {{
      if (cat === 'Рабочие профессии') {{
        setDatePreset('worker_3d');
      }} else if (cat === 'ПК / ДПП') {{
        setDatePreset('pk_15d');
      }} else if (cat === 'ОТ (Охрана труда)') {{
        setDatePreset('ot_5d');
      }} else if (cat === 'Высота и ОЗП') {{
        const today = new Date();
        const endD = new Date();
        endD.setDate(today.getDate() + 3);
        document.getElementById('overrideDates').value = `${{formatDate(today)}} - ${{formatDate(endD)}}`;
      }}
    }}

    function autoFillDatesForCategory() {{
      const cat = document.getElementById('overrideCategory').value;
      if (cat) {{
        handleCategoryChange(cat);
      }} else {{
        setDatePreset('today_14');
      }}
    }}

    function clearManualParams() {{
      document.getElementById('overrideCategory').value = '';
      document.getElementById('overrideProgram').value = '';
      document.getElementById('overrideDates').value = '';
      document.getElementById('overridePosition').value = '';
      document.getElementById('docDiploma').checked = false;
      document.getElementById('docPhoto').checked = false;
      document.getElementById('docCertificate').checked = false;
      document.querySelectorAll('input[name="progChip"]').forEach(c => c.checked = false);
    }}

    function updateSelectedPrograms() {{
      const checked = Array.from(document.querySelectorAll('input[name="progChip"]:checked')).map(c => c.value);
      document.getElementById('overrideProgram').value = checked.join('; ');
    }}

    // Auto-formatting mask for study dates input: DD.MM.YYYY - DD.MM.YYYY
    const datesInput = document.getElementById('overrideDates');
    datesInput.addEventListener('input', function(e) {{
      if (e.inputType === 'deleteContentBackward' || e.inputType === 'deleteContentForward') {{
        return;
      }}
      
      let val = this.value;
      let digits = val.replace(/[^0-9]/g, '').slice(0, 16);
      if (!digits.length) return;
      
      if (val.endsWith('.') && (digits.length === 1 || digits.length === 3 || digits.length === 9 || digits.length === 11)) {{
        if (digits.length === 1) digits = '0' + digits;
        else if (digits.length === 3) digits = digits.slice(0, 2) + '0' + digits.slice(2);
        else if (digits.length === 9) digits = digits.slice(0, 8) + '0' + digits.slice(8);
        else if (digits.length === 11) digits = digits.slice(0, 10) + '0' + digits.slice(10);
      }}
      
      let formatted = '';
      if (digits.length <= 2) {{
        formatted = digits;
        if (digits.length === 2) formatted += '.';
      }} else if (digits.length <= 4) {{
        formatted = digits.slice(0, 2) + '.' + digits.slice(2);
        if (digits.length === 4) formatted += '.';
      }} else if (digits.length <= 8) {{
        formatted = digits.slice(0, 2) + '.' + digits.slice(2, 4) + '.' + digits.slice(4);
        if (digits.length === 8) formatted += ' - ';
      }} else if (digits.length <= 10) {{
        formatted = digits.slice(0, 2) + '.' + digits.slice(2, 4) + '.' + digits.slice(4, 8) + ' - ' + digits.slice(8);
        if (digits.length === 10) formatted += '.';
      }} else if (digits.length <= 12) {{
        formatted = digits.slice(0, 2) + '.' + digits.slice(2, 4) + '.' + digits.slice(4, 8) + ' - ' + digits.slice(8, 10) + '.' + digits.slice(10);
        if (digits.length === 12) formatted += '.';
      }} else {{
        formatted = digits.slice(0, 2) + '.' + digits.slice(2, 4) + '.' + digits.slice(4, 8) + ' - ' + digits.slice(8, 10) + '.' + digits.slice(10, 12) + '.' + digits.slice(12, 16);
      }}
      
      this.value = formatted;
    }});

    async function handleFormSubmit(e) {{
      e.preventDefault();
      
      const rawText = document.getElementById('rawTextInput').value.trim();
      
      if (selectedFiles.length === 0 && !rawText) {{
        alert('Пожалуйста, добавьте файл(ы) заявки (СНИЛС, паспорт, docx, xlsx) или введите текст сообщения.');
        return;
      }}

      // UI state
      document.getElementById('btnSpinner').style.display = 'inline-block';
      document.getElementById('btnText').textContent = 'Обработка данных...';
      document.getElementById('submitBtn').disabled = true;

      const formData = new FormData();
      if (selectedFiles.length > 0) {{
        selectedFiles.forEach(file => {{
          formData.append('files', file);
        }});
      }}
      if (rawText) {{
        formData.append('raw_text', rawText);
      }}

      // Manual overrides
      formData.append('category', document.getElementById('overrideCategory').value);
      formData.append('program', document.getElementById('overrideProgram').value);
      formData.append('study_dates', document.getElementById('overrideDates').value);
      formData.append('position', document.getElementById('overridePosition').value);
      formData.append('has_diploma', document.getElementById('docDiploma').checked);
      formData.append('has_photo', document.getElementById('docPhoto').checked);
      formData.append('has_certificate', document.getElementById('docCertificate').checked);

      try {{
        const response = await fetch('/api/process', {{
          method: 'POST',
          body: formData
        }});

        const data = await response.json();
        renderResults(data);
      }} catch (err) {{
        alert('Ошибка при обработке заявки: ' + err.message);
      }} finally {{
        document.getElementById('btnSpinner').style.display = 'none';
        document.getElementById('btnText').textContent = '⚡ Обработать заявку и сформировать файл 1С';
        document.getElementById('submitBtn').disabled = false;
      }}
    }}

    function renderResults(data) {{
      if (!data.success) {{
        alert('Ошибка: ' + (data.error || 'Не удалось обработать заявку'));
        return;
      }}

      document.getElementById('initialPlaceholder').style.display = 'none';
      document.getElementById('resultsContent').style.display = 'block';
      document.getElementById('previewCard').style.display = 'block';

      document.getElementById('statStudents').textContent = data.unique_students;
      document.getElementById('statPrograms').textContent = data.programs_count;
      document.getElementById('statRows').textContent = data.total_enrollments;
      document.getElementById('statYellow').textContent = data.audit.warnings_count;

      const badge = document.getElementById('statusBadge');
      badge.style.display = 'inline-block';
      if (data.audit.rule_violations.length > 0) {{
        badge.className = 'audit-badge badge-error';
        badge.textContent = 'Обнаружены нарушения регламента';
      }} else if (data.audit.warnings_count > 0 || data.audit.document_issues.length > 0) {{
        badge.className = 'audit-badge badge-warning';
        badge.textContent = 'Требуется проверка менеджера';
      }} else {{
        badge.className = 'audit-badge';
        badge.style.backgroundColor = '#DCFCE7';
        badge.style.color = '#15803D';
        badge.textContent = 'Заявка выверена 100%';
      }}

      // 1. Violations
      const secViolations = document.getElementById('secViolations');
      const listViolations = document.getElementById('listViolations');
      listViolations.innerHTML = '';
      if (data.audit.rule_violations.length > 0) {{
        secViolations.style.display = 'block';
        document.getElementById('badgeViolations').textContent = data.audit.rule_violations.length;
        data.audit.rule_violations.forEach(v => {{
          const item = document.createElement('div');
          item.className = 'audit-item audit-item-error';
          item.innerHTML = `<span>❌</span><div><strong>${{v.student}}:</strong> ${{v.message}}</div>`;
          listViolations.appendChild(item);
        }});
      }} else {{
        secViolations.style.display = 'none';
      }}

      // 2. Document package issues
      const secDocs = document.getElementById('secDocs');
      const listDocs = document.getElementById('listDocs');
      listDocs.innerHTML = '';
      if (data.audit.document_issues.length > 0) {{
        secDocs.style.display = 'block';
        document.getElementById('badgeDocs').textContent = data.audit.document_issues.length;
        data.audit.document_issues.forEach(d => {{
          const item = document.createElement('div');
          item.className = 'audit-item audit-item-doc';
          item.innerHTML = `<span>📑</span><div><strong>${{d.student}} (${{d.category}}):</strong> ${{d.message}}</div>`;
          listDocs.appendChild(item);
        }});
      }} else {{
        secDocs.style.display = 'none';
      }}

      // 3. Yellow flags
      const secYellow = document.getElementById('secYellow');
      const listYellow = document.getElementById('listYellow');
      listYellow.innerHTML = '';
      if (data.audit.warnings.length > 0) {{
        secYellow.style.display = 'block';
        document.getElementById('badgeYellow').textContent = data.audit.warnings.length;
        data.audit.warnings.forEach(w => {{
          const item = document.createElement('div');
          item.className = 'audit-item audit-item-warning';
          const title = w.student ? w.student : w.program;
          item.innerHTML = `<span>⚠️</span><div><strong>${{title}} (${{w.field || 'программа'}}):</strong> ${{w.reason}}</div>`;
          listYellow.appendChild(item);
        }});
      }} else {{
        secYellow.style.display = 'none';
      }}

      // Download button
      const downloadBtn = document.getElementById('downloadBtn');
      downloadBtn.href = '/api/download/' + encodeURIComponent(data.output_filename);

      // Render 1C Preview Table
      render1CTable(data);
    }}

    function render1CTable(data) {{
      const container = document.getElementById('tablePreviewContainer');
      let html = '<table class="preview-1c">';
      
      // Title Row
      html += `<tr><td colspan="9" class="row-title-1c">${{data.application_title || 'ЗАЯВКА НА ОБУЧЕНИЕ'}}</td></tr>`;
      
      // Header Row
      html += `<tr>
        <th style="width: 5%;">№ п/п</th>
        <th style="width: 22%;">ФИО<br>(в именит. падеже)</th>
        <th style="width: 23%;">ФИО<br>(в дат. падеже)</th>
        <th style="width: 18%;">Должность</th>
        <th style="width: 5%;">Пол</th>
        <th style="width: 9%;">Дата рождения</th>
        <th style="width: 10%;">СНИЛС</th>
        <th style="width: 13%;">Сроки обучения</th>
        <th style="width: 15%;">Контакты</th>
      </tr>`;

      // Program blocks (TURQUOISE / БИРЮЗОВЫЙ)
      for (const [progName, progInfo] of Object.entries(data.grouped_data)) {{
        const isYellowProg = (!progInfo.is_canonical || progInfo.warning);
        html += `<tr><td colspan="9" class="row-prog-1c ${{isYellowProg ? 'yellow-prog' : ''}}">${{progName}}</td></tr>`;
        
        progInfo.students.forEach((s, idx) => {{
          const flags = s.yellow_flags || {{}};
          
          html += `<tr>
            <td style="text-align: right;">${{idx + 1}}</td>
            <td class="${{flags.nom_fio ? 'cell-yellow' : ''}}" data-tooltip="${{flags.nom_fio || ''}}">${{s.fio_nom || ''}}</td>
            <td class="${{flags.dat_fio ? 'cell-yellow' : ''}}" data-tooltip="${{flags.dat_fio || ''}}">${{s.fio_dat || ''}}</td>
            <td class="${{flags.position ? 'cell-yellow' : ''}}" data-tooltip="${{flags.position || ''}}">${{s.position || ''}}</td>
            <td style="text-align: center;" class="${{flags.gender ? 'cell-yellow' : ''}}">${{s.gender || ''}}</td>
            <td class="${{flags.birth_date ? 'cell-yellow' : ''}}" data-tooltip="${{flags.birth_date || ''}}">${{s.birth_date || ''}}</td>
            <td class="${{flags.snils ? 'cell-yellow' : ''}}" data-tooltip="${{flags.snils || ''}}">${{s.snils || ''}}</td>
            <td class="${{flags.study_dates ? 'cell-yellow' : ''}}" data-tooltip="${{flags.study_dates || ''}}">${{s.study_dates || ''}}</td>
            <td class="${{flags.contacts ? 'cell-yellow' : ''}}" data-tooltip="${{flags.contacts || ''}}">${{s.contacts || ''}}</td>
          </tr>`;
        }});
      }}

      html += '</table>';
      container.innerHTML = html;
    }}
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=HTML_TEMPLATE)

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
    has_certificate: Optional[bool] = Form(False)
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

        result = psg_agent.process_application(
            input_file=saved_file_paths if saved_file_paths else None,
            raw_text=raw_text if raw_text else None,
            output_file=None,
            manual_overrides=manual_overrides
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
