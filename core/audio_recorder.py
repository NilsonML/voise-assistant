# core/audio_recorder.py
# Запись звука с микрофона и системного аудио (то, что играет из динамиков)

import sounddevice as sd
import soundfile as sf
import numpy as np
import threading
import time
import wave
import struct
import math
from config import Config


class AudioRecorder:
    """Умеет записывать с микрофона (авто-стоп по тишине или вручную) и системный звук"""
    
    def __init__(self):
        self.CHUNK = Config.CHUNK                 # Размер порции
        self.RATE = Config.RATE                   # Частота дискретизации
        self.THRESHOLD = Config.THRESHOLD         # Порог громкости
        self.SILENCE_LIMIT = Config.SILENCE_LIMIT # Секунд тишины до остановки
        
        self.is_recording = False
        self.frames = []
        
    def _rms(self, data):
        """Вычисляет среднюю громкость звука (RMS — root mean square)"""
        if isinstance(data, np.ndarray):
            return np.sqrt(np.mean(data**2))
        
        # Для байтовых данных (например, из PyAudio)
        count = len(data) // 2
        if count == 0:
            return 0
        format_str = "<" + "h" * count
        shorts = struct.unpack_from(format_str, data)
        sum_squares = sum(sample * sample for sample in shorts)
        return math.sqrt(sum_squares / count)
    
    def record_microphone_auto(self, filename="recording.wav"):
        """Записывает с микрофона до тех пор, пока не наступит 2 секунды тишины"""
        print("\n🎤 Говорите... (авто-остановка после 2 сек тишины)")
        
        self.frames = []
        silence_counter = 0
        recording = True
        
        def callback(indata, frames, time, status):
            if status:
                print(f"Статус: {status}")
            if recording:
                self.frames.append(indata.copy())
        
        stream = sd.InputStream(
            samplerate=self.RATE,
            channels=1,
            callback=callback,
            blocksize=self.CHUNK
        )
        
        with stream:
            while True:
                if len(self.frames) > 0:
                    last_frame = self.frames[-1]
                    current_rms = np.sqrt(np.mean(last_frame**2))
                    
                    # Если тихо — увеличиваем счётчик тишины
                    if current_rms < self.THRESHOLD / 1000:
                        silence_counter += 1
                    else:
                        silence_counter = 0
                        
                    # Хватит тишины — выходим
                    if silence_counter * (self.CHUNK / self.RATE) > self.SILENCE_LIMIT:
                        break
                time.sleep(0.1)
        
        print("✅ Запись завершена")
        
        if self.frames:
            audio_data = np.concatenate(self.frames, axis=0)
            sf.write(filename, audio_data, self.RATE)
            print(f"✅ Файл сохранен: {filename}")
            return filename
        return None
    
    def record_microphone_manual(self, filename="recording.wav"):
        """Записывает с микрофона до тех пор, пока пользователь не нажмёт Enter"""
        print("\n🎤 Начало записи... (нажмите Enter для остановки)")
        
        self.frames = []
        self.is_recording = True
        
        def callback(indata, frames, time, status):
            if status:
                print(f"Статус: {status}")
            if self.is_recording:
                self.frames.append(indata.copy())
        
        stream = sd.InputStream(
            samplerate=self.RATE,
            channels=1,
            callback=callback,
            blocksize=self.CHUNK
        )
        
        with stream:
            input()  # Ждём Enter
        
        self.is_recording = False
        print("✅ Запись остановлена")
        
        if self.frames:
            audio_data = np.concatenate(self.frames, axis=0)
            sf.write(filename, audio_data, self.RATE)
            print(f"✅ Файл сохранен: {filename}")
            return filename
        return None
    
    def record_system_audio_manual(self, filename="system_audio.wav"):
        """Записывает системный звук (всё, что играет из динамиков) до нажатия Enter"""
        try:
            import pyaudiowpatch as pyaudio
            
            p = pyaudio.PyAudio()
            wasapi_info = p.get_default_wasapi_loopback()  # Виртуальное устройство для захвата вывода
            
            print(f"\n🔊 Запись системного звука...")
            print(f"Устройство: {wasapi_info['name']}")
            print("Нажмите Enter для остановки записи")
            
            RATE = int(wasapi_info['defaultSampleRate'])
            CHANNELS = wasapi_info['maxInputChannels']
            
            stream = p.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=self.CHUNK,
                input_device_index=wasapi_info['index']
            )
            
            frames = []
            print("🎙️ Запись началась...")
            
            recording = True
            
            def record_thread():
                nonlocal frames
                while recording:
                    try:
                        data = stream.read(self.CHUNK)
                        frames.append(data)
                    except Exception as e:
                        print(f"Ошибка записи: {e}")
                        break
            
            thread = threading.Thread(target=record_thread)
            thread.daemon = True
            thread.start()
            
            input()  # Ждём Enter
            recording = False
            thread.join(timeout=1)
            
            stream.stop_stream()
            stream.close()
            p.terminate()
            
            print("✅ Запись остановлена")
            
            if frames:
                with wave.open(filename, 'wb') as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
                    wf.setframerate(RATE)
                    wf.writeframes(b''.join(frames))
                
                duration = len(frames) * self.CHUNK / RATE
                print(f"✅ Файл сохранен: {filename} ({duration:.1f} сек)")
                return filename
            else:
                print("❌ Нет данных для сохранения")
                return None
            
        except AttributeError:
            print("❌ PyAudioWPatch не установлен или не поддерживает WASAPI loopback")
            print("Установите: pip install pyaudiowpatch")
            return None
        except Exception as e:
            print(f"❌ Ошибка записи системного звука: {e}")
            return None
    
    def record_system_audio_timed(self, seconds=10, filename="system_audio.wav"):
        """Записывает системный звук заданное количество секунд (простой вариант)"""
        try:
            import pyaudiowpatch as pyaudio
            
            p = pyaudio.PyAudio()
            wasapi_info = p.get_default_wasapi_loopback()
            
            print(f"\n🔊 Запись системного звука...")
            print(f"Устройство: {wasapi_info['name']}")
            print(f"Запись {seconds} секунд...")
            
            RATE = int(wasapi_info['defaultSampleRate'])
            CHANNELS = wasapi_info['maxInputChannels']
            
            stream = p.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=self.CHUNK,
                input_device_index=wasapi_info['index']
            )
            
            frames = []
            
            for _ in range(0, int(RATE / self.CHUNK * seconds)):
                data = stream.read(self.CHUNK)
                frames.append(data)
                
            stream.stop_stream()
            stream.close()
            p.terminate()
            
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
                wf.setframerate(RATE)
                wf.writeframes(b''.join(frames))
            
            print(f"✅ Файл сохранен: {filename}")
            return filename
            
        except Exception as e:
            print(f"❌ Ошибка записи системного звука: {e}")
            return None