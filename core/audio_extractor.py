# core/audio_extractor.py
# Достаём звук из видеофайлов с помощью FFmpeg

import imageio_ffmpeg
import subprocess
import os
from config import Config


class AudioExtractor:
    """Извлекает аудиодорожку из видео (MP4, AVI, MKV, MOV)"""
    
    def __init__(self):
        # imageio_ffmpeg сам скачивает FFmpeg при первом запуске
        self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        
    def extract_from_video(self, video_path, output_path=None):
        """Берёт видеофайл, вытаскивает аудио, сохраняет как WAV"""
        if not os.path.exists(video_path):
            print(f"❌ Файл не найден: {video_path}")
            return None
            
        # Если не указали куда сохранять — кладём во временную папку с тем же именем
        if output_path is None:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(Config.TEMP_DIR, f"{base_name}_audio.wav")
            
        # Команда для FFmpeg:
        # -i video_path  — входной файл
        # -vn            — без видео (video no)
        # -acodec pcm_s16le — аудиокодек WAV
        # -ar 16000      — частота 16 кГц (для распознавания)
        # -ac 1          — моно (один канал)
        # -y             — перезаписывать выходной файл, если существует
        cmd = [
            self.ffmpeg_path,
            '-i', video_path,
            '-vn',
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            '-y',
            output_path
        ]
        
        try:
            print(f"\n🎬 Извлечение аудио из видео: {video_path}")
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"✅ Аудио извлечено: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            print(f"❌ Ошибка извлечения: {e.stderr.decode()}")
            return None