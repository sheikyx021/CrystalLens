import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Base configuration class."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///social_analysis.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Apify Configuration
    APIFY_API_TOKEN = os.environ.get('APIFY_API_TOKEN')
    
    # Ollama Configuration
    OLLAMA_API_URL = os.environ.get('OLLAMA_API_URL', 'http://localhost:11434')
    OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama2')
    
    # Security
    BCRYPT_LOG_ROUNDS = int(os.environ.get('BCRYPT_LOG_ROUNDS', 12))
    
    # Application Settings
    MAX_POSTS_PER_SCRAPE = int(os.environ.get('MAX_POSTS_PER_SCRAPE', 1000))
    ANALYSIS_TIMEOUT = int(os.environ.get('ANALYSIS_TIMEOUT', 300))
    
    # File Upload Settings
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    UPLOAD_FOLDER = 'uploads'

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///social_analysis_dev.db'

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    @staticmethod
    def init_app(app):
        """Initialize production-specific checks and settings."""
        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if not db_url or 'sqlite' in db_url:
            # Defer raising until app initialization time
            raise ValueError("Production environment requires PostgreSQL database URL")

class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
