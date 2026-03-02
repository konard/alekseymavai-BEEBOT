#!/bin/bash
# BEEBOT deployment script for VPS
# Usage: ssh root@YOUR_VPS 'bash -s' < deploy.sh

set -e

APP_DIR="/opt/beebot"
REPO_URL="https://github.com/alekseymavai/BEEBOT.git"

echo "=== BEEBOT Deployment ==="

# 1. System packages
echo "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git

# 2. Create app user (if doesn't exist)
id -u beebot &>/dev/null || useradd -r -m -s /bin/bash beebot

# 3. Clone or update repo
if [ -d "$APP_DIR" ]; then
    echo "Updating existing installation..."
    cd "$APP_DIR"
    git pull
else
    echo "Fresh install..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 4. Python virtual environment
echo "Setting up Python environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 5. Download embedding model
echo "Downloading embedding model..."
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# 6. Setup .env
if [ ! -f .env ]; then
    echo "Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "!!! IMPORTANT: Edit /opt/beebot/.env with your actual tokens !!!"
    echo "  nano /opt/beebot/.env"
    echo ""
fi

# 7. Build knowledge base (if not present)
if [ ! -f data/processed/index.faiss ]; then
    echo "Building knowledge base..."
    mkdir -p data/processed data/subtitles data/texts
    python3 -m src.build_kb
fi

# 8. Set permissions
chown -R beebot:beebot "$APP_DIR"

# 9. Install systemd service
echo "Installing systemd service..."
cp beebot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable beebot
systemctl restart beebot

echo ""
echo "=== Deployment complete ==="
echo "Check status: systemctl status beebot"
echo "View logs:    journalctl -u beebot -f"
