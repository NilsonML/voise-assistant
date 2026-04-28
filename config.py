# config.py
import os
import sys
from dotenv import load_dotenv


class Config:
    @staticmethod
    def get_base_dir():
        """Определяет базовую директорию (для PyInstaller)"""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.abspath(__file__))
    
    @staticmethod
    def setup_directories():
        """Создаёт необходимые директории"""
        base_dir = Config.get_base_dir()
        Config.TEMP_DIR = os.path.join(base_dir, "temp")
        Config.LOGS_DIR = os.path.join(base_dir, "logs")
        
        os.makedirs(Config.TEMP_DIR, exist_ok=True)
        os.makedirs(Config.LOGS_DIR, exist_ok=True)
    
    @staticmethod
    def load_env():
        """Загружает .env файл, создаёт если нет"""
        env_path = os.path.join(Config.get_base_dir(), '.env')
        
        if not os.path.exists(env_path):
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write("""# OpenRouter API ключ (получить на https://openrouter.ai/keys)
OPENROUTER_API_KEY=

# Модель OpenRouter (пример: microsoft/phi-3-mini-128k-instruct:free)
OPENROUTER_MODEL=

# Голос для озвучки
EDGE_TTS_VOICE=ru-RU-SvetlanaNeural
EDGE_TTS_RATE=+0%
""")
            print("📄 Создан файл .env. Заполните OPENROUTER_API_KEY и OPENROUTER_MODEL")
        
        load_dotenv(env_path)
    
    @staticmethod
    def get_openrouter_key():
        """Возвращает API ключ или None"""
        key = os.getenv("OPENROUTER_API_KEY", "")
        if key and key.strip():
            return key.strip()
        return None

    @staticmethod
    def get_openrouter_model():
        """Возвращает модель или None"""
        model = os.getenv("OPENROUTER_MODEL", "")
        if model and model.strip():
            return model.strip()
        return None
    
    @staticmethod
    def is_openrouter_configured():
        """Проверяет, заполнены ли настройки OpenRouter"""
        return Config.get_openrouter_key() is not None and Config.get_openrouter_model() is not None
    
    # Базовые пути
    BASE_DIR = get_base_dir()
    TEMP_DIR = None
    LOGS_DIR = None
    
    # Аудио настройки
    CHUNK = 1024
    RATE = 16000
    THRESHOLD = 500
    SILENCE_LIMIT = 1
    
    # Whisper
    WHISPER_MODEL_SIZE = "base"
    WHISPER_DEVICE = "cpu"
    WHISPER_COMPUTE_TYPE = "int8"
    
    # Ollama
    OLLAMA_MODEL = "llama3.1:latest"
    
    # OpenRouter
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL = None
    OPENROUTER_API_KEY = None
    
    # Edge TTS
    EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "ru-RU-SvetlanaNeural")
    EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "+0%")
    
    # Папка для отчётов
    OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "VoiceAssistantReports")
    
    # Путь к модели Vosk
    VOSK_MODEL_PATH = None


# Инициализация
Config.setup_directories()
Config.load_env()
os.makedirs(Config.OUTPUT_DIR, exist_ok=True)

# Устанавливаем пути
Config.VOSK_MODEL_PATH = os.path.join(Config.BASE_DIR, "vosk-model-small-ru-0.22")
Config.OPENROUTER_API_KEY = Config.get_openrouter_key()
Config.OPENROUTER_MODEL = Config.get_openrouter_model()