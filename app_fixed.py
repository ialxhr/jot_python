"""
БЫСТРЫЙ ЗАМЕТЧИК ДЛЯ OBSIDIAN v3.5
===================================
Лёгкое, сверхбыстрое приложение для работы с заметками в стиле Obsidian.
Максимальная поддержка стандартов Markdown (CommonMark, GFM, Obsidian).
Оптимизировано для слабого железа (4GB RAM, Core i5 2010 и слабее).

Особенности v3.5:
  * Полноценный Smart Paste:
      - Преобразование HTML в Markdown со сохранением заголовков ссылок и таблиц.
      - Вставка текста из ИИ (ChatGPT, Gemini, Claude) без рассыпания разметки.
      - Вставка чистого URL при выделенном тексте -> [Выделенный текст](url).
      - Вставка одиночного URL -> красивое [Название ссылки](url).
      - Автополучение названий видео с YouTube через oEmbed API в фоновом потоке.
  * Естественные цвета эмодзи и пиктограмм (🚀, 🛠) даже внутри ссылок и стилей.
  * Исправленный стандарт ежедневной заметки (реальное время HH:MM, чистый стиль).
  * Бесшовный плоский интерфейс без разделяющей рамки между деревом и редактором.
  * Нулевой след на диске: файл конфигурации НЕ создаётся (хранилище по умолчанию —
    папка запуска программы, смена папки действует только на текущий сеанс).
  * Чистая архитектура для прямого портирования в WinAPI / Assembler x64.
"""

import os
import gc
import re
import json
import threading
import urllib.request
from urllib.parse import urlparse
import ctypes
from ctypes import wintypes
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ==============================================================================
# СКОМПИЛИРОВАННЫЕ ШАБЛОНЫ MARKDOWN (компиляция 1 раз при старте программы)
# ==============================================================================

RE_HR = re.compile(r"^\s*(?:-\s*-\s*-[\s-]*|\*\s*\*\s*\*[\s*]*|_\s*_\s*_[\s_]*)\s*$")
RE_NUM_LIST = re.compile(r"^(\s*)(\d+)[.)]\s")
RE_BULLET = re.compile(r"^(\s*)([-*+•])\s")
RE_CHECKBOX_LINE = re.compile(r"^(\s*)[-*+]\s+\[([ xX\-\/])\](?:\s+(.*))?$")
RE_CALLOUT_START = re.compile(r"^\s*>\s*\[!([a-zA-Z]+)\]\s*(.*)$")
RE_BLOCKQUOTE = re.compile(r"^\s*>+\s*")
RE_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
RE_MATH_BLOCK = re.compile(r"^\s*\$\$\s*$")

# Инлайн шаблоны
RE_BOLD_ITALIC = re.compile(r"(?:\*\*\*([^\*\n]+)\*\*\*|___([^_\n]+)___)")
RE_BOLD = re.compile(r"(?:\*\*([^\*\n]+)\*\*|__([^_\n]+)__)")
RE_ITALIC = re.compile(r"(?:(?<!\*)\*([^\*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_))")
RE_CODE_INLINE = re.compile(r"`([^`\n]+)`")
RE_HIGHLIGHT = re.compile(r"==([^=\n]+)==")
RE_STRIKE = re.compile(r"~~([^~\n]+)~~")
RE_MATH_INLINE = re.compile(r"(?<!\$)\$(?!\$)([^\$\n]+)\$(?!\$)")
RE_WIKILINK = re.compile(r"\[\[([^\]\n]+)\]\]")
RE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
RE_MDLINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+[\"']([^\"']+)[\"'])?\)")
RE_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
RE_BARE_URL = re.compile(r'(?<![\w"=])(https?://[^\s<]+)')
RE_TAG = re.compile(r"(?:(?<=^)|(?<=\s))#([a-zA-Zа-яА-Я0-9_/-]+)(?=\s|$)")
RE_HTTP_URL = re.compile(r"^https?://[^\s<>]+$", re.IGNORECASE)
RE_BARE_WEB_URL = re.compile(r"^(?:(?:https?:)?//)?(?:www\.)?(?:youtube\.com|youtu\.be|[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?:/[^\s<>]*)?$", re.IGNORECASE)
RE_INVALID_FILENAME = re.compile(r'[\\/*?:"<>|]')

# Естественные цветные эмодзи и пиктограммы (🚀, 🛠, 📝 и др.)
RE_EMOJI = re.compile(r'[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b00-\u2bff\u203c\u2049\u2122\u2139\u3030\u303d\u3297\u3299]')

MD_TAGS = (
    "h1", "h2", "h3", "h4", "h5", "h6",
    "bold", "italic", "bold_italic", "code", "code_block", "code_fence",
    "checkbox_todo", "checkbox_done", "checkbox_cancel", "checkbox_progress",
    "bullet_list", "number_list", "wikilink", "md_link", "md_image",
    "hide_markup", "hr", "highlight", "strike", "quote",
    "callout_header", "callout_body",
    "table_block", "table_header", "table_row", "table_row_alt", "table_sep",
    "math", "tag", "frontmatter",
    "emoji",
)

def normalize_web_url(value):
    """Нормализует URL из буфера, включая www.youtube.com без схемы."""
    value = value.strip().strip("<>\"'«»").rstrip(".,;)")
    if value.startswith("//"):
        return "https:" + value
    if re.match(r"^https?://", value, re.I):
        return value
    if RE_BARE_WEB_URL.fullmatch(value):
        return "https://" + value
    return value


def _display_bullets(text):
    """Показывает Markdown-списки со звездочкой как типографский • внутри редактора."""
    return re.sub(r"^(\s*)\*\s", r"\1• ", text, flags=re.M)


def _markdown_bullets(text):
    """Возвращает визуальные •-списки обратно в валидный Markdown со звездочкой."""
    return re.sub(r"^(\s*)•\s", r"\1* ", text, flags=re.M)


def is_http_url(value):
    return bool(RE_HTTP_URL.fullmatch(normalize_web_url(value)))


def safe_note_name(value, fallback="Новая заметка"):
    """Возвращает безопасное имя Markdown-файла без запрещённых Windows-символов."""
    name = RE_INVALID_FILENAME.sub("", value).strip().rstrip(".")
    return name or fallback


def write_text_atomic(path, content):
    """Атомарно записывает UTF-8 текст в пределах одного каталога."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ==============================================================================
# ПАРСЕР HTML В ЧИСТЫЙ MARKDOWN (Стандартная библиотека, без внешних пакетов)
# ==============================================================================

class HTMLToMarkdownConverter(HTMLParser):
    """Преобразует HTML из буфера обмена в аккуратный Markdown.

    Важный принцип: сначала разбираем HTML, а plain-text используем только
    как fallback. Это особенно важно для копирования из ChatGPT/браузера,
    где clipboard содержит и визуально отформатированный HTML, и plain text.
    """

    BLOCK_TAGS = {
        "address", "article", "aside", "div", "dl", "dt", "dd", "fieldset",
        "figcaption", "figure", "footer", "form", "header", "main", "nav",
        "section", "summary", "details",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.result = []
        self.link_href = None
        self.link_text = []
        self.skip_tags = {'script', 'style', 'button', 'svg', 'nav', 'header', 'footer', 'noscript'}
        self.skip_depth = 0
        self.in_pre = False
        self.pre_buffer = []
        self.list_stack = []
        self.in_table = False
        self.table_rows = []
        self.current_row = []
        self.current_cell = []
        self.in_cell = False
        self._link_inline_stack = []

    def _append(self, text):
        if not text:
            return
        if self.link_href is not None:
            self.link_text.append(text)
        elif self.in_cell:
            self.current_cell.append(text)
        else:
            self.result.append(text)

    def _newline(self, count=1):
        target = self.link_text if self.link_href is not None else self.result
        if not target:
            if self.link_href is not None:
                target.append("\n" * count)
            else:
                self.result.append("\n" * count)
            return
        current = target[-1] if isinstance(target[-1], str) else ""
        if current.endswith("\n" * count):
            return
        target.append("\n" * count)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.skip_tags:
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return

        attr_dict = dict(attrs)

        if self.in_pre:
            if tag == "code":
                return
            return

        if tag in ('strong', 'b'):
            self._append('**')
        elif tag in ('em', 'i'):
            self._append('*')
        elif tag in ('s', 'del', 'strike'):
            self._append('~~')
        elif tag == 'mark':
            self._append('==')
        elif tag == 'code':
            self._append('`')
        elif tag == 'pre':
            self.in_pre = True
            self.pre_buffer = []
        elif tag == 'a':
            href = unescape(attr_dict.get('href', '').strip())
            if href:
                self.link_href = normalize_web_url(href)
                self.link_text = []
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            level = int(tag[1])
            self._append('\n\n' + '#' * level + ' ')
        elif tag == 'blockquote':
            self._append('\n\n> ')
        elif tag == 'ul':
            self.list_stack.append(('ul', 0))
            self._append('\n')
        elif tag == 'ol':
            self.list_stack.append(('ol', 0))
            self._append('\n')
        elif tag == 'li':
            depth = max(0, len(self.list_stack) - 1)
            indent = '  ' * depth
            if self.list_stack and self.list_stack[-1][0] == 'ol':
                num = self.list_stack[-1][1] + 1
                self.list_stack[-1] = ('ol', num)
                self._append(f'\n{indent}{num}. ')
            else:
                self._append(f'\n{indent}- ')
        elif tag == 'table':
            self.in_table = True
            self.table_rows = []
        elif tag == 'tr':
            self.current_row = []
        elif tag in ('th', 'td'):
            self.in_cell = True
            self.current_cell = []
        elif tag == 'img':
            alt = unescape(attr_dict.get('alt', ''))
            src = unescape(attr_dict.get('src', ''))
            if src:
                self._append(f'![{alt}]({src})')
        elif tag == 'hr':
            self._append('\n\n---\n\n')
        elif tag == 'br':
            self._append('\n')
        elif tag == 'p':
            self._append('\n\n')
        elif tag in self.BLOCK_TAGS:
            self._append('\n')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.skip_tags:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth > 0:
            return

        if tag == 'pre':
            code = ''.join(self.pre_buffer).strip('\n')
            self.in_pre = False
            self.pre_buffer = []
            self._append('\n\n```\n' + code + '\n```\n\n')
        elif tag in ('strong', 'b'):
            self._append('**')
        elif tag in ('em', 'i'):
            self._append('*')
        elif tag in ('s', 'del', 'strike'):
            self._append('~~')
        elif tag == 'mark':
            self._append('==')
        elif tag == 'code':
            self._append('`')
        elif tag == 'a':
            if self.link_href is not None:
                title = ''.join(self.link_text).strip()
                href = self.link_href
                self.link_href = None
                self.link_text = []
                if not title:
                    title = href
                self._append(f'[{title}]({href})')
        elif tag in ('ul', 'ol'):
            if self.list_stack:
                self.list_stack.pop()
            self._append('\n')
        elif tag == 'blockquote':
            self._append('\n')
        elif tag in ('th', 'td'):
            self.in_cell = False
            cell_text = ''.join(self.current_cell).strip().replace('\n', ' ')
            self.current_row.append(cell_text)
        elif tag == 'tr':
            if self.current_row:
                self.table_rows.append(self.current_row)
        elif tag == 'table':
            self.in_table = False
            if self.table_rows:
                col_count = max(len(row) for row in self.table_rows)
                if col_count:
                    rows = []
                    for row in self.table_rows:
                        padded = row + [''] * (col_count - len(row))
                        rows.append(padded)
                    table_md = ['\n', '| ' + ' | '.join(rows[0]) + ' |',
                                '| ' + ' | '.join(['---'] * col_count) + ' |']
                    table_md.extend('| ' + ' | '.join(row) + ' |' for row in rows[1:])
                    table_md.append('\n')
                    self._append('\n'.join(table_md))
        elif tag in self.BLOCK_TAGS or tag == 'p':
            self._append('\n')

    def handle_data(self, data):
        if self.skip_depth > 0:
            return
        if self.in_pre:
            self.pre_buffer.append(data)
            return
        self._append(data)

    def get_markdown(self):
        raw = ''.join(self.result)
        clean = unescape(raw)
        # Убираем пробелы перед переводом строки, но не ломаем отступы списков/кода.
        clean = re.sub(r'[ \t]+\n', '\n', clean)
        clean = re.sub(r'\n[ \t]+\n', '\n\n', clean)
        clean = re.sub(r'\n{3,}', '\n\n', clean)
        return clean.strip()


# ==============================================================================
# ВСПЛЫВАЮЩИЕ ПОДСКАЗКИ
# ==============================================================================

class ToolTip:
    """Всплывающие подсказки с гарантированным Topmost."""

    def __init__(self, widget, text, delay=350):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip_window = None
        self.timer_id = None
        self.widget.bind("<Enter>", self.schedule, add="+")
        self.widget.bind("<Leave>", self.hide, add="+")
        self.widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, event=None):
        self.unschedule()
        self.timer_id = self.widget.after(self.delay, self.show)

    def unschedule(self):
        if self.timer_id:
            self.widget.after_cancel(self.timer_id)
            self.timer_id = None

    def show(self, event=None):
        if self.tooltip_window or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 5
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
            self.tooltip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            tw.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                tw, text=self.text, justify=tk.LEFT,
                background="#1e293b", foreground="#f8fafc",
                font=("Segoe UI", 8), relief=tk.SOLID,
                borderwidth=1, padx=6, pady=3
            )
            label.pack()
        except Exception:
            pass

    def hide(self, event=None):
        self.unschedule()
        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except Exception:
                pass
            self.tooltip_window = None


# ==============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ФОРМАТИРОВАНИЯ ТАБЛИЦ
# ==============================================================================

def format_markdown_table_lines(lines):
    """Выравнивает столбцы Markdown-таблицы по ширине с красивыми рамками и выравниванием (center/right/left)."""
    rows = []
    for line in lines:
        parts = [p.strip() for p in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        rows.append(parts)
    if not rows:
        return lines
    num_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < num_cols:
            r.append('')

    # Находим строку-разделитель и вычисляем выравнивание для каждого столбца
    alignments = ['left'] * num_cols
    for r in rows:
        if all(re.match(r'^:?-+:?$', cell) or not cell for cell in r) and any(cell for cell in r):
            for c, cell in enumerate(r):
                left = cell.startswith(':')
                right = cell.endswith(':')
                if left and right:
                    alignments[c] = 'center'
                elif right:
                    alignments[c] = 'right'
                else:
                    alignments[c] = 'left'
            break

    widths = [max(3, max(len(r[c]) for r in rows)) for c in range(num_cols)]
    out = []
    for r in rows:
        is_sep = all(re.match(r'^:?-+:?$', cell) or not cell for cell in r) and any(cell for cell in r)
        if is_sep:
            cells = []
            for c, cell in enumerate(r):
                w = widths[c]
                align = alignments[c]
                if align == 'center':
                    cells.append(':' + '-' * max(1, w - 2) + ':')
                elif align == 'right':
                    cells.append('-' * max(2, w - 1) + ':')
                elif align == 'left' and cell.startswith(':'):
                    cells.append(':' + '-' * max(2, w - 1))
                else:
                    cells.append('-' * max(3, w))
            out.append('| ' + ' | '.join(cells) + ' |')
        else:
            cells = []
            for c, cell in enumerate(r):
                w = widths[c]
                align = alignments[c]
                if align == 'center':
                    cells.append(cell.center(w))
                elif align == 'right':
                    cells.append(cell.rjust(w))
                else:
                    cells.append(cell.ljust(w))
            out.append('| ' + ' | '.join(cells) + ' |')
    return out


# ==============================================================================
# ГЛАВНЫЙ КЛАСС ПРИЛОЖЕНИЯ
# ==============================================================================

class QuickObsidianNotesApp(tk.Tk):
    """Главный класс приложения заметок (полностью in-memory конфигурация)."""

    def __init__(self):
        super().__init__()

        # 1. Начальная инициализация: папка запуска программы
        self.vault_path = Path.cwd()
        self.daily_notes_folder = "DailyNotes"
        self._title_cache = {}
        self._yt_title_cache = {}

        # Состояния сеанса (не сохраняются на диске)
        self.current_theme = "dark"
        self.always_on_top = False
        self.live_preview_enabled = True
        self.current_note_path = None
        self.current_target_folder = self.vault_path
        self.is_saving_internal = False
        self.is_modified = False
        self.is_mini_mode = False
        self.help_window = None
        self.mini_icon_window = None
        self._rendered_tables = {}
        self.normal_geometry = "950x640"

        # Состояние мини-иконки
        self._mini_drag_start_x = 0
        self._mini_drag_start_y = 0
        self._mini_press_x = 0
        self._mini_press_y = 0
        self._mini_dragging = False
        self._mini_edge = "top"
        self._mini_hide_timer = None
        self._mini_anim_timer = None
        self._mini_monitor = None
        self._mini_full_x = None
        self._mini_full_y = None
        self._editor_font_size = 11

        self._save_timer = None
        self._highlight_timer = None
        self._search_timer = None
        self._indent_tag_cache = set()
        self._folded_headings = set()
        self._fold_markers = []

        # Динамическая регистрация формата HTML буфера обмена (Win32 API)
        self._cf_html = self._register_cf_html()

        # 2. Цветовые палитры (Obsidian Dark / Clean Light)
        self.theme_palettes = {
            "dark": {
                "bg_sidebar": "#18181b",
                "bg_editor": "#1f1f23",
                "text_main": "#e4e4e7",
                "text_muted": "#a1a1aa",
                "accent": "#60a5fa",
                "accent_light": "#1e293b",
                "btn_bg": "#27272a",
                "btn_hover": "#3f3f46",
                "btn_active": "#1d4ed8",
                "tag_header": "#38bdf8",
                "tag_bold": "#ffffff",
                "tag_code": "#f472b6",
                "tag_code_bg": "#141416",
                "tag_code_fence_bg": "#18181c",
                "tag_done": "#71717a",
                "tag_highlight": "#854d0e",
                "tag_highlight_fg": "#fef08a",
                "tag_quote": "#27272a",
                "tag_strike": "#71717a",
                "tag_table": "#1e293b",
                "tag_table_bg": "#18181c",
                "tag_table_header_bg": "#18181c",
                "tag_table_sep_bg": "#1e1e24",
                "tag_table_alt_bg": "#1a1a20",
                "table_border": "#333333",
                "tag_tag": "#a78bfa",
                "tag_math": "#34d399",
                "tag_emoji": "#f59e0b",
                "tree_bg": "#18181b",
                "tree_fg": "#e4e4e7",
                "status_bg": "#141416",
                "status_fg": "#a1a1aa",
            },
            "light": {
                "bg_sidebar": "#f4f5f7",
                "bg_editor": "#ffffff",
                "text_main": "#1f2937",
                "text_muted": "#6b7280",
                "accent": "#2563eb",
                "accent_light": "#eff6ff",
                "btn_bg": "#ffffff",
                "btn_hover": "#f3f4f6",
                "btn_active": "#dbeafe",
                "tag_header": "#0369a1",
                "tag_bold": "#111827",
                "tag_code": "#be185d",
                "tag_code_bg": "#f3f4f6",
                "tag_code_fence_bg": "#e5e7eb",
                "tag_done": "#9ca3af",
                "tag_highlight": "#fef08a",
                "tag_highlight_fg": "#713f12",
                "tag_quote": "#f3f4f6",
                "tag_strike": "#9ca3af",
                "tag_table": "#f1f5f9",
                "tag_table_bg": "#ffffff",
                "tag_table_header_bg": "#f8fafc",
                "tag_table_sep_bg": "#f1f5f9",
                "tag_table_alt_bg": "#ffffff",
                "table_border": "#cbd5e1",
                "tag_tag": "#7c3aed",
                "tag_math": "#059669",
                "tag_emoji": "#d97706",
                "tree_bg": "#f4f5f7",
                "tree_fg": "#1f2937",
                "status_bg": "#e5e7eb",
                "status_fg": "#4b5563",
            },
        }
        self.colors = self.theme_palettes[self.current_theme]

        # 3. Настройка главного окна
        self.title("Быстрый Заметчик (Obsidian)")
        self.geometry(self.normal_geometry)
        self.minsize(280, 240)
        self.attributes("-topmost", self.always_on_top)
        self.configure(bg=self.colors["bg_sidebar"])

        # 4. Построение интерфейса
        self._setup_styles()
        self._build_top_toolbar()
        self._build_main_layout()
        self._build_status_bar()
        self._build_context_menus()

        # 5. Применение темы и загрузка заметок
        self.apply_theme()
        self.refresh_notes_tree()

        # 6. Глобальные и редакторские привязки
        self._bind_shortcuts()

        self.bind("<FocusOut>", self._on_focus_out)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    @property
    def daily_path(self):
        """Папка для ежедневных заметок: DailyNotes (если существует) или корневая папка запуска."""
        dn = self.vault_path / self.daily_notes_folder
        return dn if dn.is_dir() else self.vault_path

    # ==========================================================================
    # ИСПРАВЛЕНИЕ BUFER ОБМЕНА ЧЕРЕЗ WIN32 API (RegisterClipboardFormatW)
    # ==========================================================================

    def _register_cf_html(self):
        """Динамически регистрирует формат буфера обмена 'HTML Format' в Windows."""
        if os.name != "nt":
            return None
        try:
            user32 = ctypes.windll.user32
            user32.RegisterClipboardFormatW.restype = ctypes.c_uint
            user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
            fmt_id = user32.RegisterClipboardFormatW("HTML Format")
            return fmt_id if fmt_id != 0 else None
        except Exception:
            return None

    def _get_clipboard_html(self):
        """Надёжно извлекает CF_HTML из буфера Windows."""
        if os.name != "nt" or not self._cf_html:
            return None
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(self._cf_html)
            if not handle:
                return None
            kernel32.GlobalLock.restype = ctypes.c_void_p
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                raw_bytes = ctypes.string_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
            if not raw_bytes:
                return None
            raw = raw_bytes.decode("utf-8", errors="replace")

            marker = re.search(
                r"<!--\s*StartFragment\s*-->(.*?)<!--\s*EndFragment\s*-->",
                raw, flags=re.I | re.S,
            )
            if marker:
                return marker.group(1)

            def header_offset(name):
                m = re.search(rf"^{name}:(\d+)", raw, flags=re.I | re.M)
                return int(m.group(1)) if m else None

            start_fragment = header_offset("StartFragment")
            end_fragment = header_offset("EndFragment")
            if start_fragment is not None and end_fragment is not None:
                return raw_bytes[start_fragment:end_fragment].decode("utf-8", errors="replace")

            start_html = header_offset("StartHTML")
            end_html = header_offset("EndHTML")
            if start_html is not None and end_html is not None:
                return raw_bytes[start_html:end_html].decode("utf-8", errors="replace")

            start = raw.lower().find("<html")
            return raw[start:] if start >= 0 else None
        except Exception:
            return None
        finally:
            user32.CloseClipboard()

    # УМНЫЙ SMART PASTE ДЛЯ ССЫЛОК, ИИ И HTML
    # ==========================================================================

    def _extract_single_link_from_html(self, html_raw):
        """Возвращает (title, url), если фрагмент содержит ровно одну <a>."""
        if not html_raw:
            return None
        matches = list(re.finditer(
            r'<a\b[^>]*?\bhref\s*=\s*(["\'])(.*?)\1[^>]*>(.*?)</a\s*>',
            html_raw, re.I | re.S,
        ))
        if len(matches) != 1:
            return None
        href = unescape(re.sub(r"\s+", " ", matches[0].group(2)).strip())
        title = unescape(re.sub(r"<[^>]+>", "", matches[0].group(3)))
        title = re.sub(r"\s+", " ", title).strip()
        if href and title and title != href:
            return title, href
        return None

    def _is_ai_or_rich_markdown(self, plain_text):
        """Проверяет, является ли текст скопированным Markdown из ИИ (ChatGPT, Gemini, Claude)."""
        has_code = "```" in plain_text
        has_headers = bool(re.search(r"^\s*#{1,6}\s+\S", plain_text, re.M))
        has_lists = bool(re.search(r"^\s*[-*+]\s+\S", plain_text, re.M))
        has_num_lists = bool(re.search(r"^\s*\d+[.)]\s+\S", plain_text, re.M))
        has_bold = bool(re.search(r"\*\*[^*]+\*\*", plain_text))
        has_math = bool(re.search(r"\$\$?[^$]+\$\$?", plain_text))
        return has_code or (has_headers and (has_lists or has_bold)) or (has_lists and has_bold) or has_num_lists or has_math

    def _get_youtube_video_id(self, url):
        """Извлекает ID видео YouTube, включая www.youtube.com и ссылки без схемы."""
        url = normalize_web_url(url)
        m = re.search(r'(?:v=|/embed/|/watch\?.*?v=|youtu\.be/|/v/|/shorts/)([a-zA-Z0-9_-]{11})', url, re.I)
        return m.group(1) if m else None

    def _is_url_like_title(self, title, href):
        """Проверяет, является ли заголовок ссылки техническим URL-адресом или доменом вместо нормального названия."""
        if not title:
            return True
        t = title.strip().lower()
        h = href.strip().lower()
        if t == h:
            return True
        # Отрезаем схемы и www для сравнения
        clean_t = re.sub(r"^https?://(www\.)?", "", t).rstrip("/")
        clean_h = re.sub(r"^https?://(www\.)?", "", h).rstrip("/")
        if clean_t == clean_h:
            return True
        if t.startswith(("http://", "https://", "ftp://", "www.")):
            return True
        if t.startswith(("youtube.com", "youtu.be", "m.youtube.com")):
            return True
        # Если в заголовке нет пробелов и он похож на домен или путь
        if " " not in t and ("/" in t or any(t.endswith(ext) for ext in (".com", ".org", ".net", ".ru", ".be", ".io", ".app", ".html", ".php"))):
            return True
        return False

    def _get_url_title(self, url):
        """Получает заголовок URL; для YouTube сначала использует oEmbed."""
        url = normalize_web_url(url)
        title = None
        yt_id = self._get_youtube_video_id(url)
        if yt_id:
            # 1. Запрос через oEmbed API с канонической ссылкой watch?v= и исходной ссылкой
            for oembed_target in (f"https://www.youtube.com/watch?v={yt_id}", url):
                try:
                    req = urllib.request.Request(
                        f"https://www.youtube.com/oembed?url={oembed_target}&format=json",
                        headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, timeout=6.0) as r:
                        d = json.loads(r.read().decode('utf-8'))
                        t = d.get('title')
                        if t:
                            title = f"{t} - YouTube" if not t.endswith("YouTube") else t
                            break
                except Exception:
                    pass

        # 2. Запасной прямой запрос <title> со страницы
        if not title:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
                with urllib.request.urlopen(req, timeout=6.0) as r:
                    html = r.read(32768).decode('utf-8', errors='ignore')
                    m = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
                    if m:
                        title = unescape(m.group(1).strip())
            except Exception:
                pass

        if title:
            return re.sub(r'\s+', ' ', title).replace('[', '(').replace(']', ')').strip()
        return None

    def _fallback_url_title(self, url):
        """Возвращает короткую подпись URL, если заголовок страницы недоступен."""
        clean_url = normalize_web_url(url)
        try:
            parsed = urlparse(clean_url)
            host = (parsed.netloc or parsed.path).lower()
            if host.startswith("www."):
                host = host[4:]
            path = parsed.path.rstrip("/")
            # Хост информативнее длинного URL; для страниц без корневого пути
            # добавляем последний сегмент адреса.
            if path and path != "/":
                segment = path.rsplit("/", 1)[-1]
                if segment and len(segment) <= 48:
                    return f"{host}: {unescape(segment)}"
            return host or clean_url[:80]
        except Exception:
            return clean_url[:80] or "Ссылка"

    def _resolve_url_title_sync(self, url):
        """Получает реальный заголовок и кэширует его."""
        clean_url = normalize_web_url(url)
        yt_id = self._get_youtube_video_id(clean_url)
        if yt_id and yt_id in self._yt_title_cache:
            return self._yt_title_cache[yt_id]
        if clean_url in self._title_cache:
            return self._title_cache[clean_url]

        real_title = self._get_url_title(clean_url)
        if not real_title:
            real_title = f"YouTube: {yt_id}" if yt_id else self._fallback_url_title(clean_url)

        self._title_cache[clean_url] = real_title
        if yt_id:
            self._yt_title_cache[yt_id] = real_title
        return real_title

    def _cached_or_fallback_url_title(self, url):
        clean_url = normalize_web_url(url)
        yt_id = self._get_youtube_video_id(clean_url)
        if yt_id and yt_id in self._yt_title_cache:
            return self._yt_title_cache[yt_id]
        if clean_url in self._title_cache:
            return self._title_cache[clean_url]
        return f"YouTube: {yt_id}" if yt_id else self._fallback_url_title(clean_url)

    def _resolve_url_title_async(self, url, callback):
        """Получает заголовок в фоне, не вызывая Tk из рабочего потока."""
        clean_url = normalize_web_url(url)
        if not clean_url:
            return
        result = {"done": False, "title": None}

        def worker():
            try:
                result["title"] = self._resolve_url_title_sync(clean_url)
            finally:
                result["done"] = True

        def poll_result():
            try:
                if not self.winfo_exists():
                    return
                if result["done"]:
                    callback(clean_url, result["title"])
                else:
                    self.after(30, poll_result)
            except tk.TclError:
                pass

        self.after(30, poll_result)
        threading.Thread(target=worker, daemon=True).start()

    def _replace_selection_or_insert(self, text):
        """Заменяет выделение в редакторе или вставляет текст в текущую позицию."""
        try:
            start, end = self.editor.index("sel.first"), self.editor.index("sel.last")
            self.editor.delete(start, end)
            self.editor.insert(start, _display_bullets(text))
        except tk.TclError:
            self.editor.insert(tk.INSERT, _display_bullets(text))
        self.apply_markdown_highlighting(force=True)
        self.on_editor_key_release(None)

    def _async_replace_url_title(self, url, title, placeholder):
        """Заменяет только вставленный нами fallback-заголовок после ответа сети."""
        if not self.winfo_exists():
            return
        content = self.editor.get("1.0", tk.END)
        pattern = re.compile(r"\[" + re.escape(placeholder) + r"\]\(" + re.escape(url) + r"\)")
        match = pattern.search(content)
        if not match:
            return
        start = f"1.0+{match.start()}c"
        end = f"1.0+{match.end()}c"
        self.editor.delete(start, end)
        self.editor.insert(start, f"[{title}]({url})")
        self.apply_markdown_highlighting(force=True)
        self.on_editor_key_release(None)

    def menu_paste(self):
        """Smart Paste: HTML-ссылка, URL, Markdown/AI и обычный текст."""
        try:
            plain = self.clipboard_get()
        except tk.TclError:
            plain = ""

        html_raw = self._get_clipboard_html()
        single_link = self._extract_single_link_from_html(html_raw)
        rich_html = bool(html_raw and re.search(r"<(?:h[1-6]|p|div|ul|ol|li|pre|table|blockquote)\b", html_raw, re.I))
        if single_link and not rich_html:
            link_title, link_href = single_link
            link_href = normalize_web_url(link_href)
            try:
                selected = self.editor.get("sel.first", "sel.last").strip()
            except tk.TclError:
                selected = ""
            if selected:
                self._replace_selection_or_insert(f"[{selected}]({link_href})")
                self.show_toast("🔗 Текст обёрнут ссылкой")
                return

            if self._get_youtube_video_id(link_href) or self._is_url_like_title(link_title, link_href):
                placeholder = self._cached_or_fallback_url_title(link_href)
                self._replace_selection_or_insert(f"[{placeholder}]({link_href})")
                self._resolve_url_title_async(
                    link_href,
                    lambda url, title: self._async_replace_url_title(url, title, placeholder),
                )
            else:
                self._replace_selection_or_insert(f"[{link_title}]({link_href})")
            self.show_toast("🔗 Вставлена ссылка")
            return

        if rich_html:
            try:
                converter = HTMLToMarkdownConverter()
                converter.feed(html_raw)
                converter.close()
                md_converted = converter.get_markdown()
            except (ValueError, TypeError):
                md_converted = ""
            if md_converted:
                self._replace_selection_or_insert(md_converted)
                self.show_toast("📋 Вставлен форматированный текст")
                return

        clean_url = normalize_web_url(plain)
        if is_http_url(clean_url):
            try:
                selected = self.editor.get("sel.first", "sel.last").strip()
            except tk.TclError:
                selected = ""
            if selected:
                self._replace_selection_or_insert(f"[{selected}]({clean_url})")
                self.show_toast("🔗 Текст обёрнут ссылкой")
                return

            placeholder = self._cached_or_fallback_url_title(clean_url)
            self._replace_selection_or_insert(f"[{placeholder}]({clean_url})")
            self._resolve_url_title_async(
                clean_url,
                lambda url, title: self._async_replace_url_title(url, title, placeholder),
            )
            self.show_toast("🔗 Вставлена ссылка")
            return

        if self._is_ai_or_rich_markdown(plain):
            self._replace_selection_or_insert(plain)
            self.show_toast("🤖 Вставлена разметка ИИ")
            return

        if plain:
            self._replace_selection_or_insert(plain)

    # ==========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ И СТИЛИ
    # ==========================================================================

    def show_toast(self, message, color="#2563eb", duration=2200):
        """Всплывающее информационное уведомление."""
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=color)

        lbl = tk.Label(
            toast, text=message, fg="#ffffff", bg=color,
            font=("Segoe UI", 9, "bold"), padx=12, pady=6
        )
        lbl.pack()

        self.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() // 2) - (lbl.winfo_reqwidth() // 2)
        y = self.winfo_rooty() + self.winfo_height() - 55
        toast.geometry(f"+{x}+{y}")
        toast.after(duration, toast.destroy)

    def _on_focus_out(self, event):
        if event.widget == self:
            if self._save_timer:
                self.after_cancel(self._save_timer)
                self._save_timer = None
            self.save_current_note()

    def _setup_styles(self):
        """Настройка стилей для ttk виджетов (без лишних рамок)."""
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.style.configure(
            "Treeview",
            background=self.colors["tree_bg"],
            foreground=self.colors["tree_fg"],
            fieldbackground=self.colors["tree_bg"],
            borderwidth=0,
            font=("Segoe UI", 9),
            rowheight=24,
        )
        self.style.map(
            "Treeview",
            background=[("selected", self.colors["accent"])],
            foreground=[("selected", "#ffffff")],
        )

    def apply_theme(self):
        """Применяет текущую тему ко всем элементам интерфейса."""
        self.colors = self.theme_palettes[self.current_theme]

        self.configure(bg=self.colors["bg_sidebar"])
        self.toolbar_frame.config(bg=self.colors["bg_sidebar"])
        self.search_frame.config(bg=self.colors["bg_sidebar"])

        for btn in self._toolbar_buttons:
            is_active = getattr(btn, "_is_active", False)
            self._style_flat_button(btn, active=is_active)

        self.search_entry.config(
            bg=self.colors["bg_editor"],
            fg=self.colors["text_main"],
            insertbackground=self.colors["text_main"],
        )
        self.btn_clear_search.config(
            bg=self.colors["bg_sidebar"],
            fg=self.colors["text_muted"],
        )
        self.lbl_search.config(bg=self.colors["bg_sidebar"], fg=self.colors["text_muted"])

        # Бесшовные панели без рамок
        self.sidebar_frame.config(bg=self.colors["tree_bg"])

        self.style.configure(
            "Treeview",
            background=self.colors["tree_bg"],
            foreground=self.colors["tree_fg"],
            fieldbackground=self.colors["tree_bg"],
            borderwidth=0,
        )
        self.style.map(
            "Treeview",
            background=[("selected", self.colors["accent"])],
            foreground=[("selected", "#ffffff")],
        )

        self.editor_frame.config(bg=self.colors["bg_editor"])
        self.title_entry.config(
            bg=self.colors["bg_editor"],
            fg=self.colors["text_main"],
            insertbackground=self.colors["text_main"],
            selectbackground=self.colors["accent"],
            selectforeground="#ffffff",
        )

        self.editor.config(
            bg=self.colors["bg_editor"],
            fg=self.colors["text_main"],
            insertbackground=self.colors["text_main"],
            selectbackground=self.colors["accent"],
            selectforeground="#ffffff",
        )

        self.status_bar.config(bg=self.colors["status_bg"], fg=self.colors["status_fg"])

        theme_icon = "☀️" if self.current_theme == "dark" else "🌙"
        if hasattr(self, "btn_theme"):
            self.btn_theme.config(text=theme_icon)

        if hasattr(self, "btn_live_preview"):
            self._style_flat_button(self.btn_live_preview, active=not self.live_preview_enabled)

        self._indent_tag_cache.clear()
        self._setup_markdown_tags()
        self.apply_markdown_highlighting(force=True)

    def toggle_theme(self):
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self.apply_theme()

    def toggle_live_preview(self):
        self.live_preview_enabled = not self.live_preview_enabled
        self._style_flat_button(self.btn_live_preview, active=not self.live_preview_enabled)
        state_txt = "включён" if self.live_preview_enabled else "выключен"
        self.show_toast(f"👁️ Live Preview: {state_txt}")
        self._setup_markdown_tags()
        self.apply_markdown_highlighting(force=True)

    # ==========================================================================
    # ПЛОСКИЕ КНОПКИ
    # ==========================================================================

    def _style_flat_button(self, btn, active=False):
        danger = getattr(btn, "_danger", False)
        fg = "#ef4444" if danger else self.colors["text_main"]
        if getattr(self, "btn_live_preview", None) is btn and active:
            bg = "#55585f"  # нейтральный серый: Raw Markdown включён
        else:
            bg = self.colors["btn_active"] if active else self.colors["btn_bg"]
        btn.config(
            bg=bg, fg=fg, activebackground=self.colors["btn_hover"],
            activeforeground=fg
        )
        btn._is_active = active

    def _on_btn_enter(self, event):
        btn = event.widget
        if not getattr(btn, "_is_active", False):
            btn.config(bg=self.colors["btn_hover"])

    def _on_btn_leave(self, event):
        btn = event.widget
        if not getattr(btn, "_is_active", False):
            btn.config(bg=self.colors["btn_bg"])

    def create_icon_btn(self, parent, icon, tooltip_text, command, danger=False):
        btn = tk.Button(
            parent, text=icon, font=("Segoe UI Emoji", 11),
            width=3, height=1, bd=0, relief=tk.FLAT,
            highlightthickness=0, cursor="hand2",
            padx=2, pady=3, command=command
        )
        btn._danger = danger
        btn._is_active = False
        self._style_flat_button(btn, active=False)
        btn.bind("<Enter>", self._on_btn_enter)
        btn.bind("<Leave>", self._on_btn_leave)
        btn.pack(side=tk.LEFT, padx=2, pady=2)
        if tooltip_text:
            ToolTip(btn, tooltip_text)
        self._toolbar_buttons.append(btn)
        return btn

    # ==========================================================================
    # ПОСТРОЕНИЕ ИНТЕРФЕЙСА (БЕЗ РАМОК)
    # ==========================================================================

    def _build_top_toolbar(self):
        """Панель упорядочена по привычному сценарию: файлы, вид/форматирование, настройки."""
        self._toolbar_buttons = []
        self.toolbar_frame = tk.Frame(self, bg=self.colors["bg_sidebar"], bd=0)
        self.toolbar_frame.pack(side=tk.TOP, fill=tk.X, padx=3, pady=3)

        # Файлы и хранилище
        self.btn_vault = self.create_icon_btn(
            self.toolbar_frame, "📁", "Выбрать хранилище (на текущий сеанс)", self.select_vault_folder
        )
        self.create_icon_btn(self.toolbar_frame, "➕", "Новая заметка (Ctrl+N)", self.create_new_note)
        self.create_icon_btn(self.toolbar_frame, "▦", "Ежедневная заметка (Ctrl+D)", self.create_daily_note)
        self.create_icon_btn(
            self.toolbar_frame, "🗑️", "Удалить выбранные (Delete)",
            self.delete_selected_items, danger=True
        )

        # Поиск закреплён справа, как в образце
        self.search_frame = tk.Frame(self.toolbar_frame, bg=self.colors["bg_sidebar"])
        self.search_frame.pack(side=tk.RIGHT, padx=3, pady=2)
        self.lbl_search = tk.Label(
            self.search_frame, text="🔍", bg=self.colors["bg_sidebar"],
            font=("Segoe UI Emoji", 9)
        )
        self.lbl_search.pack(side=tk.LEFT, padx=(2, 1))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_search_changed())
        self.search_entry = tk.Entry(
            self.search_frame, textvariable=self.search_var,
            font=("Segoe UI", 9), width=12, bd=1, relief=tk.SOLID
        )
        self.search_entry.pack(side=tk.LEFT, padx=1)
        ToolTip(self.search_entry, "Поиск по имени и тексту (Ctrl+F)")
        self.btn_clear_search = tk.Button(
            self.search_frame, text="×", font=("Segoe UI", 12),
            bd=0, bg=self.colors["bg_sidebar"], fg=self.colors["text_muted"],
            activebackground=self.colors["accent_light"], relief=tk.FLAT,
            cursor="hand2", command=self.clear_search
        )
        self.btn_clear_search.pack(side=tk.LEFT, padx=1)

        # Вид и форматирование: порядок повторяет приложенный пример.
        self.format_frame = tk.Frame(self.toolbar_frame, bg=self.colors["bg_sidebar"])
        self.format_frame.pack(side=tk.LEFT, padx=(14, 3))
        self.btn_live_preview = self.create_icon_btn(
            self.format_frame, "◉", "Показать/скрыть технические символы Markdown",
            self.toggle_live_preview
        )
        # Кнопка НЕ подсвечена, когда маркеры скрыты; в Raw Markdown подсвечивается серым.
        self._style_flat_button(self.btn_live_preview, active=False)
        self.font_frame = tk.Frame(self.format_frame, bg=self.colors["bg_sidebar"])
        self.font_frame.pack(side=tk.LEFT, padx=(3, 3))
        self.create_icon_btn(self.font_frame, "A+", "Увеличить шрифт редактора", lambda: self.change_selected_font_size(1))
        self.create_icon_btn(self.font_frame, "A−", "Уменьшить шрифт редактора", lambda: self.change_selected_font_size(-1))
        self.create_icon_btn(self.format_frame, "B", "Жирный (Ctrl+B)", lambda: self.wrap_selection("**", "**"))
        self.create_icon_btn(self.format_frame, "I", "Курсив (Ctrl+I)", lambda: self.wrap_selection("*", "*"))
        self.create_icon_btn(self.format_frame, "S̶", "Зачёркивание (Ctrl+Shift+S)", lambda: self.wrap_selection("~~", "~~"))
        self.create_icon_btn(self.format_frame, "</>", "Код (Ctrl+Shift+C)", lambda: self.wrap_selection("`", "`"))
        self.create_icon_btn(self.format_frame, "✎", "Подсветка текста (Ctrl+H)", lambda: self.wrap_selection("==", "=="))
        self.create_icon_btn(self.format_frame, "⛓", "Вставить ссылку (Ctrl+K)", self._insert_link_dialog)

        # Системные команды — отдельной группой после форматирования
        self.btn_theme = self.create_icon_btn(
            self.toolbar_frame, "⚙", "Сменить светлую/тёмную тему", self.toggle_theme
        )
        self.create_icon_btn(self.toolbar_frame, "❔", "Справка и горячие клавиши (F1)", self.toggle_markdown_help)
        self.btn_pin = self.create_icon_btn(
            self.toolbar_frame, "📌", "Закрепить поверх всех окон", self.toggle_always_on_top
        )
        self._style_flat_button(self.btn_pin, active=self.always_on_top)
        self.btn_mini = self.create_icon_btn(
            self.toolbar_frame, "▣", "Свернуть в мини-иконку у края экрана", self.toggle_mini_mode
        )

        # Контекстное меню поиска с обычными операциями ввода
        self.search_context_menu = tk.Menu(self, tearoff=0, font=("Segoe UI", 9))
        self.search_context_menu.add_command(label="Вырезать", command=lambda: self._search_entry_action("cut"))
        self.search_context_menu.add_command(label="Копировать", command=lambda: self._search_entry_action("copy"))
        self.search_context_menu.add_command(label="Вставить", command=lambda: self._search_entry_action("paste"))
        self.search_context_menu.add_separator()
        self.search_context_menu.add_command(label="Выбрать всё", command=lambda: self._search_entry_action("all"))
        self.search_entry.bind("<Button-3>", self._show_search_context_menu)
        self.search_entry.bind("<Control-a>", lambda e: (self.search_entry.select_range(0, tk.END), "break")[1])

    def _build_main_layout(self):
        """Бесшовный макет: дерево файлов и редактор без видимого вертикального разделителя."""
        self.main_paned = tk.PanedWindow(
            self, orient=tk.HORIZONTAL, bd=0, sashwidth=0, sashpad=0,
            showhandle=False, opaqueresize=True, bg=self.colors["bg_editor"]
        )
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Боковая панель дерева (без внешней рамки)
        self.sidebar_frame = tk.Frame(self.main_paned, bg=self.colors["tree_bg"], bd=0, highlightthickness=0)
        self.tree = ttk.Treeview(
            self.sidebar_frame, style="Treeview",
            selectmode="extended", show="tree"
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_note_selected)
        self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)
        self.tree.bind("<Double-Button-1>", self.on_tree_double_click)

        # Панель редактора
        self.editor_frame = tk.Frame(self.main_paned, bg=self.colors["bg_editor"], bd=0, highlightthickness=0)
        self.title_entry = tk.Entry(
            self.editor_frame, font=("Segoe UI", 13, "bold"),
            bd=0, bg=self.colors["bg_editor"], fg=self.colors["text_main"],
            insertbackground=self.colors["text_main"],
            selectbackground=self.colors["accent"], selectforeground="#ffffff"
        )
        self.title_entry.pack(fill=tk.X, padx=10, pady=(6, 4))
        self.title_entry.bind("<Return>", self.on_title_commit)
        self.title_entry.bind("<FocusOut>", self.on_title_commit)

        text_container = tk.Frame(self.editor_frame, bg=self.colors["bg_editor"], bd=0)
        text_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 2))

        self.editor = tk.Text(
            text_container, wrap=tk.WORD, font=("Segoe UI", 11),
            bd=0, bg=self.colors["bg_editor"], fg=self.colors["text_main"],
            insertbackground=self.colors["text_main"],
            undo=True, maxundo=50,
            selectbackground=self.colors["accent"], selectforeground="#ffffff"
        )
        self.editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.main_paned.add(self.sidebar_frame, minsize=180, width=220)
        self.main_paned.add(self.editor_frame)

    def _build_status_bar(self):
        """Создает компактную строку состояния внизу окна."""
        self.status_bar = tk.Label(
            self, text="Готово | Строка 1, Колонка 0 | Слов: 0 | Символов: 0",
            anchor=tk.W, font=("Segoe UI", 8),
            bg=self.colors["status_bg"], fg=self.colors["status_fg"],
            padx=8, pady=3
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _update_status_bar(self):
        """Обновляет статистику в строке состояния."""
        try:
            insert_idx = self.editor.index(tk.INSERT)
            row, col = insert_idx.split(".")
            text = self.editor.get("1.0", tk.END)
            chars = max(0, len(text) - 1)
            words = len(text.split())
            status_txt = "✏️ Изменено" if self.is_modified else "💾 Сохранено"
            self.status_bar.config(
                text=f"{status_txt}  |  Стр {row}, Кол {col}  |  Слов: {words}  |  Символов: {chars}"
            )
        except Exception:
            pass

    # ==========================================================================
    # ИНТЕРАКТИВНОСТЬ: КЛИКИ ПО ЧЕКБОКСАМ И ССЫЛКАМ
    # ==========================================================================

    def _bind_shortcuts(self):
        """Привязывает горячие клавиши и интерактивные события мыши."""
        self.bind("<Control-n>", lambda e: self.create_new_note())
        self.bind("<Control-f>", lambda e: self.search_entry.focus())
        self.bind("<Control-d>", lambda e: self.create_daily_note())
        self.bind("<Control-s>", lambda e: self.save_current_note())
        self.bind("<Control-w>", lambda e: self.close_current_note())
        self.tree.bind("<Delete>", lambda e: (self.delete_selected_items(), "break")[1])
        self.tree.bind("<Shift-Delete>", lambda e: (self.delete_selected_items(), "break")[1])
        self.bind("<F1>", lambda e: self.toggle_markdown_help())

        # Редакторские события мыши
        self.editor.bind("<KeyRelease>", self.on_editor_key_release)
        self.editor.bind("<ButtonPress-1>", self._on_editor_press, add="+")
        self.editor.bind("<ButtonRelease-1>", self._on_editor_click)
        self.editor.bind("<Control-v>", lambda e: (self.menu_paste(), "break")[1])
        self.editor.bind("<Control-c>", lambda e: (self.menu_copy(), "break")[1])
        self.editor.bind("<MouseWheel>", self._on_mousewheel)
        self.editor.bind("<Button-4>", lambda e: self.editor.yview_scroll(-3, "units"))
        self.editor.bind("<Button-5>", lambda e: self.editor.yview_scroll(3, "units"))

        # Умный ввод списков, автозакрытие, табуляция
        self.editor.bind("<Return>", self._on_editor_return)
        self.editor.bind("<Tab>", self._on_editor_tab)
        self.editor.bind("<Shift-Tab>", self._on_editor_shift_tab)
        self.editor.bind("<parenleft>", lambda e: self._on_auto_pair("(", ")"))
        self.editor.bind("<braceleft>", lambda e: self._on_auto_pair("{", "}"))
        self.editor.bind("<quotedbl>", lambda e: self._on_auto_pair('"', '"'))

        # Горячие клавиши форматирования
        self.editor.bind("<Control-b>", lambda e: (self.wrap_selection("**", "**"), "break")[1])
        self.editor.bind("<Control-i>", lambda e: (self.wrap_selection("*", "*"), "break")[1])
        self.editor.bind("<Control-h>", lambda e: (self.wrap_selection("==", "=="), "break")[1])
        self.editor.bind("<Control-k>", lambda e: (self._insert_link_dialog(), "break")[1])
        self.editor.bind("<Control-Shift-C>", lambda e: (self.wrap_selection("`", "`"), "break")[1])
        self.editor.bind("<Control-Shift-S>", lambda e: (self.wrap_selection("~~", "~~"), "break")[1])
        self.editor.bind("<Control-Shift-T>", lambda e: (self.format_active_table(), "break")[1])
        self.editor.bind("<Control-Shift-t>", lambda e: (self.format_active_table(), "break")[1])
        self.editor.bind("<Control-Return>", lambda e: (self._toggle_current_line_task(), "break")[1])

        # Курсор hand2 для кликабельных элементов
        for tag in ("wikilink", "md_link"):
            self.editor.tag_bind(tag, "<Enter>", lambda e: self.editor.config(cursor="hand2"))
            self.editor.tag_bind(tag, "<Leave>", lambda e: self.editor.config(cursor="xterm"))

    def _on_editor_press(self, event):
        """Запоминает точку нажатия, чтобы drag/выделение не считались кликом по ссылке."""
        try:
            self._editor_mouse_down_index = self.editor.index(f"@{event.x},{event.y}")
        except tk.TclError:
            self._editor_mouse_down_index = None

    def _toggle_heading_fold(self, heading_line):
        """Сворачивает текст под Markdown-заголовком до следующего заголовка того же уровня."""
        lines = self.editor.get("1.0", "end-1c").split("\n")
        if heading_line < 1 or heading_line > len(lines):
            return
        match = re.match(r"^(#{1,6})\s+", lines[heading_line - 1])
        if not match:
            return
        level = len(match.group(1))
        end_line = len(lines) + 1
        for number in range(heading_line + 1, len(lines) + 1):
            next_match = re.match(r"^(#{1,6})\s+", lines[number - 1])
            if next_match and len(next_match.group(1)) <= level:
                end_line = number
                break
        tag = f"folded_section_{heading_line}"
        if heading_line in self._folded_headings:
            self._folded_headings.remove(heading_line)
            self.editor.tag_remove(tag, "1.0", "end")
        else:
            self._folded_headings.add(heading_line)
            if end_line > heading_line + 1:
                self.editor.tag_add(tag, f"{heading_line + 1}.0", f"{end_line}.0")
                self.editor.tag_configure(tag, elide=True)
        self._refresh_fold_markers()

    def _refresh_fold_markers(self):
        """Рисует небольшие кликабельные стрелки слева от заголовков."""
        for marker in self._fold_markers:
            try:
                marker.destroy()
            except tk.TclError:
                pass
        self._fold_markers = []
        lines = self.editor.get("1.0", "end-1c").split("\n")
        for number, line in enumerate(lines, 1):
            if not re.match(r"^#{1,6}\s+", line):
                continue
            info = self.editor.dlineinfo(f"{number}.0")
            if not info:
                continue
            arrow = "▸" if number in self._folded_headings else "▾"
            marker = tk.Label(self.editor, text=arrow, bd=0, padx=0, pady=0,
                              cursor="hand2", font=("Segoe UI", 9),
                              bg=self.colors["bg_editor"], fg=self.colors["text_muted"])
            # Отступ заголовка задаётся тегами ниже, поэтому стрелка находится
            # слева и не перекрывает символы Markdown или текст заголовка.
            marker.place(x=0, y=info[1], width=14, height=max(14, info[3]))
            marker.bind("<Button-1>", lambda event, n=number: self._toggle_heading_fold(n))
            self._fold_markers.append(marker)

    def _on_editor_click(self, event):
        """Открывает ссылку только при настоящем клике, но не после выделения текста."""
        try:
            release_index = self.editor.index(f"@{event.x},{event.y}")
            press_index = getattr(self, "_editor_mouse_down_index", None)
            if press_index and release_index != press_index:
                self._update_status_bar()
                return
            # Если выделение действительно осталось после drag, не открываем URL.
            if self.editor.tag_ranges("sel"):
                sel_start = self.editor.index("sel.first")
                sel_end = self.editor.index("sel.last")
                if sel_start != sel_end:
                    self._update_status_bar()
                    return
        except tk.TclError:
            pass
        index = self.editor.index(f"@{event.x},{event.y}")
        line_num, col_num = map(int, index.split("."))
        line_text = self.editor.get(f"{line_num}.0", f"{line_num}.end")

        if event.x <= 14 and re.match(r"^#{1,6}\s+", line_text):
            self._toggle_heading_fold(line_num)
            return "break"

        # 1. Проверка клика по чекбоксу
        m_task = RE_CHECKBOX_LINE.match(line_text)
        if m_task:
            prefix_len = len(m_task.group(1))
            cb_start = prefix_len + 2
            cb_end = cb_start + 3
            if cb_start <= col_num <= cb_end + 1:
                cur_state = m_task.group(2)
                next_state = " " if cur_state in ("x", "X", "-", "/") else "x"
                new_line = f"{m_task.group(1)}- [{next_state}]"
                if m_task.group(3):
                    new_line += f" {m_task.group(3)}"
                self.editor.delete(f"{line_num}.0", f"{line_num}.end")
                self.editor.insert(f"{line_num}.0", new_line)
                self.on_editor_key_release(None)
                return "break"

        # 2. Проверка клика по вики-ссылке [[Note]]
        tags_here = self.editor.tag_names(index)
        if "wikilink" in tags_here:
            for m in RE_WIKILINK.finditer(line_text):
                if m.start() <= col_num <= m.end():
                    raw_target = m.group(1).split("|")[0].split("#")[0].strip()
                    self._follow_wikilink(raw_target)
                    return "break"

        # 3. Проверка клика по веб-ссылке [Title](URL) или https://
        if "md_link" in tags_here:
            for m in RE_MDLINK.finditer(line_text):
                if m.start() <= col_num <= m.end():
                    self._open_url(m.group(2))
                    return "break"
            for m in RE_BARE_URL.finditer(line_text):
                if m.start() <= col_num <= m.end():
                    self._open_url(m.group(1))
                    return "break"
            for m in RE_AUTOLINK.finditer(line_text):
                if m.start() <= col_num <= m.end():
                    self._open_url(m.group(1))
                    return "break"

        self.apply_markdown_highlighting()
        self._update_status_bar()

    def _toggle_current_line_task(self):
        """Переключает статус чекбокса на текущей строке (Ctrl+Enter)."""
        idx = self.editor.index(tk.INSERT)
        line_num = int(idx.split(".")[0])
        line_text = self.editor.get(f"{line_num}.0", f"{line_num}.end")
        m_task = RE_CHECKBOX_LINE.match(line_text)
        if m_task:
            cur_state = m_task.group(2)
            next_state = " " if cur_state in ("x", "X", "-", "/") else "x"
            new_line = f"{m_task.group(1)}- [{next_state}]"
            if m_task.group(3):
                new_line += f" {m_task.group(3)}"
            self.editor.delete(f"{line_num}.0", f"{line_num}.end")
            self.editor.insert(f"{line_num}.0", new_line)
            self.on_editor_key_release(None)
        else:
            stripped = line_text.lstrip()
            indent = line_text[:len(line_text) - len(stripped)]
            if stripped.startswith("- ") or stripped.startswith("* "):
                new_line = f"{indent}- [ ] {stripped[2:]}"
            else:
                new_line = f"{indent}- [ ] {stripped}"
            self.editor.delete(f"{line_num}.0", f"{line_num}.end")
            self.editor.insert(f"{line_num}.0", new_line)
            self.on_editor_key_release(None)

    def _follow_wikilink(self, target_name):
        """Открывает заметку по вики-ссылке. Если нет — предлагает создать."""
        if not target_name:
            return
        clean_name = re.sub(r'[\\/*?:"<>|]', "", target_name).strip()
        found = None
        for p in self.vault_path.glob(f"**/{clean_name}.md"):
            found = p
            break

        if found and found.exists():
            self.open_note(found)
            self.show_toast(f"📄 Открыта: {clean_name}")
        else:
            if messagebox.askyesno("Создать заметку?", f"Заметка [[{clean_name}]] не найдена.\nСоздать новую?"):
                new_path = self.current_target_folder / f"{clean_name}.md"
                now = datetime.now().strftime("Создано: %d.%m.%Y  %H:%M")
                with open(new_path, "w", encoding="utf-8") as f:
                    f.write(f"# {clean_name}\n\n\n`{now}`\n")
                self.refresh_notes_tree()
                self.open_note(new_path)
                self.show_toast(f"✅ Создана: {clean_name}", "#10b981")

    def _open_url(self, url):
        """Открывает ссылку в системном браузере."""
        if not url:
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            self.show_toast("🌐 Открыто в браузере", "#0284c7")
        except Exception as e:
            self.show_toast(f"Ошибка открытия ссылки: {e}")

    # ==========================================================================
    # УМНОЕ РЕДАКТИРОВАНИЕ: АВТОПРОДОЛЖЕНИЕ СПИСКОВ И ПАРНЫЕ СКОБКИ
    # ==========================================================================

    def _on_editor_return(self, event):
        """Автопродолжение списков и чекбоксов на Enter."""
        cursor = self.editor.index(tk.INSERT)
        line_num, col = map(int, cursor.split("."))
        line_text = self.editor.get(f"{line_num}.0", f"{line_num}.end")

        # 1. Чекбокс
        m_cb = RE_CHECKBOX_LINE.match(line_text)
        if m_cb:
            body = m_cb.group(3) or ""
            if not body.strip():
                self.editor.delete(f"{line_num}.0", f"{line_num}.end")
                return "break"
            indent = m_cb.group(1)
            self.editor.insert(cursor, f"\n{indent}- [ ] ")
            self.editor.see(tk.INSERT)
            self.on_editor_key_release(None)
            return "break"

        # 2. Нумерованный список
        m_num = RE_NUM_LIST.match(line_text)
        if m_num:
            indent = m_num.group(1)
            cur_num = int(m_num.group(2))
            body = line_text[m_num.end():].strip()
            if not body:
                self.editor.delete(f"{line_num}.0", f"{line_num}.end")
                return "break"
            self.editor.insert(cursor, f"\n{indent}{cur_num + 1}. ")
            self.editor.see(tk.INSERT)
            self.on_editor_key_release(None)
            return "break"

        # 3. Маркированный список
        m_bul = RE_BULLET.match(line_text)
        if m_bul:
            # Если это Markdown-* список, перед продолжением сразу показываем маркер как •.
            if m_bul.group(2) == "*":
                self._display_current_star_list_marker()
            indent = m_bul.group(1)
            body = line_text[m_bul.end():].strip()
            if not body:
                self.editor.delete(f"{line_num}.0", f"{line_num}.end")
                return "break"
            marker = m_bul.group(2)
            self.editor.insert(cursor, f"\n{indent}{marker} ")
            self.editor.see(tk.INSERT)
            self.on_editor_key_release(None)
            return "break"

        # 4. Цитата
        m_quote = RE_BLOCKQUOTE.match(line_text)
        if m_quote:
            prefix = m_quote.group(0)
            body = line_text[m_quote.end():].strip()
            if not body:
                self.editor.delete(f"{line_num}.0", f"{line_num}.end")
                return "break"
            self.editor.insert(cursor, f"\n{prefix}")
            self.editor.see(tk.INSERT)
            self.on_editor_key_release(None)
            return "break"

        self.editor.insert(cursor, "\n")
        self.editor.see(tk.INSERT)
        self.on_editor_key_release(None)
        return "break"

    def _on_editor_tab(self, event):
        cursor = self.editor.index(tk.INSERT)
        line_num = int(cursor.split(".")[0])
        line_text = self.editor.get(f"{line_num}.0", f"{line_num}.end")
        if RE_BULLET.match(line_text) or RE_NUM_LIST.match(line_text):
            self.editor.insert(f"{line_num}.0", "  ")
            self.on_editor_key_release(None)
            return "break"
        self.editor.insert(tk.INSERT, "  ")
        return "break"

    def _on_editor_shift_tab(self, event):
        cursor = self.editor.index(tk.INSERT)
        line_num = int(cursor.split(".")[0])
        line_text = self.editor.get(f"{line_num}.0", f"{line_num}.end")
        if line_text.startswith("  "):
            self.editor.delete(f"{line_num}.0", f"{line_num}.2")
            self.on_editor_key_release(None)
            return "break"
        elif line_text.startswith(" "):
            self.editor.delete(f"{line_num}.0", f"{line_num}.1")
            self.on_editor_key_release(None)
            return "break"
        return "break"

    def _on_auto_pair(self, open_char, close_char):
        try:
            start, end = self.editor.index("sel.first"), self.editor.index("sel.last")
            selected = self.editor.get(start, end)
            self.editor.delete(start, end)
            self.editor.insert(start, f"{open_char}{selected}{close_char}")
            self.editor.tag_add("sel", start, f"{start}+{len(open_char + selected + close_char)}c")
            self.on_editor_key_release(None)
            return "break"
        except tk.TclError:
            pass

        self.editor.insert(tk.INSERT, f"{open_char}{close_char}")
        self.editor.mark_set(tk.INSERT, "insert-1c")
        return "break"

    def _insert_link_dialog(self):
        """Вставляет ссылку в сохранённое место, даже когда фокус перешёл в диалог."""
        try:
            start, end = self.editor.index("sel.first"), self.editor.index("sel.last")
            selected = self.editor.get(start, end)
            has_selection = True
        except tk.TclError:
            start = end = self.editor.index(tk.INSERT)
            selected = ""
            has_selection = False

        dialog = tk.Toplevel(self)
        dialog.title("Вставить ссылку")
        dialog.transient(self)
        dialog.configure(bg=self.colors["bg_editor"])
        dialog.resizable(False, False)
        dialog.geometry("420x178")
        # Метки Tk сохраняют позицию вставки независимо от фокуса диалога.
        self.editor.mark_set("_link_dialog_start", start)
        self.editor.mark_set("_link_dialog_end", end)
        self.editor.mark_gravity("_link_dialog_start", tk.LEFT)
        self.editor.mark_gravity("_link_dialog_end", tk.RIGHT)

        tk.Label(dialog, text="Текст ссылки:", bg=self.colors["bg_editor"], fg=self.colors["text_main"], font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(10, 2))
        entry_text = tk.Entry(dialog, font=("Segoe UI", 9), bg=self.colors["bg_sidebar"], fg=self.colors["text_main"], width=48)
        entry_text.pack(fill=tk.X, padx=12)
        entry_text.insert(0, selected)
        tk.Label(dialog, text="Адрес URL или [[Название заметки]]:", bg=self.colors["bg_editor"], fg=self.colors["text_main"], font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(6, 2))
        entry_url = tk.Entry(dialog, font=("Segoe UI", 9), bg=self.colors["bg_sidebar"], fg=self.colors["text_main"], width=48)
        entry_url.pack(fill=tk.X, padx=12)

        # Контекстное меню ввода доступно в обоих полях диалога ссылки.
        entry_context_menu = tk.Menu(dialog, tearoff=0, font=("Segoe UI", 9))
        entry_context_menu.add_command(label="Вырезать", command=lambda: focused_entry_action("cut"))
        entry_context_menu.add_command(label="Копировать", command=lambda: focused_entry_action("copy"))
        entry_context_menu.add_command(label="Вставить", command=lambda: focused_entry_action("paste"))
        entry_context_menu.add_separator()
        entry_context_menu.add_command(label="Выбрать всё", command=lambda: focused_entry_action("all"))
        focused_entry = {"widget": entry_url}

        def focused_entry_action(action):
            widget = focused_entry["widget"]
            try:
                widget.focus_set()
                if action == "cut":
                    widget.event_generate("<<Cut>>")
                elif action == "copy":
                    widget.event_generate("<<Copy>>")
                elif action == "paste":
                    widget.event_generate("<<Paste>>")
                elif action == "all":
                    widget.select_range(0, tk.END)
                    widget.icursor(tk.END)
            except tk.TclError:
                pass

        def show_entry_context_menu(event):
            focused_entry["widget"] = event.widget
            event.widget.focus_set()
            try:
                entry_context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                entry_context_menu.grab_release()
            return "break"

        for link_entry in (entry_text, entry_url):
            link_entry.bind("<Button-3>", show_entry_context_menu)
            link_entry.bind("<Button-2>", show_entry_context_menu)
            link_entry.bind("<Control-a>", lambda e: (e.widget.select_range(0, tk.END), "break")[1])

        def do_insert(event=None):
            label = entry_text.get().strip()
            target = entry_url.get().strip()
            if not target:
                entry_url.focus_set()
                return "break"
            if target.startswith("[[") and target.endswith("]]" ):
                markdown = target
            else:
                target = normalize_web_url(target)
                if label:
                    markdown = f"[{label}]({target})"
                else:
                    markdown = f"[{target}]({target})"
            try:
                a = self.editor.index("_link_dialog_start")
                b = self.editor.index("_link_dialog_end")
                if self.editor.compare(a, "<", b):
                    self.editor.delete(a, b)
                self.editor.insert(a, markdown)
                self.editor.mark_set(tk.INSERT, f"{a}+{len(markdown)}c")
                self.editor.tag_remove("sel", "1.0", tk.END)
                self.editor.focus_set()
                self.on_editor_key_release(None)
            except tk.TclError:
                pass
            dialog.destroy()
            return "break"

        buttons = tk.Frame(dialog, bg=self.colors["bg_editor"])
        buttons.pack(pady=10)
        tk.Button(buttons, text="Вставить", command=do_insert, bg=self.colors["accent"], fg="#ffffff", relief=tk.FLAT, width=11).pack(side=tk.LEFT, padx=4)
        tk.Button(buttons, text="Отмена", command=dialog.destroy, bg=self.colors["btn_bg"], fg=self.colors["text_main"], relief=tk.FLAT, width=11).pack(side=tk.LEFT, padx=4)
        dialog.bind("<Return>", do_insert)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        entry_url.focus_set()
        if not has_selection:
            entry_text.insert(0, "")
        dialog.wait_visibility()
        dialog.grab_set()

    def _show_search_context_menu(self, event):
        self.search_entry.focus_set()
        try:
            self.search_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.search_context_menu.grab_release()
        return "break"

    def _search_entry_action(self, action):
        entry = self.search_entry
        try:
            if action == "cut":
                entry.event_generate("<<Cut>>")
            elif action == "copy":
                entry.event_generate("<<Copy>>")
            elif action == "paste":
                entry.event_generate("<<Paste>>")
            elif action == "all":
                entry.select_range(0, tk.END)
                entry.icursor(tk.END)
        except tk.TclError:
            pass

    def _on_search_changed(self):
        self.schedule_search()
        self.after_idle(self.highlight_search_matches)

    def highlight_search_matches(self):
        """Подсвечивает совпадения поискового запроса в открытой заметке светло-зелёным."""
        if not hasattr(self, "editor"):
            return
        query = self.search_var.get().strip()
        self.editor.tag_remove("search_match", "1.0", tk.END)
        self.editor.tag_configure("search_match", background="#d9f99d", foreground="#1f2937")
        if len(query) < 1:
            return
        start = "1.0"
        query_lower = query.lower()
        while True:
            pos = self.editor.search(query, start, stopindex=tk.END, nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            self.editor.tag_add("search_match", pos, end)
            start = end

    # ==========================================================================
    # КОНТЕКСТНЫЕ МЕНЮ
    # ==========================================================================

    def _build_context_menus(self):
        self.context_menu = tk.Menu(self, tearoff=0, font=("Segoe UI", 9))
        self.context_menu.add_command(label="Вырезать", accelerator="Ctrl+X", command=self.menu_cut)
        self.context_menu.add_command(label="Копировать", accelerator="Ctrl+C", command=self.menu_copy)
        self.context_menu.add_command(label="Вставить", accelerator="Ctrl+V", command=self.menu_paste)
        self.context_menu.add_command(label="Удалить", command=self.menu_delete)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Выбрать всё", accelerator="Ctrl+A", command=self.menu_select_all)
        self.editor.bind("<Button-3>", self.show_editor_menu)
        self.title_entry.bind("<Button-3>", self.show_editor_menu)

        self.tree_menu = tk.Menu(self, tearoff=0, font=("Segoe UI", 9))
        self.tree_menu.add_command(label="➕ Новая заметка здесь", command=self._create_note_in_selected)
        self.tree_menu.add_command(label="📁 Новая папка здесь", command=self._create_folder_in_selected)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="✏️ Переименовать", command=self.rename_in_tree)
        self.tree_menu.add_command(label="🗑️ Удалить", command=self.delete_selected_items)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="📂 Показать в Проводнике", command=self._open_in_explorer)
        self.tree_menu.add_command(label="🔄 Обновить дерево", command=self.refresh_notes_tree)
        self.tree.bind("<Button-3>", self.show_tree_menu)

    def show_editor_menu(self, event):
        if event.widget in (self.editor, self.title_entry):
            event.widget.focus_set()
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
        return "break"

    def show_tree_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.tree.focus(item)
            try:
                self.tree_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.tree_menu.grab_release()

    def wrap_selection(self, prefix, suffix):
        try:
            start, end = self.editor.index("sel.first"), self.editor.index("sel.last")
            selected = self.editor.get(start, end)
            self.editor.delete(start, end)
            self.editor.insert(start, f"{prefix}{selected}{suffix}")
            self.editor.tag_add("sel", start, f"{start}+{len(prefix + selected + suffix)}c")
            self.on_editor_key_release(None)
        except tk.TclError:
            self.show_toast("Сначала выделите текст", "#f59e0b")

    def change_selected_font_size(self, delta):
        self._editor_font_size = max(8, min(36, self._editor_font_size + delta))
        self.editor.config(font=("Segoe UI", self._editor_font_size))
        self._setup_markdown_tags()
        self.apply_markdown_highlighting(force=True)
        self.show_toast(f"Размер шрифта: {self._editor_font_size} pt")

    def menu_cut(self):
        focused = self.focus_get()
        if focused in (self.editor, self.title_entry):
            focused.event_generate("<<Cut>>")

    def menu_copy(self):
        focused = self.focus_get()
        if focused == self.editor:
            try:
                start, end = self.editor.index("sel.first"), self.editor.index("sel.last")
            except tk.TclError:
                return
            text = self.editor.get(start, end)
            self.clipboard_clear()
            self.clipboard_append(_markdown_bullets(text))
            return
        if focused == self.title_entry:
            focused.event_generate("<<Copy>>")

    def menu_delete(self):
        focused = self.focus_get()
        try:
            if focused == self.editor:
                self.editor.delete("sel.first", "sel.last")
            elif focused == self.title_entry:
                self.title_entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

    def menu_select_all(self):
        focused = self.focus_get()
        if focused == self.editor:
            self.editor.tag_add("sel", "1.0", tk.END)
        elif focused == self.title_entry:
            self.title_entry.select_range(0, tk.END)

    def _open_in_explorer(self):
        selected = self.tree.selection()
        if not selected:
            path_to_open = self.vault_path
        else:
            values = self.tree.item(selected[0], "values")
            path_to_open = Path(values[0]) if values else self.vault_path
        try:
            if path_to_open.is_file():
                os.system(f'explorer /select,"{path_to_open}"')
            else:
                os.system(f'explorer "{path_to_open}"')
        except Exception as e:
            self.show_toast(f"Ошибка открытия: {e}")

    def _create_note_in_selected(self):
        selected = self.tree.selection()
        if selected:
            values = self.tree.item(selected[0], "values")
            if values:
                p = Path(values[0])
                self.current_target_folder = p if p.is_dir() else p.parent
        self.create_new_note()

    def _create_folder_in_selected(self):
        selected = self.tree.selection()
        target_dir = self.vault_path
        if selected:
            values = self.tree.item(selected[0], "values")
            if values:
                p = Path(values[0])
                target_dir = p if p.is_dir() else p.parent

        dialog = tk.Toplevel(self)
        dialog.title("Новая папка")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=self.colors["bg_editor"])
        dialog.geometry("320x120")

        tk.Label(
            dialog, text="Имя новой папки:", bg=self.colors["bg_editor"],
            fg=self.colors["text_main"], font=("Segoe UI", 9)
        ).pack(anchor="w", padx=12, pady=(10, 2))

        entry = tk.Entry(dialog, font=("Segoe UI", 9), bg=self.colors["bg_sidebar"], fg=self.colors["text_main"])
        entry.pack(fill=tk.X, padx=12, pady=5)
        entry.focus()

        def do_create():
            name = entry.get().strip()
            clean = re.sub(r'[\\/*?:"<>|]', "", name)
            if clean:
                new_folder = target_dir / clean
                new_folder.mkdir(parents=True, exist_ok=True)
                self.refresh_notes_tree()
                self.show_toast(f"📁 Папка создана: {clean}", "#10b981")
            dialog.destroy()

        btn_box = tk.Frame(dialog, bg=self.colors["bg_editor"])
        btn_box.pack(pady=5)
        tk.Button(btn_box, text="OK", command=do_create, bg=self.colors["accent"], fg="#ffffff", relief=tk.FLAT, width=8).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_box, text="Отмена", command=dialog.destroy, bg=self.colors["btn_bg"], fg=self.colors["text_main"], relief=tk.FLAT, width=8).pack(side=tk.LEFT, padx=3)
        dialog.bind("<Return>", lambda e: do_create())

    # ==========================================================================
    # ПЕРЕИМЕНОВАНИЕ И УДАЛЕНИЕ
    # ==========================================================================

    def rename_in_tree(self):
        selected = self.tree.selection()
        if not selected or len(selected) > 1:
            self.show_toast("Выберите один элемент для переименования", "#f59e0b")
            return

        item = selected[0]
        values = self.tree.item(item, "values")
        if not values or len(values) < 2:
            return
        path_obj = Path(values[0])
        if not path_obj.exists():
            return

        current_name = path_obj.stem
        dialog = tk.Toplevel(self)
        dialog.title("Переименовать")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=self.colors["bg_editor"])
        dialog.resizable(False, False)

        bbox = self.tree.bbox(item)
        if bbox:
            x = self.tree.winfo_rootx() + bbox[0] + 10
            y = self.tree.winfo_rooty() + bbox[1] + 10
            dialog.geometry(f"+{x}+{y}")

        frame = tk.Frame(dialog, bg=self.colors["bg_editor"])
        frame.pack(padx=10, pady=10)

        tk.Label(frame, text="Новое имя:", bg=self.colors["bg_editor"], fg=self.colors["text_main"], font=("Segoe UI", 10)).pack(anchor="w")
        entry = tk.Entry(
            frame, font=("Segoe UI", 10), width=30,
            bg=self.colors["bg_sidebar"], fg=self.colors["text_main"],
            insertbackground=self.colors["text_main"]
        )
        entry.insert(0, current_name)
        entry.select_range(0, tk.END)
        entry.pack(pady=5, fill=tk.X)
        entry.focus()

        btn_frame = tk.Frame(frame, bg=self.colors["bg_editor"])
        btn_frame.pack(pady=5)

        def do_rename():
            new_name = entry.get().strip()
            if not new_name or new_name == current_name:
                dialog.destroy()
                return
            new_name_clean = re.sub(r'[\\/*?:"<>|]', "", new_name)
            if not new_name_clean:
                dialog.destroy()
                return
            new_path = path_obj.parent / f"{new_name_clean}{path_obj.suffix}"
            if new_path.exists():
                self.show_toast("Файл с таким именем уже существует!", "#f59e0b")
                return
            try:
                path_obj.rename(new_path)
                dialog.destroy()
                self.refresh_notes_tree()
                if self.current_note_path == path_obj:
                    self.current_note_path = new_path
                    self.title_entry.delete(0, tk.END)
                    self.title_entry.insert(0, new_path.stem)
            except Exception as e:
                self.show_toast(f"Ошибка: {e}")

        tk.Button(btn_frame, text="OK", command=do_rename, bg=self.colors["accent"], fg="white", relief=tk.FLAT, bd=0, width=8).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_frame, text="Отмена", command=dialog.destroy, bg=self.colors["btn_bg"], fg=self.colors["text_main"], relief=tk.FLAT, bd=0, width=8).pack(side=tk.LEFT, padx=3)
        entry.bind("<Return>", lambda e: do_rename())

    def delete_selected_items(self):
        selected = self.tree.selection()
        if not selected:
            self.show_toast("Нет выбранных элементов", "#f59e0b")
            return

        for item in selected:
            values = self.tree.item(item, "values")
            if values and len(values) >= 2:
                path_obj = Path(values[0])
                if path_obj == self.daily_path:
                    self.show_toast("Нельзя удалить папку DailyNotes!", "#ef4444")
                    return

        count = len(selected)
        selected_names = []
        for item in selected:
            values = self.tree.item(item, "values")
            if values and len(values) >= 1:
                selected_names.append(Path(values[0]).name or str(values[0]))
        if count == 1:
            target_name = selected_names[0] if selected_names else "выбранный элемент"
            confirm_text = f'Удалить «{target_name}»? Это действие нельзя отменить.'
        else:
            preview = "\n".join(f"• {name}" for name in selected_names[:5])
            if count > 5:
                preview += f"\n… и ещё {count - 5}"
            confirm_text = f"Удалить {count} элементов? Это действие нельзя отменить.\n\n{preview}"
        if messagebox.askyesno("Подтверждение удаления", confirm_text):
            deleted = 0
            for item in selected:
                values = self.tree.item(item, "values")
                if not values or len(values) < 2:
                    continue
                path_obj = Path(values[0])
                if not path_obj.exists():
                    continue
                try:
                    if path_obj.is_dir():
                        import shutil
                        shutil.rmtree(path_obj)
                    else:
                        path_obj.unlink()
                    deleted += 1
                except Exception as e:
                    print(f"Ошибка удаления {path_obj}: {e}")

            if self.current_note_path and not self.current_note_path.exists():
                self.current_note_path = None
                self.editor.delete("1.0", tk.END)
                self.title_entry.delete(0, tk.END)

            # Не перестраиваем всё дерево: это сворачивало/сбрасывало состояние папок.
            # Удаляем только реально удалённые узлы Treeview.
            for item in list(selected):
                try:
                    values = self.tree.item(item, "values")
                    if values and len(values) >= 2 and not Path(values[0]).exists():
                        self.tree.delete(item)
                except tk.TclError:
                    pass
            self.show_toast(f"🗑️ Удалено {deleted} элементов", "#ef4444")

    # ==========================================================================
    # МИНИ-РЕЖИМ: плавающая выезжающая иконка у края экрана
    # ==========================================================================

    def toggle_mini_mode(self):
        self.is_mini_mode = not self.is_mini_mode
        if self.is_mini_mode:
            self.update_idletasks()
            self.normal_geometry = self.geometry()
            self.withdraw()
            self.tree.delete(*self.tree.get_children())
            self.search_var.set("")
            if self._save_timer:
                self.after_cancel(self._save_timer)
                self._save_timer = None
            if self._highlight_timer:
                self.after_cancel(self._highlight_timer)
                self._highlight_timer = None
            gc.collect()
            self._create_mini_icon()
        else:
            self._cancel_mini_timers()
            if self.mini_icon_window and self.mini_icon_window.winfo_exists():
                self.mini_icon_window.destroy()
                self.mini_icon_window = None
            if hasattr(self, "normal_geometry") and self.normal_geometry:
                try:
                    self.geometry(self.normal_geometry)
                except Exception:
                    pass
            self.deiconify()
            self.update_idletasks()
            try:
                self.geometry(self.normal_geometry)
            except tk.TclError:
                pass
            self.lift()
            self.focus_force()
            self.refresh_notes_tree()

    def _cancel_mini_timers(self):
        for attr in ("_mini_hide_timer", "_mini_anim_timer"):
            tid = getattr(self, attr, None)
            if tid:
                try:
                    self.after_cancel(tid)
                except Exception:
                    pass
                setattr(self, attr, None)

    def _get_monitors(self):
        """Возвращает рабочие области мониторов, исключая панель задач Windows."""
        if os.name != "nt":
            return [{"left": 0, "top": 0, "right": self.winfo_screenwidth(), "bottom": self.winfo_screenheight(), "id": "primary", "primary": True}]

        monitors = []
        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        user32 = ctypes.windll.user32
        get_info = user32.GetMonitorInfoW
        get_info.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
        get_info.restype = wintypes.BOOL
        def callback(hmon, hdc, rect_ptr, data):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if get_info(hmon, ctypes.byref(info)):
                r = info.rcWork
                monitors.append({"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom, "id": str(int(hmon)), "primary": bool(info.dwFlags & 1)})
            return 1
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
        return monitors or [{"left": 0, "top": 0, "right": self.winfo_screenwidth(), "bottom": self.winfo_screenheight(), "id": "primary", "primary": True}]

    def _mini_monitor_for_point(self, x, y):
        monitors = self._get_monitors()
        best, best_dist = monitors[0], float("inf")
        for m in monitors:
            cx = min(max(x, m["left"]), m["right"] - 1)
            cy = min(max(y, m["top"]), m["bottom"] - 1)
            d = (x - cx) ** 2 + (y - cy) ** 2
            if d < best_dist:
                best, best_dist = m, d
        return best

    def _mini_monitor_by_id(self, monitor_id):
        if monitor_id:
            for monitor in self._get_monitors():
                if monitor["id"] == monitor_id:
                    return monitor
        return self._mini_monitor_for_point(self._mini_full_x or self.winfo_screenwidth() // 2, self._mini_full_y or self.winfo_screenheight() // 2)

    def _mini_clamp(self, x, y, monitor):
        size = self.icon_size
        return (
            max(monitor["left"], min(int(x), monitor["right"] - size)),
            max(monitor["top"], min(int(y), monitor["bottom"] - size)),
        )

    def _mini_edge_position(self, edge, x, y, monitor, hidden=False):
        x, y = self._mini_clamp(x, y, monitor)
        half = self.icon_size // 2
        if edge == "top":
            return x, monitor["top"] - half if hidden else monitor["top"]
        if edge == "bottom":
            return x, monitor["bottom"] - half if hidden else monitor["bottom"] - self.icon_size
        if edge == "left":
            return monitor["left"] - half if hidden else monitor["left"], y
        return monitor["right"] - half if hidden else monitor["right"] - self.icon_size, y

    def _mini_nearest_edge(self, x, y):
        monitor = self._mini_monitor_for_point(x + self.icon_size // 2, y + self.icon_size // 2)
        cx, cy = x + self.icon_size // 2, y + self.icon_size // 2
        distances = {"left": abs(cx - monitor["left"]), "right": abs(monitor["right"] - cx), "top": abs(cy - monitor["top"]), "bottom": abs(monitor["bottom"] - cy)}
        self._mini_monitor = monitor["id"]
        return min(distances, key=distances.get)

    def _create_mini_icon(self):
        if self.mini_icon_window and self.mini_icon_window.winfo_exists():
            return
        self.icon_size = 56
        win = self.mini_icon_window = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=self.colors["accent"])
        lbl_icon = tk.Label(win, text="📝", font=("Segoe UI Emoji", 26), bg=self.colors["accent"], fg="#ffffff", cursor="fleur")
        lbl_icon.pack(expand=True, fill=tk.BOTH)
        lbl_icon.bind("<ButtonPress-1>", self._on_mini_icon_drag_start)
        lbl_icon.bind("<B1-Motion>", self._on_mini_icon_drag_motion)
        lbl_icon.bind("<ButtonRelease-1>", self._on_mini_icon_drag_end)
        lbl_icon.bind("<Double-Button-1>", lambda e: self.toggle_mini_mode())
        lbl_icon.bind("<Enter>", self._on_mini_enter)
        lbl_icon.bind("<Leave>", self._on_mini_leave)
        ToolTip(win, "Перетащите к краю экрана · 1 клик — развернуть")

        monitors = self._get_monitors()
        monitor = next((m for m in monitors if m["id"] == self._mini_monitor), monitors[0])
        self._mini_monitor = monitor["id"]
        if self._mini_full_x is None or self._mini_full_y is None:
            self._mini_full_x = (monitor["left"] + monitor["right"] - self.icon_size) // 2
            self._mini_full_y = monitor["top"]
        self._mini_full_x, self._mini_full_y = self._mini_clamp(self._mini_full_x, self._mini_full_y, monitor)
        x, y = self._mini_edge_position(self._mini_edge, self._mini_full_x, self._mini_full_y, monitor)
        win.geometry(f"{self.icon_size}x{self.icon_size}+{x}+{y}")
        win.lift()
        self.after(100, self._mini_hide_half)

    def _animate_mini_to(self, target_x, target_y, steps=8, delay=12):
        self._cancel_mini_timers()
        win = self.mini_icon_window
        if not win or not win.winfo_exists():
            return
        try:
            start_x, start_y = win.winfo_x(), win.winfo_y()
        except tk.TclError:
            return
        def step(i=0):
            if not (self.mini_icon_window and self.mini_icon_window.winfo_exists()):
                return
            t = i / steps
            nx, ny = int(start_x + (target_x - start_x) * t), int(start_y + (target_y - start_y) * t)
            self.mini_icon_window.geometry(f"+{nx}+{ny}")
            if i < steps:
                self._mini_anim_timer = self.after(delay, lambda: step(i + 1))
            else:
                self._mini_anim_timer = None
                self.mini_icon_window.lift()
        step()

    def _mini_reveal(self):
        if not (self.mini_icon_window and self.mini_icon_window.winfo_exists()):
            return
        monitor = self._mini_monitor_by_id(self._mini_monitor)
        x, y = self._mini_edge_position(self._mini_edge, self._mini_full_x, self._mini_full_y, monitor)
        self._animate_mini_to(x, y)

    def _mini_hide_half(self):
        if not (self.mini_icon_window and self.mini_icon_window.winfo_exists()):
            return
        monitor = self._mini_monitor_by_id(self._mini_monitor)
        x, y = self._mini_edge_position(self._mini_edge, self._mini_full_x, self._mini_full_y, monitor, hidden=True)
        self._animate_mini_to(x, y)

    def _on_mini_enter(self, event):
        if self._mini_hide_timer:
            self.after_cancel(self._mini_hide_timer)
            self._mini_hide_timer = None
        if not self._mini_dragging:
            self._mini_reveal()

    def _on_mini_leave(self, event):
        if self._mini_dragging:
            return
        if self._mini_hide_timer:
            self.after_cancel(self._mini_hide_timer)
        self._mini_hide_timer = self.after(700, self._mini_hide_half)

    def _on_mini_icon_drag_start(self, event):
        self._mini_dragging = True
        self._cancel_mini_timers()
        self._mini_drag_start_x, self._mini_drag_start_y = event.x, event.y
        self._mini_press_x, self._mini_press_y = event.x_root, event.y_root

    def _on_mini_icon_drag_motion(self, event):
        if not self.mini_icon_window or not self.mini_icon_window.winfo_exists():
            return
        x = self.mini_icon_window.winfo_x() + event.x - self._mini_drag_start_x
        y = self.mini_icon_window.winfo_y() + event.y - self._mini_drag_start_y
        monitor = self._mini_monitor_for_point(event.x_root, event.y_root)
        x, y = self._mini_clamp(x, y, monitor)
        self.mini_icon_window.geometry(f"+{x}+{y}")

    def _on_mini_icon_drag_end(self, event):
        self._mini_dragging = False
        if not self.mini_icon_window or not self.mini_icon_window.winfo_exists():
            return
        dx = abs(event.x_root - getattr(self, "_mini_press_x", event.x_root))
        dy = abs(event.y_root - getattr(self, "_mini_press_y", event.y_root))
        if dx < 6 and dy < 6:
            self.toggle_mini_mode()
            return
        x, y = self.mini_icon_window.winfo_x(), self.mini_icon_window.winfo_y()
        self._mini_edge = self._mini_nearest_edge(x, y)
        monitor = self._mini_monitor_by_id(self._mini_monitor)
        self._mini_full_x, self._mini_full_y = self._mini_clamp(x, y, monitor)
        self._mini_full_x, self._mini_full_y = self._mini_clamp(self._mini_full_x, self._mini_full_y, monitor)
        full_x, full_y = self._mini_edge_position(self._mini_edge, self._mini_full_x, self._mini_full_y, monitor)
        self._mini_full_x, self._mini_full_y = self._mini_clamp(full_x, full_y, monitor)
        self._animate_mini_to(full_x, full_y)
        self._mini_hide_timer = self.after(900, self._mini_hide_half)

    def toggle_always_on_top(self):
        self.always_on_top = not self.always_on_top
        self.attributes("-topmost", self.always_on_top)
        self._style_flat_button(self.btn_pin, active=self.always_on_top)

    # ==========================================================================
    # СПРАВКА ПО MARKDOWN
    # ==========================================================================

    def toggle_markdown_help(self):
        if self.help_window is not None and self.help_window.winfo_exists():
            self.help_window.destroy()
            self.help_window = None
            return

        self.help_window = tk.Toplevel(self)
        self.help_window.title("Справка и горячие клавиши")
        self.help_window.geometry("620x650")
        self.help_window.transient(self)
        self.help_window.configure(bg=self.colors["bg_editor"])
        self.help_window.bind("<Escape>", lambda e: self.help_window.destroy())

        # Верхняя панель заголовка
        header_frame = tk.Frame(self.help_window, bg=self.colors["bg_sidebar"], padx=16, pady=12)
        header_frame.pack(fill=tk.X)
        lbl_title = tk.Label(
            header_frame, text="📖 Быстрый Заметчик — Справка и возможности",
            font=("Segoe UI", 12, "bold"),
            bg=self.colors["bg_sidebar"], fg=self.colors["tag_header"]
        )
        lbl_title.pack(side=tk.LEFT)

        # Контейнер содержимого
        content_frame = tk.Frame(self.help_window, bg=self.colors["bg_editor"], padx=16, pady=10)
        content_frame.pack(fill=tk.BOTH, expand=True)

        txt_help = tk.Text(
            content_frame, font=("Segoe UI", 10),
            bd=0, bg=self.colors["bg_sidebar"], fg=self.colors["text_main"],
            padx=14, pady=12, wrap=tk.WORD
        )
        scroll = ttk.Scrollbar(content_frame, orient=tk.VERTICAL, command=txt_help.yview)
        txt_help.config(yscrollcommand=scroll.set)
        txt_help.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Настройка стилей для справки
        txt_help.tag_configure("h1", font=("Segoe UI", 11, "bold"), foreground=self.colors["tag_header"], spacing1=12, spacing3=4)
        txt_help.tag_configure("badge", font=("Consolas", 9, "bold"), background=self.colors["accent_light"], foreground=self.colors["accent"])
        txt_help.tag_configure("code", font=("Consolas", 10), background=self.colors["tag_code_bg"], foreground=self.colors["tag_code"])
        txt_help.tag_configure("desc", font=("Segoe UI", 10), foreground=self.colors["text_main"])
        txt_help.tag_configure("dim", font=("Segoe UI", 9), foreground=self.colors["text_muted"])
        txt_help.tag_configure("bullet", font=("Segoe UI", 10, "bold"), foreground=self.colors["accent"])

        def ins(text, tag="desc"):
            txt_help.insert(tk.END, text, tag)

        # 1. Горячие клавиши
        ins("⌨️ ГОРЯЧИЕ КЛАВИШИ\n", "h1")
        shortcuts = [
            ("Ctrl+N", "Новая заметка в выбранной папке"),
            ("Ctrl+D", "Ежедневная заметка (канонический формат HH:MM)"),
            ("Ctrl+S", "Сохранить текущую заметку на диск"),
            ("Ctrl+F", "Быстрый поиск заметок по названию и тексту"),
            ("Ctrl+K", "Обернуть текст ссылкой или вставить URL"),
            ("Ctrl+B", "Жирный шрифт (**текст**)"),
            ("Ctrl+I", "Курсивный шрифт (*текст*)"),
            ("Ctrl+H", "Выделение текста маркёром (==текст==)"),
            ("Ctrl+Shift+S", "Зачёркивание (~~текст~~)"),
            ("Ctrl+Shift+C", "Инлайн код (`код`)"),
            ("Ctrl+Shift+T", "Автоматически выровнять Markdown-таблицу"),
            ("Ctrl+Enter", "Переключить статус чекбокса [-] / [x] / [ ]"),
            ("Tab / Shift+Tab", "Увеличить / уменьшить отступ списков"),
            ("Ctrl+W", "Закрыть текущую заметку"),
            ("Delete", "Удалить выбранную заметку или папку"),
        ]
        for key, desc in shortcuts:
            ins(f"  {key:<14}", "badge")
            ins(f"  {desc}\n", "desc")

        # 2. Умная вставка (Smart Paste)
        ins("\n🌐 УМНАЯ ВСТАВКА (SMART PASTE)\n", "h1")
        ins("• YouTube видео: ", "bullet")
        ins("при вставке ссылки с YouTube (включая Shorts) моментально запрашивается и отображается реальное название ролика без задержек и временных заглушек.\n", "desc")
        ins("• Браузерный Smart Copy: ", "bullet")
        ins("сохраняет чистые названия ссылок, заголовки и таблицы из скопированного HTML.\n", "desc")
        ins("• Текст из ИИ: ", "bullet")
        ins("ответы ChatGPT, Gemini, Claude и Perplexity вставляются в оригинальном чистом Markdown без рассыпания разметки.\n", "desc")
        ins("• Выделенный текст: ", "bullet")
        ins("выделите фрагмент текста и нажмите Ctrl+V для автоматического создания ссылки [Текст](URL).\n", "desc")

        # 3. Форматирование текста
        ins("\n📝 РАЗМЕТКА И ФОРМАТИРОВАНИЕ\n", "h1")
        ins("• Заголовки: ", "bullet")
        ins("# H1  ..  ###### H6   или подчеркивание === и ---\n", "code")
        ins("• Блоки кода: ", "bullet")
        ins("```lang ... ``` (отображаются цельным прямоугольным блоком)\n", "code")
        ins("• Таблицы GFM: ", "bullet")
        ins("| Имя | Значение | (поддерживают выравнивание и цельный стиль)\n", "code")
        ins("• Математика: ", "bullet")
        ins("$E=mc^2$ или блоки $$формула$$\n", "code")
        ins("• Эмодзи (🚀, 🛠): ", "bullet")
        ins("отображаются естественными символами и цветами без разбиения на квадраты.\n", "desc")

        # 4. Коллауты Obsidian
        ins("\nℹ️ КОЛЛАУТЫ (CALLOUTS / ADMONITIONS)\n", "h1")
        ins("• > [!NOTE]  ", "badge")
        ins(" Информационный блок с подсветкой\n", "desc")
        ins("• > [!TIP]   ", "badge")
        ins(" Полезная подсказка или рекомендация\n", "desc")
        ins("• > [!WARNING]", "badge")
        ins(" Предупреждение о важных моментах\n", "desc")
        ins("• > [!DANGER]", "badge")
        ins(" Критическая опасность или ошибка\n", "desc")

        txt_help.config(state=tk.DISABLED)

        # Нижняя панель закрытия
        footer_frame = tk.Frame(self.help_window, bg=self.colors["bg_sidebar"], padx=16, pady=8)
        footer_frame.pack(fill=tk.X)
        btn_close = tk.Button(
            footer_frame, text="Закрыть (Esc)", font=("Segoe UI", 9),
            bg=self.colors["accent"], fg="#ffffff", activebackground=self.colors["btn_active"],
            relief=tk.FLAT, bd=0, padx=12, pady=4, cursor="hand2", command=self.help_window.destroy
        )
        btn_close.pack(side=tk.RIGHT)

    # ==========================================================================
    # ПОДСВЕТКА MARKDOWN, LIVE PREVIEW И ЕСТЕСТВЕННЫЕ ЭМОДЗИ
    # ==========================================================================

    def _display_current_star_list_marker(self):
        """Показывает маркер Markdown-списка * как типографский •, не меняя файл на диске."""
        try:
            line_num = int(self.editor.index(tk.INSERT).split(".")[0])
            line = self.editor.get(f"{line_num}.0", f"{line_num}.end")
            if not re.match(r"^(\s*)\*\s", line):
                return
            # Не трогаем строки внутри fenced code block.
            before = self.editor.get("1.0", f"{line_num}.0").splitlines()
            in_fence = sum(1 for item in before if item.startswith("```")) % 2 == 1
            if in_fence:
                return
            m = re.match(r"^(\s*)\*(\s)", line)
            if not m:
                return
            start = f"{line_num}.0+{len(m.group(1))}c"
            self.editor.delete(start, f"{start}+1c")
            self.editor.insert(start, "•")
        except (tk.TclError, ValueError):
            pass

    def on_editor_key_release(self, event):
        if self.is_saving_internal:
            return
        self._display_current_star_list_marker()
        self.is_modified = True
        self._update_status_bar()
        if self._save_timer:
            self.after_cancel(self._save_timer)
        self._save_timer = self.after(1000, self.save_current_note)
        if self._highlight_timer:
            self.after_cancel(self._highlight_timer)
        self._highlight_timer = self.after(250, self.apply_markdown_highlighting)

    def _get_indent_tag(self, base, indent_spaces):
        depth = min(indent_spaces // 2, 8)
        tag_name = f"{base}_{depth}"
        if tag_name not in self._indent_tag_cache:
            margin = 20 + depth * 16
            self.editor.tag_configure(
                tag_name, foreground=self.colors["text_main"],
                lmargin1=margin, lmargin2=margin
            )
            self._indent_tag_cache.add(tag_name)
        return tag_name

    def format_active_table(self):
        """Выравнивает столбцы Markdown-таблицы под курсором в цельную прямоугольную таблицу."""
        try:
            cur_line = int(self.editor.index(tk.INSERT).split(".")[0])
        except Exception:
            return
        lines = self.editor.get("1.0", tk.END).split("\n")
        total_lines = len(lines)
        if cur_line > total_lines:
            return
        if "|" not in lines[cur_line - 1]:
            self.show_toast("Поместите курсор внутри таблицы для выравнивания")
            return
        start_line = cur_line
        while start_line > 1 and "|" in lines[start_line - 2]:
            start_line -= 1
        end_line = cur_line
        while end_line < total_lines and "|" in lines[end_line]:
            end_line += 1
        table_lines = lines[start_line - 1:end_line]
        formatted = format_markdown_table_lines(table_lines)
        start_idx = f"{start_line}.0"
        end_idx = f"{end_line}.end"
        self.editor.delete(start_idx, end_idx)
        self.editor.insert(start_idx, "\n".join(formatted))
        self.apply_markdown_highlighting(force=True)
        self.show_toast("📊 Таблица выровнена")

    def apply_markdown_highlighting(self, force=False):
        """Сканирует текст построчно и накладывает теги форматирования."""
        text_content = self.editor.get("1.0", tk.END)
        if not force and not text_content.strip():
            return

        for tag in MD_TAGS:
            self.editor.tag_remove(tag, "1.0", tk.END)
        for tag in self._indent_tag_cache:
            self.editor.tag_remove(tag, "1.0", tk.END)
        for tag in self.editor.tag_names():
            if tag.startswith("callout_header_") or tag.startswith("callout_body_"):
                self.editor.tag_remove(tag, "1.0", tk.END)

        lines = text_content.split("\n")
        try:
            cursor_line = int(self.editor.index(tk.INSERT).split(".")[0])
        except Exception:
            cursor_line = -1

        in_code_block = False
        in_frontmatter = False
        in_math_block = False

        for idx, line in enumerate(lines, start=1):
            line_start = f"{idx}.0"
            line_end = f"{idx}.end"
            full_line_end = f"{idx}.end + 1c"
            is_active = (idx == cursor_line) or (not self.live_preview_enabled)

            # YAML Frontmatter в начале файла
            if idx == 1 and line.strip() == "---":
                in_frontmatter = True
                self.editor.tag_add("frontmatter", line_start, full_line_end)
                continue
            if in_frontmatter:
                self.editor.tag_add("frontmatter", line_start, full_line_end)
                if line.strip() == "---":
                    in_frontmatter = False
                continue

            # Блоки кода ```lang (цельная прямоугольная область со всеми строками)
            if line.startswith("```"):
                in_code_block = not in_code_block
                self.editor.tag_add("code_fence", line_start, full_line_end)
                self.editor.tag_add("code_block", line_start, full_line_end)
                if not is_active:
                    self.editor.tag_add("hide_markup", line_start, line_end)
                continue
            if in_code_block:
                self.editor.tag_add("code_block", line_start, full_line_end)
                continue

            # Блоки формул $$
            if RE_MATH_BLOCK.match(line):
                in_math_block = not in_math_block
                self.editor.tag_add("math", line_start, full_line_end)
                if not is_active:
                    self.editor.tag_add("hide_markup", line_start, line_end)
                continue
            if in_math_block:
                self.editor.tag_add("math", line_start, full_line_end)
                continue

            # Заголовки H1..H6
            if line.startswith("# "):
                self.editor.tag_add("h1", line_start, line_end)
                if not is_active:
                    self.editor.tag_add("hide_markup", line_start, f"{idx}.2")
            elif line.startswith("## "):
                self.editor.tag_add("h2", line_start, line_end)
                if not is_active:
                    self.editor.tag_add("hide_markup", line_start, f"{idx}.3")
            elif line.startswith("### "):
                self.editor.tag_add("h3", line_start, line_end)
                if not is_active:
                    self.editor.tag_add("hide_markup", line_start, f"{idx}.4")
            elif line.startswith("#### "):
                self.editor.tag_add("h4", line_start, line_end)
                if not is_active:
                    self.editor.tag_add("hide_markup", line_start, f"{idx}.5")
            elif line.startswith("##### "):
                self.editor.tag_add("h5", line_start, line_end)
                if not is_active:
                    self.editor.tag_add("hide_markup", line_start, f"{idx}.6")
            elif line.startswith("###### "):
                self.editor.tag_add("h6", line_start, line_end)
                if not is_active:
                    self.editor.tag_add("hide_markup", line_start, f"{idx}.7")

            # Разделительная линия
            if RE_HR.match(line):
                self.editor.tag_add("hr", line_start, line_end)

            # Коллауты Obsidian: мягкая цветовая подсветка по типу [!NOTE]/[!WARNING]/[!DANGER]...
            m_callout = RE_CALLOUT_START.match(line)
            if m_callout:
                kind = m_callout.group(1).upper()
                known = {
                    "NOTE", "INFO", "TIP", "SUCCESS", "WARNING", "CAUTION",
                    "DANGER", "FAILURE", "BUG", "IMPORTANT", "QUESTION",
                    "ABSTRACT", "EXAMPLE"
                }
                suffix = kind if kind in known else "default"
                self.editor.tag_add(f"callout_header_{suffix}", line_start, full_line_end)
            elif line.lstrip().startswith(">"):
                # Тело callout определяется ближайшим заголовком выше.
                callout_kind = None
                j = idx - 2
                while j >= 0 and lines[j].lstrip().startswith(">"):
                    previous = RE_CALLOUT_START.match(lines[j])
                    if previous:
                        callout_kind = previous.group(1).upper()
                        break
                    j -= 1
                if callout_kind:
                    known = {
                        "NOTE", "INFO", "TIP", "SUCCESS", "WARNING", "CAUTION",
                        "DANGER", "FAILURE", "BUG", "IMPORTANT", "QUESTION",
                        "ABSTRACT", "EXAMPLE"
                    }
                    suffix = callout_kind if callout_kind in known else "default"
                    self.editor.tag_add(f"callout_body_{suffix}", line_start, full_line_end)
                else:
                    self.editor.tag_add("quote", line_start, full_line_end)

            stripped = line.strip()

            # Таблицы GFM (цельные прямоугольные блоки со столбцами)
            if not in_code_block and not in_frontmatter and "|" in stripped:
                self.editor.tag_add("table_block", line_start, full_line_end)
                if RE_TABLE_SEP.match(stripped):
                    self.editor.tag_add("table_sep", line_start, full_line_end)
                elif idx < len(lines) and RE_TABLE_SEP.match(lines[idx].strip()):
                    self.editor.tag_add("table_header", line_start, full_line_end)
                else:
                    if idx % 2 == 0:
                        self.editor.tag_add("table_row_alt", line_start, full_line_end)
                    else:
                        self.editor.tag_add("table_row", line_start, full_line_end)

            # Чекбоксы задач
            m_task = RE_CHECKBOX_LINE.match(line)
            if m_task:
                state = m_task.group(2).lower()
                marker_end = f"{idx}.{tk_p(m_task.end(2) + 1)}"
                marker_start = f"{idx}.{tk_p(m_task.start(2) - 1)}"
                self.editor.tag_add("task_marker", marker_start, marker_end)
                if state == "x":
                    self.editor.tag_add("checkbox_done", line_start, line_end)
                    self.editor.tag_add("task_marker_done", marker_start, marker_end)
                elif state == "-":
                    self.editor.tag_add("checkbox_cancel", line_start, line_end)
                    self.editor.tag_add("task_marker_cancel", marker_start, marker_end)
                elif state == "/":
                    self.editor.tag_add("checkbox_progress", line_start, line_end)
                    self.editor.tag_add("task_marker_progress", marker_start, marker_end)
                else:
                    self.editor.tag_add("checkbox_todo", line_start, line_end)
                    self.editor.tag_add("task_marker_todo", marker_start, marker_end)
            else:
                m_bullet = RE_BULLET.match(line)
                m_number = RE_NUM_LIST.match(line)
                if m_bullet:
                    tag = self._get_indent_tag("bullet_list", len(m_bullet.group(1)))
                    self.editor.tag_add(tag, line_start, line_end)
                elif m_number:
                    tag = self._get_indent_tag("number_list", len(m_number.group(1)))
                    self.editor.tag_add(tag, line_start, line_end)

            # ИНЛАЙН СКАНИРОВАНИЕ С КОРРЕКЦИЕЙ СУРРОГАТОВ UTF-16 (для эмодзи 🚀, 🛠)
            if any(ord(c) > 0xFFFF for c in line):
                tk_offset = 0
                py_to_tk = []
                for ch in line:
                    py_to_tk.append(tk_offset)
                    tk_offset += 2 if ord(ch) > 0xFFFF else 1
                py_to_tk.append(tk_offset)
                def tk_p(pos):
                    return py_to_tk[pos] if pos < len(py_to_tk) else tk_offset
            else:
                def tk_p(pos):
                    return pos

            # 1. Вики-ссылки [[Note|Alias]]
            for m in RE_WIKILINK.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                text_s_idx = f"{idx}.{tk_p(m.start() + 2)}"
                text_e_idx = f"{idx}.{tk_p(m.end() - 2)}"
                self.editor.tag_add("wikilink", text_s_idx, text_e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, text_s_idx)
                    self.editor.tag_add("hide_markup", text_e_idx, e_idx)

            # 2. Изображения ![Alt](URL)
            for m in RE_IMAGE.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                label_s_idx = f"{idx}.{tk_p(m.start() + 2)}"
                label_e_idx = f"{idx}.{tk_p(m.start() + 2 + len(m.group(1)))}"
                self.editor.tag_add("md_image", label_s_idx, label_e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, label_s_idx)
                    self.editor.tag_add("hide_markup", label_e_idx, e_idx)

            # 3. Markdown ссылки [Text](URL) — скрытие URL в Live Preview
            for m in RE_MDLINK.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                label_s_idx = f"{idx}.{tk_p(m.start() + 1)}"
                label_e_idx = f"{idx}.{tk_p(m.start() + 1 + len(m.group(1)))}"
                self.editor.tag_add("md_link", label_s_idx, label_e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, label_s_idx)
                    self.editor.tag_add("hide_markup", label_e_idx, e_idx)

            # 4. Ссылки авто и bare URL
            for m in RE_AUTOLINK.finditer(line):
                self.editor.tag_add("md_link", f"{idx}.{tk_p(m.start() + 1)}", f"{idx}.{tk_p(m.end() - 1)}")
            for m in RE_BARE_URL.finditer(line):
                self.editor.tag_add("md_link", f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}")

            # 5. Жирный курсив ***текст*** или ___текст___
            for m in RE_BOLD_ITALIC.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                self.editor.tag_add("bold_italic", s_idx, e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 3)}")
                    self.editor.tag_add("hide_markup", f"{idx}.{tk_p(m.end() - 3)}", e_idx)

            # 6. Жирный **текст** или __текст__
            for m in RE_BOLD.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                self.editor.tag_add("bold", s_idx, e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 2)}")
                    self.editor.tag_add("hide_markup", f"{idx}.{tk_p(m.end() - 2)}", e_idx)

            # 7. Курсив *текст* или _текст_
            for m in RE_ITALIC.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                self.editor.tag_add("italic", s_idx, e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 1)}")
                    self.editor.tag_add("hide_markup", f"{idx}.{tk_p(m.end() - 1)}", e_idx)

            # 8. Код `code`
            for m in RE_CODE_INLINE.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                self.editor.tag_add("code", s_idx, e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 1)}")
                    self.editor.tag_add("hide_markup", f"{idx}.{tk_p(m.end() - 1)}", e_idx)

            # 9. Подсветка маркёром ==highlight==
            for m in RE_HIGHLIGHT.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                self.editor.tag_add("highlight", s_idx, e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 2)}")
                    self.editor.tag_add("hide_markup", f"{idx}.{tk_p(m.end() - 2)}", e_idx)

            # 10. Зачёркивание ~~strike~~
            for m in RE_STRIKE.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                self.editor.tag_add("strike", s_idx, e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 2)}")
                    self.editor.tag_add("hide_markup", f"{idx}.{tk_p(m.end() - 2)}", e_idx)

            # 11. Инлайн математика $math$ — маркеры скрываются после завершения редактирования.
            for m in RE_MATH_INLINE.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                self.editor.tag_add("math", s_idx, e_idx)
                if not is_active:
                    self.editor.tag_add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 1)}")
                    self.editor.tag_add("hide_markup", f"{idx}.{tk_p(m.end() - 1)}", e_idx)

            # 12. Теги #tag
            for m in RE_TAG.finditer(line):
                self.editor.tag_add("tag", f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}")

            # 13. Смайлики и пиктограммы (естественные цвета, полный охват суррогатов)
            for m in RE_EMOJI.finditer(line):
                self.editor.tag_add("emoji", f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}")

        # Гарантируем наивысший приоритет тега emoji, чтобы смайлики не перекрашивались и не подчёркивались ссылками
        self.editor.tag_raise("emoji")

        # Интерактивное отображение таблиц в стиле Obsidian Live Preview
        self._update_rendered_tables(lines, cursor_line, force)

        self._refresh_fold_markers()

    def _parse_table_data(self, tbl_lines):
        """Парсит строки Markdown-таблицы, определяет выравнивание столбцов и ячейки."""
        rows = []
        for l in tbl_lines:
            parts = [p.strip() for p in re.split(r"(?<!\\)\|", l.strip().strip("|"))]
            rows.append(parts)
        if len(rows) < 2:
            return None, None
        sep_idx = -1
        for i, r in enumerate(rows):
            if all(re.match(r"^:?-+:?$", c) or not c for c in r) and any(c for c in r):
                sep_idx = i
                break
        if sep_idx == -1:
            return None, None

        alignments = []
        for c in rows[sep_idx]:
            left = c.startswith(":")
            right = c.endswith(":")
            if left and right:
                alignments.append("center")
            elif right:
                alignments.append("right")
            else:
                alignments.append("left")

        data_rows = []
        for i, r in enumerate(rows):
            if i == sep_idx:
                continue
            is_hdr = (i < sep_idx)
            data_rows.append((r, is_hdr))
        return alignments, data_rows

    def _create_table_widget(self, alignments, rows, start_line):
        """Создает интерактивную таблицу в стиле Obsidian с рамками и точным выравниванием."""
        border_col = self.colors.get("table_border", "#333333")
        tbl = tk.Frame(self.editor, bg=border_col, bd=0)
        num_cols = len(alignments)
        fs = self._editor_font_size

        for r_idx, (cols, is_hdr) in enumerate(rows):
            bg = self.colors.get("tag_table_header_bg", "#18181c") if is_hdr else self.colors.get("tag_table_bg", "#18181c")
            fg = self.colors.get("accent", "#60a5fa") if is_hdr else self.colors.get("text_main", "#e4e4e7")
            fnt = ("Segoe UI", fs - 1, "bold" if is_hdr else "normal")
            target_line = start_line if is_hdr else (start_line + 1 + r_idx)

            for c_idx in range(num_cols):
                raw_val = cols[c_idx] if c_idx < len(cols) else ""
                val = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw_val)
                val = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", val)
                align = alignments[c_idx]
                anchor = {"center": "center", "right": "e", "left": "w"}.get(align, "w")

                lbl = tk.Label(
                    tbl, text=val, font=fnt, fg=fg, bg=bg,
                    anchor=anchor, justify=align, padx=12, pady=5
                )
                lbl.grid(row=r_idx, column=c_idx, sticky="nsew", padx=1, pady=1)
                tbl.grid_columnconfigure(c_idx, weight=1)
                lbl.bind("<Button-1>", lambda e, tl=target_line: self._on_rendered_table_click(tl))

        tbl.bind("<Button-1>", lambda e, tl=start_line: self._on_rendered_table_click(tl))
        return tbl

    def _on_rendered_table_click(self, line_num):
        """Переводит курсор на строку таблицы и разворачивает её исходный код для редактирования."""
        self.editor.focus_set()
        self.editor.mark_set(tk.INSERT, f"{line_num}.0")
        self.apply_markdown_highlighting(force=True)
        return "break"

    def _remove_table_window_at(self, line_num):
        """Удаляет встроенный элемент window из указанной строки текста."""
        try:
            self.editor.configure(undo=False)
            for item in list(self.editor.dump(f"{line_num}.0", f"{line_num}.end")):
                if item[0] == "window":
                    self.editor.delete(item[2])
        except Exception:
            pass
        finally:
            self.editor.configure(undo=True)

    def _clear_all_rendered_tables(self):
        """Очищает все созданные виджеты таблиц при переключении заметки."""
        for key, (_, widget) in list(self._rendered_tables.items()):
            try:
                widget.destroy()
            except Exception:
                pass
            self._remove_table_window_at(key[0])
            try:
                self.editor.tag_remove("hide_table", f"{key[0]}.0", f"{key[1]}.end")
            except Exception:
                pass
        self._rendered_tables.clear()

    def _update_rendered_tables(self, lines, cursor_line, force=False):
        """Отображает таблицы в виде интерактивных виджетов с границами и выравниванием в Live Preview."""
        table_blocks = []
        i = 0
        n = len(lines)
        while i < n:
            stripped = lines[i].strip()
            if stripped.startswith("```"):
                i += 1
                while i < n and not lines[i].strip().startswith("```"):
                    i += 1
                i += 1
                continue
            if i == 0 and stripped == "---":
                i += 1
                while i < n and lines[i].strip() != "---":
                    i += 1
                i += 1
                continue
            if "|" in stripped and i + 1 < n and RE_TABLE_SEP.match(lines[i + 1].strip()):
                start_line = i + 1  # 1-based
                tbl_lines = [lines[i], lines[i + 1]]
                j = i + 2
                while j < n and "|" in lines[j] and lines[j].strip():
                    tbl_lines.append(lines[j])
                    j += 1
                end_line = j  # 1-based (inclusive)
                table_blocks.append((start_line, end_line, tbl_lines))
                i = j
            else:
                i += 1

        active_keys = set()
        for start_line, end_line, tbl_lines in table_blocks:
            key = (start_line, end_line)
            active_keys.add(key)
            is_cursor_in_table = (start_line <= cursor_line <= end_line)

            if not self.live_preview_enabled or is_cursor_in_table:
                if key in self._rendered_tables:
                    _, widget = self._rendered_tables.pop(key)
                    try:
                        widget.destroy()
                    except Exception:
                        pass
                    self._remove_table_window_at(start_line)
                    self.editor.tag_remove("hide_table", f"{start_line}.0", f"{end_line}.end")
                continue

            lines_tuple = tuple(tbl_lines)
            if key in self._rendered_tables and not force:
                prev_tuple, widget = self._rendered_tables[key]
                if prev_tuple == lines_tuple and widget.winfo_exists():
                    continue
                else:
                    try:
                        widget.destroy()
                    except Exception:
                        pass
                    self._remove_table_window_at(start_line)
                    self.editor.tag_remove("hide_table", f"{start_line}.0", f"{end_line}.end")

            alignments, rows = self._parse_table_data(tbl_lines)
            if not alignments:
                continue

            widget = self._create_table_widget(alignments, rows, start_line)
            try:
                self.editor.configure(undo=False)
                self.editor.window_create(f"{start_line}.0", window=widget)
                self.editor.tag_add("hide_table", f"{start_line}.1", f"{end_line}.end")
            except tk.TclError:
                pass
            finally:
                self.editor.configure(undo=True)
            self._rendered_tables[key] = (lines_tuple, widget)

        for old_key in list(self._rendered_tables.keys()):
            if old_key not in active_keys:
                _, widget = self._rendered_tables.pop(old_key)
                try:
                    widget.destroy()
                except Exception:
                    pass
                self._remove_table_window_at(old_key[0])
                try:
                    self.editor.tag_remove("hide_table", f"{old_key[0]}.0", f"{old_key[1]}.end")
                except Exception:
                    pass

    def _configure_callout_tags(self, fs):
        """Настраивает мягкие цвета Obsidian-callout по типу [!TYPE]."""
        dark = self.current_theme == "dark"
        palette = {
            "NOTE": ("#60a5fa", "#172033" if dark else "#eff6ff"),
            "INFO": ("#38bdf8", "#12212b" if dark else "#ecfeff"),
            "TIP": ("#34d399", "#10261f" if dark else "#ecfdf5"),
            "SUCCESS": ("#4ade80", "#102417" if dark else "#f0fdf4"),
            "WARNING": ("#f87171", "#2a1718" if dark else "#fef2f2"),
            "CAUTION": ("#fb7185", "#2a1718" if dark else "#fff1f2"),
            "DANGER": ("#ef4444", "#2a1416" if dark else "#fef2f2"),
            "FAILURE": ("#ef4444", "#2a1416" if dark else "#fef2f2"),
            "BUG": ("#f87171", "#2a1718" if dark else "#fef2f2"),
            "IMPORTANT": ("#a78bfa", "#211b30" if dark else "#f5f3ff"),
            "QUESTION": ("#c084fc", "#24172e" if dark else "#faf5ff"),
            "ABSTRACT": ("#818cf8", "#191d35" if dark else "#eef2ff"),
            "EXAMPLE": ("#2dd4bf", "#102522" if dark else "#f0fdfa"),
        }
        default_fg = self.colors["accent"]
        default_bg = self.colors["tag_quote"]
        for kind, (fg, bg) in palette.items():
            self.editor.tag_configure(
                f"callout_header_{kind}", font=("Segoe UI", fs, "bold"),
                foreground=fg, background=bg, lmargin1=16, lmargin2=16
            )
            self.editor.tag_configure(
                f"callout_body_{kind}", foreground=self.colors["text_main"],
                background=bg, lmargin1=16, lmargin2=16
            )
        self.editor.tag_configure(
            "callout_header_default", font=("Segoe UI", fs, "bold"),
            foreground=default_fg, background=default_bg, lmargin1=16, lmargin2=16
        )
        self.editor.tag_configure(
            "callout_body_default", foreground=self.colors["text_main"],
            background=default_bg, lmargin1=16, lmargin2=16
        )

    def _setup_markdown_tags(self):
        """Конфигурация визуальных стилей тегов (соответствие CHARFORMAT2 / RichEdit)."""
        fs = self._editor_font_size
        # Оставляем свободную полосу слева для кнопки сворачивания заголовка.
        heading_indent = 15
        self.editor.tag_configure("h1", font=("Segoe UI", fs + 6, "bold"), foreground=self.colors["tag_header"], lmargin1=heading_indent, lmargin2=heading_indent)
        self.editor.tag_configure("h2", font=("Segoe UI", fs + 4, "bold"), foreground=self.colors["tag_header"], lmargin1=heading_indent, lmargin2=heading_indent)
        self.editor.tag_configure("h3", font=("Segoe UI", fs + 2, "bold"), foreground=self.colors["tag_header"], lmargin1=heading_indent, lmargin2=heading_indent)
        self.editor.tag_configure("h4", font=("Segoe UI", fs + 1, "bold"), foreground=self.colors["text_muted"], lmargin1=heading_indent, lmargin2=heading_indent)
        self.editor.tag_configure("h5", font=("Segoe UI", fs, "bold"), foreground=self.colors["text_muted"], lmargin1=heading_indent, lmargin2=heading_indent)
        self.editor.tag_configure("h6", font=("Segoe UI", fs, "italic"), foreground=self.colors["text_muted"], lmargin1=heading_indent, lmargin2=heading_indent)

        self.editor.tag_configure("bold", font=("Segoe UI", fs, "bold"), foreground=self.colors["tag_bold"])
        self.editor.tag_configure("italic", font=("Segoe UI", fs, "italic"), foreground=self.colors["text_main"])
        self.editor.tag_configure("bold_italic", font=("Segoe UI", fs, "bold italic"), foreground=self.colors["tag_bold"])

        self.editor.tag_configure(
            "code", font=("Consolas", fs - 1), foreground=self.colors["tag_code"],
            background=self.colors["tag_code_bg"]
        )
        # Блоки кода: аккуратная прямоугольная выделенная область с отступами и интервалами
        self.editor.tag_configure(
            "code_block", font=("Consolas", fs - 1), foreground=self.colors["tag_code"],
            background=self.colors["tag_code_bg"], lmargin1=24, lmargin2=24, rmargin=24,
            spacing1=2, spacing3=2
        )
        self.editor.tag_configure(
            "code_fence", font=("Consolas", fs - 2, "bold"), foreground=self.colors["text_muted"],
            background=self.colors["tag_code_fence_bg"], lmargin1=24, lmargin2=24, rmargin=24
        )

        self.editor.tag_configure("checkbox_todo", foreground=self.colors["text_main"])
        self.editor.tag_configure("task_marker", font=("Segoe UI", fs, "bold"), relief=tk.FLAT)
        self.editor.tag_configure("task_marker_todo", foreground="#9ca3af", background=self.colors["bg_editor"])
        self.editor.tag_configure("task_marker_done", foreground="#6b7280", background="#e5e7eb")
        self.editor.tag_configure("task_marker_cancel", foreground="#9ca3af", background=self.colors["bg_editor"])
        self.editor.tag_configure("task_marker_progress", foreground="#ffffff", background=self.colors["accent"])
        self.editor.tag_configure("checkbox_done", foreground="#9ca3af", overstrike=True)
        self.editor.tag_configure("checkbox_cancel", foreground=self.colors["tag_done"], overstrike=True)
        self.editor.tag_configure("checkbox_progress", foreground=self.colors["accent"])

        self.editor.tag_configure("bullet_list", foreground=self.colors["text_main"], lmargin1=20, lmargin2=20)
        self.editor.tag_configure("number_list", foreground=self.colors["text_main"], lmargin1=20, lmargin2=20)

        self.editor.tag_configure("wikilink", foreground=self.colors["accent"], underline=True)
        self.editor.tag_configure("md_link", foreground=self.colors["accent"], underline=True)
        self.editor.tag_configure("md_image", foreground=self.colors["accent"], font=("Segoe UI", fs, "italic"))

        self.editor.tag_configure("hr", foreground=self.colors["text_muted"])
        self.editor.tag_configure(
            "highlight", font=("Segoe UI", fs, "bold"),
            background=self.colors["tag_highlight"], foreground=self.colors["tag_highlight_fg"]
        )
        self.editor.tag_configure("strike", foreground=self.colors["tag_strike"], overstrike=True)

        self.editor.tag_configure(
            "quote", foreground=self.colors["text_muted"],
            background=self.colors["tag_quote"], lmargin1=16, lmargin2=16
        )
        self._configure_callout_tags(fs)

        # Таблицы GFM: цельные прямоугольные таблицы со столбцами
        self.editor.tag_configure(
            "table_block", font=("Consolas", fs - 1),
            background=self.colors["tag_table_bg"], lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure(
            "table_header", font=("Consolas", fs - 1, "bold"),
            foreground=self.colors["accent"], background=self.colors["tag_table_header_bg"],
            lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure(
            "table_sep", font=("Consolas", fs - 1),
            foreground=self.colors["text_muted"], background=self.colors["tag_table_sep_bg"],
            lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure(
            "table_row", font=("Consolas", fs - 1),
            background=self.colors["tag_table_bg"], lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure(
            "table_row_alt", font=("Consolas", fs - 1),
            background=self.colors["tag_table_alt_bg"], lmargin1=20, lmargin2=20, rmargin=20
        )

        self.editor.tag_configure("tag", foreground=self.colors["tag_tag"], font=("Segoe UI", fs, "bold"))
        self.editor.tag_configure("math", foreground=self.colors["tag_math"], font=("Consolas", fs - 1, "italic"))
        self.editor.tag_configure("frontmatter", foreground=self.colors["text_muted"], font=("Consolas", fs - 1))

        # Естественные цвета эмодзи (отдельный шрифт Segoe UI Emoji, теплый естественный оттенок)
        self.editor.tag_configure("emoji", font=("Segoe UI Emoji", fs), foreground=self.colors["tag_emoji"], underline=False)

        # Настоящий Live Preview: elide=True схлопывает символы до нулевой ширины!
        self.editor.tag_configure("hide_table", elide=True)
        if self.live_preview_enabled:
            self.editor.tag_configure("hide_markup", elide=True)
        else:
            self.editor.tag_configure("hide_markup", elide=False, foreground=self.colors["text_muted"])

    # ==========================================================================
    # ПОИСК И ДЕРЕВО ЗАМЕТОК
    # ==========================================================================

    def schedule_search(self):
        if self._search_timer:
            self.after_cancel(self._search_timer)
        self._search_timer = self.after(300, self.filter_notes_tree)

    def clear_search(self):
        self.search_var.set("")
        self.editor.tag_remove("search_match", "1.0", tk.END)
        self.refresh_notes_tree()

    def select_vault_folder(self):
        """Выбор папки хранилища на время текущего сеанса (без сохранения в конфиг)."""
        folder_selected = filedialog.askdirectory(
            title="Выберите папку хранилища (на время текущего сеанса)", initialdir=str(self.vault_path)
        )
        if folder_selected:
            self.vault_path = Path(folder_selected)
            self.current_target_folder = self.vault_path
            self.current_note_path = None
            self.editor.delete("1.0", tk.END)
            self.title_entry.delete(0, tk.END)
            self.refresh_notes_tree()
            self.show_toast(f"📁 Хранилище сеанса: {self.vault_path.name}")

    def refresh_notes_tree(self):
        self.tree.delete(*self.tree.get_children())
        if not self.vault_path or not self.vault_path.exists():
            return
        root_id = self.tree.insert(
            "", "end", text=f"📚 {self.vault_path.name}",
            open=True, values=[str(self.vault_path), "root"]
        )
        self._add_folder_children(root_id, self.vault_path)

    def _add_folder_children(self, parent_node, path_obj):
        try:
            items = sorted(list(path_obj.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
        except Exception:
            return
        for item in items:
            if item.name.startswith("."):
                continue
            if item.is_dir():
                folder_id = self.tree.insert(
                    parent_node, "end", text=f"📁 {item.name}",
                    open=False, values=[str(item), "folder"]
                )
                self.tree.insert(folder_id, "end", text="⏳ загрузка...")
            elif item.is_file() and item.suffix.lower() == ".md":
                self.tree.insert(
                    parent_node, "end", text=f"📝 {item.stem}",
                    values=[str(item), "file"]
                )

    def on_tree_open(self, event):
        item = self.tree.focus()
        values = self.tree.item(item, "values")
        if not values or len(values) < 2 or values[1] != "folder":
            return
        children = self.tree.get_children(item)
        if len(children) == 1 and self.tree.item(children[0])["text"] == "⏳ загрузка...":
            self.tree.delete(children[0])
            self._add_folder_children(item, Path(values[0]))

    def on_tree_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.rename_in_tree()

    def filter_notes_tree(self):
        query = self.search_var.get().strip().lower()
        if not query:
            self.refresh_notes_tree()
            return
        self.tree.delete(*self.tree.get_children())
        root_id = self.tree.insert(
            "", "end", text=f"🔍 Результаты: '{query}'",
            open=True, values=["", "root"]
        )
        try:
            for file_path in self.vault_path.glob("**/*.md"):
                if file_path.name.startswith("."):
                    continue
                note_name = file_path.stem.lower()
                matches = query in note_name
                if not matches:
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                if query in line.lower():
                                    matches = True
                                    break
                    except Exception:
                        pass
                if matches:
                    rel_path = file_path.relative_to(self.vault_path)
                    self.tree.insert(
                        root_id, "end", text=f"📝 {rel_path}",
                        values=[str(file_path), "file"]
                    )
        except Exception as e:
            self.show_toast(f"Ошибка поиска: {e}")

    def on_note_selected(self, event):
        selected = self.tree.selection()
        if not selected or len(selected) > 1:
            return
        item = selected[0]
        values = self.tree.item(item, "values")
        if not values or len(values) < 2:
            return
        file_path_str, item_type = values[0], values[1]
        if item_type == "folder":
            self.current_target_folder = Path(file_path_str)
        elif item_type == "file":
            file_path = Path(file_path_str)
            if file_path.suffix.lower() != ".md":
                return
            self.current_target_folder = file_path.parent
            self.open_note(file_path)

    def open_note(self, note_path):
        note_path = Path(note_path)
        if note_path.suffix.lower() != ".md" or not note_path.is_file():
            self.show_toast("⚠️ Открываются только Markdown-файлы (.md)", "#f59e0b")
            return
        self.save_current_note()
        self.current_note_path = note_path
        try:
            with open(note_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.is_saving_internal = True
            self._clear_all_rendered_tables()
            self.title_entry.delete(0, tk.END)
            self.title_entry.insert(0, note_path.stem)
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", _display_bullets(content))
            self.is_saving_internal = False
            self.is_modified = False
            self.apply_markdown_highlighting(force=True)
            self.highlight_search_matches()
            self._update_status_bar()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{e}")

    def close_current_note(self):
        if self.current_note_path:
            self.save_current_note()
            self.current_note_path = None
            self._clear_all_rendered_tables()
            self.editor.delete("1.0", tk.END)
            self.title_entry.delete(0, tk.END)
            self.is_modified = False
            self._update_status_bar()

    # ==========================================================================
    # СОЗДАНИЕ И СОХРАНЕНИЕ ЗАМЕТОК
    # ==========================================================================

    def create_new_note(self):
        self.save_current_note()
        target_dir = self.current_target_folder if self.current_target_folder.exists() else self.vault_path
        base_name = "Новая заметка"
        new_path = target_dir / f"{base_name}.md"
        counter = 1
        while new_path.exists():
            new_path = target_dir / f"{base_name} ({counter}).md"
            counter += 1
        now = datetime.now().strftime("Создано: %d.%m.%Y  %H:%M")
        template = f"# Заголовок\n\nНачните писать здесь...\n\n\n`{now}`\n"
        try:
            write_text_atomic(new_path, template)
            self.refresh_notes_tree()
            self.open_note(new_path)
            self.editor.focus()
            self.show_toast("✅ Новая заметка создана", "#10b981")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать заметку:\n{e}")

    def create_daily_note(self):
        """Создает ежедневную заметку по каноническому стандарту Obsidian (HH:MM)."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")
        daily_file = self.daily_path / f"{date_str}.md"
        if daily_file.exists():
            self.open_note(daily_file)
            return

        weekday = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"][now.weekday()]
        template = f"""# {date_str} — {weekday}

`Создано: {date_str}  {time_str}`

## Задачи
- [ ] 

## Заметки
- 

## Журнал дня
- 
"""
        try:
            write_text_atomic(daily_file, template)
            self.refresh_notes_tree()
            self.open_note(daily_file)
            self.editor.focus()
            self.show_toast("📅 Ежедневная заметка создана", "#0284c7")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать ежедневную заметку:\n{e}")

    def save_current_note(self):
        if not self.current_note_path or self.is_saving_internal:
            return
        try:
            content = self.editor.get("1.0", tk.END)
            content = _markdown_bullets(content).rstrip() + "\n"
            write_text_atomic(self.current_note_path, content)
            self.is_modified = False
            self._update_status_bar()
        except Exception as e:
            print(f"Ошибка сохранения: {e}")

    def on_title_commit(self, event=None):
        """Переименовывает заметку только после Enter или потери фокуса."""
        if not self.current_note_path or self.is_saving_internal:
            return
        new_title = self.title_entry.get().strip()
        new_title_clean = safe_note_name(new_title, self.current_note_path.stem)
        if new_title_clean == self.current_note_path.stem:
            return
        new_path = self.current_note_path.parent / f"{new_title_clean}.md"
        if new_path.exists():
            self.show_toast("⚠️ Файл с таким именем уже существует", "#f59e0b")
            self.is_saving_internal = True
            self.title_entry.delete(0, tk.END)
            self.title_entry.insert(0, self.current_note_path.stem)
            self.is_saving_internal = False
            return
        try:
            self.current_note_path.rename(new_path)
            self.current_note_path = new_path
            self.refresh_notes_tree()
        except OSError as e:
            self.show_toast(f"Ошибка переименования: {e}")

    on_title_changed = on_title_commit
    def on_closing(self):
        """Закрытие программы без сохранения файла конфигурации."""
        self._cancel_mini_timers()
        if self.mini_icon_window and self.mini_icon_window.winfo_exists():
            self.mini_icon_window.destroy()
        if self._save_timer:
            self.after_cancel(self._save_timer)
            self._save_timer = None
        self.save_current_note()
        self.destroy()

    def _on_mousewheel(self, event):
        self.editor.yview_scroll(int(-1 * (event.delta / 120)), "units")


if __name__ == "__main__":
    app = QuickObsidianNotesApp()
    app.mainloop()
