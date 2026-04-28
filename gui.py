# gui.py
import sys
import os
import time
import json
import wave
import queue
import threading
import gc
from datetime import datetime
from typing import Optional

import numpy as np
import pyaudiowpatch as pyaudio
import sounddevice as sd
import vosk

# PyQt6 импорты
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QTextEdit, QScrollArea, QProgressBar, 
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QSizePolicy, QFrame,
    QDialog, QLineEdit, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QShortcut, QShortcutEvent

# Импорты ядра проекта
from docx import Document
from config import Config
from core.audio_recorder import AudioRecorder
from core.audio_extractor import AudioExtractor
from core.speech_recognizer import SpeechRecognizer
from core.ai_processor import AIProcessor
from core.tts_engine import TTSEngine
from core.report_saver import ReportSaver
from core.logger import log
from core.command_manager import CommandManager, CommandManagerGUI

# Для PDF
try:
    import pypdf
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


class AutoResizeLabel(QLabel):
    """QLabel с автоматическим изменением высоты под содержимое"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | 
                                     Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setMaximumWidth(450)
    
    def setText(self, text: str):
        super().setText(text)
        self.adjustSize()
        self.updateGeometry()


class MessageColors:
    USER = "#2b5b84"
    ASSISTANT = "#2d6a4f"
    SYSTEM = "#4a4a4a"
    PROCESS = "#6b4e2e"
    ERROR = "#8b3a3a"
    
    @classmethod
    def get(cls, msg_type: str) -> str:
        colors = {"user": cls.USER, "assistant": cls.ASSISTANT, 
                  "system": cls.SYSTEM, "process": cls.PROCESS, "error": cls.ERROR}
        return colors.get(msg_type, cls.SYSTEM)


class WorkerSignals(QObject):
    """Потокобезопасные сигналы"""
    add_message = pyqtSignal(str, str, str, str)
    update_process = pyqtSignal(str, bool)
    clear_chat = pyqtSignal()
    set_button_state = pyqtSignal(str, bool)
    update_label = pyqtSignal(str, str, str)
    tts_started = pyqtSignal()
    tts_stopped = pyqtSignal()


class VoiceAssistantGUI(QMainWindow):
    SAMPLE_RATE = 16000
    SILENCE_TIMEOUT = 2.0
    SILENCE_THRESHOLD = 0.01
    WAKE_WORD_COOLDOWN = 3
    MAX_TEXT_FOR_AI = 4000
    
    def __init__(self):
        super().__init__()
        log.info("Инициализация GUI (PyQt6)")
        
        self.setWindowTitle("AURA")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 700)
        
        os.makedirs(Config.TEMP_DIR, exist_ok=True)
        os.makedirs(Config.LOGS_DIR, exist_ok=True)
        
        self.recorder = AudioRecorder()
        self.extractor = AudioExtractor()
        self.saver = ReportSaver()
        self.cmd_manager = CommandManager()
        self.recognizer: Optional[SpeechRecognizer] = None
        self.ai: Optional[AIProcessor] = None
        self.tts: Optional[TTSEngine] = None
        
        self.system_audio_save_path = Config.TEMP_DIR
        self.reports_save_path = Config.OUTPUT_DIR
        
        self.save_responses = True
        self.mode = "local"
        self.report_format = "both"
        
        self.current_audio = None
        self.current_video = None
        self.current_document = None
        self.last_recognized_text = None
        self.current_temp_files = []
        
        self.cancel_operation = False
        self.is_processing = False
        self.is_manual_recording = False
        self.system_recording = False
        self.is_listening_for_command = False
        self.wake_word_active = False
        self.is_speaking = False
        
        self.manual_recording_frames = []
        self.system_recording_frames = []
        self.system_save_filename = None
        
        self.vosk_model = None
        self.vosk_recognizer = None
        self.audio_queue = queue.Queue()
        self.last_wake_detection = 0
        
        self._message_containers = []
        self._message_bubbles = []
        self._message_labels = []
        
        self.signals = WorkerSignals()
        self._connect_signals()
        self._apply_stylesheet()
        self._setup_ui()
        self._setup_hotkeys()
    
        self._request_in_progress = False
        self._request_lock = threading.Lock()
        
        self._cleanup_temp_files()
        
        threading.Thread(target=self._init_components_async, daemon=True).start()
        QTimer.singleShot(2000, self._start_wake_word)
        
        QTimer.singleShot(3600000, self._periodic_cleanup)
        QTimer.singleShot(300000, self._periodic_gc)
    
    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================
    
    def _is_search_query(self, text: str) -> bool:
        search_triggers = ["найди", "поищи", "поиск", "найти", "узнай", "расскажи о"]
        return any(trigger in text.lower() for trigger in search_triggers)

    def _extract_search_query(self, text: str) -> str:
        query = text.lower()
        search_triggers = ["найди", "поищи", "поиск", "найти", "узнай", "расскажи о"]
        for trigger in search_triggers:
            query = query.replace(trigger, "")
        query = query.strip()
        return query if query else text
    
    def _init_tts(self):
        try:
            if self.tts is None:
                self.tts = TTSEngine()
        except Exception as e:
            print(f"⚠️ Ошибка инициализации TTS: {e}")
            self.tts = None
    
    def _periodic_gc(self):
        gc.collect()
        QTimer.singleShot(300000, self._periodic_gc)

    # ==================== ОЧИСТКА ФАЙЛОВ ====================
    
    def _cleanup_temp_files(self):
        try:
            if os.path.exists(Config.TEMP_DIR):
                current_time = time.time()
                for filename in os.listdir(Config.TEMP_DIR):
                    filepath = os.path.join(Config.TEMP_DIR, filename)
                    if os.path.isfile(filepath):
                        if current_time - os.path.getmtime(filepath) > 3600:
                            os.remove(filepath)
        except Exception as e:
            print(f"Ошибка очистки: {e}")
    
    def _periodic_cleanup(self):
        self._cleanup_temp_files()
        QTimer.singleShot(3600000, self._periodic_cleanup)
    
    def _add_temp_file(self, filepath: str):
        if filepath and os.path.exists(filepath):
            self.current_temp_files.append(filepath)
    
    def _cleanup_current_temp_files(self):
        for filepath in self.current_temp_files:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                print(f"Ошибка удаления: {e}")
        self.current_temp_files.clear()
    
    def _force_cleanup_all_temp_files(self):
        try:
            if os.path.exists(Config.TEMP_DIR):
                for filename in os.listdir(Config.TEMP_DIR):
                    filepath = os.path.join(Config.TEMP_DIR, filename)
                    if os.path.isfile(filepath):
                        os.remove(filepath)
        except Exception as e:
            print(f"Ошибка принудительной очистки: {e}")
        
        self.current_temp_files.clear()
        
        # Дополнительная очистка памяти, если слишком много сообщений
        MAX_MESSAGES = 500
        if len(self._message_containers) > MAX_MESSAGES:
            while len(self._message_containers) > MAX_MESSAGES:
                old = self._message_containers.pop(0)
                if old:
                    old.deleteLater()
            while len(self._message_bubbles) > MAX_MESSAGES:
                old = self._message_bubbles.pop(0)
                if old:
                    old.deleteLater()
            while len(self._message_labels) > MAX_MESSAGES:
                old = self._message_labels.pop(0)
                if old:
                    old.deleteLater()
        
        gc.collect()

    # ==================== СТИЛИ ====================

    def _apply_stylesheet(self):
        QApplication.instance().setStyleSheet("""
            * {
                background-color: #242424;
                color: #e0e0e0;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10pt;
            }
            QTextEdit { background-color: #1e1e1e; border: 1px solid #444; border-radius: 6px; padding: 5px; }
            QPushButton { 
                background-color: #1f538d; border: none; border-radius: 6px; padding: 8px; font-weight: bold; color: white;
            }
            QPushButton:hover { background-color: #14375e; }
            QPushButton:disabled { background-color: #333; color: #777; }
            QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 15px; padding-top: 15px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #aaaaaa; }
            QProgressBar { border: 1px solid #444; border-radius: 5px; text-align: center; background-color: #1e1e1e; color: white; }
            QProgressBar::chunk { background-color: #1f538d; border-radius: 4px; }
            QScrollArea { border: none; background-color: transparent; }
            QScrollBar:vertical { border: none; background-color: #242424; width: 12px; margin: 0px; }
            QScrollBar::handle:vertical { background-color: #555; min-height: 20px; border-radius: 6px; }
            QScrollBar::handle:vertical:hover { background-color: #777; }
            QComboBox { background-color: #1e1e1e; border: 1px solid #444; border-radius: 4px; padding: 4px; }
            QComboBox QAbstractItemView { background-color: #1e1e1e; selection-background-color: #1f538d; selection-color: white; border: 1px solid #444; }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #555; border-radius: 4px; background-color: #1e1e1e; }
            QCheckBox::indicator:checked { background-color: #1f538d; }
        """)

    def _connect_signals(self):
        self.signals.add_message.connect(self._ui_add_message)
        self.signals.update_process.connect(self._ui_update_process)
        self.signals.clear_chat.connect(self._ui_clear_chat)
        self.signals.set_button_state.connect(self._ui_set_button_state)
        self.signals.update_label.connect(self._ui_update_label)
        self.signals.tts_started.connect(self._on_tts_started)
        self.signals.tts_stopped.connect(self._on_tts_stopped)

    def _setup_hotkeys(self):
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._send_text)
        self.keyPressEvent = self._fix_russian_layout

    def _fix_russian_layout(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            key = event.key()
            widget = QApplication.focusWidget()
            if widget:
                if key == 1057 or key == Qt.Key.Key_C:
                    QApplication.postEvent(widget, QShortcutEvent(QKeySequence("Ctrl+C"), widget))
                elif key == 1052 or key == Qt.Key.Key_V:
                    QApplication.postEvent(widget, QShortcutEvent(QKeySequence("Ctrl+V"), widget))
                elif key == 1063 or key == Qt.Key.Key_X:
                    QApplication.postEvent(widget, QShortcutEvent(QKeySequence("Ctrl+X"), widget))
                elif key == 1060 or key == Qt.Key.Key_A:
                    QApplication.postEvent(widget, QShortcutEvent(QKeySequence("Ctrl+A"), widget))
        super().keyPressEvent(event)

    # ==================== НАСТРОЙКИ ====================
    
    def _show_settings_window(self):
        """Показывает окно настроек с полями для API ключа и модели"""
        dialog = QDialog(self)
        dialog.setWindowTitle("⚙️ Настройки OpenRouter")
        dialog.setMinimumWidth(550)
        dialog.setModal(True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        
        layout = QVBoxLayout(dialog)
        
        title = QLabel("Настройки OpenRouter")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; margin-bottom: 10px;")
        layout.addWidget(title)
        
        info = QLabel(
            "🔑 OpenRouter позволяет использовать бесплатные модели ИИ.\n"
            "Получите ключ на сайте: https://openrouter.ai/keys\n\n"
            "📌 Примеры моделей:\n"
            "   microsoft/phi-3-mini-128k-instruct:free\n"
            "   meta-llama/llama-3.2-3b-instruct:free\n"
            "   mistralai/mistral-7b-instruct:free"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaaaaa; margin-bottom: 15px;")
        layout.addWidget(info)
        
        layout.addWidget(QLabel("API ключ OpenRouter:"))
        api_key_input = QLineEdit()
        api_key_input.setPlaceholderText("sk-or-v1-... (обязательное поле)")
        current_key = Config.get_openrouter_key()
        if current_key:
            api_key_input.setText(current_key)
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(api_key_input)
        
        show_key_checkbox = QCheckBox("Показать ключ")
        show_key_checkbox.toggled.connect(lambda checked: api_key_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        ))
        layout.addWidget(show_key_checkbox)
        
        layout.addSpacing(10)
        
        layout.addWidget(QLabel("Модель OpenRouter:"))
        model_input = QLineEdit()
        model_input.setPlaceholderText("например: microsoft/phi-3-mini-128k-instruct:free (обязательное поле)")
        current_model = Config.get_openrouter_model()
        if current_model:
            model_input.setText(current_model)
        layout.addWidget(model_input)
        
        hint = QLabel(
            "💡 Список всех моделей: https://openrouter.ai/models\n"
            "Для бесплатного использования выбирайте модели с :free в конце"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888; font-size: 9pt; margin-top: 5px;")
        layout.addWidget(hint)
        
        if Config.is_openrouter_configured():
            status_text = "✅ Настройки заполнены"
            status_color = "#4caf50"
        else:
            status_text = "❌ Настройки не заполнены (требуются ключ и модель)"
            status_color = "#ff4444"
        
        status_label = QLabel(f"📌 Текущий статус: {status_text}")
        status_label.setStyleSheet(f"color: {status_color}; margin-top: 10px;")
        layout.addWidget(status_label)
        
        layout.addSpacing(20)
        
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 Сохранить")
        btn_save.setStyleSheet("background-color: #2e7d32;")
        btn_save.clicked.connect(lambda: self._save_settings(api_key_input.text().strip(), model_input.text().strip(), dialog))
        
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.clicked.connect(dialog.reject)
        
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        dialog.exec()

    def _save_settings(self, api_key: str, model: str, dialog: QDialog):
        if not api_key:
            QMessageBox.warning(dialog, "Ошибка", 
                "API ключ не может быть пустым!\n\nПолучите ключ на https://openrouter.ai/keys")
            return
        
        if not model:
            QMessageBox.warning(dialog, "Ошибка", 
                "Модель не может быть пустой!\n\nПример: microsoft/phi-3-mini-128k-instruct:free")
            return
        
        try:
            env_path = os.path.join(Config.get_base_dir(), '.env')
            
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(f"OPENROUTER_API_KEY={api_key}\n")
                f.write(f"OPENROUTER_MODEL={model}\n")
                f.write(f"EDGE_TTS_VOICE={Config.EDGE_TTS_VOICE}\n")
                f.write(f"EDGE_TTS_RATE={Config.EDGE_TTS_RATE}\n")
            
            from dotenv import load_dotenv
            load_dotenv(env_path, override=True)
            
            Config.OPENROUTER_API_KEY = api_key
            Config.OPENROUTER_MODEL = model
            
            if self.ai:
                self.ai._init_openrouter()
            
            self.signals.add_message.emit("system", "✅ Настройки", 
                f"Настройки сохранены!\nМодель: {model}", None)
            dialog.accept()
            
        except Exception as e:
            QMessageBox.critical(dialog, "Ошибка", f"Не удалось сохранить настройки: {e}")

    def _check_settings_before_online(self) -> bool:
        Config.load_env()
        api_key = Config.get_openrouter_key()
        model = Config.get_openrouter_model()
        
        if not api_key or not model:
            self.signals.add_message.emit("error", "❌", 
                f"Для онлайн-режима необходимо настроить OpenRouter!\n\n"
                f"API ключ: {'✓' if api_key else '✗'}\n"
                f"Модель: {'✓' if model else '✗'}\n\n"
                "1. Нажмите на шестерёнку ⚙️ в верхней панели\n"
                "2. Введите API ключ\n"
                "3. Введите модель\n"
                "4. Нажмите 'Сохранить'", None)
            return False
        return True

    # ==================== ИНТЕРФЕЙС ====================

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        top_bar = QHBoxLayout()
        title_lbl = QLabel("🎙️ Голосовой Ассистент")
        title_lbl.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #ffffff;")
        top_bar.addWidget(title_lbl)
        
        self.wake_indicator = QLabel("🔴 Аура: выкл")
        self.wake_indicator.setStyleSheet("color: #ff4444; font-weight: bold;")
        top_bar.addStretch()
        top_bar.addWidget(self.wake_indicator)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["💻 Локальный", "🌍 Онлайн"])
        self.mode_combo.currentTextChanged.connect(self._change_mode)
        top_bar.addWidget(self.mode_combo)
        
        btn_cmds = QPushButton("📋 Команды")
        btn_cmds.setStyleSheet("background-color: #6a1b9a;")
        btn_cmds.clicked.connect(self._show_command_manager)
        top_bar.addWidget(btn_cmds)
        
        btn_settings = QPushButton("⚙️ Настройки")
        btn_settings.clicked.connect(self._show_settings_window)
        top_bar.addWidget(btn_settings)
        
        main_layout.addLayout(top_bar)
        
        content_layout = QHBoxLayout()
        
        left_panel = QWidget()
        left_panel.setFixedWidth(410)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_content = QWidget()
        self.left_vbox = QVBoxLayout(left_content)
        
        self._build_control_panel()
        self.left_vbox.addStretch()
        left_scroll.setWidget(left_content)
        left_layout.addWidget(left_scroll)
        content_layout.addWidget(left_panel)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        lbl_chat = QLabel("Диалог (выделите текст для копирования)")
        lbl_chat.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        right_layout.addWidget(lbl_chat)
        
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_content = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_scroll.setWidget(self.chat_content)
        right_layout.addWidget(self.chat_scroll, stretch=1)
        
        prog_layout = QHBoxLayout()
        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        prog_layout.addWidget(self.progress_label)
        prog_layout.addWidget(self.progress_bar)
        right_layout.addLayout(prog_layout)
        
        input_layout = QHBoxLayout()
        self.text_input = QTextEdit()
        self.text_input.setFixedHeight(100)
        self.text_input.setPlaceholderText("💬 Введите запрос... (Ctrl+Enter для отправки)")
        self.text_input.setFont(QFont("Segoe UI", 11))
        
        btn_container = QWidget()
        btn_container.setFixedWidth(130)
        btn_vlayout = QVBoxLayout(btn_container)
        btn_vlayout.setContentsMargins(0, 0, 0, 0)
        btn_vlayout.setSpacing(5)
        
        self.btn_send = QPushButton("✉️ Отправить")
        self.btn_send.setFixedSize(120, 70)
        self.btn_send.setStyleSheet("background-color: #6a1b9a; font-size: 14px; font-weight: bold; padding: 5px;")
        self.btn_send.clicked.connect(self._send_text)
        
        self.btn_search = QPushButton("🌐 Поиск")
        self.btn_search.setFixedSize(120, 70)
        self.btn_search.setStyleSheet("background-color: #ef6c00; font-size: 14px; font-weight: bold; padding: 5px;")
        self.btn_search.clicked.connect(self._search_web)
        
        btn_vlayout.addWidget(self.btn_send)
        btn_vlayout.addWidget(self.btn_search)
        
        input_layout.addWidget(self.text_input)
        input_layout.addWidget(btn_container)
        right_layout.addLayout(input_layout)
        
        content_layout.addWidget(right_panel, stretch=1)
        main_layout.addLayout(content_layout)

    def _build_control_panel(self):
        gb_mic = QGroupBox("🎤 Запись с микрофона (нужно разрешить доступ)")
        l_mic = QVBoxLayout()
        self.btn_mic_start = QPushButton("⏺️ Ручная запись")
        self.btn_mic_start.setStyleSheet("background-color: #2e7d32;")
        self.btn_mic_start.clicked.connect(self._record_microphone_manual_start)
        self.btn_mic_stop = QPushButton("⏹️ Остановить")
        self.btn_mic_stop.setStyleSheet("background-color: #c62828;")
        self.btn_mic_stop.setEnabled(False)
        self.btn_mic_stop.clicked.connect(self._record_microphone_manual_stop)
        l_mic.addWidget(self.btn_mic_start)
        l_mic.addWidget(self.btn_mic_stop)
        gb_mic.setLayout(l_mic)
        self.left_vbox.addWidget(gb_mic)
        
        gb_sys = QGroupBox("🔊 Запись системного звука")
        l_sys = QVBoxLayout()
        self.btn_sys_start = QPushButton("⏺️ Начать запись")
        self.btn_sys_start.setStyleSheet("background-color: #ef6c00;")
        self.btn_sys_start.clicked.connect(self._record_system_audio_start)
        self.btn_sys_stop = QPushButton("⏹️ Остановить")
        self.btn_sys_stop.setStyleSheet("background-color: #c62828;")
        self.btn_sys_stop.setEnabled(False)
        self.btn_sys_stop.clicked.connect(self._record_system_audio_stop)
        l_sys.addWidget(self.btn_sys_start)
        l_sys.addWidget(self.btn_sys_stop)
        gb_sys.setLayout(l_sys)
        self.left_vbox.addWidget(gb_sys)
        
        gb_files = QGroupBox("📁 Файлы (распознавание содержимого в виде текста)")
        l_files = QVBoxLayout()
        btn_video = QPushButton("🎬 Загрузить видео")
        btn_video.clicked.connect(self._process_video)
        btn_audio = QPushButton("🎵 Загрузить аудио")
        btn_audio.clicked.connect(self._process_audio)
        btn_doc = QPushButton("📄 Загрузить документ (TXT/DOCX/PDF)")
        btn_doc.setStyleSheet("background-color: #00838f;")
        btn_doc.clicked.connect(self._process_document)
        l_files.addWidget(btn_video)
        l_files.addWidget(btn_audio)
        l_files.addWidget(btn_doc)
        gb_files.setLayout(l_files)
        self.left_vbox.addWidget(gb_files)
        
        gb_info = QGroupBox("📄 Загруженные файлы:")
        l_info = QVBoxLayout()
        self.lbl_vid_info = QLabel("🎬 Видео: не загружено")
        self.lbl_aud_info = QLabel("🎵 Аудио: не загружено")
        self.lbl_doc_info = QLabel("📄 Документ: не загружен")
        for lbl in [self.lbl_vid_info, self.lbl_aud_info, self.lbl_doc_info]:
            lbl.setStyleSheet("color: #aaa;")
            lbl.setWordWrap(True)
            l_info.addWidget(lbl)
        gb_info.setLayout(l_info)
        self.left_vbox.addWidget(gb_info)
        
        gb_extra = QGroupBox("💾 Сохранение")
        l_extra = QVBoxLayout()
        self.chk_save = QCheckBox("Сохранять ответы в файл")
        self.chk_save.setChecked(True)
        self.chk_save.stateChanged.connect(self._toggle_save_responses)
        
        self.combo_format = QComboBox()
        self.combo_format.addItems(["Оба", "TXT", "DOCX", "Не сохранять"])
        self.combo_format.currentTextChanged.connect(self._change_report_format)
        
        btn_folder = QPushButton("📁 Выбрать папку для отчётов")
        btn_folder.setStyleSheet("background-color: #00838f;")
        btn_folder.clicked.connect(self._change_reports_path)
        
        l_extra.addWidget(self.chk_save)
        l_extra.addWidget(self.combo_format)
        l_extra.addWidget(btn_folder)
        gb_extra.setLayout(l_extra)
        self.left_vbox.addWidget(gb_extra)
        
        gb_ctrl = QGroupBox("⚙️ Управление")
        l_ctrl = QVBoxLayout()
        self.btn_send_rec = QPushButton("🤖 Отправить распознанное в ИИ")
        self.btn_send_rec.setStyleSheet("background-color: #2e7d32;")
        self.btn_send_rec.setEnabled(False)
        self.btn_send_rec.clicked.connect(self._send_recognized_to_ai)
        
        btn_clear = QPushButton("🗑️ Очистить историю")
        btn_clear.setStyleSheet("background-color: #c62828;")
        btn_clear.clicked.connect(lambda: self.signals.clear_chat.emit())
        
        self.btn_cancel = QPushButton("⏹️ Отменить операцию")
        self.btn_cancel.setStyleSheet("background-color: #ef6c00;")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_current_operation)
        
        l_ctrl.addWidget(self.btn_send_rec)
        l_ctrl.addWidget(btn_clear)
        l_ctrl.addWidget(self.btn_cancel)
        gb_ctrl.setLayout(l_ctrl)
        self.left_vbox.addWidget(gb_ctrl)

    # ==================== TTS КОНТРОЛЬ ====================

    def _on_tts_started(self):
        self.is_speaking = True
        self.btn_send.setText("⏹️ Стоп")
        self.btn_send.setStyleSheet("background-color: #c62828; font-size: 14px; font-weight: bold; padding: 5px;")
        try:
            self.btn_send.clicked.disconnect()
        except:
            pass
        self.btn_send.clicked.connect(self._stop_tts)
        self.btn_send.setEnabled(True)
        self._set_buttons_enabled(False)

    def _on_tts_stopped(self):
        self.is_speaking = False
        self.btn_send.setText("✉️ Отправить")
        self.btn_send.setStyleSheet("background-color: #6a1b9a; font-size: 14px; font-weight: bold; padding: 5px;")
        try:
            self.btn_send.clicked.disconnect()
        except:
            pass
        self.btn_send.clicked.connect(self._send_text)
        self._set_buttons_enabled(True)
        self._force_cleanup_all_temp_files()

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_mic_start.setEnabled(enabled and not self.is_manual_recording)
        self.btn_mic_stop.setEnabled(not enabled and self.is_manual_recording)
        self.btn_sys_start.setEnabled(enabled)
        self.btn_sys_stop.setEnabled(False)
        self.btn_send_rec.setEnabled(enabled and self.last_recognized_text is not None)
        self.btn_search.setEnabled(enabled)
        self.mode_combo.setEnabled(enabled)
        self.text_input.setEnabled(enabled)
        self.btn_cancel.setEnabled(not enabled and self.is_processing)

    def _stop_tts(self):
        if self.tts:
            self.tts.stop()
        self.signals.tts_stopped.emit()

    # ==================== ПОИСК В ИНТЕРНЕТЕ ====================

    def _search_web(self):
        text = self.text_input.toPlainText().strip()
        if not text:
            self.signals.add_message.emit("error", "❌ Ошибка", "Введите поисковый запрос", None)
            return
        
        self.text_input.clear()
        self.cancel_operation = False
        self.signals.add_message.emit("user", "👤 Поиск", f"🌐 {text}", None)
        self.signals.update_process.emit("🌐 Поиск в интернете...", True)
        
        def search():
            try:
                response = self.ai.search_web(text)
                self._finish_processing(response)
            except Exception as e:
                self.signals.add_message.emit("error", "❌ Ошибка", str(e), None)
                self.signals.update_process.emit("", False)
                self.btn_send.setEnabled(True)
                self.btn_search.setEnabled(True)
        
        threading.Thread(target=search, daemon=True).start()
        self.btn_send.setEnabled(False)
        self.btn_search.setEnabled(False)

    # ==================== СИГНАЛЫ И UI ОБНОВЛЕНИЯ ====================

    def _ui_add_message(self, msg_type: str, sender: str, text: str, file_info: Optional[str]):
        bg_color = MessageColors.get(msg_type)
        is_user = (msg_type == "user")
        
        container = QWidget()
        self._message_containers.append(container)
        main_lay = QVBoxLayout(container)
        main_lay.setContentsMargins(0, 5, 0, 5)
        main_lay.setSpacing(2)
        
        header = QLabel(f"{sender} • {datetime.now().strftime('%H:%M:%S')}")
        header.setStyleSheet("color: #888; font-size: 8pt; font-weight: bold;")
        
        bubble = QFrame()
        bubble.setStyleSheet(f"QFrame {{ background-color: {bg_color}; border-radius: 8px; }}")
        bubble.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self._message_bubbles.append(bubble)
        
        bubble_lay = QVBoxLayout(bubble)
        bubble_lay.setContentsMargins(10, 10, 10, 10)
        
        msg_label = AutoResizeLabel()
        msg_label.setText(text)
        msg_label.setStyleSheet("background-color: transparent; color: #ffffff; border: none;")
        msg_label.setFont(QFont("Segoe UI", 11))
        self._message_labels.append(msg_label)
        
        bubble_lay.addWidget(msg_label)
        
        align = Qt.AlignmentFlag.AlignRight if is_user else Qt.AlignmentFlag.AlignLeft
        main_lay.addWidget(header, alignment=align)
        
        wrapper_lay = QHBoxLayout()
        wrapper_lay.setContentsMargins(0, 0, 0, 0)
        if is_user:
            wrapper_lay.addStretch()
            wrapper_lay.addWidget(bubble)
        else:
            wrapper_lay.addWidget(bubble)
            wrapper_lay.addStretch()
        
        main_lay.addLayout(wrapper_lay)
        
        if file_info:
            f_lbl = QLabel(file_info)
            f_lbl.setStyleSheet("color: #81d4fa; font-size: 8pt;")
            main_lay.addWidget(f_lbl, alignment=align)
        
        self.chat_layout.addWidget(container)
        
        # Ограничиваем количество сообщений в чате (максимум 500)
        MAX_MESSAGES = 500
        while self.chat_layout.count() > MAX_MESSAGES:
            item = self.chat_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
            if len(self._message_containers) > MAX_MESSAGES:
                self._message_containers.pop(0)
            if len(self._message_bubbles) > MAX_MESSAGES:
                self._message_bubbles.pop(0)
            if len(self._message_labels) > MAX_MESSAGES:
                self._message_labels.pop(0)
        
        QTimer.singleShot(50, lambda: self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        ))

    def _ui_update_process(self, text: str, show_progress: bool):
        self.progress_label.setText(text)
        self.progress_bar.setVisible(show_progress)
        self.btn_cancel.setEnabled(show_progress)

    def _ui_clear_chat(self):
        # Очищаем контейнеры
        for container in self._message_containers:
            if container:
                container.setParent(None)
                container.deleteLater()
        
        # Очищаем пузыри
        for bubble in self._message_bubbles:
            if bubble:
                bubble.setParent(None)
                bubble.deleteLater()
        
        # Очищаем метки
        for label in self._message_labels:
            if label:
                label.setParent(None)
                label.deleteLater()
        
        self._message_containers.clear()
        self._message_bubbles.clear()
        self._message_labels.clear()
        
        if self.ai:
            self.ai.clear_history()
            self.ai.clear_cache()
        
        self.last_recognized_text = None
        self.btn_send_rec.setEnabled(False)
        gc.collect()
        print("🧹 Чат и кэш очищены")

    def _ui_set_button_state(self, btn_name: str, state: bool):
        if hasattr(self, btn_name):
            getattr(self, btn_name).setEnabled(state)

    def _ui_update_label(self, lbl_name: str, text: str, color: str):
        if hasattr(self, lbl_name):
            lbl = getattr(self, lbl_name)
            lbl.setText(text)
            lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

    # ==================== НАСТРОЙКИ ====================

    def _toggle_save_responses(self):
        self.save_responses = self.chk_save.isChecked()

    def _change_report_format(self, value):
        fmt_map = {"Оба": "both", "TXT": "txt", "DOCX": "docx", "Не сохранять": "none"}
        self.report_format = fmt_map.get(value, "both")
        self.saver.default_format = self.report_format
    
    def _change_reports_path(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения отчётов")
        if path:
            self.reports_save_path = path
            self.saver.output_dir = path
            self.signals.add_message.emit("system", "📁 Папка отчётов", f"Отчёты будут сохраняться в:\n{path}", None)
        
    def _show_command_manager(self):
        try:
            dlg = CommandManagerGUI(self.cmd_manager, self)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dlg.exec()
        except Exception as e:
            self.signals.add_message.emit("error", "❌ Ошибка", f"Не удалось открыть управление командами: {e}", None)

    def _cancel_current_operation(self):
        self.cancel_operation = True
        self.signals.update_process.emit("⏹️ Отмена операции...", False)

    # ==================== ИНИЦИАЛИЗАЦИЯ И РЕЖИМЫ ====================

    def _init_components_async(self):
        self.signals.update_process.emit("🔄 Инициализация компонентов...", True)
        try:
            self.recognizer = SpeechRecognizer(use_local=True)
            
            # Проверяем настройки OpenRouter (только для информации)
            has_key = Config.get_openrouter_key() is not None
            has_model = Config.get_openrouter_model() is not None
            
            if not has_key or not has_model:
                # Просто уведомляем, но не блокируем локальный режим
                self.signals.add_message.emit("system", "ℹ️", 
                    "OpenRouter не настроен. Онлайн-режим будет недоступен.\n"
                    "Локальный режим (Ollama) работает без дополнительных настроек.\n"
                    "Для онлайн-режима нажмите ⚙️ и введите API ключ и модель.", None)
            
            # ВАЖНО: НЕ МЕНЯЕМ РЕЖИМ, ЕСЛИ ПОЛЬЗОВАТЕЛЬ ВЫБРАЛ ЛОКАЛЬНЫЙ
            # Только если пользователь выбрал онлайн, но нет настроек - переключаем на локальный
            if self.mode == "online" and (not has_key or not has_model):
                self.signals.add_message.emit("error", "⚠️", 
                    "Онлайн-режим не настроен! Переключаю на локальный режим.\n"
                    "Нажмите ⚙️ и введите API ключ и модель для онлайн-режима.", None)
                self.mode = "local"
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentText("💻 Локальный")
                self.mode_combo.blockSignals(False)
            
            # Инициализируем AIProcessor с выбранным режимом
            self.ai = AIProcessor(use_local=(self.mode == "local"))
            
            # Проверяем доступность Ollama для локального режима
            if self.mode == "local":
                if hasattr(self.ai, 'ollama_available') and not self.ai.ollama_available:
                    self.signals.add_message.emit("error", "⚠️", 
                        "Ollama не доступен! Установите Ollama с сайта https://ollama.com/download\n"
                        "Или настройте онлайн-режим через шестерёнку ⚙️", None)
                else:
                    self.signals.add_message.emit("system", "✅", 
                        f"Локальный режим активен. Модель: {Config.OLLAMA_MODEL}", None)
            else:
                self._init_tts()
                
            self.signals.update_process.emit(f"✅ Готово. Режим: {self.mode}", False)
        except Exception as e:
            self.signals.add_message.emit("error", "❌ Ошибка", f"Сбой: {e}", None)
            self.signals.update_process.emit("", False)

    def _change_mode(self, mode_str):
        new_mode = "local" if "Локальный" in mode_str else "online"
        
        if new_mode == "online":
            if not self._check_settings_before_online():
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentText("💻 Локальный")
                self.mode_combo.blockSignals(False)
                return
        
        self.mode = new_mode
        self.signals.update_process.emit(f"🔄 Переключение в режим: {mode_str}...", True)
        
        def switch():
            try:
                self.ai = AIProcessor(use_local=(self.mode == "local"))
                
                if self.mode != "local":
                    if self.tts is None:
                        self._init_tts()
                else:
                    if self.tts is not None:
                        self.tts.stop()
                        self.tts = None
                
                if self.mode == "local":
                    if hasattr(self.ai, 'ollama_available') and not self.ai.ollama_available:
                        self.signals.add_message.emit("error", "⚠️", 
                            "Локальный режим недоступен (Ollama не установлен)\n"
                            "Установите Ollama с сайта https://ollama.com/download\n"
                            "Или настройте онлайн-режим через шестерёнку ⚙️", None)
                    else:
                        self.signals.add_message.emit("system", "✅", "Локальный режим активен", None)
                else:
                    model_name = self.ai.model if hasattr(self.ai, 'model') and self.ai.model else "стандартная"
                    self.signals.add_message.emit("system", "✅", f"Онлайн-режим активен. Модель: {model_name}", None)
                        
                self.signals.update_process.emit(f"✅ Режим изменен на {mode_str}", False)
            except Exception as e:
                self.signals.add_message.emit("error", "❌", f"Ошибка: {e}", None)
                self.signals.update_process.emit("", False)
        
        threading.Thread(target=switch, daemon=True).start()

    # ==================== ЧТЕНИЕ ДОКУМЕНТОВ ====================

    def _process_document(self):
        if self.is_processing:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Документ", "", 
            "Документы (*.txt *.docx *.pdf);;Текстовые файлы (*.txt);;Word документы (*.docx);;PDF файлы (*.pdf)"
        )
        if not file_path:
            return
        self.cancel_operation = False
        self.current_document = file_path
        self.signals.update_label.emit("lbl_doc_info", f"📄 Документ: {os.path.basename(file_path)}", "#81d4fa")
        self.signals.add_message.emit("user", "📄 Документ", f"Загружен: {os.path.basename(file_path)}", None)
        
        def process():
            self.is_processing = True
            self.signals.update_process.emit("📖 Чтение...", True)
            try:
                text = self._read_document(file_path)
                if self.cancel_operation:
                    return
                if text and not text.startswith("Ошибка"):
                    self.signals.add_message.emit("user", "Содержимое документа", text[:self.MAX_TEXT_FOR_AI] + ("..." if len(text)>self.MAX_TEXT_FOR_AI else ""), None)
                    self.signals.update_process.emit("🤔 ИИ анализирует...", True)
                    response = self.ai.process(f"Проанализируй документ. Изложи краткое содержание:\n\n{text[:self.MAX_TEXT_FOR_AI]}")
                    if response and not self.cancel_operation:
                        self._finish_processing(response)
                else:
                    self.signals.add_message.emit("error", "❌ Ошибка чтения", text, None)
            except Exception as e:
                self.signals.add_message.emit("error", "❌ Ошибка", str(e), None)
            finally:
                self.is_processing = False
                self.signals.update_process.emit("", False)
        threading.Thread(target=process, daemon=True).start()

    def _read_document(self, file_path: str) -> str:
        if file_path.endswith('.txt'):
            for enc in ['utf-8', 'cp1251', 'windows-1251', 'koi8-r']:
                try:
                    with open(file_path, 'r', encoding=enc) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            with open(file_path, 'rb') as f:
                return f.read().decode('utf-8', errors='replace')
        
        elif file_path.endswith('.docx'):
            try:
                doc = Document(file_path)
                return '\n'.join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
            except Exception as e:
                return f"Ошибка DOCX: {e}"
        
        elif file_path.endswith('.pdf'):
            if not HAS_PDF:
                return "Ошибка: Библиотека pypdf не установлена. Установите: pip install pypdf"
            
            try:
                text_parts = []
                with open(file_path, 'rb') as f:
                    pdf_reader = pypdf.PdfReader(f)
                    for page in pdf_reader.pages:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                
                if text_parts:
                    return '\n'.join(text_parts)
                else:
                    return "Не удалось извлечь текст из PDF (возможно, файл содержит только изображения)"
            except Exception as e:
                return f"Ошибка чтения PDF: {e}"
        
        return "Неподдерживаемый формат"

    # ==================== МЕДИА ФАЙЛЫ ====================

    def _process_video(self):
        if self.is_processing:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Видео", "", "Video (*.mp4 *.avi *.mkv *.mov)")
        if not file_path:
            return
        self.cancel_operation = False
        self.current_video = file_path
        self.signals.update_label.emit("lbl_vid_info", f"🎬 Видео: {os.path.basename(file_path)}", "#81d4fa")
        self.signals.add_message.emit("user", "📹 Видео файл", f"Загружен: {os.path.basename(file_path)}", None)
        
        def process():
            self.signals.update_process.emit("🎬 Извлечение аудио...", True)
            try:
                audio_path = self.extractor.extract_from_video(file_path)
                if audio_path and not self.cancel_operation:
                    self.current_audio = audio_path
                    self._add_temp_file(audio_path)
                    self.signals.update_label.emit("lbl_aud_info", f"🎵 Аудио: {os.path.basename(audio_path)}", "#81d4fa")
                    self._process_audio_thread(audio_path, "видео", False)
                else:
                    self.signals.add_message.emit("error", "❌ Ошибка", "Не удалось извлечь аудио", None)
            except Exception as e:
                self.signals.add_message.emit("error", "❌ Ошибка", str(e), None)
            finally:
                self.signals.update_process.emit("", False)
        threading.Thread(target=process, daemon=True).start()

    def _process_audio(self):
        if self.is_processing:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Аудио", "", "Audio (*.wav *.mp3 *.m4a *.ogg *.flac)")
        if not file_path:
            return
        self.cancel_operation = False
        self.current_audio = file_path
        self.signals.update_label.emit("lbl_aud_info", f"🎵 Аудио: {os.path.basename(file_path)}", "#81d4fa")
        self.signals.add_message.emit("user", "🎵 Аудио файл", f"Загружен: {os.path.basename(file_path)}", None)
        self._add_temp_file(file_path)
        threading.Thread(target=self._process_audio_thread, args=(file_path, "аудио", False), daemon=True).start()

    # ==================== ЗАПИСЬ (МИКРОФОН И СИСТЕМА) ====================

    def _record_microphone_manual_start(self):
        if self.is_processing:
            return
        self.cancel_operation = False
        self.is_manual_recording = True
        self.manual_recording_frames = []
        self.signals.add_message.emit("user", "🎤 Микрофон", "Запись начата...", None)
        self.signals.update_process.emit("🎙️ Идет запись...", True)
        self.signals.set_button_state.emit("btn_mic_start", False)
        self.signals.set_button_state.emit("btn_mic_stop", True)
        
        def record():
            def cb(indata, f, t, s):
                if self.is_manual_recording:
                    self.manual_recording_frames.append(indata.copy())
            with sd.InputStream(samplerate=self.recorder.RATE, channels=1, callback=cb, blocksize=self.recorder.CHUNK):
                while self.is_manual_recording:
                    time.sleep(0.1)
                
            if self.manual_recording_frames and not self.cancel_operation:
                import soundfile as sf
                filename = os.path.join(Config.TEMP_DIR, f"mic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")
                sf.write(filename, np.concatenate(self.manual_recording_frames, axis=0), self.recorder.RATE)
                self.current_audio = filename
                self._add_temp_file(filename)
                self.signals.update_label.emit("lbl_aud_info", f"🎵 Аудио: {os.path.basename(filename)}", "#81d4fa")
                self._process_audio_thread(filename, "микрофон", True)
            
            self.manual_recording_frames.clear()
            
            self.signals.set_button_state.emit("btn_mic_start", True)
            self.signals.set_button_state.emit("btn_mic_stop", False)
        threading.Thread(target=record, daemon=True).start()

    def _record_microphone_manual_stop(self):
        self.is_manual_recording = False

    def _record_system_audio_start(self):
        if self.is_processing:
            return
        self.cancel_operation = False
        self.system_recording = True
        self.system_recording_frames = []
        self.system_save_filename = os.path.join(self.system_audio_save_path, f"sys_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")
        self.signals.add_message.emit("user", "🔊 Системный звук", "Запись начата...", None)
        self.signals.update_process.emit("🔊 Запись системы...", True)
        self.signals.set_button_state.emit("btn_sys_start", False)
        self.signals.set_button_state.emit("btn_sys_stop", True)
        
        def record():
            try:
                p = pyaudio.PyAudio()
                info = p.get_default_wasapi_loopback()
                stream = p.open(format=pyaudio.paInt16, channels=info['maxInputChannels'], rate=int(info['defaultSampleRate']), input=True, frames_per_buffer=self.recorder.CHUNK, input_device_index=info['index'])
                while self.system_recording:
                    try:
                        self.system_recording_frames.append(stream.read(self.recorder.CHUNK))
                    except Exception:
                        break
                stream.stop_stream()
                stream.close()
                p.terminate()
                
                if self.system_recording_frames and not self.cancel_operation:
                    with wave.open(self.system_save_filename, 'wb') as wf:
                        wf.setnchannels(info['maxInputChannels'])
                        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
                        wf.setframerate(int(info['defaultSampleRate']))
                        wf.writeframes(b''.join(self.system_recording_frames))
                    self.current_audio = self.system_save_filename
                    self._add_temp_file(self.system_save_filename)
                    self.signals.update_label.emit("lbl_aud_info", f"🎵 Аудио: {os.path.basename(self.system_save_filename)}", "#81d4fa")
                    self._process_audio_thread(self.system_save_filename, "система", False)
                
                self.system_recording_frames.clear()
                
            except Exception as e:
                self.signals.add_message.emit("error", "❌ Ошибка", str(e), None)
            finally:
                self.signals.set_button_state.emit("btn_sys_start", True)
                self.signals.set_button_state.emit("btn_sys_stop", False)
        threading.Thread(target=record, daemon=True).start()

    def _record_system_audio_stop(self):
        self.system_recording = False

    # ==================== ВЕЙК-ВОРД ====================

    def _start_wake_word(self):
        model_path = Config.VOSK_MODEL_PATH
        
        if not os.path.exists(model_path):
            alt_paths = [
                os.path.join(Config.BASE_DIR, "vosk-model-small-ru-0.22"),
                os.path.join(os.path.dirname(sys.executable), "vosk-model-small-ru-0.22"),
                r"C:\Users\user\Desktop\voice_assistant\vosk-model-small-ru-0.22",
            ]
            
            for alt in alt_paths:
                if os.path.exists(alt):
                    model_path = alt
                    break
        
        if not os.path.exists(model_path):
            self.signals.add_message.emit("error", "❌", 
                f"Модель Vosk не найдена. Вейк-ворд отключен.", None)
            return
        
        try:
            self.vosk_model = vosk.Model(model_path)
            self.vosk_recognizer = vosk.KaldiRecognizer(self.vosk_model, self.SAMPLE_RATE)
            self.wake_word_active = True
            threading.Thread(target=self._wake_word_listener, daemon=True).start()
            self.wake_indicator.setText("🟢 Аура: активен")
            self.wake_indicator.setStyleSheet("color: #4caf50; font-weight: bold;")
            self.signals.add_message.emit("system", "✅ Вейк-ворд", "Активирован! Скажите 'Аура'", None)
        except Exception as e:
            self.signals.add_message.emit("error", "❌", f"Сбой VOSK: {e}", None)

    def _wake_word_listener(self):
        try:
            with sd.RawInputStream(samplerate=self.SAMPLE_RATE, blocksize=8000, dtype='int16', channels=1, callback=lambda i,f,t,s: self.audio_queue.put(bytes(i))):
                while self.wake_word_active:
                    try:
                        data = self.audio_queue.get(timeout=0.5)
                        if self.vosk_recognizer.AcceptWaveform(data):
                            res = json.loads(self.vosk_recognizer.Result())
                            if res.get("text", "").lower() == "аура" and not self.is_listening_for_command and not self.is_processing:
                                if time.time() - self.last_wake_detection > self.WAKE_WORD_COOLDOWN:
                                    self.last_wake_detection = time.time()
                                    self.is_listening_for_command = True
                                    self.signals.add_message.emit("system", "🎯 Аура", "Слушаю...", None)
                                    self._record_microphone_and_send_to_ai()
                    except queue.Empty:
                        continue
        except Exception:
            pass

    def _record_microphone_and_send_to_ai(self):
        self.signals.update_process.emit("🎤 Слушаю...", True)
        def record():
            try:
                import soundfile as sf
                filename = os.path.join(Config.TEMP_DIR, f"mic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")
                recording, silence, speaking, stop = [], 0, False, False
                
                def cb(indata, frames, time, status):
                    nonlocal silence, speaking, stop
                    vol = np.sqrt(np.mean(indata**2))
                    if vol > self.SILENCE_THRESHOLD:
                        silence = 0
                        speaking = True
                    elif speaking:
                        silence += frames / self.SAMPLE_RATE
                        if silence >= self.SILENCE_TIMEOUT:
                            stop = True
                            raise sd.CallbackAbort()
                    recording.append(indata.copy())
                
                try:
                    with sd.InputStream(samplerate=self.SAMPLE_RATE, channels=1, callback=cb):
                        while not stop and self.is_listening_for_command and not self.cancel_operation:
                            time.sleep(0.1)
                except sd.CallbackAbort:
                    pass
                
                if recording and not self.cancel_operation:
                    audio_data = np.concatenate(recording, axis=0)
                    if len(audio_data) / self.SAMPLE_RATE > 0.5:
                        sf.write(filename, audio_data, self.SAMPLE_RATE)
                        self.current_audio = filename
                        self._add_temp_file(filename)
                        self.signals.update_label.emit("lbl_aud_info", f"🎵 Аудио: {os.path.basename(filename)}", "#81d4fa")
                        self._process_audio_thread(filename, "микрофон", send_to_ai=True)
            except Exception as e:
                self.signals.add_message.emit("error", "❌ Ошибка", str(e), None)
            finally:
                self.is_listening_for_command = False
        threading.Thread(target=record, daemon=True).start()

    # ==================== ИИ И ОБРАБОТКА ТЕКСТА ====================

    def _process_audio_thread(self, path: str, source: str, send_to_ai: bool):
        self.is_processing = True
        self.signals.update_process.emit("🔍 Распознавание...", True)
        
        self._add_temp_file(path)
        
        try:
            if self.cancel_operation:
                self._cleanup_current_temp_files()
                return
            
            text = self.recognizer.recognize(path)
            
            if self.cancel_operation:
                self._cleanup_current_temp_files()
                return
            
            if text and not text.startswith('❌'):
                self.last_recognized_text = text
                self.signals.add_message.emit("user", f"🗣️ Из: {source}", text, None)
                self.signals.set_button_state.emit("btn_send_rec", True)
                
                self._cleanup_current_temp_files()
                
                if send_to_ai:
                    if self._is_search_query(text):
                        query = self._extract_search_query(text)
                        self.signals.update_process.emit(f"🌐 Поиск в интернете: {query}", True)
                        response = self.ai.search_web(query)
                        self._finish_processing(response)
                    else:
                        self._ai_process_thread(text)
            else:
                self._cleanup_current_temp_files()
                self.signals.add_message.emit("error", "❌ Ошибка", text, None)
                
        except Exception as e:
            self._cleanup_current_temp_files()
            self.signals.add_message.emit("error", "❌ Ошибка", str(e), None)
        finally:
            self.is_processing = False
            self.signals.update_process.emit("", False)

    def _send_recognized_to_ai(self):
        if not self.last_recognized_text or self.is_processing:
            return
        text = self.last_recognized_text
        self.cancel_operation = False
        threading.Thread(target=self._ai_process_thread, args=(text,), daemon=True).start()

    def _send_text(self):
        if self.is_processing or self.is_speaking:
            return
        
        text = self.text_input.toPlainText().strip()
        self.last_recognized_text = text
        
        if not text:
            return
        
        self.text_input.clear()
        self.cancel_operation = False
        self.signals.add_message.emit("user", "👤 Вы", text, None)
        
        if self._is_search_query(text):
            query = self._extract_search_query(text)
            self.signals.update_process.emit(f"🌐 Поиск в интернете: {query}", True)
            threading.Thread(target=lambda: self._finish_processing(self.ai.search_web(query)), daemon=True).start()
        else:
            threading.Thread(target=self._ai_process_thread, args=(text,), daemon=True).start()
        
        self.btn_send.setEnabled(False)
        self.btn_search.setEnabled(False)

    def _ai_process_thread(self, text: str):
        self.is_processing = True
        self.signals.update_process.emit("🤔 ИИ анализирует...", True)
        try:
            cmd = self.cmd_manager.get_command_by_alias(text)
            if cmd:
                self.cmd_manager.execute_command(cmd)
                self.signals.add_message.emit("assistant", "🤖 Ассистент", f"Выполняю команду: {cmd['name']}", None)
                self._finish_processing(None)
            else:
                resp = self.ai.process(text)
                
                if resp and not self.cancel_operation:
                    self._finish_processing(resp)
                elif self.cancel_operation:
                    self.signals.update_process.emit("", False)
                    self.btn_send.setEnabled(True)
                    self.btn_search.setEnabled(True)
                else:
                    self.signals.add_message.emit("error", "❌ Ошибка", "Не удалось получить ответ от ИИ", None)
                    self.signals.update_process.emit("", False)
                    self.btn_send.setEnabled(True)
                    self.btn_search.setEnabled(True)
        except Exception as e:
            self.signals.add_message.emit("error", "❌ Ошибка", str(e), None)
            self.btn_send.setEnabled(True)
            self.btn_search.setEnabled(True)
        finally:
            self.is_processing = False

    def _is_error_response(self, text: str) -> bool:
        if not text:
            return True
        
        error_patterns = [
            "❌", "ошибка", "error", "не удалось", "failed", "exception",
            "извините, произошла ошибка", "не получилось", "не могу обработать",
            "что-то пошло не так", "не удалось распознать", "не найден",
            "не доступен", "таймаут", "timeout", "неверный", "invalid"
        ]
        
        text_lower = text.lower()
        for pattern in error_patterns:
            if pattern in text_lower or pattern in text:
                return True
        return False

    def _finish_processing(self, response: Optional[str]):
        if response:
            self.signals.add_message.emit("assistant", "🤖 Ассистент", response, None)
            
            is_error = self._is_error_response(response)
            
            if not is_error and self.save_responses and self.report_format != "none":
                self._save_report(response)
            
            if self.mode == "online" and self.tts and not is_error:
                self.signals.tts_started.emit()
                self.signals.update_process.emit("🔊 Озвучивание...", True)
                
                def on_tts_finished():
                    self.signals.update_process.emit("", False)
                    self.signals.tts_stopped.emit()
                    self.btn_send.setEnabled(True)
                    self.btn_search.setEnabled(True)
                
                def speak_quick():
                    try:
                        clean_text = response.replace('\n', ' ').replace('  ', ' ')
                        self.tts.say(clean_text, on_tts_finished)
                    except Exception as e:
                        log.error(f"TTS Error: {e}")
                        on_tts_finished()
                
                threading.Thread(target=speak_quick, daemon=True).start()
                return
            
            self.signals.update_process.emit("", False)
            self.btn_send.setEnabled(True)
            self.btn_search.setEnabled(True)
        else:
            self.signals.update_process.emit("", False)
            self.btn_send.setEnabled(True)
            self.btn_search.setEnabled(True)
        
        self.cancel_operation = False
        self._force_cleanup_all_temp_files()

    def _save_report(self, response: str):
        try:
            paths = self.saver.save_report(text=self.last_recognized_text, analysis=response, format=self.report_format, output_dir=self.reports_save_path)
            for fmt, path in paths.items():
                if path:
                    self.signals.update_process.emit(f"📄 Сохранено: {os.path.basename(path)}", False)
        except Exception as e:
            print(e)


if __name__ == "__main__":
    Config.setup_directories()
    Config.load_env()
    
    app = QApplication(sys.argv)
    window = VoiceAssistantGUI()
    window.show()
    sys.exit(app.exec())