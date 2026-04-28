# core/web_search.py
# Поиск в интернете через DuckDuckGo (без API ключа, бесплатно)

from ddgs import DDGS
from typing import List, Dict, Optional


class WebSearcher:
    """
    Ищет информацию в интернете через DuckDuckGo.
    Не требует API ключа, работает бесплатно.
    """
    
    def __init__(self):
        self.ddgs = DDGS()
    
    def search(self, query: str, max_results: int = 5) -> Optional[List[Dict[str, str]]]:
        """
        Выполняет поиск и возвращает список результатов.
        
        Каждый результат содержит:
        - title: заголовок страницы
        - href: полная ссылка
        - body: краткое описание (сниппет)
        """
        print(f"🔍 WebSearcher.search() получил запрос: {query}")
        try:
            results = []
            
            for result in self.ddgs.text(
                query,
                region="ru-ru",          # Регион — Россия
                safesearch="moderate",   # Умеренная фильтрация взрослого контента
                max_results=max_results
            ):
                print(f"🔍 Найден результат: {result.get('title', '')[:50]}...")
                
                href = result.get('href', '')
                # Убираем параметры отслеживания из ссылки
                if href and '://' in href and '?' in href:
                    href = href.split('?')[0]
                
                results.append({
                    'title': result.get('title', ''),
                    'href': href,
                    'body': result.get('body', '')
                })
            
            print(f"🔍 Всего найдено: {len(results)} результатов")
            return results if results else None
            
        except Exception as e:
            print(f"❌ Ошибка поиска: {e}")
            return None
    
    def format_results_for_ai(self, results: List[Dict[str, str]], query: str) -> str:
        """
        Форматирует результаты поиска для передачи в ИИ.
        ИИ получит структурированный список источников.
        """
        if not results:
            return f"По запросу '{query}' ничего не найдено."
        
        formatted = f"Результаты поиска по запросу '{query}':\n\n"
        for i, r in enumerate(results, 1):
            formatted += f"--- ИСТОЧНИК {i} ---\n"
            formatted += f"Заголовок: {r['title']}\n"
            formatted += f"Ссылка: {r['href']}\n"
            formatted += f"Описание: {r['body']}\n\n"
        
        return formatted