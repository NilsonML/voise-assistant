# core/tts_engine.py
import edge_tts
import asyncio
import tempfile
import os
import re
import pygame
import threading
from config import Config


class TTSEngine:
    """Озвучка текста через Edge TTS"""
    
    def __init__(self, voice=None, rate=None):
        self.voice = voice or Config.EDGE_TTS_VOICE
        self.rate = rate or Config.EDGE_TTS_RATE
        self._init_pygame()
        self.is_speaking = False
        self._stop_flag = False
    
    def _init_pygame(self):
        try:
            pygame.mixer.init(frequency=24000, buffer=512)
        except Exception as e:
            print(f"⚠️ Ошибка инициализации pygame: {e}")
    
    def clean_text(self, text):
        text = re.sub(r'[*•▪#]', '', text)
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        text = re.sub(r'\[.*?\]\(.*?\)', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _play_audio(self, file_path, callback=None):
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy() and not self._stop_flag:
                pygame.time.wait(100)
            
            if self._stop_flag:
                pygame.mixer.music.stop()
            
            pygame.mixer.music.unload()
            
        except Exception as e:
            print(f"⚠️ Ошибка воспроизведения: {e}")
        finally:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
            except:
                pass
            self.is_speaking = False
            self._stop_flag = False
            if callback:
                callback()
    
    def say(self, text, on_finished=None):
        if not text:
            if on_finished:
                on_finished()
            return
        
        if self.is_speaking:
            self.stop()
        
        clean_text = self.clean_text(text)
        if not clean_text:
            if on_finished:
                on_finished()
            return
        
        self.is_speaking = True
        self._stop_flag = False
        
        def _speak_async():
            try:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp_path = tmp.name
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def generate():
                    communicate = edge_tts.Communicate(
                        text=clean_text,
                        voice=self.voice,
                        rate=self.rate
                    )
                    await communicate.save(tmp_path)
                
                loop.run_until_complete(generate())
                loop.close()
                
                self._play_audio(tmp_path, on_finished)
                
            except Exception as e:
                print(f"⚠️ Ошибка TTS: {e}")
                self.is_speaking = False
                self._stop_flag = False
                if on_finished:
                    on_finished()
        
        thread = threading.Thread(target=_speak_async, daemon=True)
        thread.start()
    
    def stop(self):
        self._stop_flag = True
        try:
            pygame.mixer.music.stop()
        except:
            pass
        self.is_speaking = False