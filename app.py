from flask import Flask, jsonify
import threading
import subprocess
import os
import time
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Status globalny
app_status = {
    "started_at": time.time(),
    "monitoring": False,
    "last_ping": None
}

def run_instagram_monitor():
    """Uruchamia monitoring Instagram"""
    global app_status
    
    instagram_username = os.getenv('INSTAGRAM_USERNAME')
    discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    refresh_interval = os.getenv('REFRESH_INTERVAL', '3600')
    message_content = os.getenv('MESSAGE_CONTENT', '')
    
    if not instagram_username or not discord_webhook_url:
        logging.error("Błąd: Brak wymaganych zmiennych środowiskowych")
        return
    
    cmd = [
        'python', '-m', 'instawebhooks',
        instagram_username,
        discord_webhook_url,
        '-i', refresh_interval,
        '-v'
    ]
    
    if message_content:
        cmd.extend(['-c', message_content])
    
    # Dodaj logowanie jeśli są dane
    instagram_login = os.getenv('INSTAGRAM_LOGIN')
    instagram_password = os.getenv('INSTAGRAM_PASSWORD')
    
    if instagram_login and instagram_password:
        cmd.extend(['-l', instagram_login, instagram_password])
    
    logging.info(f"Uruchamiam monitoring: {instagram_username}")
    app_status["monitoring"] = True
    
    try:
        subprocess.run(cmd)
    except Exception as e:
        logging.error(f"Błąd monitoring: {e}")
        app_status["monitoring"] = False

@app.route('/')
def home():
    return jsonify({
        "service": "InstaWebhooks",
        "status": "running",
        "uptime_seconds": int(time.time() - app_status["started_at"]),
        "monitoring": app_status["monitoring"],
        "instagram_user": os.getenv('INSTAGRAM_USERNAME', 'not_set')
    })

@app.route('/health')
def health():
    """Endpoint dla UptimeRobot - szybki i prosty"""
    app_status["last_ping"] = time.time()
    return "OK", 200

@app.route('/ping')
def ping():
    """Alternatywny endpoint dla UptimeRobot"""
    return "pong", 200

if __name__ == '__main__':
    # Uruchom monitoring w osobnym wątku
    monitor_thread = threading.Thread(target=run_instagram_monitor, daemon=True)
    monitor_thread.start()
    
    # Uruchom serwer Flask
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)