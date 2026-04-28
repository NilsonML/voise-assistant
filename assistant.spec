# assistant.spec
import os

# Путь к папке vosk
vosk_path = r"C:\Users\user\Desktop\voice_assistant\venv\Lib\site-packages\vosk"

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[
        (os.path.join(vosk_path, 'libvosk.dll'), 'vosk'),
        (os.path.join(vosk_path, 'libstdc++-6.dll'), 'vosk'),
        (os.path.join(vosk_path, 'libgcc_s_seh-1.dll'), 'vosk'),
        (os.path.join(vosk_path, 'libwinpthread-1.dll'), 'vosk'),
    ],
    datas=[
        ('vosk-model-small-ru-0.22', 'vosk-model-small-ru-0.22'),
        ('commands.json', '.'),
        ('core', 'core'),
    ],
    hiddenimports=[
        'vosk',
        'faster_whisper',
        'pyaudiowpatch',
        'sounddevice',
        'ddgs',
        'PyQt6',
        'pypdf',
        'docx',
        'ollama',
        'openai',
        'edge_tts',
        'pygame',
        'numpy',
        'ctypes',
        'soundfile',
        'librosa',
        'sklearn',
        'resampy',
        'imageio_ffmpeg',
    ],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VoiceAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)