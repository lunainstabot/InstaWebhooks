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
        logging.info(f"Ostatni post w bazie: {last_shortcode}")
        
        if not last_shortcode:
            cmd.extend(['-p', '1'])
            logging.info("Dodano -p 1 (catchup)")
        
        # Ustaw custom message content
        message_template = os.getenv('MESSAGE_CONTENT', '')
        
        # Usuń "MESSAGE_CONTENT:" jeśli jest na początku
        if message_template.startswith('MESSAGE_CONTENT:'):
            message_template = message_template.replace('MESSAGE_CONTENT:', '').strip()
        
        if not message_template:
            message_template = "{owner_name} dodała nowy post na Instagramie\\n{post_url}\\n@everyone"
        
        # Zamień \n na prawdziwe nowe linie
        message_template = message_template.replace('\\n', '\n')
        
        logging.info(f"Message template: {repr(message_template)}")
        cmd.extend(['-c', message_template])
        
        # Dodaj logowanie jeśli są dane
        instagram_login = os.getenv('INSTAGRAM_LOGIN')
        instagram_password = os.getenv('INSTAGRAM_PASSWORD')
        
        if instagram_login and instagram_password:
            cmd.extend(['-l', instagram_login, instagram_password])
            logging.info("Dodano dane logowania Instagram")
        
        logging.info(f"Pełna komenda: {cmd}")
        self.is_running = True
        
        try:
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,  # Oddzielny stderr
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            logging.info(f"Proces uruchomiony, PID: {process.pid}")
            
            # Czytaj stdout i stderr
            import select
            import sys
            
            line_count = 0
            max_lines = 1000  # Zabezpieczenie przed nieskończoną pętlą
            
            while self.is_running and process.poll() is None and line_count < max_lines:
                # Sprawdź czy są dane do odczytu
                ready, _, _ = select.select([process.stdout, process.stderr], [], [], 1.0)
                
                if process.stdout in ready:
                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
                        logging.info(f"InstaWebhooks STDOUT: {line}")
                        line_count += 1
                        
                        # Sprawdź czy wysłano post
                        if "Sending post" in line or "sent to Discord" in line:
                            post_info = self.extract_post_info_from_log(line)
                            if post_info:
                                if not db_manager.is_post_sent(post_info['shortcode']):
                                    db_manager.save_post(post_info)
                                    db_manager.update_monitoring_status(
                                        self.username, 
                                        post_info['shortcode']
                                    )
                                    logging.info(f"Zapisano nowy post {post_info['shortcode']} do bazy")
                        
                        # Aktualizuj status monitorowania
                        if "Checking for new posts" in line:
                            db_manager.update_monitoring_status(self.username)
                
                if process.stderr in ready:
                    error_line = process.stderr.readline()
                    if error_line:
                        error_line = error_line.strip()
                        logging.error(f"InstaWebhooks STDERR: {error_line}")
                        line_count += 1
                
                # Sprawdź czy proces się zakończył
                if process.poll() is not None:
                    logging.info(f"Proces zakończony z kodem: {process.returncode}")
                    break
                
                time.sleep(0.1)
            
            # Przeczytaj pozostałe linie
            remaining_stdout, remaining_stderr = process.communicate(timeout=5)
            
            if remaining_stdout:
                logging.info(f"Pozostały STDOUT: {remaining_stdout}")
            if remaining_stderr:
                logging.error(f"Pozostały STDERR: {remaining_stderr}")
            
            logging.info(f"Proces zakończony. Return code: {process.returncode}")
            
        except Exception as e:
            logging.error(f"Błąd podczas monitorowania: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
        finally:
            self.is_running = False
            if 'process' in locals() and process.poll() is None:
                logging.info("Kończę proces...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logging.warning("Proces nie zakończył się, wymuszam...")
                    process.kill()
    
    def stop(self):
        """Zatrzymuje monitoring"""
        self.is_running = False
        logging.info("Otrzymano sygnał stop")