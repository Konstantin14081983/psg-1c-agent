#!/bin/bash
set -e

echo "=========================================================="
echo "🚀 Установка Агента 1С ПСГ на сервер RuVDS..."
echo "=========================================================="

# 1. Update and install packages
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng libgl1 libglib2.0-0 curl

# 2. Setup directory
APP_DIR="/opt/psg-1c-agent"
if [ -d "$APP_DIR" ]; then
    echo "📁 Обновление существующего репозитория в $APP_DIR..."
    cd "$APP_DIR"
    git pull origin main
else
    echo "📁 Клонирование репозитория в $APP_DIR..."
    git clone https://github.com/Konstantin14081983/psg-1c-agent.git "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. Create virtual environment
echo "🐍 Настройка виртуального окружения Python..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. Create systemd service for 24/7 autostart
echo "⚙️ Настройка службы автозапуска systemd..."
cat << 'SERVICE_EOF' > /etc/systemd/system/psg-agent.service
[Unit]
Description=PSG 1C Application Agent Web Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/psg-1c-agent
ExecStart=/opt/psg-1c-agent/venv/bin/uvicorn web_app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=PORT=8000

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable psg-agent
systemctl restart psg-agent

# 5. Check firewall if ufw is active
if command -v ufw >/dev/null 2>&1; then
    ufw allow 8000/tcp || true
fi

echo "=========================================================="
echo "✅ УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА!"
echo "🌐 Приложение работает 24/7 и доступно по адресу:"
echo "👉 http://$(curl -s ifconfig.me):8000"
echo "=========================================================="
