from flask import Flask, jsonify
import threading
import os
import time
import logging
from instagram_monitor import InstagramMonitor
from database import db_manager

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Status globalny
app_status = {
    "started_at": time.time(),
    "monitoring": False,
    "last_ping": None,
    "monitor_instance": None
}

def run_instagram_monitor():
    """Uruchamia monitoring Instagram z bazą danych"""
    global app_status
    
    instagram_username = os.getenv('INSTAGRAM_USERNAME')
    discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    refresh_interval = int(os.getenv('REFRESH_INTERVAL', '3600'))
    message_content = os.getenv('MESSAGE_CONTENT', '')
    
    if not instagram_username or not discord_webhook_url:
        logging.error("Błąd: Brak wymaganych zmiennych środowiskowych")
        return
    
    # Stwórz instancję monitora
    monitor = InstagramMonitor(
        username=instagram_username,
        webhook_url=discord_webhook_url,
        refresh_interval=refresh_interval,
        message_content=message_content
    )
    
    app_status["monitor_instance"] = monitor
    app_status["monitoring"] = True
    
    try:
        monitor.run_with_database_tracking()
    except Exception as e:
        logging.error(f"Błąd monitoring: {e}")
    finally:
        app_status["monitoring"] = False

@app.route('/')
def home():
    instagram_username = os.getenv('INSTAGRAM_USERNAME', 'not_set')
    stats = db_manager.get_stats(instagram_username) if instagram_username != 'not_set' else {}
    
    return jsonify({
        "service": "InstaWebhooks with PostgreSQL",
        "status": "running",
        "uptime_seconds": int(time.time() - app_status["started_at"]),
        "monitoring": app_status["monitoring"],
        "instagram_user": instagram_username,
        "database_connected": db_manager.engine is not None,
        "stats": stats,
        "message_format": "Custom format with newlines"
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

@app.route('/stats')
def stats():
    """Endpoint ze statystykami z bazy danych"""
    instagram_username = os.getenv('INSTAGRAM_USERNAME', 'not_set')
    if instagram_username == 'not_set':
        return jsonify({"error": "Instagram username not configured"}), 400
    
    stats = db_manager.get_stats(instagram_username)
    return jsonify({
        "username": instagram_username,
        "database_connected": db_manager.engine is not None,
        "stats": stats,
        "monitoring": app_status["monitoring"]
    })

@app.route('/posts')
def recent_posts():
    """Endpoint z ostatnimi postami z bazy"""
    instagram_username = os.getenv('INSTAGRAM_USERNAME', 'not_set')
    if instagram_username == 'not_set' or not db_manager.SessionLocal:
        return jsonify({"error": "Database not available"}), 400
    
    session = db_manager.get_session()
    try:
        from database import InstagramPost
        posts = session.query(InstagramPost).filter_by(
            username=instagram_username
        ).order_by(InstagramPost.created_at.desc()).limit(10).all()
        
        posts_data = []
        for post in posts:
            posts_data.append({
                "shortcode": post.post_shortcode,
                "url": post.post_url,
                "caption": post.post_caption[:100] + "..." if post.post_caption and len(post.post_caption) > 100 else post.post_caption,
                "sent_to_discord": post.sent_to_discord,
                "sent_at": post.sent_at.isoformat() if post.sent_at else None,
                "created_at": post.created_at.isoformat() if post.created_at else None
            })
        
        return jsonify({
            "username": instagram_username,
            "posts": posts_data,
            "total_posts": len(posts_data)
        })
        
    except Exception as e:
        logging.error(f"Błąd pobierania postów: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        session.close()

@app.route('/stop')
def stop_monitoring():
    """Zatrzymuje monitoring (dla debugowania)"""
    global app_status
    
    if app_status["monitor_instance"]:
        app_status["monitor_instance"].stop()
        app_status["monitoring"] = False
        return jsonify({"message": "Monitoring stopped"})
    else:
        return jsonify({"message": "No monitoring instance found"})

if __name__ == '__main__':
    # Uruchom monitoring w osobnym wątku
    monitor_thread = threading.Thread(target=run_instagram_monitor, daemon=True)
    monitor_thread.start()
    
    # Uruchom serwer Flask
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)