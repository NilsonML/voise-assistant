# core/ai_processor.py
import time
import ollama
from openai import OpenAI
from config import Config
import re
from typing import Optional, Dict, Any
from collections import OrderedDict
from core.web_search import WebSearcher


class AIProcessor:
    """Обработка текста через ИИ (локально или онлайн)"""
    
    MAX_HISTORY_LENGTH = 8
    MAX_RESPONSE_TOKENS = 1000
    CACHE_MAX_SIZE = 25
    CACHE_TTL = 1800  # 30 минут
    
    def __init__(self, use_local=True):
        self.use_local = use_local
        self.conversation_history = []
        self.searcher = WebSearcher()
        self.ollama_available = False
        self.ollama_model_available = False
        self.client = None
        self.model = None
        
        # Кэш с ограничением
        self.response_cache = OrderedDict()
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Системный промпт
        self.system_prompt = {
            "role": "system",
            "content": (
                "Ты русскоязычный ассистент женского рода и тебя зовут 'Аура'."
                "ТОЛЬКО на русском. Без английских слов. По делу."
            )
        }
        
        self.conversation_history.append(self.system_prompt)
        
        
        # Инициализация в зависимости от режима
        if use_local:
            self._check_ollama()
        else:
            self._init_openrouter()
        
        self._start_cache_cleaner()
    
    def _start_cache_cleaner(self):
        """Запускает фоновую очистку кэша каждые 5 минут"""
        def clean_loop():
            while True:
                time.sleep(300)
                self._cleanup_cache()
        import threading
        thread = threading.Thread(target=clean_loop, daemon=True)
        thread.start()
    
    def _cleanup_cache(self):
        """Очищает устаревшие записи кэша"""
        current_time = time.time()
        keys_to_remove = []
        
        for key, item in list(self.response_cache.items()):
            if current_time - item.get('timestamp', 0) > self.CACHE_TTL:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.response_cache[key]
        
        if keys_to_remove:
            print(f"🗑️ Кэш очищен: удалено {len(keys_to_remove)} записей")
    
    def _get_from_cache(self, text: str) -> Optional[str]:
        """Получает ответ из кэша"""
        cache_key = text.lower().strip()
        
        if cache_key in self.response_cache:
            item = self.response_cache[cache_key]
            if time.time() - item.get('timestamp', 0) < self.CACHE_TTL:
                self.cache_hits += 1
                return item.get('value')
            else:
                del self.response_cache[cache_key]
        
        self.cache_misses += 1
        return None
    
    def _add_to_cache(self, text: str, response: str):
        """Добавляет ответ в кэш"""
        cache_key = text.lower().strip()
        
        while len(self.response_cache) >= self.CACHE_MAX_SIZE:
            self.response_cache.popitem(last=False)
        
        self.response_cache[cache_key] = {
            'value': response,
            'timestamp': time.time()
        }
    
    def clear_cache(self):
        """Очищает весь кэш"""
        self.response_cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0
    
    def _check_ollama(self):
        """Проверяет доступность Ollama и наличие модели"""
        try:
            models_response = ollama.list()
            self.ollama_available = True
            
            # Получаем список доступных моделей
            available_models = []
            if hasattr(models_response, 'models'):
                available_models = [m.model for m in models_response.models]
            elif isinstance(models_response, dict):
                available_models = [m.get('name', '') for m in models_response.get('models', [])]
            
            model_name = Config.OLLAMA_MODEL
            if model_name in available_models:
                self.ollama_model_available = True
                print(f"✅ Ollama доступен, модель: {model_name}")
            else:
                self.ollama_model_available = False
                print(f"⚠️ Модель {model_name} не найдена")
                print(f"📦 Доступные модели: {available_models[:3] if available_models else 'нет'}")
                print("💡 Установите: ollama pull llama3.2:1b")
                print("🔄 Переключение на онлайн-режим")
                self.use_local = False
                self._init_openrouter()
                
        except Exception as e:
            self.ollama_available = False
            self.ollama_model_available = False
            print(f"⚠️ Ollama не доступен: {e}")
            print("💡 Установите Ollama: https://ollama.com/download")
            print("🔄 Переключение на онлайн-режим")
            self.use_local = False
            self._init_openrouter()
    
    def _init_openrouter(self):
        """Инициализация OpenRouter"""
        api_key = Config.get_openrouter_key()
        model = Config.get_openrouter_model()
        
        if not api_key:
            print("⚠️ OpenRouter API ключ не найден")
            print("💡 Добавьте OPENROUTER_API_KEY в .env")
            self.use_local = True
            return
        
        if not model:
            print("⚠️ Модель OpenRouter не выбрана")
            print("💡 Добавьте OPENROUTER_MODEL в .env")
            self.use_local = True
            return
            
        try:
            self.client = OpenAI(
                api_key=api_key,
                base_url=Config.OPENROUTER_BASE_URL
            )
            self.model = model
            print(f"✅ OpenRouter готов. Модель: {self.model}")
            self.use_local = False
        except Exception as e:
            print(f"❌ Ошибка OpenRouter: {e}")
            self.use_local = True
    
    def _update_model_from_env(self):
        """Обновляет модель из .env"""
        if self.use_local:
            return
        
        current_model = Config.get_openrouter_model()
        if current_model and self.model != current_model:
            print(f"🔄 Обновление модели: {self.model} -> {current_model}")
            self.model = current_model
    
    def process(self, text: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """Основной метод обработки запроса"""
        if not text or text.startswith('❌'):
            return None
        
        # Проверка кэша
        cached = self._get_from_cache(text)
        if cached:
            print(f"📦 Кэш: HIT (всего: {len(self.response_cache)})")
            return cached
        
        # Добавляем запрос в историю
        self.conversation_history.append({"role": "user", "content": text})
        
        # Обрезаем историю
        if len(self.conversation_history) > self.MAX_HISTORY_LENGTH + 1:
            # Сохраняем системный промпт и последние MAX_HISTORY_LENGTH сообщений
            self.conversation_history = [self.conversation_history[0]] + self.conversation_history[-self.MAX_HISTORY_LENGTH:]
        
        # Получаем ответ
        start_time = time.time()
        
        if self.use_local and self.ollama_available and self.ollama_model_available:
            response = self._process_local()
        else:
            response = self._process_online()
        
        elapsed = time.time() - start_time
        print(f"⏱️ Время ответа: {elapsed:.1f} сек")
        
        if response:
            response = self._clean_response(response)
            self._add_to_cache(text, response)
            self.conversation_history.append({"role": "assistant", "content": response})
        
        return response
    
    def _clean_response(self, text: str) -> str:
        """Очистка ответа"""
        if not text:
            return text
        
        replacements = {
            'looks like': 'похоже', 'Looks like': 'Похоже',
            'sounds like': 'звучит как', 'Sounds like': 'Звучит как',
            'okay': 'хорошо', 'Okay': 'Хорошо',
            'sorry': 'извините', 'Sorry': 'Извините',
            'please': 'пожалуйста', 'well': 'ну', 'so': 'итак',
        }
        
        for eng, rus in replacements.items():
            text = text.replace(eng, rus)
        
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        
        return text.strip()
    
    def _process_local(self) -> Optional[str]:
        """Обработка через Ollama"""
        try:
            model = Config.OLLAMA_MODEL
            print(f"🤖 Ollama ({model})...")
            
            messages = [{"role": msg["role"], "content": msg["content"]} 
                       for msg in self.conversation_history]
            
            response = ollama.chat(
                model,
                messages=messages,
                options={
                    "num_predict": self.MAX_RESPONSE_TOKENS,
                    "temperature": 0.5,
                    "top_p": 0.8,
                }
            )
            print("✅ Ответ получен")
            return response['message']['content']
            
        except Exception as e:
            print(f"❌ Ошибка Ollama: {e}")
            self.ollama_available = False
            self.use_local = False
            return self._process_online()
    
    def _process_online(self) -> Optional[str]:
        """Обработка через OpenRouter"""
        self._update_model_from_env()
        
        if self.client is None:
            self._init_openrouter()
            if self.client is None:
                return "⚠️ OpenRouter не инициализирован"
        
        try:
            print(f"🌐 OpenRouter ({self.model})...")
            
            messages = [{"role": msg["role"], "content": msg["content"]} 
                       for msg in self.conversation_history]
            
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.5,
                max_tokens=self.MAX_RESPONSE_TOKENS,
                top_p=0.8,
                timeout=30,
            )
            print("✅ Ответ получен")
            return completion.choices[0].message.content
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Ошибка: {error_msg[:100]}")
            
            if "429" in error_msg:
                return "⚠️ Модель перегружена. Попробуйте позже или смените модель в .env"
            elif "400" in error_msg:
                return "⚠️ Ошибка запроса. Проверьте модель в .env"
            else:
                return f"⚠️ Ошибка: {error_msg[:200]}"
    
    def clear_history(self):
        """Очистка истории"""
        self.conversation_history = [self.system_prompt]
        self.clear_cache()
        print("История и кэш очищены")
    
    def get_last_response(self) -> Optional[str]:
        """Получить последний ответ"""
        for msg in reversed(self.conversation_history):
            if msg["role"] == "assistant":
                return msg["content"]
        return None

    def search_web(self, query: str) -> str:
        """Поиск в интернете"""
        print(f"🌐 Поиск: {query}")
        
        results = self.searcher.search(query, max_results=5)
        
        if not results:
            return f"❌ Ничего не найдено по запросу '{query}'."
        
        search_results = self.searcher.format_results_for_ai(results, query)
        
        prompt = f"""Вопрос: {query}

Информация:
{search_results}

Краткий ответ на русском со ссылками:"""

        self.conversation_history.append({"role": "user", "content": prompt})
        
        if self.use_local and self.ollama_available and self.ollama_model_available:
            response = self._process_local()
        else:
            response = self._process_online()
        
        self.conversation_history.pop()
        
        return response if response else f"❌ Ошибка обработки поиска по '{query}'"

    def search_and_answer(self, query: str) -> str:
        return self.search_web(query)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Статистика кэша"""
        total = self.cache_hits + self.cache_misses
        return {
            'size': len(self.response_cache),
            'max_size': self.CACHE_MAX_SIZE,
            'hits': self.cache_hits,
            'misses': self.cache_misses,
            'hit_ratio': self.cache_hits / total if total > 0 else 0
        }