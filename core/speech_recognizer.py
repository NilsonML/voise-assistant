# core/speech_recognizer.py
# Превращает аудиофайл в текст (распознавание речи)

import speech_recognition as sr
from faster_whisper import WhisperModel
from config import Config
import os


class SpeechRecognizer:
    """
    Распознаёт речь из аудиофайла.
    
    Два режима:
    - локальный (Whisper) — работает без интернета, но нужен мощный компьютер
    - онлайн (Google) — нужен интернет, но работает быстрее и точнее
    """
    
    def __init__(self, use_local=True):
        self.use_local = use_local
        self.whisper_model = None
        
        if use_local:
            self._init_whisper()
            
    def _init_whisper(self):
        """Загружаем модель Whisper (может занять время и память)"""
        try:
            print(f"Загрузка Whisper модели ({Config.WHISPER_MODEL_SIZE})...")
            self.whisper_model = WhisperModel(
                Config.WHISPER_MODEL_SIZE,
                device=Config.WHISPER_DEVICE,      # cpu или cuda
                compute_type=Config.WHISPER_COMPUTE_TYPE   # int8, float16, float32
            )
            print("✅ Whisper модель загружена")
        except Exception as e:
            print(f"❌ Ошибка загрузки Whisper: {e}")
            self.use_local = False
            print("Переключение на онлайн-режим (Google Speech)")
            
    def recognize(self, audio_file, language='ru'):
        """Распознаёт речь из файла и возвращает текст"""
        if not os.path.exists(audio_file):
            return f"❌ Файл не найден: {audio_file}"
            
        if self.use_local:
            return self._recognize_whisper(audio_file, language)
        else:
            return self._recognize_google(audio_file, language)
            
    def _recognize_whisper(self, audio_file, language='ru'):
        """Локальное распознавание через Whisper"""
        try:
            print("🔍 Распознавание речи (Whisper)...")
            segments, info = self.whisper_model.transcribe(
                audio_file,
                beam_size=5,          # Ширина луча поиска (чем больше, тем точнее, но медленнее)
                language=language
            )
            
            print(f"Обнаружен язык: {info.language} (вероятность: {info.language_probability:.2f})")
            
            text = ''
            for segment in segments:
                text += segment.text
                
            if text.strip():
                print("✅ Распознавание завершено")
                return text.strip()
            else:
                return "❌ Не удалось распознать речь"
                
        except Exception as e:
            print(f"❌ Ошибка Whisper: {e}")
            return f"❌ Ошибка распознавания: {e}"
            
    def _recognize_google(self, audio_file, language='ru-RU'):
        """Онлайн распознавание через Google Speech (нужен интернет)"""
        try:
            print("🔍 Распознавание речи (Google)...")
            recognizer = sr.Recognizer()
            
            with sr.AudioFile(audio_file) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)  # Адаптируемся к шуму
                audio = recognizer.record(source)
                
            text = recognizer.recognize_google(audio, language=language)
            print("✅ Распознавание завершено")
            return text
            
        except sr.UnknownValueError:
            return "❌ Не удалось распознать речь (слишком тихо или неразборчиво)"
        except sr.RequestError as e:
            return f"❌ Ошибка сервиса распознавания: {e}"
        except Exception as e:
            return f"❌ Ошибка: {e}"