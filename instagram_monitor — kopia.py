import subprocess
import logging
import time
import re
import os
from datetime import datetime, timezone
from database import db_manager

class InstagramMonitor:
    def __init__(self, username, webhook_url, refresh_interval=3600, message_content=""):
        self.username = username
        self.webhook_url = webhook_url
        self.refresh_interval = refresh_interval
        self.message_content = message_content
        self.is_running = False
    
    def extract_post_info_from_log(self, log_line):
        """Wyciąga informacje o poście z logów InstaWebhooks"""
        # Przykładowy log: "Sending post https://www.instagram.com/p/ABC123/ to Discord"
        url_pattern = r'https://www\.instagram\.com/p/([A-Za-z0-9_-]+)/'
        match = re.search(url_pattern, log_line)
        
        if match:
            shortcode = match.group(1)
            return {
                'username': self.username,
                'shortcode': shortcode,
                'url': f"https://www.instagram.com/p/{shortcode}/",
                'posted_at': datetime.now(timezone.utc)
            }
        return None
    
    def run_with_database_tracking(self):
        """Uruchamia InstaWebhooks z śledzeniem w bazie danych"""
        cmd = [
            'python', '-m', 'instawebhooks',
            self.username,
            self.webhook_url,
            '-i', str(self.refresh_interval),
            '-v'
        ]
        
        # Sprawdź czy mamy ostatni post w bazie
        last_shortcode = db_manager.get_last_post_shortcode(self.username)
        if not last_shortcode:
            # Pierwszy raz - pobierz tylko 1 ostatni post
            cmd.extend(['-p', '1'])
        
        # Ustaw custom message content
        message_template = os.getenv('MESSAGE_CONTENT', '')
        if not message_template:
            # Domyślny format jeśli nie ustawiono
            message_template = "{owner_name} dodała nowy post na Instagramie\\n{post_url}\\n@everyone"
        
        # Zamień \n na prawdziwe nowe linie
        message_template = message_template.replace('\\n', '\n')
        
        cmd.extend(['-c', message_template])
        
        # Dodaj logowanie jeśli są dane
        instagram_login = os.getenv('INSTAGRAM_LOGIN')
        instagram_password = os.getenv('INSTAGRAM_PASSWORD')
        
        if instagram_login and instagram_password:
            cmd.extend(['-l', instagram_login, instagram_password])
        
        logging.info(f"Uruchamiam monitoring: {' '.join(cmd)}")
        self.is_running = True
        
        try:
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            while self.is_running and process.poll() is None:
                line = process.stdout.readline()
                if line:
                    line = line.strip()
                    logging.info(f"InstaWebhooks: {line}")
                    
                    # Sprawdź czy wysłano post
                    if "Sending post" in line or "sent to Discord" in line:
                        post_info = self.extract_post_info_from_log(line)
                        if post_info:
                            # Sprawdź czy już nie wysłaliśmy tego posta
                            if not db_manager.is_post_sent(post_info['shortcode']):
                                db_manager.save_post(post_info)
                                db_manager.update_monitoring_status(
                                    self.username, 
                                    post_info['shortcode']
                                )
                                logging.info(f"Zapisano nowy post {post_info['shortcode']} do bazy")
                    
                    # Aktualizuj status monitorowania co jakiś czas
                    if "Checking for new posts" in line:
                        db_manager.update_monitoring_status(self.username)
                
                time.sleep(0.1)  # Krótka pauza żeby nie obciążać CPU
                
        except Exception as e:
            logging.error(f"Błąd podczas monitorowania: {e}")
        finally:
            self.is_running = False
            if process and process.poll() is None:
                process.terminate()
    
    def stop(self):
        """Zatrzymuje monitoring"""
        self.is_running = False