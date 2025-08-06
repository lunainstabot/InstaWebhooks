from flask import Flask, jsonify
import threading
import subprocess
import os
import time
import logging
import traceback
import requests
import json

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Status globalny
app_status = {
    "started_at": time.time(),
    "monitoring": False,
    "last_ping": None,
    "monitor_instance": None,
    "last_error": None,
    "process_pid": None
}

def run_simple_instagram_monitor():
    """Prosta wersja monitoringu bez skomplikowanych modułów"""
    global app_status
    
    logging.info("=== URUCHAMIAM PROSTY MONITORING ===")
    
    try:
        # Sprawdź zmienne środowiskowe
        instagram_username = os.getenv('INSTAGRAM_USERNAME')
        discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        refresh_interval = os.getenv('REFRESH_INTERVAL', '300')  # 5 minut domyślnie
        message_content = os.getenv('MESSAGE_CONTENT', '')
        
        logging.info(f"Instagram username: {instagram_username}")
        logging.info(f"Discord webhook: {'SET' if discord_webhook_url else 'NOT_SET'}")
        logging.info(f"Refresh interval: {refresh_interval}")
        
        if not instagram_username or not discord_webhook_url:
            logging.error("Brak wymaganych zmiennych środowiskowych")
            app_status["last_error"] = "Missing required environment variables"
            return
        
        # Przygotuj format wiadomości
        if not message_content:
            message_content = "{owner_name} dodała nowy post na Instagramie\\n{post_url}\\n@everyone"
        
        # Zamień \n na prawdziwe nowe linie
        message_content = message_content.replace('\\n', '\n')
        
        # Prosta komenda bez catchup
        cmd = [
            'python', '-m', 'instawebhooks',
            instagram_username,
            discord_webhook_url,
            '-i', refresh_interval,
            '-c', message_content,
            '-v'
        ]
        
        logging.info(f"Uruchamiam komendę: {' '.join(cmd)}")
        app_status["monitoring"] = True
        app_status["last_error"] = None
        
        # Uruchom proces
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        app_status["process_pid"] = process.pid
        logging.info(f"Proces uruchomiony z PID: {process.pid}")
        
        # Czytaj output
        line_count = 0
        max_lines = 2000  # Zabezpieczenie
        
        while app_status["monitoring"] and process.poll() is None and line_count < max_lines:
            try:
                line = process.stdout.readline()
                if line:
                    line = line.strip()
                    logging.info(f"InstaWebhooks: {line}")
                    line_count += 1
                    
                    # Sprawdź czy są błędy
                    if any(error in line.lower() for error in ['error', 'failed', 'exception']):
                        logging.error(f"Błąd w InstaWebhooks: {line}")
                        app_status["last_error"] = line
                    
                    # Sprawdź czy wysłano post
                    if "sent to discord" in line.lower() or "sending post" in line.lower():
                        logging.info(f"🎉 Post wysłany: {line}")
                
                time.sleep(0.1)
                
            except Exception as e:
                logging.error(f"Błąd czytania output: {e}")
                break
        
        # Sprawdź dlaczego się skończyło
        if process.poll() is not None:
            return_code = process.returncode
            logging.info(f"Proces zakończony z kodem: {return_code}")
            
            if return_code != 0:
                app_status["last_error"] = f"Process exited with code {return_code}"
        
        if line_count >= max_lines:
            logging.warning("Osiągnięto maksymalną liczbę linii")
            
    except Exception as e:
        error_msg = f"Błąd monitoringu: {e}"
        logging.error(error_msg)
        logging.error(f"Traceback: {traceback.format_exc()}")
        app_status["last_error"] = str(e)
    finally:
        app_status["monitoring"] = False
        app_status["process_pid"] = None
        logging.info("Monitoring zakończony")

@app.route('/')
def home():
    instagram_username = os.getenv('INSTAGRAM_USERNAME', 'not_set')
    
    return jsonify({
        "service": "InstaWebhooks Simple",
        "status": "running",
        "uptime_seconds": int(time.time() - app_status["started_at"]),
        "monitoring": app_status["monitoring"],
        "instagram_user": instagram_username,
        "process_pid": app_status["process_pid"],
        "last_error": app_status["last_error"],
        "refresh_interval": os.getenv('REFRESH_INTERVAL', '300'),
        "message_content_set": bool(os.getenv('MESSAGE_CONTENT'))
    })

@app.route('/health')
def health():
    """Endpoint dla UptimeRobot"""
    app_status["last_ping"] = time.time()
    return "OK", 200

@app.route('/ping')
def ping():
    """Alternatywny endpoint dla UptimeRobot"""
    return "pong", 200

@app.route('/debug')
def debug():
    """Szczegółowe informacje debug"""
    try:
        return jsonify({
            "env_vars": {
                "INSTAGRAM_USERNAME": os.getenv('INSTAGRAM_USERNAME', 'NOT_SET'),
                "DISCORD_WEBHOOK_URL": "SET" if os.getenv('DISCORD_WEBHOOK_URL') else "NOT_SET",
                "REFRESH_INTERVAL": os.getenv('REFRESH_INTERVAL', 'NOT_SET'),
                "MESSAGE_CONTENT": "SET" if os.getenv('MESSAGE_CONTENT') else "NOT_SET"
            },
            "app_status": app_status,
            "current_dir": os.getcwd(),
            "python_version": os.sys.version
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test-webhook')
def test_webhook():
    """Test webhook Discord"""
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        return jsonify({"error": "No webhook URL configured"}), 400
    
    try:
        payload = {
            "content": f"🧪 Test webhook z InstaWebhooks - {int(time.time())}"
        }
        
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        return jsonify({
            "status": "success" if response.status_code == 204 else "error",
            "status_code": response.status_code,
            "response": response.text
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/check-instagram-user')
def check_instagram_user():
    """Sprawdź czy użytkownik Instagram istnieje"""
    try:
        instagram_username = os.getenv('INSTAGRAM_USERNAME')
        if not instagram_username:
            return jsonify({"error": "No username set"}), 400
        
        url = f"https://www.instagram.com/{instagram_username}/"
        
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        return jsonify({
            "username": instagram_username,
            "url": url,
            "status_code": response.status_code,
            "exists": response.status_code == 200,
            "private": "This Account is Private" in response.text,
            "content_length": len(response.text)
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test-instawebhooks')
def test_instawebhooks():
    """Test czy InstaWebhooks działa"""
    try:
        result = subprocess.run(
            ['python', '-m', 'instawebhooks', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        return jsonify({
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test-real-run')
def test_real_run():
    """Test rzeczywistego uruchomienia InstaWebhooks z timeoutem"""
    try:
        instagram_username = os.getenv('INSTAGRAM_USERNAME')
        discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        
        if not instagram_username or not discord_webhook_url:
            return jsonify({"error": "Missing env vars"}), 400
        
        # Bardzo prosta komenda - tylko sprawdź czy może się połączyć
        cmd = [
            'python', '-m', 'instawebhooks',
            instagram_username,
            discord_webhook_url,
            '-i', '10',  # 10 sekund
            '-v'
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20  # 20 sekund timeout
        )
        
        return jsonify({
            "command": ' '.join(cmd),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0
        })
        
    except subprocess.TimeoutExpired as e:
        return jsonify({
            "error": "Command timed out after 20 seconds",
            "stdout": e.stdout.decode() if e.stdout else "",
            "stderr": e.stderr.decode() if e.stderr else "",
            "timeout": True
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/restart-monitoring')
def restart_monitoring():
    """Restart monitoringu"""
    global app_status
    
    # Zatrzymaj obecny monitoring
    app_status["monitoring"] = False
    time.sleep(2)
    
    # Uruchom nowy wątek
    monitor_thread = threading.Thread(target=run_simple_instagram_monitor, daemon=True)
    monitor_thread.start()
    
    return jsonify({"message": "Monitoring restarted"})

@app.route('/stop-monitoring')
def stop_monitoring():
    """Zatrzymaj monitoring"""
    global app_status
    app_status["monitoring"] = False
    return jsonify({"message": "Monitoring stopped"})

@app.route('/send-test-post')
def send_test_post():
    """Wyślij testowy post na Discord"""
    try:
        webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        if not webhook_url:
            return jsonify({"error": "No webhook URL"}), 400
        
        instagram_username = os.getenv('INSTAGRAM_USERNAME', 'test_user')
        
        # Symuluj post
        message = f"{instagram_username} dodała nowy post na Instagramie\nhttps://www.instagram.com/p/TEST123/\n@everyone"
        
        payload = {
            "content": message,
            "embeds": [{
                "title": f"Test post od @{instagram_username}",
                "description": "To jest testowy post",
                "url": "https://www.instagram.com/p/TEST123/",
                "color": 0xE4405F,
                "author": {
                    "name": instagram_username,
                    "icon_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Instagram_icon.png/1024px-Instagram_icon.png"
                }
            }]
        }
        
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        return jsonify({
            "status": "success" if response.status_code == 204 else "error",
            "status_code": response.status_code,
            "message": "Test post sent"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    logging.info("=== URUCHAMIAM PROSTĄ APLIKACJĘ ===")
    
    # Sprawdź zmienne środowiskowe przy starcie
    required_vars = ['INSTAGRAM_USERNAME', 'DISCORD_WEBHOOK_URL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logging.error(f"Brakuje zmiennych środowiskowych: {missing_vars}")
    else:
        logging.info("Wszystkie wymagane zmienne środowiskowe są ustawione")
    
    # Uruchom monitoring w osobnym wątku
    monitor_thread = threading.Thread(target=run_simple_instagram_monitor, daemon=True)
    monitor_thread.start()
    
    # Uruchom serwer Flask
    port = int(os.environ.get('PORT', 10000))
    logging.info(f"Uruchamiam Flask na porcie {port}")
    app.run(host='0.0.0.0', port=port, debug=False)