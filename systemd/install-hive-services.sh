#!/bin/bash
# Install groq-proxy and groq-tunnel as systemd services on the hive dev server.
# Run as root: sudo bash systemd/install-hive-services.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEEBOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Installing BEEBOT hive services ==="

# Verify SSH key exists for hive user
if [ ! -f /home/hive/.ssh/id_rsa ] && [ ! -f /home/hive/.ssh/id_ed25519 ]; then
    echo ""
    echo "ERROR: No SSH key found for hive user."
    echo "Generate one and copy to VPS:"
    echo "  sudo -u hive ssh-keygen -t ed25519 -C 'beebot-hive'"
    echo "  sudo -u hive ssh-copy-id root@185.233.200.13"
    echo ""
    exit 1
fi

# Verify venv exists
if [ ! -f "$BEEBOT_DIR/.venv/bin/python" ]; then
    echo "ERROR: Python venv not found at $BEEBOT_DIR/.venv"
    echo "Run: cd $BEEBOT_DIR && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Install services
echo "Copying service files to /etc/systemd/system/..."
cp "$SCRIPT_DIR/groq-proxy.service" /etc/systemd/system/
cp "$SCRIPT_DIR/groq-tunnel.service" /etc/systemd/system/

# Reload and enable
systemctl daemon-reload
systemctl enable groq-proxy groq-tunnel
systemctl restart groq-proxy groq-tunnel

echo ""
echo "=== Done ==="
systemctl status groq-proxy --no-pager -l
echo "---"
systemctl status groq-tunnel --no-pager -l
echo ""
echo "Useful commands:"
echo "  journalctl -u groq-proxy -f    # proxy logs"
echo "  journalctl -u groq-tunnel -f   # tunnel logs"
echo "  systemctl restart groq-tunnel  # restart after VPS reboot"
