# core/speaker_diarization.py
# Определяет, кто и когда говорит в аудиозаписи (пока в разработке)

import numpy as np
import librosa
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')
from core.logger import log

# Проверяем наличие библиотек (sklearn нужна для кластеризации голосов)
try:
    from sklearn.cluster import SpectralClustering
    from sklearn.preprocessing import normalize
    import resampy
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    print("⚠️ sklearn не установлен. Распознавание говорящих отключено. Установите: pip install scikit-learn")

try:
    import speech_recognition as sr
    HAS_SPEECH_REC = True
except ImportError:
    HAS_SPEECH_REC = False


class SpeakerDiarization:
    """
    Распознавание говорящих — разбивает аудио на сегменты и пытается понять,
    сколько разных людей говорят и когда.
    
    ВНИМАНИЕ: эта функция экспериментальная и не всегда работает точно.
    """
    
    def __init__(self, num_speakers=2):
        self.num_speakers = num_speakers   # Предполагаемое количество говорящих
        self.sr = 16000                     # Частота дискретизации
        
    def extract_features(self, audio_path):
        """
        Извлекает MFCC-признаки из аудио — это "отпечаток" голоса.
        MFCC = Mel-frequency cepstral coefficients (как голос звучит)
        """
        try:
            y, sr = librosa.load(audio_path, sr=self.sr)
            
            # Извлекаем 13 MFCC коэффициентов
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, n_fft=2048, hop_length=512)
            
            # Добавляем дельты (скорость изменения признаков)
            mfcc_delta = librosa.feature.delta(mfcc)
            mfcc_delta2 = librosa.feature.delta(mfcc, order=2)
            
            # Объединяем все признаки в один вектор
            features = np.vstack([mfcc, mfcc_delta, mfcc_delta2])
            
            return features.T, y, sr
            
        except Exception as e:
            log.error(f"Ошибка извлечения признаков: {e}")
            return None, None, None
    
    def segment_audio(self, y, sr, segment_duration=2.0):
        """Разбиваем аудио на кусочки по segment_duration секунд"""
        hop_length = int(segment_duration * sr)
        segments = []
        
        for start in range(0, len(y), hop_length):
            end = min(start + hop_length, len(y))
            if end - start > hop_length // 2:   # Отбрасываем слишком короткие куски
                segments.append((start, end))
        
        return segments
    
    def diarize(self, audio_path):
        """
        Основной метод: анализируем аудио, возвращаем, сколько говорящих,
        их временные отрезки и текст.
        """
        if not HAS_SKLEARN:
            log.warning("sklearn не установлен, распознавание говорящих недоступно")
            return {"num_speakers": 1, "segments": [], "full_text": None}
        
        log.info(f"Начало распознавания говорящих: {audio_path}")
        
        # Извлекаем признаки
        features, y, sr = self.extract_features(audio_path)
        
        if features is None or len(features) < 10:
            log.warning("Недостаточно данных для распознавания говорящих")
            return {"num_speakers": 1, "segments": [], "full_text": None}
        
        # Нормализуем признаки (приводим к одному масштабу)
        features_norm = normalize(features)
        
        # Кластеризация — группируем похожие голоса
        try:
            clustering = SpectralClustering(
                n_clusters=min(self.num_speakers, len(features_norm) // 10),
                affinity='nearest_neighbors',
                n_neighbors=10,
                random_state=42
            )
            labels = clustering.fit_predict(features_norm)
            
            unique_speakers = len(np.unique(labels))
            log.info(f"Обнаружено говорящих: {unique_speakers}")
            
            # Разбиваем на сегменты и приписываем каждому говорящего
            segments = self.segment_audio(y, sr)
            speaker_segments = []
            
            full_text = self._transcribe_audio(audio_path)
            
            for i, (start, end) in enumerate(segments):
                if i < len(labels):
                    speaker_id = labels[i] + 1   # 1, 2, 3...
                    start_sec = start / sr
                    end_sec = end / sr
                    
                    speaker_segments.append({
                        "speaker": f"Speaker {speaker_id}",
                        "start": round(start_sec, 2),
                        "end": round(end_sec, 2),
                        "duration": round((end_sec - start_sec), 2)
                    })
            
            # Группируем по говорящим для удобства
            speakers_summary = defaultdict(list)
            for seg in speaker_segments:
                speakers_summary[seg["speaker"]].append(seg)
            
            return {
                "num_speakers": unique_speakers,
                "segments": speaker_segments,
                "speakers_summary": dict(speakers_summary),
                "full_text": full_text,
                "total_duration": round(len(y) / sr, 2)
            }
            
        except Exception as e:
            log.exception(f"Ошибка кластеризации: {e}")
            return {"num_speakers": 1, "segments": [], "full_text": None}
    
    def _transcribe_audio(self, audio_path):
        """Пытаемся распознать текст из аудио (для отчёта)"""
        try:
            if not HAS_SPEECH_REC:
                return None
            
            recognizer = sr.Recognizer()
            with sr.AudioFile(audio_path) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.record(source)
                text = recognizer.recognize_google(audio, language="ru-RU")
                return text
        except Exception as e:
            log.error(f"Ошибка распознавания текста: {e}")
            return None
    
    def get_diarization_report(self, audio_path):
        """Возвращает красивый текстовый отчёт о говорящих"""
        result = self.diarize(audio_path)
        
        if not result["segments"]:
            return "Не удалось распознать говорящих"
        
        report = []
        report.append("=" * 50)
        report.append("РАСПОЗНАВАНИЕ ГОВОРЯЩИХ")
        report.append("=" * 50)
        report.append(f"Общее количество говорящих: {result['num_speakers']}")
        report.append(f"Общая длительность: {result['total_duration']} сек")
        report.append("")
        
        report.append("Временная шкала:")
        report.append("-" * 40)
        
        for seg in result["segments"]:
            report.append(f"{seg['start']:>5.1f}с - {seg['end']:>5.1f}с : {seg['speaker']}")
        
        report.append("")
        report.append("=" * 50)
        
        return "\n".join(report)


# Упрощённый интерфейс для вызова из других модулей
def analyze_speakers(audio_path):
    diar = SpeakerDiarization()
    return diar.get_diarization_report(audio_path)