FROM python:3.11-slim

# Install system packages: Tesseract OCR (with Russian + English language packs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure upload/output directories exist
RUN mkdir -p uploads output_1c static

# Expose default port
ENV PORT=8000
EXPOSE 8000

# Start Uvicorn bound to 0.0.0.0 and dynamic PORT from Render
CMD ["sh", "-c", "uvicorn web_app:app --host 0.0.0.0 --port ${PORT}"]
