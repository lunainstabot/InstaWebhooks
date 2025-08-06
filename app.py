from flask import Flask, jsonify
import threading
import subprocess
import os
import time
import logging
import traceback

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Status globalny
app_status = {
    "started_at": time.time(),
    "monitoring": False,
    "last_ping": None,
    "monitor_instance": None,
    "last_error": None
}

def run_instagram_monitor():
    """Uruchamia monitoring Instagram z debugowaniem"""
    global app_status
    
    logging.info("=== ROZPOCZYNAM MONITORING ===")
    
    try:
        # Sprawdź zmienne środowiskowe
        instagram_username = os.getenv('INSTAGRAM_USERNAME')
        discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        refresh_interval = os.getenv('REFRESH_INTERVAL', '3600')
        message_content = os.getenv('MESSAGE_CONTENT', '')
        
        logging.info(f"Instagram username: {instagram_username}")
        logging.info(f"Discord webhook: {'SET' if discord_webhook_url else 'NOT_SET'}")
        logging.info(f"Refresh interval: {refresh_interval}")
        logging.info(f"Message content: {message_content[:50]}..." if message_content else "Message content: NOT_SET")
        
        if not instagram_username:
            logging.error("BŁĄD: Brak INSTAGRAM_USERNAME")
            app_status["last_error"] = "Missing INSTAGRAM_USERNAME"
            return
            
        if not discord_webhook_url:
            logging.error("BŁĄD: Brak DISCORD_WEBHOOK_URL")
            app_status["last_error"] = "Missing DISCORD_WEBHOOK_URL"
            return
        
        # Sprawdź czy pliki istnieją
        logging.info("Sprawdzam pliki...")
        files_status = {}
        for file in ['instagram_monitor.py', 'database.py']:
            exists = os.path.exists(file)
            files_status[file] = exists
            logging.info(f"{file}: {'EXISTS' if exists else 'MISSING'}")
        
        # Jeśli brakuje plików, użyj prostej wersji
        if not all(files_status.values()):
            logging.warning("Brakuje plików - używam prostej wersji")
            run_simple_monitor(instagram_username, discord_webhook_url, refresh_interval, message_content)
            return
        
        # Spróbuj zaimportować moduły
        logging.info("Importuję moduły...")
        try:
            from instagram_monitor import InstagramMonitor
            from database import db_manager
            logging.info("Moduły zaimportowane pomyślnie")
        except ImportError as e:
            logging.error(f"Błąd importu: {e}")
            logging.warning("Używam prostej wersji bez bazy danych")
            run_simple_monitor(instagram_username, discord_webhook_url, refresh_interval, message_content)
            return
        
        # Sprawdź połączenie z bazą
        logging.info(f"Baza danych połączona: {db_manager.engine is not None}")
        
        # Stwórz instancję monitora
        logging.info("Tworzę instancję monitora...")
        monitor = InstagramMonitor(
            username=instagram_username,
            webhook_url=discord_webhook_url,
            refresh_interval=int(refresh_interval),
            message_content=message_content
        )
        
        app_status["monitor_instance"] = monitor
        app_status["monitoring"] = True
        app_status["last_error"] = None
        
        logging.info("Uruchamiam monitoring z bazą danych...")
        monitor.run_with_database_tracking()
        
    except Exception as e:
        error_msg = f"BŁĄD MONITORING: {e}"
        logging.error(error_msg)
        logging.error(f"Traceback: {traceback.format_exc()}")
        app_status["last_error"] = str(e)
        
        # Fallback do prostej wersji
        logging.info("Próbuję prostą wersję jako fallback...")
        try:
            instagram_username = os.getenv('INSTAGRAM_USERNAME')
            discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
            refresh_interval = os.getenv('REFRESH_INTERVAL', '3600')
            message_content = os.getenv('MESSAGE_CONTENT', '')
            
            if instagram_username and discord_webhook_url:
                run_simple_monitor(instagram_username, discord_webhook_url, refresh_interval, message_content)
        except Exception as fallback_error:
            logging.error(f"Fallback też nie działa: {fallback_error}")
            app_status["last_error"] = f"Main: {e}, Fallback: {fallback_error}"
    finally:
        app_status["monitoring"] = False
        logging.info("Monitoring zakończony")

def run_simple_monitor(instagram_username, discord_webhook_url, refresh_interval, message_content):
    """Prosta wersja monitoringu bez bazy danych"""
    logging.info("=== URUCHAMIAM PROSTĄ WERSJĘ ===")
    
    # Przygotuj format wiadomości
    if not message_content:
        message_content = "{owner_name} dodała nowy post na Instagramie\\n{post_url}\\n@everyone"
    
    # Zamień \n na prawdziwe nowe linie
    message_content = message_content.replace('\\n', '\n')
    
    cmd = [
        'python', '-m', 'instawebhooks',
        instagram_username,
        discord_webhook_url,
        '-i', refresh_interval,
        '-p', '1',  # Wyślij 1 ostatni post do testu
        '-c', message_content,
        '-v'
    ]
    
    logging.info(f"Uruchamiam komendę: {' '.join(cmd)}")
    app_status["monitoring"] = True
    
    try:
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        logging.info("Proces uruchomiony, czytam output...")
        
        while app_status["monitoring"] and process.poll() is None:
            line = process.stdout.readline()
            if line:
                line = line.strip()
                logging.info(f"InstaWebhooks: {line}")
            time.sleep(0.1)
                
    except Exception as e:
        logging.error(f"Błąd prostego monitoringu: {e}")
        app_status["last_error"] = f"Simple monitor: {e}"

@app.route('/')
def home():
    instagram_username = os.getenv('INSTAGRAM_USERNAME', 'not_set')
    
    # Sprawdź czy moduły istnieją
    modules_status = {}
    try:
        from database import db_manager
        modules_status["database"] = True
        modules_status["db_connected"] = db_manager.engine is not None
        stats = db_manager.get_stats(instagram_username) if instagram_username != 'not_set' else {}
    except:
        modules_status["database"] = False
        modules_status["db_connected"] = False
        stats = {}
    
    try:
        from instagram_monitor import InstagramMonitor
        modules_status["instagram_monitor"] = True
    except:
        modules_status["instagram_monitor"] = False
    
    return jsonify({
        "service": "InstaWebhooks with Debug",
        "status": "running",
        "uptime_seconds": int(time.time() - app_status["started_at"]),
        "monitoring": app_status["monitoring"],
        "instagram_user": instagram_username,
        "modules_status": modules_status,
        "stats": stats,
        "last_error": app_status["last_error"],
        "files_exist": {
            "instagram_monitor.py": os.path.exists("instagram_monitor.py"),
            "database.py": os.path.exists("database.py"),
            "app.py": os.path.exists("app.py")
        }
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

@app.route('/debug')
def debug():
    """Szczegółowe informacje debug"""
    return jsonify({
        "env_vars": {
            "INSTAGRAM_USERNAME": os.getenv('INSTAGRAM_USERNAME', 'NOT_SET'),
            "DISCORD_WEBHOOK_URL": "SET" if os.getenv('DISCORD_WEBHOOK_URL') else "NOT_SET",
            "DATABASE_URL": "SET" if os.getenv('DATABASE_URL') else "NOT_SET",
            "REFRESH_INTERVAL": os.getenv('REFRESH_INTERVAL', 'NOT_SET'),
            "MESSAGE_CONTENT": os.getenv('MESSAGE_CONTENT', 'NOT_SET')[:100] + "..." if os.getenv('MESSAGE_CONTENT') else "NOT_SET"
        },
        "app_status": app_status,
        "current_dir": os.getcwd(),
        "files_in_dir": os.listdir('.'),
        "python_path": os.environ.get('PYTHONPATH', 'NOT_SET')
    })

@app.route('/logs')
def recent_logs():
    """Ostatnie logi (jeśli dostępne)"""
    return jsonify({
        "message": "Check Render logs panel for detailed logs",
        "monitoring": app_status["monitoring"],
        "last_error": app_status["last_error"]
    })

@app.route('/test-webhook')
def test_webhook():
    """Test webhook Discord"""
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        return jsonify({"error": "No webhook URL configured"}), 400
    
    try:
        import requests
        import json
        
        payload = {
            "content": "🧪 Test webhook z InstaWebhooks - " + str(int(time.time()))
        }
        
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'}
        )
        
        return jsonify({
            "status": "success" if response.status_code == 204 else "error",
            "status_code": response.status_code,
            "response": response.text
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
    monitor_thread = threading.Thread(target=run_instagram_monitor, daemon=True)
    monitor_thread.start()
    
    return jsonify({"message": "Monitoring restarted"})

if __name__ == '__main__':
    logging.info("=== URUCHAMIAM APLIKACJĘ ===")
    
    # Sprawdź zmienne środowiskowe przy starcie
    required_vars = ['INSTAGRAM_USERNAME', 'DISCORD_WEBHOOK_URL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logging.error(f"Brakuje zmiennych środowiskowych: {missing_vars}")
    else:
        logging.info("Wszystkie wymagane zmienne środowiskowe są ustawione")
    
    # Uruchom monitoring w osobnym wątku
    monitor_thread = threading.Thread(target=run_instagram_monitor, daemon=True)
    monitor_thread.start()
    
    # Uruchom serwer Flask
    port = int(os.environ.get('PORT', 10000))
    logging.info(f"Uruchamiam Flask na porcie {port}")
    app.run(host='0.0.0.0', port=port, debug=False)