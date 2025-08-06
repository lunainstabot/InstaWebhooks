import os
import logging
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, DateTime, Integer, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

# Konfiguracja
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    # Render używa postgres://, ale SQLAlchemy potrzebuje postgresql://
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

Base = declarative_base()

class InstagramPost(Base):
    __tablename__ = 'instagram_posts'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False, index=True)
    post_shortcode = Column(String(20), nullable=False, unique=True, index=True)
    post_url = Column(String(200), nullable=False)
    owner_name = Column(String(100))
    owner_username = Column(String(50))
    post_caption = Column(Text)
    post_image_url = Column(String(500))
    posted_at = Column(DateTime(timezone=True))
    sent_to_discord = Column(Boolean, default=False)
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class MonitoringStatus(Base):
    __tablename__ = 'monitoring_status'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False, unique=True, index=True)
    last_check = Column(DateTime(timezone=True))
    last_post_shortcode = Column(String(20))
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class DatabaseManager:
    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.setup_database()
    
    def setup_database(self):
        """Inicjalizuje połączenie z bazą danych"""
        if not DATABASE_URL:
            logging.warning("Brak DATABASE_URL - używam trybu bez bazy danych")
            return
        
        try:
            self.engine = create_engine(DATABASE_URL, echo=False)
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            
            # Stwórz tabele jeśli nie istnieją
            Base.metadata.create_all(bind=self.engine)
            logging.info("Połączono z bazą danych PostgreSQL")
            
        except Exception as e:
            logging.error(f"Błąd połączenia z bazą danych: {e}")
            self.engine = None
            self.SessionLocal = None
    
    def get_session(self):
        """Zwraca sesję bazy danych"""
        if self.SessionLocal:
            return self.SessionLocal()
        return None
    
    def is_post_sent(self, shortcode):
        """Sprawdza czy post został już wysłany"""
        if not self.SessionLocal:
            return False
        
        session = self.get_session()
        try:
            post = session.query(InstagramPost).filter_by(
                post_shortcode=shortcode,
                sent_to_discord=True
            ).first()
            return post is not None
        except SQLAlchemyError as e:
            logging.error(f"Błąd sprawdzania posta: {e}")
            return False
        finally:
            session.close()
    
    def save_post(self, post_data):
        """Zapisuje informacje o poście"""
        if not self.SessionLocal:
            logging.warning("Brak połączenia z bazą - nie zapisuję posta")
            return False
        
        session = self.get_session()
        try:
            # Sprawdź czy post już istnieje
            existing_post = session.query(InstagramPost).filter_by(
                post_shortcode=post_data['shortcode']
            ).first()
            
            if existing_post:
                # Aktualizuj istniejący post
                existing_post.sent_to_discord = True
                existing_post.sent_at = datetime.now(timezone.utc)
            else:
                # Stwórz nowy post
                new_post = InstagramPost(
                    username=post_data['username'],
                    post_shortcode=post_data['shortcode'],
                    post_url=post_data['url'],
                    owner_name=post_data.get('owner_name', ''),
                    owner_username=post_data.get('owner_username', ''),
                    post_caption=post_data.get('caption', ''),
                    post_image_url=post_data.get('image_url', ''),
                    posted_at=post_data.get('posted_at'),
                    sent_to_discord=True,
                    sent_at=datetime.now(timezone.utc)
                )
                session.add(new_post)
            
            session.commit()
            logging.info(f"Zapisano post {post_data['shortcode']} do bazy")
            return True
            
        except SQLAlchemyError as e:
            logging.error(f"Błąd zapisywania posta: {e}")
            session.rollback()
            return False
        finally:
            session.close()
    
    def update_monitoring_status(self, username, last_shortcode=None):
        """Aktualizuje status monitorowania"""
        if not self.SessionLocal:
            return
        
        session = self.get_session()
        try:
            status = session.query(MonitoringStatus).filter_by(username=username).first()
            
            if status:
                status.last_check = datetime.now(timezone.utc)
                if last_shortcode:
                    status.last_post_shortcode = last_shortcode
                status.updated_at = datetime.now(timezone.utc)
            else:
                status = MonitoringStatus(
                    username=username,
                    last_check=datetime.now(timezone.utc),
                    last_post_shortcode=last_shortcode,
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(status)
            
            session.commit()
            
        except SQLAlchemyError as e:
            logging.error(f"Błąd aktualizacji statusu: {e}")
            session.rollback()
        finally:
            session.close()
    
    def get_last_post_shortcode(self, username):
        """Pobiera shortcode ostatniego posta"""
        if not self.SessionLocal:
            return None
        
        session = self.get_session()
        try:
            status = session.query(MonitoringStatus).filter_by(username=username).first()
            return status.last_post_shortcode if status else None
        except SQLAlchemyError as e:
            logging.error(f"Błąd pobierania ostatniego posta: {e}")
            return None
        finally:
            session.close()
    
    def get_stats(self, username):
        """Pobiera statystyki dla użytkownika"""
        if not self.SessionLocal:
            return {}
        
        session = self.get_session()
        try:
            total_posts = session.query(InstagramPost).filter_by(username=username).count()
            sent_posts = session.query(InstagramPost).filter_by(
                username=username, 
                sent_to_discord=True
            ).count()
            
            status = session.query(MonitoringStatus).filter_by(username=username).first()
            
            return {
                'total_posts': total_posts,
                'sent_posts': sent_posts,
                'last_check': status.last_check.isoformat() if status and status.last_check else None,
                'last_post': status.last_post_shortcode if status else None
            }
        except SQLAlchemyError as e:
            logging.error(f"Błąd pobierania statystyk: {e}")
            return {}
        finally:
            session.close()

# Globalna instancja
db_manager = DatabaseManager()