# core/logger.py
# Логирование — записываем всё, что происходит, в файл и в консоль

import logging
import os
from datetime import datetime
from config import Config


class Logger:
    """Один логгер на всю программу (синглтон), пишет и в файл, и в консоль"""
    
    _instance = None
    
    def __new__(cls):
        # Если экземпляр ещё не создан — создаём
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup_logger()
        return cls._instance
    
    def _setup_logger(self):
        """Настраиваем логгер: куда писать, в каком формате"""
        log_dir = os.path.join(Config.BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        # Имя файла лога: assistant_20241201.log (дата сегодняшняя)
        log_file = os.path.join(log_dir, f"assistant_{datetime.now().strftime('%Y%m%d')}.log")
        
        # Формат записи: время - имя логгера - уровень - сообщение
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Пишем в файл (с кодировкой UTF-8, чтобы русские буквы не ломались)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        
        # Пишем в консоль (чтобы видеть при запуске из терминала)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        # Корневой логгер
        self.logger = logging.getLogger('VoiceAssistant')
        self.logger.setLevel(logging.DEBUG)   # Логируем всё, от DEBUG и выше
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Красивая черта в начале лога
        self.logger.info("=" * 50)
        self.logger.info("Логирование инициализировано")
        self.logger.info(f"Файл лога: {log_file}")
        self.logger.info("=" * 50)
    
    # Упрощённые методы для удобного использования
    def debug(self, message):
        self.logger.debug(message)
    
    def info(self, message):
        self.logger.info(message)
    
    def warning(self, message):
        self.logger.warning(message)
    
    def error(self, message):
        self.logger.error(message)
    
    def exception(self, message):
        """Логирует ошибку с полной трассировкой стека"""
        self.logger.exception(message)


# Глобальный экземпляр — импортируем `log` в любом модуле и пишем
log = Logger()