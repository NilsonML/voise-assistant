# core/command_manager.py
# Пользовательские голосовые команды — например, "открой браузер" или "калькулятор"

import json
import os
import subprocess
import webbrowser
from typing import List, Dict, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QLabel, QTextEdit, QComboBox
)
from PyQt6.QtCore import Qt


class CommandManager:
    """Хранит список команд и умеет их выполнять"""
    
    def __init__(self, commands_file: str = "commands.json"):
        self.commands_file = commands_file
        self.commands = []
        self.load_commands()
    
    def load_commands(self):
        """Загружаем команды из JSON-файла, если нет — создаём стандартные"""
        if os.path.exists(self.commands_file):
            try:
                with open(self.commands_file, 'r', encoding='utf-8') as f:
                    self.commands = json.load(f)
            except:
                self.commands = self._get_default_commands()
        else:
            self.commands = self._get_default_commands()
            self.save_commands()
    
    def save_commands(self):
        """Сохраняем команды в JSON-файл"""
        with open(self.commands_file, 'w', encoding='utf-8') as f:
            json.dump(self.commands, f, ensure_ascii=False, indent=2)
    
    def _get_default_commands(self) -> List[Dict]:
        """Стандартные команды (без поисковых запросов, чтобы не мешать)"""
        return [
            {
                "name": "Открыть браузер",
                "phrases": ["открой браузер", "запусти браузер", "браузер"],
                "action_type": "url",
                "action": "https://www.google.com"
            },
            {
                "name": "Открыть YouTube",
                "phrases": ["открой ютуб", "включи ютуб", "youtube"],
                "action_type": "url",
                "action": "https://www.youtube.com"
            },
            {
                "name": "Блокнот",
                "phrases": ["открой блокнот", "запусти блокнот", "блокнот"],
                "action_type": "app",
                "action": "notepad.exe"
            },
            {
                "name": "Калькулятор",
                "phrases": ["открой калькулятор", "калькулятор", "посчитай"],
                "action_type": "app",
                "action": "calc.exe"
            },
            {
                "name": "Проводник",
                "phrases": ["открой проводник", "проводник", "мои документы"],
                "action_type": "folder",
                "action": os.path.expanduser("~")
            }
        ]
    
    def get_command_by_alias(self, text: str) -> Optional[Dict]:
        """Ищем команду по фразе. Если похоже на поисковый запрос — пропускаем."""
        text_lower = text.lower().strip()
        
        # Слова, которые означают, что пользователь хочет искать в интернете, а не выполнять команду
        search_triggers = ["найди", "поищи", "поиск", "найти", "узнай", "расскажи о"]
        for trigger in search_triggers:
            if trigger in text_lower:
                return None
        
        for cmd in self.commands:
            for phrase in cmd.get("phrases", []):
                if phrase.lower() in text_lower:
                    return cmd
        return None
    
    def execute_command(self, command: Dict):
        """Выполняем действие команды: открываем сайт, программу, папку или файл"""
        try:
            action_type = command.get("action_type", "url")
            action = command.get("action")
            
            if action_type == "url":
                webbrowser.open(action)
            elif action_type == "app":
                subprocess.Popen(action, shell=True)
            elif action_type == "folder":
                os.startfile(action)
            elif action_type == "file":
                os.startfile(action)
                
        except Exception as e:
            print(f"Ошибка выполнения команды: {e}")


class CommandManagerGUI(QDialog):
    """Окошко для редактирования команд (добавлять, удалять, менять)"""
    
    def __init__(self, cmd_manager: CommandManager, parent=None):
        super().__init__(parent)
        self.cmd_manager = cmd_manager
        self.setWindowTitle("📋 Управление командами")
        self.setMinimumSize(800, 600)
        
        self.setup_ui()
        self.load_commands()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        info_label = QLabel(
            "🎤 Голосовые команды\n\n"
            "Добавьте команды, которые будет понимать ассистент.\n"
            "Пример: если сказать 'открой YouTube' - откроется сайт."
        )
        info_label.setStyleSheet("color: #aaa; padding: 10px; background-color: #1e1e1e; border-radius: 5px;")
        layout.addWidget(info_label)
        
        # Таблица команд
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Название", "Фразы (через запятую)", "Тип", "Действие"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("alternate-background-color: #2a2a2a;")
        layout.addWidget(self.table)
        
        # Кнопки управления
        btn_layout = QHBoxLayout()
        
        btn_add = QPushButton("➕ Добавить команду")
        btn_add.setStyleSheet("background-color: #2e7d32;")
        btn_add.clicked.connect(self.add_command)
        
        btn_edit = QPushButton("✏️ Редактировать")
        btn_edit.setStyleSheet("background-color: #1f538d;")
        btn_edit.clicked.connect(self.edit_command)
        
        btn_delete = QPushButton("🗑️ Удалить")
        btn_delete.setStyleSheet("background-color: #c62828;")
        btn_delete.clicked.connect(self.delete_command)
        
        btn_save = QPushButton("💾 Сохранить")
        btn_save.setStyleSheet("background-color: #6a1b9a;")
        btn_save.clicked.connect(self.save_commands)
        
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        
        layout.addLayout(btn_layout)
    
    def load_commands(self):
        """Показываем команды в таблице"""
        self.table.setRowCount(len(self.cmd_manager.commands))
        
        type_map = {
            "url": "🌐 Сайт",
            "app": "📱 Программа",
            "folder": "📁 Папка",
            "file": "📄 Файл"
        }
        
        for row, cmd in enumerate(self.cmd_manager.commands):
            self.table.setItem(row, 0, QTableWidgetItem(cmd.get("name", "")))
            phrases = ", ".join(cmd.get("phrases", []))
            self.table.setItem(row, 1, QTableWidgetItem(phrases))
            action_type = cmd.get("action_type", "url")
            self.table.setItem(row, 2, QTableWidgetItem(type_map.get(action_type, action_type)))
            self.table.setItem(row, 3, QTableWidgetItem(cmd.get("action", "")))
    
    def add_command(self):
        """Открываем диалог добавления новой команды"""
        dialog = CommandEditDialog(self)
        if dialog.exec():
            command = dialog.get_command()
            if command:
                self.cmd_manager.commands.append(command)
                self.load_commands()
    
    def edit_command(self):
        """Редактируем выбранную команду"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите команду для редактирования")
            return
        
        command = self.cmd_manager.commands[row]
        dialog = CommandEditDialog(self, command)
        if dialog.exec():
            new_command = dialog.get_command()
            if new_command:
                self.cmd_manager.commands[row] = new_command
                self.load_commands()
    
    def delete_command(self):
        """Удаляем выбранную команду"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите команду для удаления")
            return
        
        reply = QMessageBox.question(self, "Подтверждение", 
                                     "Удалить команду?", 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.cmd_manager.commands.pop(row)
            self.load_commands()
    
    def save_commands(self):
        """Сохраняем все команды в файл"""
        self.cmd_manager.save_commands()
        QMessageBox.information(self, "Успех", "Команды сохранены!")


class CommandEditDialog(QDialog):
    """Диалоговое окно для создания или редактирования одной команды"""
    
    def __init__(self, parent=None, command=None):
        super().__init__(parent)
        self.command = command.copy() if command else None
        self.setWindowTitle("Редактирование команды" if command else "Новая команда")
        self.setMinimumWidth(500)
        
        self.setup_ui()
        if self.command:
            self.load_data()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("📝 Название команды:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Например: Открыть YouTube")
        layout.addWidget(self.name_edit)
        
        layout.addWidget(QLabel("🎤 Фразы для активации (через запятую):"))
        self.phrases_edit = QTextEdit()
        self.phrases_edit.setMaximumHeight(80)
        self.phrases_edit.setPlaceholderText("Например:\nоткрой ютуб, включи ютуб, youtube")
        layout.addWidget(self.phrases_edit)
        
        layout.addWidget(QLabel("🔧 Тип действия:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["🌐 Открыть сайт", "📱 Запустить программу", "📁 Открыть папку", "📄 Открыть файл"])
        layout.addWidget(self.type_combo)
        
        layout.addWidget(QLabel("📍 Путь/ссылка:"))
        self.action_edit = QLineEdit()
        self.action_edit.setPlaceholderText("https://...  или  C:\\путь\\к\\файлу.exe")
        layout.addWidget(self.action_edit)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 Сохранить")
        btn_save.setStyleSheet("background-color: #2e7d32;")
        btn_save.clicked.connect(self.accept)
        
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
    
    def load_data(self):
        """Заполняем поля из существующей команды"""
        if not self.command:
            return
        
        self.name_edit.setText(self.command.get("name", ""))
        phrases = ", ".join(self.command.get("phrases", []))
        self.phrases_edit.setPlainText(phrases)
        
        type_map = {
            "url": 0, "app": 1, "folder": 2, "file": 3
        }
        action_type = self.command.get("action_type", "url")
        self.type_combo.setCurrentIndex(type_map.get(action_type, 0))
        self.action_edit.setText(self.command.get("action", ""))
    
    def get_command(self) -> Optional[Dict]:
        """Собираем данные из полей в словарь команды"""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Введите название команды")
            return None
        
        phrases_text = self.phrases_edit.toPlainText().strip()
        if not phrases_text:
            QMessageBox.warning(self, "Ошибка", "Введите хотя бы одну фразу для активации")
            return None
        
        phrases = [p.strip() for p in phrases_text.split(",") if p.strip()]
        
        action = self.action_edit.text().strip()
        if not action:
            QMessageBox.warning(self, "Ошибка", "Введите путь или ссылку")
            return None
        
        type_map = {
            "🌐 Открыть сайт": "url",
            "📱 Запустить программу": "app",
            "📁 Открыть папку": "folder",
            "📄 Открыть файл": "file"
        }
        
        return {
            "name": name,
            "phrases": phrases,
            "action_type": type_map.get(self.type_combo.currentText(), "url"),
            "action": action
        }