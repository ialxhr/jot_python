"""
БЫСТРЫЙ ЗАМЕТЧИК ДЛЯ OBSIDIAN v0.1
Лёгкое, сверхбыстрое приложение для работы с заметками в стиле Obsidian.
Максимальная поддержка стандартов Markdown (CommonMark, GFM, Obsidian).
Оптимизировано для слабого железа (4GB RAM, Core i5 2010 и слабее).
Особенности v3.5:
 Полноценный Smart Paste:
  Преобразование HTML в Markdown со сохранением заголовков ссылок и таблиц.
  Вставка текста из ИИ (ChatGPT, Gemini, Claude) без рассыпания разметки.
  Вставка чистого URL при выделенном тексте -> [Выделенный текст](url).
  Вставка одиночного URL -> красивое [Название ссылки](url).
  Автополучение названий видео с YouTube через oEmbed API в фоновом потоке.
  Естественные цвета эмодзи и пиктограмм (🚀, 🛠) даже внутри ссылок и стилей.
  Исправленный стандарт ежедневной заметки (реальное время HH:MM, чистый стиль).
  Бесшовный плоский интерфейс без разделяющей рамки между деревом и редактором.
  Нулевой след на диске: файл конфигурации НЕ создаётся (хранилище по умолчанию —
  папка запуска программы, смена папки действует только на текущий сеанс).
"""
import os
import gc
import re
import json
import threading
import time
import urllib.request
from urllib.parse import urlparse, quote
import ctypes
from ctypes import wintypes
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

# ==============================================================================
# СКОМПИЛИРОВАННЫЕ ШАБЛОНЫ MARKDOWN (компиляция 1 раз при старте программы)
# ==============================================================================
RE_HR = re.compile(r"^\s*(?:-\s*-\s*-[\s-]*|\*\s*\*\s*\*[\s\*]*|_\s*_\s*_[\s_]*)\s*$")
RE_NUM_LIST = re.compile(r"^(\s*)(\d+)[.)]\s")
RE_BULLET = re.compile(r"^(\s*)([-*+•◦])\s")
# Чекбоксы в редакторе показываются символами ☐ ☑ ☒ ◐, а на диске остаются «- [ ]» / «- [x]».
RE_CHECKBOX_LINE = re.compile(r"^(\s*)([☐☑☒])(?:\s+(.*))?$")
RE_TASK_MD = re.compile(r"^(\s*)-\s+\[([ xX\-/])\](?=\s|$)", re.M)
RE_TASK_GLYPH = re.compile(r"^(\s*)([☐☑◐])", re.M)
RE_HEADING_PREFIX = re.compile(r"^#{1,6}\s+")
TASK_GLYPH = {" ": "☐", "x": "☑", "X": "☑", "-": "☒", "/": "◐"}
GLYPH_STATE = {"☐": " ", "☑": "x", "☒": "-", "◐": "/"}
RE_CALLOUT_START = re.compile(r"^\s*>\s*\[!([a-zA-Z]+)\]\s*(.*)$")
RE_BLOCKQUOTE = re.compile(r"^\s*>+\s*")
RE_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
RE_MATH_BLOCK = re.compile(r"^\s*\$\$\s*$")
# Инлайн шаблоны
RE_BOLD_ITALIC = re.compile(r"(?:\*\*\*([^*\n]+)\*\*\*|___([^_\n]+)___)")
RE_BOLD = re.compile(r"(?:\*\*([^*\n]+)\*\*|__([^_\n]+)__)")
RE_ITALIC = re.compile(r"(?:(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_))")
RE_CODE_INLINE = re.compile(r"`([^`\n]+)`")
RE_HIGHLIGHT = re.compile(r"==([^=\n]+)==")
RE_STRIKE = re.compile(r"~~([^~\n]+)~~")
# Подчёркивание: у Markdown своего синтаксиса нет, Obsidian понимает HTML-тег <u>.
RE_UNDERLINE = re.compile(r"<u>([^<\n]+)</u>")
# Формулы: $…$ (группа 1) и \( … \) (группа 2; так их отдают Google, Gemini и ChatGPT).
RE_MATH_INLINE = re.compile(
    r"(?<![\$\\])\$(?!\$)(?=\S)([^$\n]*?\S)\$(?![\$\d])"
    r"|\\\((.+?)\\\)"
)
RE_WIKILINK = re.compile(r"\[\[([^\]\n]+)\]\]")
RE_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^)]+)\)")
# Подпись не содержит «[» — иначе в «[[1](u1), [2](u2)]» первая ссылка захватывала внешнюю скобку
# («[1» вместо «1»), и первая цифра сноски выглядела как обычный крупный текст.
RE_MDLINK = re.compile(r'(?<!!)\[([^\[]+)\]\(([^)\s]+)(?:\s+["\']([^"\']*)["\'])?\)')
RE_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
RE_BARE_URL = re.compile(r'(?<![\w"=])(https?://[^\s<]+)')
RE_TAG = re.compile(r"(?:(?<=^)|(?<=\s))#([a-zA-Zа-яА-Я0-9_/-]+)(?=\s|$)")
RE_HTTP_URL = re.compile(r"^https?://[^\s<>]+$", re.IGNORECASE)
RE_BARE_WEB_URL = re.compile(
    r"^(?:(?:https?:)?//)?(?:www\.)?"
    r"(?:youtube\.com|youtu\.be|[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
    r"(?:/[^\s<>]*)?$",
    re.IGNORECASE,
)
RE_INVALID_FILENAME = re.compile(r'[\\/*?:"<>|]')
# Подписи языка из веб-чатов («powershell», «bash» …) на отдельной строке перед блоком кода:
# при вставке склеиваются с ограждением (```powershell), а не оставляют пустой зазор.
CODE_LANGS = frozenset({
    "powershell", "pwsh", "bash", "shell", "sh", "zsh", "cmd", "batch", "bat", "python", "py",
    "javascript", "js", "typescript", "ts", "json", "yaml", "yml", "toml", "ini", "html", "css",
    "sql", "xml", "csharp", "cpp", "java", "go", "rust", "php", "ruby", "kotlin", "swift", "lua",
    "diff", "markdown", "md", "text", "plaintext", "dockerfile", "asm", "nasm", "console",
})
RE_LANG_LABEL = re.compile(
    r"^[ \t]*`?(" + "|".join(sorted(map(re.escape, CODE_LANGS), key=len, reverse=True)) + r")`?[ \t]*\n+(`{3,})\n",
    re.I | re.M,
)
# Маска для разбора стилей: «(url)» после «]», <автоссылки>, «голые» адреса и `код` заменяются
# символом \x00 той же длины. Индексы не сдвигаются, а «*», «_», «=» внутри URL больше
# не воспринимаются как разметка (раньше ломали жирный курсив рядом со ссылками).
RE_MASK = re.compile(
    r'(?<=\]\()([^)\s]*(?:\s+["\'][^"\']*["\'])?)'
    r"|<https?://[^>\s]+>"
    r'|(?<![\w"=])https?://[^\s<)]+'
    r"|`[^`\n]+`"
)


def _mask_blank(m):
    return "\x00" * len(m.group(0))


# Inline-Markdown внутри ячеек таблицы: именованные внешние группы, чтобы m.lastgroup
# возвращал вид токена (а не вложенную группу с содержимым).
RE_INLINE_TOKEN = re.compile(
    # Формула стоит ПЕРВОЙ: иначе «\» из «\( … \)» съедается как экранированная скобка и в ячейке
    # остаются «((H_{2}SiO_{3}))».
    r"(?P<math>(?:(?<![\$\\])\$(?!\$)(?=\S)(?P<math_t>[^$\n]*?\S)\$(?![\$\d])|\\\((?P<math_u>.+?)\\\)))"
    r"|(?P<esc>\\(?P<esc_c>[`*_{}\[\]()#+\-.!|~=$<>]))"
    r"|(?P<br><br\s*/?>)"
    r"|(?P<code>`(?P<code_t>[^`\n]+)`)"
    r'|(?P<link>\[(?P<link_t>[^\[]+)\]\((?P<link_u>[^)\s]+)(?:\s+["\'][^"\']*["\'])?\))'
    r"|(?P<wiki>\[\[(?:[^\]\n|]+\|)?(?P<wiki_t>[^\]\n]+)\]\])"
    r"|(?P<hsub><sub>(?P<hsub_t>.*?)</sub>)"
    r"|(?P<hsup><sup>(?P<hsup_t>.*?)</sup>)"
    r"|(?P<hins><(?:ins|u)>(?P<hins_t>.*?)</(?:ins|u)>)"
    r"|(?P<bi>\*\*\*(?P<bi_t>.+?)\*\*\*)"
    r"|(?P<b>\*\*(?P<b_t>.+?)\*\*)"
    r"|(?P<b2>__(?P<b2_t>.+?)__)"
    r"|(?P<i>(?<![\w*])\*(?P<i_t>[^*\s](?:[^*]*[^*\s])?)\*(?![\w*]))"
    r"|(?P<i2>(?<![\w_])_(?P<i2_t>[^_\s](?:[^_]*[^_\s])?)_(?![\w_]))"
    r"|(?P<s>~~(?P<s_t>.+?)~~)"
    r"|(?P<m>==(?P<m_t>.+?)==)"
)
# Флаги сегментов: b жирный, i курсив, c код, s зачёркнутый, m маркер, x формула,
# u нижний индекс, p верхний индекс, n подчёркнутый (<ins>).
_INLINE_FLAGS = {"bi": "bi", "b": "b", "b2": "b", "i": "i", "i2": "i", "s": "s", "m": "m",
                 "hsub": "u", "hsup": "p", "hins": "n"}
# Формулы LaTeX (подмножество): индексы _ ^, обёртки \mathrm{...}, греческие буквы и знаки.
RE_TEX_CMD = re.compile(r"\\([A-Za-z]+)")
# Разделители формул из веб-чатов: \( … \) и \[ … \]; в Markdown (Obsidian, GitHub) это $…$ и $$…$$.
RE_TEX_PAREN = re.compile(r"\\\((.+?)\\\)")
RE_TEX_BRACK = re.compile(r"\\\[(.+?)\\\]", re.S)
RE_TEX_SCRIPT = re.compile(r"([_^])(?:\{((?:[^{}]|\{[^{}]*\})*)\}|([A-Za-z0-9+\-\u2212]))")
RE_TEX_WRAP = re.compile(
    r"\\(?:mathrm|mathbf|mathit|mathsf|textrm|textbf|text|operatorname)"
    r"\{((?:[^{}]|\{[^{}]*\})*)\}"
)
RE_HTML_SCRIPT = re.compile(r"<(sub|sup)>([^<\n]+)</\1>")
_TEX_WRAPPERS = frozenset(("mathrm", "mathbf", "mathit", "mathsf", "textrm", "textbf", "text",
                           "operatorname", "mathcal", "mathbb"))
_TEX_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ",
    "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "times": "×", "cdot": "·", "pm": "±", "mp": "∓", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥",
    "ne": "≠", "neq": "≠", "approx": "≈", "to": "→", "rightarrow": "→", "leftarrow": "←",
    "infty": "∞", "circ": "°", "degree": "°", "sum": "Σ", "int": "∫", "partial": "∂",
    "nabla": "∇", "sqrt": "√", "ldots": "…", "dots": "…", "cdots": "⋯", "div": "÷",
    "propto": "∝", "in": "∈", "quad": " ", "qquad": "  ", "vert": "|", "displaystyle": "",
}


def _merge_flags(a, b):
    return a + "".join(ch for ch in b if ch not in a)


def _tex_group(tex, i):
    """tex[i] == '{': возвращает (содержимое группы без внешних скобок, индекс после '}')."""
    depth = 0
    for j in range(i, len(tex)):
        if tex[j] == "{":
            depth += 1
        elif tex[j] == "}":
            depth -= 1
            if depth == 0:
                return tex[i + 1:j], j + 1
    return tex[i + 1:], len(tex)


def parse_math_segments(tex, flags=""):
    """LaTeX-формулу -> список (текст, флаги) с u/p для индексов.
    В ячейках таблицы можно подставлять символы (\\alpha -> α), поэтому, в отличие от редактора,
    здесь команды раскрываются, а _{...} и ^{...} становятся сегментами с нижним/верхним индексом."""
    out, buf = [], []
    i, n = 0, len(tex)

    def flush():
        if buf:
            out.append(("".join(buf), flags))
            buf.clear()

    while i < n:
        ch = tex[i]
        if ch == "\\":
            m = RE_TEX_CMD.match(tex, i)
            if m:
                cmd = m.group(1)
                i = m.end()
                if cmd in _TEX_WRAPPERS and i < n and tex[i] == "{":
                    arg, i = _tex_group(tex, i)
                    flush()
                    out.extend(parse_math_segments(arg, flags))
                else:
                    buf.append(_TEX_SYMBOLS.get(cmd, cmd))
                continue
            if i + 1 < n:
                buf.append(tex[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch in "_^":
            flush()
            i += 1
            if i >= n:
                break
            if tex[i] == "{":
                arg, i = _tex_group(tex, i)
            elif tex[i] == "\\":
                m = RE_TEX_CMD.match(tex, i)
                if m:
                    arg, i = tex[i:m.end()], m.end()
                else:
                    arg, i = tex[i:i + 2], i + 2
            else:
                arg, i = tex[i], i + 1
            out.extend(parse_math_segments(arg, _merge_flags(flags, "u" if ch == "_" else "p")))
            continue
        if ch in "{}":
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush()
    return out


def parse_inline_segments(text, flags="", url=""):
    """Разбирает inline-Markdown в список (текст, флаги, url).
    Вложенные стили (жирный внутри ссылки и наоборот) разбираются рекурсией. Нужен ячейкам
    таблицы: Label не умеет смешивать шрифты, поэтому такие ячейки рисуются Text-виджетом
    с тегами. Формулы $...$ раскрываются в сегменты с флагами x/u/p."""
    out = []
    pos = 0
    for m in RE_INLINE_TOKEN.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], flags, url))
        pos = m.end()
        kind = m.lastgroup
        if kind == "esc":
            out.append((m.group("esc_c"), flags, url))
        elif kind == "code":
            out.append((m.group("code_t"), _merge_flags(flags, "c"), url))
        elif kind == "math":
            for seg_text, seg_flags in parse_math_segments(
                    m.group("math_t") or m.group("math_u"), _merge_flags(flags, "x")):
                out.append((seg_text, seg_flags, url))
        elif kind == "br":
            out.append(("\n", flags, url))       # <br> в ячейке таблицы — перенос строки
        elif kind == "link":
            out.extend(parse_inline_segments(m.group("link_t"), flags, m.group("link_u")))
        elif kind == "wiki":
            out.append((m.group("wiki_t"), flags, url))
        else:
            out.extend(parse_inline_segments(
                m.group(kind + "_t"), _merge_flags(flags, _INLINE_FLAGS[kind]), url))
    if pos < len(text):
        out.append((text[pos:], flags, url))
    return out


def layout_columns(max_w, min_w, avail):
    """Ширины столбцов в пикселях (с внутренними полями) по правилам авто-раскладки таблиц HTML.
    Умещается целиком — столбцы остаются по ширине содержимого (узкая таблица не растягивается).
    Не умещается — каждый столбец получает ширину самого длинного слова, а остаток делится
    пропорционально «запасу переноса» (max - min): длинные тексты получают больше места,
    короткие столбцы не раздуваются. Сумма всегда равна avail."""
    if sum(max_w) <= avail:
        return list(max_w)
    if sum(min_w) >= avail:
        tot = sum(min_w) or 1
        cols = [max(1, int(m * avail / tot)) for m in min_w]
    else:
        extra = avail - sum(min_w)
        need = [max(0, mx - mn) for mx, mn in zip(max_w, min_w)]
        tn = sum(need) or 1
        cols = [int(mn + extra * nd / tn) for mn, nd in zip(min_w, need)]
    cols[cols.index(max(cols))] += avail - sum(cols)   # остаток округления — самому широкому
    return cols


def count_wrapped_lines(items, inner_px):
    """Число строк при переносе по словам. items: [(ширина_px, это_пробел)].
    Нужна, чтобы задать высоту ячейки-Text до первой отрисовки (без «прыжка»); точное значение
    потом уточняет сам Tk через count -displaylines."""
    lines, x = 1, 0
    for w, is_space in items:
        if w < 0:                      # принудительный перенос строки (<br>)
            lines, x = lines + 1, 0
            continue
        if is_space:
            if x:
                x += w
            continue
        if x and x + w > inner_px:
            lines += 1
            x = 0
        x += w
        while inner_px > 0 and x > inner_px:   # слово длиннее строки переносится по символам
            lines += 1
            x -= inner_px
    return lines


# <sub>/<sup> -> Unicode, если все символы есть в таблице; иначе остаются HTML-тегами
# (GitHub их поддерживает, редактор показывает их индексами).
_SUB_SRC = "0123456789+-\u2212=()aehijklmnoprstuvx"
_SUB_DST = "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"
_SUP_SRC = "0123456789+-\u2212=()ni"
_SUP_DST = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿⁱ"
_SUB_MAP = str.maketrans(_SUB_SRC, _SUB_DST)
_SUP_MAP = str.maketrans(_SUP_SRC, _SUP_DST)


def _script_text(kind, s):
    if "](" in s or "\n" in s or not s.strip():
        return s   # внутри ссылка/сноска — теги не нужны, остаётся содержимое
    src, table = (_SUB_SRC, _SUB_MAP) if kind == "sub" else (_SUP_SRC, _SUP_MAP)
    if all(ch in src for ch in s):
        return s.translate(table)
    return f"<{kind}>{s}</{kind}>"


# MathML -> TeX (когда у формулы нет TeX-аннотации): токены, индексы, дроби, корни.
_MML_SYMBOLS = {"×": r"\times ", "·": r"\cdot ", "±": r"\pm ", "−": "-", "≤": r"\le ", "≥": r"\ge ",
                "≠": r"\ne ", "→": r"\to ", "∞": r"\infty ", "°": r"^\circ ", "⋅": r"\cdot "}


def _mml_wrap(s):
    return s if len(s) == 1 else "{" + s + "}"


def _mml_node_tex(node):
    tag, _attrs, kids = node
    els = [k for k in kids if isinstance(k, list)]
    if tag in ("mi", "mn", "mo", "ms"):
        s = "".join(k for k in kids if isinstance(k, str)).strip()
        return _MML_SYMBOLS.get(s, s)
    if tag == "mtext":
        s = "".join(k for k in kids if isinstance(k, str)).strip()
        return r"\text{" + s + "}" if s else " "
    if tag == "mspace":
        return " "
    if tag in ("annotation", "annotation-xml"):
        return ""
    parts = [_mml_node_tex(k) for k in els]
    if tag in ("msub", "munder") and len(parts) >= 2:
        return f"{parts[0]}_{_mml_wrap(parts[1])}"
    if tag in ("msup", "mover") and len(parts) >= 2:
        return f"{parts[0]}^{_mml_wrap(parts[1])}"
    if tag in ("msubsup", "munderover") and len(parts) >= 3:
        return f"{parts[0]}_{_mml_wrap(parts[1])}^{_mml_wrap(parts[2])}"
    if tag == "mfrac" and len(parts) >= 2:
        return r"\frac{" + parts[0] + "}{" + parts[1] + "}"
    if tag == "msqrt":
        return r"\sqrt{" + "".join(parts) + "}"
    if tag == "mroot" and len(parts) >= 2:
        return r"\sqrt[" + parts[1] + "]{" + parts[0] + "}"
    return "".join(_mml_node_tex(k) if isinstance(k, list) else "" for k in kids)


_TBL_PADX = 12   # внутренний горизонтальный отступ ячейки таблицы, px
BUILD = "09.11.2026-3"   # показывается в заголовке окна: сразу видно, какая версия запущена


class _Mark(str):
    """Маркер форматирования (**, *, ~~, ==, `) в потоке токенов конвертера: отличается от текста
    страницы по типу, поэтому литеральная «*» из текста никогда не путается с разметкой."""
    __slots__ = ()


# Естественные цветные эмодзи и пиктограммы (🚀, , 📝 и др.)
RE_EMOJI = re.compile(
    r'[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff'
    r'\u2b00-\u2bff\u203c\u2049\u2122\u2139\u3030\u303d\u3297\u3299]'
)
MD_TAGS = (
    "h1", "h2", "h3", "h4", "h5", "h6",
    "bold", "italic", "bold_italic", "code", "code_block", "code_fence",
    "checkbox_todo", "checkbox_done", "checkbox_cancel", "checkbox_progress",
    "bullet_list", "number_list", "wikilink", "md_link", "md_image",
    "hide_markup", "hr", "highlight", "strike", "quote",
    "callout_header", "callout_body",
    "table_block", "table_header", "table_row", "table_row_alt", "table_sep",
    "math", "tag", "frontmatter",
    "emoji", "bullet_mark", "number_mark", "cite", "code_lang",
    "math_sub", "math_sup", "html_sub", "html_sup", "underline", "hr_src",
    "task_marker", "task_marker_todo", "task_marker_done",
    "task_marker_cancel", "task_marker_progress",
)
CALLOUT_KINDS = frozenset({
    "NOTE", "INFO", "TIP", "SUCCESS", "WARNING", "CAUTION", "DANGER", "FAILURE",
    "BUG", "IMPORTANT", "QUESTION", "ABSTRACT", "EXAMPLE",
})
# Все статические теги одной строкой: сброс подсветки — один вызов Tcl (см. apply_markdown_highlighting).
_STATIC_TAGS_STR = " ".join(MD_TAGS + tuple(
    f"callout_{part}_{kind}" for part in ("header", "body")
    for kind in (*CALLOUT_KINDS, "default")))


def _identity(pos):
    return pos


def _tk_len(s):
    """Длина строки в индексах Tk: символы вне BMP (эмодзи) занимают 2 позиции UTF-16."""
    return len(s) + sum(1 for c in s if ord(c) > 0xFFFF)


def _toggle_task_line(m):
    """Строка с переключённым чекбоксом: ☐ -> ☑, всё остальное -> ☐."""
    nxt = "☐" if m.group(2) in "☑☒◐" else "☑"
    return m.group(1) + nxt + (" " + m.group(3) if m.group(3) else "")


# ==============================================================================
# DPI / ШРИФТЫ / МАСШТАБ (чёткий ClearType вместо растянутой битмап-картинки)
# ==============================================================================
FONT_UI = "Segoe UI"
FONT_ICON = "Segoe MDL2 Assets"  # родные значки Windows 10/11; если шрифта нет — эмодзи-запасной вариант
HAS_ICON_FONT = False
FONT_MONO = "Consolas"
UI_SCALE = 1.0
RE_WS = re.compile(r"[ \t\r\n\f\xa0]+")
# HTML из буфера считаем «смысловым», только если в нём есть реальная разметка
# (а не просто <div>/<p> вокруг простого текста — его надёжнее взять как plain).
RE_HTML_SEMANTIC = re.compile(
    r"<(?:h[1-6]|ul|ol|li|pre|table|blockquote|strong|b|em|i|code|del|s|strike|mark|a|img|hr|input)\b"
    r'|<span\b[^>]*style\s*=\s*["\'][^"\']*'
    r"(?:font-weight\s*:\s*(?:bold|bolder|[6-9]00)"
    r"|font-style\s*:\s*italic|line-through)",
    re.I,
)


def S(px):
    """Пиксели -> физические пиксели с учётом DPI (оптимизация: простое умножение)."""
    return max(1, int(round(px * UI_SCALE)))


def _enable_dpi_awareness():
    """Объявляет процесс DPI-aware ДО создания окна Tk.
    Причина «мыльного» текста: без этого Windows рендерит окно в 96 DPI и
    растягивает битмап, отключая субпиксельный ClearType. System-DPI (1) выбран
    вместо Per-Monitor, т.к. Tk не обрабатывает WM_DPICHANGED.
    """
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _init_scale(root):
    """Масштаб интерфейса по DPI."""
    global UI_SCALE, HAS_ICON_FONT
    try:
        UI_SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except tk.TclError:
        UI_SCALE = 1.0
    try:
        HAS_ICON_FONT = FONT_ICON in tkfont.families(root)  # один раз при старте
    except tk.TclError:
        HAS_ICON_FONT = False


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


# Маркеры списков: на диске «*» и «+», в редакторе «•» (закрашенный) и «◦» (пустой), как рисуют браузеры
# для вложенных <ul>. «-» остаётся тире. Регулярки скомпилированы один раз и без \s, чтобы не съедать «\n».
BULLET_VIEW = {"*": "•", "+": "◦"}
BULLET_MD = {"•": "*", "◦": "+"}
RE_BUL_TO_VIEW = re.compile(r"^([ \t]*)([*+])[ \t]", re.M)
RE_BUL_TO_MD = re.compile(r"^([ \t]*)([•◦])[ \t]", re.M)


def _bullet_to_view(m):
    return m.group(1) + BULLET_VIEW[m.group(2)] + " "


def _bullet_to_md(m):
    return m.group(1) + BULLET_MD[m.group(2)] + " "


def _bullets_text(text, rx, repl):
    """Подстановка маркеров списков только вне ```-блоков: в коде «+ строка» диффа и «* вызов» остаются как есть.
    Оптимизация: без ограждений (почти все заметки) — один вызов regex по всему тексту;
    с ограждениями — построчный проход, но regex запускается только на строках вне кода."""
    if "```" not in text:
        return rx.sub(repl, text)
    in_code = False
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("```"):
            in_code = not in_code
        elif not in_code:
            lines[i] = rx.sub(repl, ln)
    return "\n".join(lines)


def _display_bullets(text):
    """Показывает Markdown-списки: «*» как • и «+» как ◦ (и чекбоксы как ☐/☑) внутри редактора."""
    text = RE_TASK_MD.sub(lambda m: m.group(1) + TASK_GLYPH[m.group(2)], text)
    return _bullets_text(text, RE_BUL_TO_VIEW, _bullet_to_view)


def _markdown_bullets(text):
    """Возвращает визуальные •/◦-списки обратно в валидный Markdown («*» и «+»)."""
    text = RE_TASK_GLYPH.sub(lambda m: m.group(1) + "- [" + GLYPH_STATE[m.group(2)] + "]", text)
    return _bullets_text(text, RE_BUL_TO_MD, _bullet_to_md)


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
                pass# ==============================================================================
# ПАРСЕР HTML В ЧИСТЫЙ MARKDOWN (Стандартная библиотека, без внешних пакетов)
# ==============================================================================
class HTMLToMarkdownConverter(HTMLParser):
    """Преобразует HTML из буфера обмена (Edge/Chrome CF_HTML) в аккуратный Markdown.
    Важный принцип: сначала разбираем HTML, а plain-text используем только
    как fallback. Поддержано: заголовки, жирный/курсив/зачёркнутый/маркер
    (в т.ч. через style у <span>), код и блоки кода с языком, цитаты любой
    вложенности, вложенные списки, чекбоксы, таблицы, ссылки, картинки.
    """
    BLOCK_TAGS = {
        "address", "article", "aside", "div", "dl", "dt", "dd", "fieldset",
        "figcaption", "figure", "footer", "form", "header", "main", "nav",
        "section", "summary", "details",
    }
    RE_BOLD_STYLE = re.compile(r"font-weight\s*:\s*(?:bold|bolder|[6-9]00)")
    RE_ITALIC_STYLE = re.compile(r"font-style\s*:\s*italic")
    RE_STRIKE_STYLE = re.compile(r"text-decoration[^;]*line-through")
    RE_MONO_STYLE = re.compile(r"font-family\s*:[^;]*(?:mono|consolas|courier|menlo|cascadia)")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.result = []
        self.link_href = None
        self.link_text = []
        self.cite_ids = {}        # href -> номер сноски (один источник = один номер)
        self.open_marks = []      # [маркер, открыт_внутри_ссылки] — стек открытых **, *, ~~, ==, `
        self.after_link = []      # маркеры, открытые ДО ссылки и закрытые внутри неё: выводим после ссылки
        self.math_skip = None     # [тег, глубина]: внутри элемента, уже заменённого формулой $...$
        self.mml = None           # события внутри <math>, пока TeX формулы не получен из аннотации
        self.mml_display = False  # формула блочная ($$...$$)
        self.math_display_hint = False   # перед <math> встретился контейнер katex-display
        self.skip_tags = {'script', 'style', 'button', 'svg', 'nav', 'header', 'footer', 'noscript'}
        self.skip_depth = 0
        self.in_pre = False
        self.pre_buffer = []
        self.code_buffer = []
        self.pre_code_depth = 0
        self.pre_has_code = False
        self.pre_lang = ""
        self.list_stack = []      # [тип, счётчик, число элементов]
        self.in_table = False
        self.table_rows = []
        self.current_row = []
        self.current_cell = []
        self.in_cell = False
        self.box_stack = []       # (тег, тип callout|None, индекс в result|None)
        self.style_stack = []
        self.heading_depth = 0
        self._after_open = False  # только что открыт маркер **/*/~~ — срезаем пробел после него
        self._just_li = False     # только что выведен маркер списка — не вставляем пустую строку

    # ------------------------------------------------------------------ вывод
    def _target(self):
        if self.link_href is not None:
            return self.link_text
        if self.in_cell:
            return self.current_cell
        return self.result

    def _append(self, text):
        if not text:
            return
        self._after_open = False
        self._just_li = False
        self._target().append(text)

    def _open_mark(self, mark):
        self._append(_Mark(mark))
        self.open_marks.append([mark, self.link_href is not None])
        self._after_open = True

    def _close_mark(self, mark):
        """Закрывающий маркер: пробелы выносятся наружу ('**a **' -> '**a** '), пустой — убирается.
        Маркеры никогда не пересекают границу ссылки: открытый до <a> и закрытый внутри неё
        откладывается на «после ссылки» (иначе получалось «***[A](u) ... [B***](u)» — звёздочки
        внутри подписи ссылки, которые разметка не распознаёт)."""
        pos = -1
        for k in range(len(self.open_marks) - 1, -1, -1):
            if self.open_marks[k][0] == mark:
                pos = k
                break
        if pos < 0:
            return  # закрытие без открытия (кривая вёрстка) — «осиротевший» ** не выводим
        opened_in_link = self.open_marks.pop(pos)[1]
        if self.link_href is not None and not opened_in_link:
            self.after_link.append(mark)
            return
        tgt = self._target()
        if tgt and isinstance(tgt[-1], _Mark) and tgt[-1] == mark and self._after_open:
            tgt.pop()
            self._after_open = False
            return
        trailing = ""
        if tgt and isinstance(tgt[-1], str) and not isinstance(tgt[-1], _Mark):
            stripped = tgt[-1].rstrip(" \t")
            trailing = tgt[-1][len(stripped):]
            if stripped:
                tgt[-1] = stripped
            else:
                tgt.pop()
        self._append(_Mark(mark))
        if trailing:
            self._append(trailing)

    def _rstrip_newlines(self):
        tgt = self._target()
        while tgt and isinstance(tgt[-1], str):
            s = tgt[-1].rstrip("\n")
            if s:
                tgt[-1] = s
                break
            tgt.pop()

    def _pre_write(self, text):
        self.pre_buffer.append(text)
        if self.pre_code_depth > 0:
            self.code_buffer.append(text)

    @staticmethod
    def _callout_kind(cls):
        """Тип callout по CSS-классам: MS Learn (alert is-*), GitHub, Docusaurus, class="NOTE"."""
        c = (cls or "").lower()
        if not c:
            return None
        m = re.search(r"markdown-alert-(note|tip|important|warning|caution)", c)
        if m:
            return m.group(1).upper()
        m = re.search(r"admonition-(note|tip|info|important|warning|caution|danger)", c)
        if m:
            return m.group(1).upper()
        # GitHub Docs: ghd-alert-accent/success/attention/danger/done и старый extended-markdown note|tip|...
        m = re.search(r'extended-markdown[^"]*?(?<![\w-])(note|tip|important|warning|caution|danger)(?![\w-])', c)
        if m:
            return "CAUTION" if m.group(1) == "danger" else m.group(1).upper()
        if re.search(r"(?<![\w-])alert(?![\w-])", c):
            for token, kind in (("is-primary", "NOTE"), ("is-info", "IMPORTANT"), ("is-success", "TIP"),
                                ("is-warning", "WARNING"), ("is-danger", "DANGER")):
                if token in c:
                    return kind
            return "NOTE"
        m = re.fullmatch(r"\s*(note|tip|important|warning|caution)\s*", c)
        return m.group(1).upper() if m else None

    @staticmethod
    def _ul_marker(a, depth):
        """Маркер Markdown для <ul> так, как его рисует браузер: диск «•» -> «*», круг «◦» -> «+», квадрат -> «-».
        Явный стиль (атрибут type или list-style-type) важнее вложенности; иначе по умолчанию браузера:
        верхний уровень — диск, вложенный — круг, глубже — квадрат. Редактор показывает «*» как •, «+» как ◦."""
        style = ((a.get("style") or "") + " " + (a.get("type") or "")).lower()
        if "circle" in style:
            return "+"
        if "square" in style:
            return "-"
        if "disc" in style:
            return "*"
        return "*+-"[min(depth, 2)]

    def _style_marks(self, style):
        """Маркеры Markdown для <span style="...">: жирный/курсив/зачёркнутый/моноширинный."""
        if not style:
            return []
        s = style.lower()
        if self.RE_MONO_STYLE.search(s) and not self.in_pre:
            return ["`"]
        marks = []
        if self.heading_depth == 0 and self.RE_BOLD_STYLE.search(s):
            marks.append("**")
        if self.RE_ITALIC_STYLE.search(s):
            marks.append("*")
        if self.RE_STRIKE_STYLE.search(s):
            marks.append("~~")
        return marks

    # ------------------------------------------------------------------ формулы
    _TEX_ATTRS = ("data-latex", "data-tex", "data-math", "data-formula", "data-katex", "alttext")
    _VOID_TAGS = frozenset(("img", "br", "hr", "input", "meta", "link", "wbr"))

    @classmethod
    def _tex_from_attrs(cls, a):
        """TeX формулы из атрибутов (alttext у MathML, data-latex у MathJax/редакторов и т.п.)."""
        for key in cls._TEX_ATTRS:
            v = (a.get(key) or "").strip()
            if v:
                m = re.match(r"^\{\\displaystyle\s*(.*)\}$", v, re.S)
                return (m.group(1) if m else v).strip()
        return ""

    def _emit_math(self, tex, display=False):
        tex = re.sub(r"\s+", " ", tex).strip().replace("|", r"\vert ")
        if not tex:
            return
        if display:
            self._append(f"\n\n$$\n{tex}\n$$\n\n")
        else:
            self._append(f"${tex}$")

    @staticmethod
    def _mml_to_tex(events):
        """Собирает TeX из событий MathML; сначала ищет готовую <annotation encoding="...tex">."""
        for k, (kind, val, attrs) in enumerate(events):
            if kind == "open" and val == "annotation" and "tex" in ((attrs or {}).get("encoding") or "").lower():
                buf = []
                for kind2, val2, _ in events[k + 1:]:
                    if kind2 == "data":
                        buf.append(val2)
                    elif kind2 == "close" and val2 == "annotation":
                        break
                if "".join(buf).strip():
                    return "".join(buf).strip()
        root = ["math", {}, []]
        stack = [root]
        for kind, val, attrs in events:
            if kind == "open":
                node = [val, attrs or {}, []]
                stack[-1][2].append(node)
                stack.append(node)
            elif kind == "close":
                for k in range(len(stack) - 1, 0, -1):
                    if stack[k][0] == val:
                        del stack[k:]
                        break
            else:
                stack[-1][2].append(val)
        return _mml_node_tex(root)

    # ------------------------------------------------------------------ теги
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        # Формулы: элемент, уже замещённый $tex$, и его потомки пропускаются целиком.
        if self.math_skip:
            if tag == self.math_skip[0]:
                self.math_skip[1] += 1
            return
        if self.mml is not None:
            self.mml.append(("open", tag, dict(attrs)))
            return
        ma = dict(attrs)
        mcls = (ma.get("class") or "")
        if "katex-display" in mcls:
            self.math_display_hint = True
        if tag == "img" and "math" in mcls and "fallback" in mcls:
            return   # растровая копия формулы (Википедия) — формула уже пришла из MathML
        if "katex-html" in mcls or "MathJax_Preview" in mcls:
            self.math_skip = [tag, 1]   # визуальный дубль формулы (KaTeX/MathJax)
            return
        tex = self._tex_from_attrs(ma)
        if tex:
            self._emit_math(tex, ma.get("display") == "block" or self.math_display_hint)
            self.math_display_hint = False
            if tag not in self._VOID_TAGS:
                self.math_skip = [tag, 1]
            return
        if tag == "math":
            self.mml = []
            self.mml_display = ma.get("display") == "block" or self.math_display_hint
            self.math_display_hint = False
            return
        # <button> внутри ссылки — это «кнопка-сноска» с номером источника: текст не выбрасываем.
        if tag in self.skip_tags and not (tag == "button" and self.link_href is not None):
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return
        a = dict(attrs)
        if self.in_pre:
            if tag == "code":
                self.pre_has_code = True
                self.pre_code_depth += 1
                m = re.search(r"(?:language|lang)-([\w+#.-]+)", a.get("class") or "")
                if m and not self.pre_lang:
                    self.pre_lang = m.group(1)
            elif tag == "br":
                self._pre_write("\n")
            return
        if tag in ("strong", "b"):
            if not self.heading_depth:
                self._open_mark("**")
        elif tag in ("em", "i"):
            self._open_mark("*")
        elif tag in ("s", "del", "strike"):
            self._open_mark("~~")
        elif tag == "mark":
            self._open_mark("==")
        elif tag in ("code", "kbd", "samp", "tt"):
            self._open_mark("`")
        elif tag in ("sub", "sup"):
            # Служебные символы: на выходе get_markdown превратит их в Unicode-индексы или <sub>/<sup>.
            self._append("\x02" if tag == "sub" else "\x03")
        elif tag == "span":
            marks = self._style_marks(a.get("style"))
            self.style_stack.append(marks)
            for m in marks:
                self._open_mark(m)
        elif tag == "pre":
            self.in_pre = True
            self.pre_buffer = []
            self.code_buffer = []
            self.pre_code_depth = 0
            self.pre_has_code = False
            self.pre_lang = ""
        elif tag == "a":
            href = unescape((a.get("href") or "").strip())
            if href and not href.startswith(("#", "javascript:")) and self.link_href is None:
                self.link_href = normalize_web_url(href)
                self.link_text = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_depth += 1
            self._append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("blockquote", "div", "aside", "section"):
            kind = self._callout_kind(a.get("class"))
            if tag == "blockquote" or kind:
                self._append("\n\n")
                self.box_stack.append((tag, kind, len(self.result)))
            else:
                self.box_stack.append((tag, None, None))
                if not self._just_li:
                    self._append("\n")
        elif tag in ("ul", "ol"):
            start = 0
            if tag == "ol":
                try:
                    start = int(a.get("start", "1")) - 1
                except ValueError:
                    start = 0
            self.list_stack.append([tag, start, 0, self._ul_marker(a, len(self.list_stack)) if tag == "ul" else ""])
            self._append("\n")
        elif tag == "li":
            depth = max(0, len(self.list_stack) - 1)
            if self.list_stack:
                entry = self.list_stack[-1]
                if entry[2] > 0 or depth > 0:
                    self._rstrip_newlines()  # плотный список без пустых строк между пунктами
                entry[2] += 1
                if entry[0] == "ol":
                    entry[1] += 1
                    marker = f"{entry[1]}. "
                else:
                    marker = entry[3] + " "
            else:
                marker = "- "
            self._append(f"\n{'  ' * depth}{marker}")
            self._just_li = True
        elif tag == "input":
            if (a.get("type") or "").lower() == "checkbox":
                self._append("[x] " if "checked" in a else "[ ] ")
        elif tag == "table":
            self.in_table = True
            self.table_rows = []
        elif tag == "tr":
            self.current_row = []
        elif tag in ("th", "td"):
            self.in_cell = True
            self.current_cell = []
        elif tag == "img":
            alt = unescape(a.get("alt", ""))
            src = unescape(a.get("src", ""))
            if src and not src.startswith("data:"):
                self._append(f"![{alt}]({src})")
            elif alt:
                self._append(alt)
        elif tag == "hr":
            self._append("\n\n---\n\n")
        elif tag == "br":
            self._append("\n")
        elif tag == "p":
            if not self._just_li:
                self._append("\n\n")
        elif tag in self.BLOCK_TAGS:
            if not self._just_li:
                self._append("\n")
        # Заголовок callout («Примечание») помечаем служебным символом — вынесем в [!TYPE] Заголовок.
        cls = (a.get("class") or "").lower()
        if (tag in ("p", "div", "span") and "title" in cls and re.search(r"alert|admonition|callout", cls)
                and any(e[1] for e in self.box_stack)):
            self._append("\x01")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.math_skip:
            if tag == self.math_skip[0]:
                self.math_skip[1] -= 1
                if self.math_skip[1] <= 0:
                    self.math_skip = None
            return
        if self.mml is not None:
            if tag == "math":
                events, display = self.mml, self.mml_display
                self.mml = None
                self._emit_math(self._mml_to_tex(events), display)
            else:
                self.mml.append(("close", tag, None))
            return
        if tag in self.skip_tags and not (tag == "button" and self.link_href is not None):
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth > 0:
            return
        if self.in_pre and tag != "pre":
            if tag == "code" and self.pre_code_depth > 0:
                self.pre_code_depth -= 1
            return
        if tag == "pre":
            # Если внутри есть <code>, берём только его (отбрасываем подпись языка/кнопки ИИ-чатов).
            code = "".join(self.code_buffer if self.pre_has_code else self.pre_buffer).strip("\n")
            lang = self.pre_lang
            if not lang:
                # Подпись языка могла попасть первой строкой внутрь <pre> — переносим её в ограждение.
                first, sep, rest = code.partition("\n")
                if sep and first.strip().lower() in CODE_LANGS:
                    lang, code = first.strip().lower(), rest.lstrip("\n")
            self.in_pre = False
            self.pre_buffer = []
            self.code_buffer = []
            self.pre_lang = ""
            fence = "```"
            while fence in code:
                fence += "`"
            self._append(f"\n\n{fence}{lang}\n{code}\n{fence}\n\n")
        elif tag in ("strong", "b"):
            if not self.heading_depth:
                self._close_mark("**")
        elif tag in ("em", "i"):
            self._close_mark("*")
        elif tag in ("s", "del", "strike"):
            self._close_mark("~~")
        elif tag == "mark":
            self._close_mark("==")
        elif tag in ("code", "kbd", "samp", "tt"):
            self._close_mark("`")
        elif tag in ("sub", "sup"):
            self._append("\x04" if tag == "sub" else "\x05")
        elif tag == "span":
            if self.style_stack:
                for m in reversed(self.style_stack.pop()):
                    self._close_mark(m)
        elif tag == "a":
            if self.link_href is not None:
                # Маркеры, открытые внутри подписи и не закрытые к </a>: закрываем в подписи
                # и открываем заново после ссылки — подпись всегда сбалансирована.
                reopen = [e[0] for e in self.open_marks if e[1]]
                self.open_marks = [e for e in self.open_marks if not e[1]]
                for mk in reversed(reopen):
                    self.link_text.append(_Mark(mk))
                title = "".join(t for t in self.link_text if not isinstance(t, _Mark)).strip()
                label = "".join(self.link_text).strip()
                href = self.link_href
                self.link_href = None
                self.link_text = []
                if not title:
                    # Ссылка без текста (номер нарисован CSS/значком) — это сноска-источник:
                    # нумеруем по порядку появления, повторный источник получает прежний номер.
                    if href.lower().startswith(("http://", "https://")):
                        title = str(self.cite_ids.setdefault(href, max(self.cite_ids.values(), default=0) + 1))
                    else:
                        title = href
                    label = title  # маркеры без текста в подпись не попадают
                elif title.isdigit() and len(title) <= 3:
                    self.cite_ids.setdefault(href, int(title))  # явные номера тоже учитываем
                    label = title  # номер сноски — без обёртки **/*: иначе [1] не опознаётся как сноска
                tgt = self._target()
                if title.isdigit() and tgt and isinstance(tgt[-1], str) and re.search(r"\[\d{1,3}\]\([^)]*\)$", tgt[-1]):
                    self._append(" ")  # соседние сноски [1] [2] не должны слипаться
                self._append(f"[{label}]({href})")
                for mk in self.after_link:      # закрытия, отложенные с момента, когда ссылка была открыта
                    self._append(_Mark(mk))
                self.after_link = []
                for mk in reopen:
                    self._open_mark(mk)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_depth = max(0, self.heading_depth - 1)
            self._append("\n\n")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self._append("\n")
        elif tag in ("blockquote", "div", "aside", "section"):
            entry = self.box_stack.pop() if self.box_stack else None
            if entry and entry[2] is not None and (entry[1] or tag == "blockquote"):
                kind, start = entry[1], entry[2]
                chunk = re.sub(r"\n{3,}", "\n\n", "".join(self.result[start:])).strip("\n")
                del self.result[start:]
                head = None
                if kind:
                    title = ""
                    if "\x01" in chunk:
                        before, rest = chunk.split("\x01", 1)
                        title, _, rest = rest.partition("\n")
                        chunk = (before + rest).strip("\n")
                    head = f"> [!{kind}]" + (f" {title.strip()}" if title.strip() else "")
                body = [("> " + ln) if ln.strip() else ">" for ln in chunk.split("\n")] if chunk else []
                self._append("\n\n" + "\n".join(([head] if head else []) + body) + "\n\n")
            else:
                self._append("\n")
        elif tag in ("th", "td"):
            self.in_cell = False
            # Перенос строки внутри ячейки — <br> (так таблицы GFM и Obsidian хранят многострочные ячейки).
            cell_text = re.sub(r"\s*\n\s*", "<br>", "".join(self.current_cell).strip()).replace("|", "\\|")
            self.current_row.append(cell_text)
        elif tag == "tr":
            if self.current_row:
                self.table_rows.append(self.current_row)
        elif tag == "table":
            self.in_table = False
            if self.table_rows:
                col_count = max(len(row) for row in self.table_rows)
                if col_count:
                    rows = []
                    for row in self.table_rows:
                        rows.append(row + [''] * (col_count - len(row)))
                    table_md = ['\n', '| ' + ' | '.join(rows[0]) + ' |',
                                '| ' + ' | '.join(['---'] * col_count) + ' |']
                    table_md.extend('| ' + ' | '.join(row) + ' |' for row in rows[1:])
                    table_md.append('\n')
                    self._append('\n'.join(table_md))
        elif tag in self.BLOCK_TAGS or tag == "p":
            self._append("\n")

    def handle_data(self, data):
        if self.math_skip:
            return
        if self.mml is not None:
            self.mml.append(("data", data, None))
            return
        if self.skip_depth > 0:
            return
        if self.in_pre:
            self._pre_write(data)
            return
        # Схлопывание пробелов как в браузере: перенос строки в исходнике HTML — это пробел.
        data = RE_WS.sub(" ", data)
        tgt = self._target()
        tail = tgt[-1] if tgt else ""
        if data.startswith(" ") and (not tail or tail[-1] in "\n " or self._after_open):
            data = data.lstrip(" ")
        if data:
            self._append(data)

    def get_markdown(self):
        clean = unescape("".join(self.result)).replace("\x01", "")
        clean = re.sub("\x02([^\x03]*)\x03", lambda m: _script_text("sub", m.group(1)), clean)
        clean = re.sub("\x04([^\x05]*)\x05", lambda m: _script_text("sup", m.group(1)), clean)
        clean = re.sub("[\x02-\x05]", "", clean)   # непарные служебные символы
        # Формулы \( … \) и \[ … \] -> $…$ и $$…$$. Код (``` и `…`) пропускается: там «\(» — обычный
        # текст (регулярные выражения, PowerShell). Чётные элементы split — текст вне кода.
        parts = re.split(r"(```.*?```|`[^`\n]+`)", clean, flags=re.S)
        for k in range(0, len(parts), 2):
            parts[k] = RE_TEX_BRACK.sub(lambda m: "\n\n$$\n" + m.group(1).strip() + "\n$$\n\n", parts[k])
            parts[k] = RE_TEX_PAREN.sub(lambda m: "$" + m.group(1).strip() + "$", parts[k])
        clean = "".join(parts)
        # Пункты чекбокс-списков должны остаться «- [ ]» (так их узнаёт RE_TASK_MD), а не «* [ ]» / «+ [ ]».
        clean = re.sub(r"^([ \t]*)[*+] (?=\[[ xX]\] )", r"\1- ", clean, flags=re.M)
        # Убираем пробелы перед переводом строки, но не ломаем отступы списков/кода.
        clean = re.sub(r'[ \t]+\n', '\n', clean)
        clean = re.sub(r'\n[ \t]+\n', '\n\n', clean)
        clean = re.sub(r'\n{3,}', '\n\n', clean)
        clean = RE_LANG_LABEL.sub(lambda m: m.group(2) + m.group(1).lower() + "\n", clean)
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
                font=(FONT_UI, 8), relief=tk.SOLID,
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
    return out# ==============================================================================
# ГЛАВНЫЙ КЛАСС ПРИЛОЖЕНИЯ
# ==============================================================================
class QuickObsidianNotesApp(tk.Tk):
    """Главный класс приложения заметок (полностью in-memory конфигурация)."""

    def __init__(self):
        _enable_dpi_awareness()  # строго ДО создания окна Tk
        super().__init__()
        _init_scale(self)
        self._fold_refresh_pending = False
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
        self._rendered_tables = []      # записи таблиц-виджетов (см. _update_rendered_tables)
        self._tbl_fonts = {}            # кэш tkfont.Font для ячеек таблиц: (размер, шапка, флаги) -> Font
        self._code_blocks = []          # [(строка открывающего ```, строка закрывающего | None)]
        self._code_btns = []            # пул кнопок «Копировать» (виджеты-накладки на редакторе)
        self._code_btn_pending = False
        self._code_btn_busy = False
        self._code_btn_theme = None
        self._no_fold = []              # диапазоны строк без стрелок сворачивания (код, frontmatter, $$)
        self._tbl_edit = None           # правка ячейки на месте: {entry, r, c, w, orig}
        self._tbl_pending_edit = None   # (строка таблицы, (ряд, столбец)) — открыть после перерисовки
        self._tbl_resize_job = None
        self._tbl_avail_used = 0
        self.normal_geometry = f"{S(950)}x{S(640)}"
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
        self._undo_prev = None   # текст ДО последней серии правок (отмена на 1 шаг)
        self._undo_cur = ""      # текст ПОСЛЕ неё; больше копий текста не хранится
        self._cursor_mem = {}    # путь заметки -> индекс курсора «строка.колонка», только на время сеанса
        self._clip_ready = False  # типы Win32-функций буфера обмена прописаны
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
                "tag_code_bg": "#2a2a2f",
                "tag_code_fence_bg": "#151518",
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
                "scroll_thumb": "#3f3f46",
                "scroll_hover": "#5b5b64",
                "border_soft": "#26262c",
            },
            "light": {
                "bg_sidebar": "#f4f5f7",
                "bg_editor": "#ffffff",
                "text_main": "#1f2937",
                "text_muted": "#6b7280",
                "accent": "#2563eb",
                "accent_light": "#eff6ff",
                "btn_bg": "#f4f5f7",  # плоские кнопки: тот же цвет, что и панель (без белых плиток)
                "btn_hover": "#e3e6eb",
                "btn_active": "#dbeafe",
                "tag_header": "#0369a1",
                "tag_bold": "#111827",
                "tag_code": "#be185d",
                "tag_code_bg": "#eceef2",
                "tag_code_fence_bg": "#f5f6f8",
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
                "scroll_thumb": "#cbd5e1",
                "scroll_hover": "#94a3b8",
                "border_soft": "#e6e9ef",
            },
        }
        self.colors = self.theme_palettes[self.current_theme]
        # 3. Настройка главного окна
        self.title(f"Быстрый Заметчик (Obsidian) · сборка {BUILD}")
        self.geometry(self.normal_geometry)
        self.minsize(S(280), S(240))
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
    # ИСПРАВЛЕНИЕ БУФЕРА ОБМЕНА ЧЕРЕЗ WIN32 API (RegisterClipboardFormatW)
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
        """Надёжно извлекает CF_HTML (Edge/Chrome) из буфера Windows.
        Главная причина «не работает вставка из Edge» на x64: без argtypes/restype
        ctypes обрезает 64-битные HANDLE до int32, и GlobalLock возвращает 0.
        """
        if os.name != "nt" or not self._cf_html:
            return None
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t
        # Буфер может быть на мгновение занят источником (Edge) — короткие повторы.
        opened = False
        for _ in range(20):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.01)
        if not opened:
            return None
        try:
            if not user32.IsClipboardFormatAvailable(self._cf_html):
                return None
            handle = user32.GetClipboardData(self._cf_html)
            if not handle:
                return None
            size = kernel32.GlobalSize(handle)
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                raw_bytes = ctypes.string_at(ptr, size).split(b"\x00", 1)[0]
            finally:
                kernel32.GlobalUnlock(handle)
            if not raw_bytes:
                return None

            def header_offset(name):
                m = re.search(rb"^" + name + rb":\s*(\d+)", raw_bytes, flags=re.I | re.M)
                return int(m.group(1)) if m else None

            # Смещения в заголовке — в БАЙТАХ UTF-8, поэтому режем bytes, а не str.
            start_fragment = header_offset(b"StartFragment")
            end_fragment = header_offset(b"EndFragment")
            if (start_fragment is not None and end_fragment is not None
                    and 0 <= start_fragment < end_fragment <= len(raw_bytes)):
                return raw_bytes[start_fragment:end_fragment].decode("utf-8", errors="replace")
            raw = raw_bytes.decode("utf-8", errors="replace")
            marker = re.search(
                r"<!--\s*StartFragment\s*-->(.*?)<!--\s*EndFragment\s*-->",
                raw, flags=re.I | re.S,
            )
            if marker:
                return marker.group(1)
            start = raw.lower().find("<html")
            return raw[start:] if start >= 0 else None
        except Exception:
            return None
        finally:
            user32.CloseClipboard()

    # ==========================================================================
    # УМНЫЙ SMART PASTE ДЛЯ ССЫЛОК, ИИ И HTML
    # ==========================================================================
    def _clip_api(self):
        """user32/kernel32 с прописанными типами (без argtypes 64-битные HANDLE обрезаются до int32)."""
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        if not self._clip_ready:
            u32.OpenClipboard.argtypes = [wintypes.HWND]
            u32.OpenClipboard.restype = wintypes.BOOL
            u32.EmptyClipboard.restype = wintypes.BOOL
            u32.CloseClipboard.restype = wintypes.BOOL
            u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
            u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
            u32.GetClipboardData.argtypes = [wintypes.UINT]
            u32.GetClipboardData.restype = ctypes.c_void_p
            u32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
            u32.SetClipboardData.restype = ctypes.c_void_p
            k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            k32.GlobalAlloc.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            k32.GlobalUnlock.restype = wintypes.BOOL
            k32.GlobalFree.argtypes = [ctypes.c_void_p]
            k32.GlobalFree.restype = ctypes.c_void_p
            self._clip_ready = True
        return u32, k32

    def _clip_open(self, owner=None):
        """OpenClipboard с повторами: источник (Edge) или менеджер буфера держит его доли секунды.
        Без повторов Tk при занятом буфере сразу даёт ошибку — отсюда «перестало вставляться»."""
        u32 = ctypes.windll.user32
        for _ in range(20):
            if u32.OpenClipboard(owner):
                return True
            time.sleep(0.01)
        return False

    def _read_clipboard_unicode(self):
        """Текст буфера (CF_UNICODETEXT) напрямую из Win32. None — прочитать не удалось, "" — текста нет."""
        u32, k32 = self._clip_api()
        if not self._clip_open():
            return None
        try:
            if not u32.IsClipboardFormatAvailable(13):
                return ""
            handle = u32.GetClipboardData(13)
            if not handle:
                return None
            ptr = k32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr).replace("\r\n", "\n").replace("\r", "\n")
            finally:
                k32.GlobalUnlock(handle)
        finally:
            u32.CloseClipboard()

    def _clipboard_text(self):
        """Текст из буфера: сначала Win32 с повторами, при неудаче — штатный Tk."""
        text = None
        if os.name == "nt":
            try:
                text = self._read_clipboard_unicode()
            except Exception:
                text = None
        if text is None:
            try:
                text = self.clipboard_get()
            except tk.TclError:
                text = ""
        return text

    def _set_clipboard_text(self, text):
        """Кладёт текст в буфер сразу, а не «отложенной выдачей» Tk: данные не пропадают, пока окно занято
        или после его закрытия. Если Win32 не удался — запасной путь через Tk."""
        if os.name == "nt":
            handle = None
            try:
                u32, k32 = self._clip_api()
                data = (text.replace("\n", "\r\n") + "\0").encode("utf-16-le")
                handle = k32.GlobalAlloc(0x0002, len(data))          # GMEM_MOVEABLE
                ptr = k32.GlobalLock(handle) if handle else None
                if ptr:
                    ctypes.memmove(ptr, data, len(data))
                    k32.GlobalUnlock(handle)
                    if self._clip_open(self.winfo_id()):
                        try:
                            u32.EmptyClipboard()
                            if u32.SetClipboardData(13, handle):     # CF_UNICODETEXT; память теперь у системы
                                handle = None
                                return
                        finally:
                            u32.CloseClipboard()
                if handle:
                    k32.GlobalFree(handle)
            except Exception:
                pass
        self.clipboard_clear()
        self.clipboard_append(text)

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

    def _clean_link_title(self, title, url):
        """Название ссылки: без [ ], счётчика уведомлений «(3)» и суффикса « - YouTube»."""
        title = re.sub(r"\s+", " ", title or "").strip()
        if self._get_youtube_video_id(url):
            title = re.sub(r"^\(\d+\)\s*", "", title)
            title = re.sub(r"\s*[-–—|]\s*YouTube$", "", title, flags=re.I)
        return title.replace("[", "(").replace("]", ")").strip()

    def _get_url_title(self, url):
        """Получает заголовок URL; для YouTube сначала использует oEmbed."""
        url = normalize_web_url(url)
        title = None
        yt_id = self._get_youtube_video_id(url)
        if yt_id:
            # 1. Запрос через oEmbed API с канонической ссылкой watch?v= и исходной ссылкой
            for oembed_target in (f"https://www.youtube.com/watch?v={yt_id}", url):
                try:
                    # quote(): иначе «&t=…» в исходной ссылке ломает параметры oEmbed-запроса.
                    req = urllib.request.Request(
                        f"https://www.youtube.com/oembed?url={quote(oembed_target, safe='')}&format=json",
                        headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, timeout=6.0) as r:
                        d = json.loads(r.read().decode('utf-8'))
                        t = d.get('title')
                        if t:
                            title = t
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
            return self._clean_link_title(title, url) or None
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
            # Неудачу НЕ кэшируем: раньше разовый сбой сети навсегда оставлял «YouTube: id».
            return f"YouTube: {yt_id}" if yt_id else self._fallback_url_title(clean_url)
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
        if title == placeholder:
            return
        # Поиск средствами Tk с elide=True: в Live Preview «](url)» скрыт (elide) и иначе не находится.
        # Смещения берём у самого Tk (а не из Python-строки): эмодзи выше по тексту сдвигали индексы
        # на 1 символ, и замена попадала не туда.
        old = f"[{placeholder}]({url})"
        start = self.editor.search(old, "1.0", stopindex=tk.END, exact=True, elide=True)
        if not start:
            return
        end = f"{start}+{_tk_len(old)}c"
        self.editor.delete(start, end)
        self.editor.insert(start, f"[{title}]({url})")
        self.apply_markdown_highlighting(force=True)
        self.on_editor_key_release(None)

    def menu_paste(self):
        """Smart Paste: HTML-ссылка, URL, Markdown/AI и обычный текст."""
        plain = self._clipboard_text()
        html_raw = self._get_clipboard_html()
        single_link = self._extract_single_link_from_html(html_raw)
        rich_html = bool(html_raw and RE_HTML_SEMANTIC.search(html_raw))
        # «Чистая ссылка»: после удаления <a>…</a> в HTML не остаётся ни текста, ни разметки с текстом.
        pure_link = bool(single_link) and not re.sub(
            r"<[^>]+>|\s+", "", re.sub(r"<a\b.*?</a\s*>", "", html_raw or "", flags=re.I | re.S))
        if single_link and pure_link:
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
            # Название берём ИЗ БУФЕРА (Edge кладёт <a href>Название</a>), в том числе для YouTube;
            # в сеть идём только если в буфере лишь голый адрес.
            link_title = self._clean_link_title(link_title, link_href)
            if self._is_url_like_title(link_title, link_href):
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
            except Exception:
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
        # Светлая тема: светлая плашка с чёрным текстом и цветной кромкой (белый текст на светлом не читался);
        # тёмная тема: сплошная заливка цветом уведомления с белым текстом.
        light = self.current_theme == "light"
        bg, fg = ("#ffffff", "#111827") if light else (color, "#ffffff")
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=color)   # кромка 2 px: pack(padx/pady=2) ниже оставляет её видимой
        lbl = tk.Label(
            toast, text=message, fg=fg, bg=bg,
            font=(FONT_UI, 9, "bold"), padx=12, pady=6
        )
        lbl.pack(padx=2, pady=2)
        self.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() // 2) - (lbl.winfo_reqwidth() // 2)
        y = self.winfo_rooty() + self.winfo_height() - 55
        toast.geometry(f"+{x}+{y}")
        toast.after(duration, toast.destroy)

    def _center_window(self, win, width=None, height=None):
        """Ставит всплывающее окно по центру главного (или экрана, если главное окно скрыто).
        Размер известен заранее (width/height) — окно позиционируется сразу, без update_idletasks,
        поэтому не мигает в углу. Высота ограничена экраном: на слабых ноутбуках 768 px справка не влезала."""
        if width is None or height is None:
            win.update_idletasks()
            width, height = win.winfo_reqwidth(), win.winfo_reqheight()
        else:
            height = min(height, self.winfo_screenheight() - S(80))
        if self.winfo_viewable():
            px, py, pw, ph = self.winfo_rootx(), self.winfo_rooty(), self.winfo_width(), self.winfo_height()
        else:
            px, py, pw, ph = 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
        x = px + (pw - width) // 2
        y = max(0, py + (ph - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")

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
        # Убираем светлую рамку Treeview из clam: границу рисует тонкий контур sidebar_frame.
        self.style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        self.style.configure(
            "Treeview",
            background=self.colors["tree_bg"],
            foreground=self.colors["tree_fg"],
            fieldbackground=self.colors["tree_bg"],
            borderwidth=0,
            font=(FONT_UI, 10),
            rowheight=S(26),
        )
        self.style.map(
            "Treeview",
            background=[("selected", self.colors["accent"])],
            foreground=[("selected", "#ffffff")],
        )
        self._setup_scrollbar_style()

    def _setup_scrollbar_style(self):
        """Тонкий плоский скроллбар без стрелок (как в веб-интерфейсах)."""
        c = self.colors
        for name, trough in (("Editor", c["bg_editor"]), ("Tree", c["tree_bg"])):
            style = f"{name}.Vertical.TScrollbar"
            self.style.layout(style, [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
            self.style.configure(
                style, troughcolor=trough, background=c["scroll_thumb"], bordercolor=trough,
                lightcolor=c["scroll_thumb"], darkcolor=c["scroll_thumb"], relief="flat",
                borderwidth=0, width=S(10), arrowsize=S(10), gripcount=0,
            )
            hover = [("pressed", c["scroll_hover"]), ("active", c["scroll_hover"])]
            self.style.map(style, background=hover, lightcolor=hover, darkcolor=hover)

    def apply_theme(self):
        """Применяет текущую тему ко всем элементам интерфейса."""
        self.colors = self.theme_palettes[self.current_theme]
        self.configure(bg=self.colors["bg_sidebar"])
        self.toolbar_frame.config(bg=self.colors["bg_sidebar"])
        self.search_frame.config(bg=self.colors["bg_sidebar"])
        # Группы кнопок и «держатели» создавались в тёмной теме; без этой строки в светлой
        # вокруг них оставались чёрные рамки.
        for fr in (self.format_frame, self.font_frame, *self._toolbar_holders):
            fr.config(bg=self.colors["bg_sidebar"])
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
        self.sidebar_frame.config(bg=self.colors["tree_bg"], highlightbackground=self.colors["border_soft"],
                                  highlightcolor=self.colors["border_soft"])
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
        self._setup_scrollbar_style()
        self.editor_frame.config(bg=self.colors["bg_editor"])
        if hasattr(self, "gutter"):
            self.gutter.config(bg=self.colors["bg_editor"])
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
        if hasattr(self, "btn_theme"):
            # Солнце/луна всегда эмодзи-шрифтом: в Segoe MDL2 Assets они рисовались «кракозяброй».
            self.btn_theme.config(text="☀️" if self.current_theme == "dark" else "🌙",
                                  font=("Segoe UI Emoji", 11))
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

    def create_icon_btn(self, parent, icon, tooltip_text, command, danger=False, glyph=None, font=None):
        """glyph — код из Segoe MDL2 Assets (родной значок); icon — запасной текст/эмодзи."""
        if glyph and HAS_ICON_FONT:
            icon, font = glyph, (FONT_ICON, 12)
        # Оптимизация/вид: кнопка кладётся в Frame фиксированного размера (pack_propagate(False)),
        # поэтому все кнопки одинаковы независимо от метрик шрифта (A+, B, </>, значки MDL2).
        holder = tk.Frame(parent, width=S(34), height=S(30), bg=parent.cget("bg"), bd=0)
        holder.pack_propagate(False)
        self._toolbar_holders.append(holder)
        btn = tk.Button(
            holder, text=icon, font=font or ("Segoe UI Emoji", 11),
            bd=0, relief=tk.FLAT,
            highlightthickness=0, cursor="hand2",
            padx=0, pady=0, command=command
        )
        btn._danger = danger
        btn._is_active = False
        self._style_flat_button(btn, active=False)
        btn.bind("<Enter>", self._on_btn_enter)
        btn.bind("<Leave>", self._on_btn_leave)
        btn.pack(fill=tk.BOTH, expand=True)
        holder.pack(side=tk.LEFT, padx=1, pady=2)
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
        self._toolbar_holders = []
        self.toolbar_frame = tk.Frame(self, bg=self.colors["bg_sidebar"], bd=0)
        self.toolbar_frame.pack(side=tk.TOP, fill=tk.X, padx=3, pady=3)
        # Файлы и хранилище
        self.btn_vault = self.create_icon_btn(
            self.toolbar_frame, "📁", "Выбрать хранилище (на текущий сеанс)", self.select_vault_folder, glyph="\uE838"
        )
        self.create_icon_btn(self.toolbar_frame, "➕", "Новая заметка (Ctrl+N)", self.create_new_note, glyph="\uE710")
        self.create_icon_btn(self.toolbar_frame, "📅", "Ежедневная заметка (Ctrl+D)", self.create_daily_note, glyph="\uE787")
        self.create_icon_btn(
            self.toolbar_frame, "🗑️", "Удалить выбранные (Delete)",
            self.delete_selected_items, danger=True, glyph="\uE74D"
        )
        # Поиск закреплён справа, как в образце
        self.search_frame = tk.Frame(self.toolbar_frame, bg=self.colors["bg_sidebar"])
        self.search_frame.pack(side=tk.RIGHT, padx=3, pady=2)
        self.lbl_search = tk.Label(
            self.search_frame, text="\uE721" if HAS_ICON_FONT else "🔍", bg=self.colors["bg_sidebar"],
            font=(FONT_ICON, 10) if HAS_ICON_FONT else ("Segoe UI Emoji", 9)
        )
        self.lbl_search.pack(side=tk.LEFT, padx=(2, 1))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_search_changed())
        self.search_entry = tk.Entry(
            self.search_frame, textvariable=self.search_var,
            font=(FONT_UI, 9), width=12, bd=1, relief=tk.SOLID
        )
        self.search_entry.pack(side=tk.LEFT, padx=1)
        ToolTip(self.search_entry, "Поиск по имени и тексту (Ctrl+F)")
        self.btn_clear_search = tk.Button(
            self.search_frame, text="×", font=(FONT_UI, 12),
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
            self.toggle_live_preview, glyph="\uE890"
        )
        # Кнопка НЕ подсвечена, когда маркеры скрыты; в Raw Markdown подсвечивается серым.
        self._style_flat_button(self.btn_live_preview, active=False)
        self.font_frame = tk.Frame(self.format_frame, bg=self.colors["bg_sidebar"])
        self.font_frame.pack(side=tk.LEFT, padx=(3, 3))
        self.create_icon_btn(self.font_frame, "A+", "Увеличить шрифт редактора", lambda: self.change_selected_font_size(1), font=(FONT_UI, 10, "bold"))
        self.create_icon_btn(self.font_frame, "A−", "Уменьшить шрифт редактора", lambda: self.change_selected_font_size(-1), font=(FONT_UI, 10, "bold"))
        self.create_icon_btn(self.format_frame, "B", "Жирный (Ctrl+B)", lambda: self.wrap_selection("**", "**"), font=(FONT_UI, 11, "bold"))
        self.create_icon_btn(self.format_frame, "I", "Курсив (Ctrl+I)", lambda: self.wrap_selection("*", "*"), font=(FONT_UI, 11, "italic"))
        self.create_icon_btn(self.format_frame, "U", "Подчёркивание (Ctrl+U)", lambda: self.wrap_selection("<u>", "</u>"), font=(FONT_UI, 11, "underline"))
        self.create_icon_btn(self.format_frame, "S̶", "Зачёркивание (Ctrl+Shift+S)", lambda: self.wrap_selection("~~", "~~"), font=(FONT_UI, 11))
        self.create_icon_btn(self.format_frame, "</>", "Код (Ctrl+Shift+C)", lambda: self.wrap_selection("`", "`"), font=(FONT_MONO, 10, "bold"))
        self.create_icon_btn(self.format_frame, "✎", "Подсветка текста (Ctrl+H)", lambda: self.wrap_selection("==", "=="), glyph="\uE7E6")
        self.create_icon_btn(self.format_frame, "🔗", "Вставить ссылку (Ctrl+K)", self._insert_link_dialog, glyph="\uE71B")
        # Системные команды — отдельной группой после форматирования
        self.btn_theme = self.create_icon_btn(
            self.toolbar_frame, "⚙", "Сменить светлую/тёмную тему", self.toggle_theme, glyph="\uE706"
        )
        self.create_icon_btn(self.toolbar_frame, "❔", "Справка и горячие клавиши (F1)", self.toggle_markdown_help, glyph="\uE897")
        self.btn_pin = self.create_icon_btn(
            self.toolbar_frame, "📌", "Закрепить поверх всех окон", self.toggle_always_on_top, glyph="\uE718"
        )
        self._style_flat_button(self.btn_pin, active=self.always_on_top)
        self.btn_mini = self.create_icon_btn(
            self.toolbar_frame, "▣", "Свернуть в мини-иконку у края экрана", self.toggle_mini_mode, glyph="\uE73F"
        )
        # Контекстное меню поиска с обычными операциями ввода
        self.search_context_menu = tk.Menu(self, tearoff=0, font=(FONT_UI, 9))
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
        self.sidebar_frame = tk.Frame(self.main_paned, bg=self.colors["tree_bg"], bd=0, highlightthickness=1,
                                      highlightbackground=self.colors["border_soft"], highlightcolor=self.colors["border_soft"])
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
            self.editor_frame, font=(FONT_UI, 17, "bold"),
            bd=0, bg=self.colors["bg_editor"], fg=self.colors["text_main"],
            insertbackground=self.colors["text_main"],
            selectbackground=self.colors["accent"], selectforeground="#ffffff"
        )
        self.title_entry.config(highlightthickness=0, relief=tk.FLAT)
        self.title_entry.pack(fill=tk.X, padx=S(30), pady=(S(14), S(4)))
        self.title_entry.bind("<Return>", self.on_title_commit)
        self.title_entry.bind("<FocusOut>", self.on_title_commit)
        text_container = tk.Frame(self.editor_frame, bg=self.colors["bg_editor"], bd=0)
        text_container.pack(fill=tk.BOTH, expand=True, padx=0, pady=(0, 2))
        # Полоса прокрутки создаётся первой (pack RIGHT), чтобы редактор занял остаток ширины.
        self.editor_scroll = ttk.Scrollbar(
            text_container, orient=tk.VERTICAL, style="Editor.Vertical.TScrollbar",
            command=lambda *args: self.editor.yview(*args))
        self.editor_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        # Жёлоб слева от текста: стрелки сворачивания живут в нём, а не поверх Text,
        # поэтому физически не могут перекрыть буквы.
        self.gutter = tk.Frame(text_container, width=S(24), bg=self.colors["bg_editor"], bd=0, highlightthickness=0)
        self.gutter.pack(side=tk.LEFT, fill=tk.Y)
        self.editor = tk.Text(
            text_container, wrap=tk.WORD, font=(FONT_UI, self._editor_font_size),
            bd=0, relief=tk.FLAT, highlightthickness=0,
            bg=self.colors["bg_editor"], fg=self.colors["text_main"],
            insertbackground=self.colors["text_main"], insertwidth=2,
            padx=S(6), pady=S(10), spacing1=S(2), spacing2=S(3), spacing3=S(2),
            undo=False,   # отмена — свой снимок из двух строк (см. _undo_checkpoint): стек Tk с копиями правок не нужен
            selectbackground=self.colors["accent"], selectforeground="#ffffff",
            inactiveselectbackground=self.colors["accent"],
            yscrollcommand=self._on_editor_yscroll
        )
        self.editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.editor.bind("<Configure>", self._on_editor_configure, add="+")
        self.main_paned.add(self.sidebar_frame, minsize=S(180), width=S(220))
        self.main_paned.add(self.editor_frame)

    def _build_status_bar(self):
        """Создает компактную строку состояния внизу окна."""
        self.status_bar = tk.Label(
            self, text="Готово | Строка 1, Колонка 0 | Слов: 0 | Символов: 0",
            anchor=tk.W, font=(FONT_UI, 8),
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
        self.tree.bind("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
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
        self.editor.bind("<Control-u>", lambda e: (self.wrap_selection("<u>", "</u>"), "break")[1])
        # Ctrl+буква по аппаратному коду клавиши (VK_*): работает в любой раскладке. В русской раскладке keysym —
        # кириллица, и привязки вида <Control-z> молча не срабатывают. Ключ: (код клавиши, нажат ли Shift).
        # Латинская раскладка использует более точные привязки выше, остальное попадает сюда.
        self._ctrl_actions = {
            (90, False): self.undo_last,
            (88, False): self.menu_cut, (67, False): self.menu_copy, (86, False): self.menu_paste,
            (65, False): self.menu_select_all,
            (66, False): lambda: self.wrap_selection("**", "**"),
            (73, False): lambda: self.wrap_selection("*", "*"),
            (85, False): lambda: self.wrap_selection("<u>", "</u>"),
            (72, False): lambda: self.wrap_selection("==", "=="),
            (75, False): self._insert_link_dialog,
            (67, True): lambda: self.wrap_selection("`", "`"),
            (83, True): lambda: self.wrap_selection("~~", "~~"),
            (84, True): self.format_active_table,
        }
        self.editor.bind("<Control-KeyPress>", self._on_editor_ctrl_key)
        self.tree.bind("<Control-KeyPress>", self._on_tree_ctrl_key)
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

    def _on_editor_configure(self, event):
        """Кнопки кода переставляются сразу; таблицы пересчитываются под новую ширину с задержкой
        (не на каждый пиксель перетаскивания границы окна)."""
        self._schedule_code_buttons()
        if (self._rendered_tables and self._tbl_resize_job is None and not self._tbl_edit
                and abs(self._table_avail_px() - self._tbl_avail_used) >= S(12)):
            self._tbl_resize_job = self.after(180, self._relayout_tables)

    def _relayout_tables(self):
        self._tbl_resize_job = None
        if not self._tbl_edit:
            self.apply_markdown_highlighting(force=True)

    def _on_editor_yscroll(self, first, last):
        """Обновляет скроллбар и (с троттлингом) позиции стрелок сворачивания.
        Оптимизация: стрелки привязаны к координатам строк, поэтому при прокрутке
        пересчитываются не чаще раза в 40 мс, а не на каждый тик колеса.
        """
        self.editor_scroll.set(first, last)
        if self._code_blocks:
            self._place_code_buttons()   # синхронно: иначе кнопки отстают от строк при прокрутке
        if not self._fold_refresh_pending:
            self._fold_refresh_pending = True
            self.after(40, self._deferred_fold_refresh)

    def _deferred_fold_refresh(self):
        self._fold_refresh_pending = False
        try:
            self._refresh_fold_markers()
        except tk.TclError:
            pass

    def _on_editor_press(self, event):
        """Запоминает точку нажатия, чтобы drag/выделение не считались кликом по ссылке."""
        try:
            self._editor_mouse_down_index = self.editor.index(f"@{event.x},{event.y}")
        except tk.TclError:
            self._editor_mouse_down_index = None

    def _in_no_fold(self, number):
        """Строка внутри блока кода, frontmatter или $$-формулы: «#» там — не заголовок.
        Диапазоны собирает apply_markdown_highlighting (единицы записей), поэтому проверка
        дешёвая и не требует разбирать документ заново."""
        for a, b in self._no_fold:
            if a <= number <= b:
                return True
        return False

    def _toggle_heading_fold(self, heading_line):
        """Сворачивает текст под Markdown-заголовком до следующего заголовка того же уровня."""
        lines = self.editor.get("1.0", "end-1c").split("\n")
        if heading_line < 1 or heading_line > len(lines) or self._in_no_fold(heading_line):
            return
        match = re.match(r"^(#{1,6})\s+", lines[heading_line - 1])
        if not match:
            return
        level = len(match.group(1))
        end_line = len(lines) + 1
        for number in range(heading_line + 1, len(lines) + 1):
            next_match = re.match(r"^(#{1,6})\s+", lines[number - 1])
            if next_match and len(next_match.group(1)) <= level and not self._in_no_fold(number):
                end_line = number   # «# комментарий» внутри блока кода раздел не заканчивает
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
        """Стрелки сворачивания для видимых заголовков из пула виджетов.
        Оптимизация: Label не пересоздаются на каждый вызов, а из Text читаются
        только видимые строки (а не весь документ).
        """
        try:
            first = int(self.editor.index("@0,0").split(".")[0])
            last = int(self.editor.index(f"@0,{self.editor.winfo_height()}").split(".")[0])
            lines = self.editor.get(f"{first}.0", f"{last}.end").split("\n")
        except (tk.TclError, ValueError):
            return
        pool, used = self._fold_markers, 0
        for offset, line in enumerate(lines):
            if line[:1] != "#" or not RE_HEADING_PREFIX.match(line):
                continue
            number = first + offset
            if self._in_no_fold(number):   # «# комментарий» в коде — не заголовок, стрелка не нужна
                continue
            info = self.editor.dlineinfo(f"{number}.0")
            if not info:  # строка свёрнута (elide) или вне экрана
                continue
            if used == len(pool):
                marker = tk.Label(self.gutter, bd=0, padx=0, pady=0, cursor="hand2", font=(FONT_UI, 9))
                marker.bind("<Button-1>", lambda e, w=marker: self._toggle_heading_fold(w._line))
                pool.append(marker)
            marker = pool[used]
            used += 1
            marker._line = number
            marker.config(text="▸" if number in self._folded_headings else "▾",
                          bg=self.colors["bg_editor"], fg=self.colors["text_muted"])
            marker.place(x=S(4), y=info[1], width=S(16), height=max(S(14), info[3]))
        for marker in pool[used:]:
            marker.place_forget()

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
        if event.x <= S(3) and re.match(r"^#{1,6}\s+", line_text) and not self._in_no_fold(line_num):
            self._toggle_heading_fold(line_num)
            return "break"
        # 1. Проверка клика по чекбоксу
        m_task = RE_CHECKBOX_LINE.match(line_text)
        if m_task:
            gs = len(m_task.group(1))
            if gs <= col_num <= gs + 1:  # клик именно по символу-чекбоксу
                self.editor.delete(f"{line_num}.0", f"{line_num}.end")
                self.editor.insert(f"{line_num}.0", _toggle_task_line(m_task))
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
        """Ctrl+Enter: переключает чекбокс строки или превращает строку в задачу."""
        line_num = int(self.editor.index(tk.INSERT).split(".")[0])
        line_text = self.editor.get(f"{line_num}.0", f"{line_num}.end")
        m_task = RE_CHECKBOX_LINE.match(line_text)
        if m_task:
            new_line = _toggle_task_line(m_task)
        else:
            stripped = line_text.lstrip()
            indent = line_text[:len(line_text) - len(stripped)]
            body = stripped[2:] if stripped.startswith(("- ", "* ", "• ")) else stripped
            new_line = f"{indent}☐ {body}"
        self.editor.delete(f"{line_num}.0", f"{line_num}.end")
        self.editor.insert(f"{line_num}.0", new_line)
        self.on_editor_key_release(None)

    # ==========================================================================
    # ОТМЕНА (Ctrl+Z, глубина 1 шаг) И СОЧЕТАНИЯ ПО КОДУ КЛАВИШИ
    # ==========================================================================
    def _undo_reset(self, text=""):
        """Новая заметка или пустой редактор: отмена начинается с нуля (чужой текст не должен «воскреснуть»)."""
        self._undo_prev = None
        self._undo_cur = text

    def _undo_checkpoint(self):
        """Запоминает состояние после серии правок (после секунды тишины и перед самой отменой).
        Оптимизация памяти: вместо стека Tk (до 50 записей с копиями вставок и удалений) хранятся ровно
        две строки — «до» и «после» последней серии. Серия правок = один шаг отмены."""
        text = self.editor.get("1.0", "end-1c")
        if text != self._undo_cur:
            self._undo_prev, self._undo_cur = self._undo_cur, text

    def _autosave_tick(self):
        """Секунда без ввода: сохранить файл и зафиксировать шаг отмены."""
        self._save_timer = None
        self.save_current_note()
        self._undo_checkpoint()

    def undo_last(self):
        """Ctrl+Z: откат последней серии правок. Глубина — 1 шаг: повторный Ctrl+Z ничего не вернёт."""
        self._undo_checkpoint()                 # правки последней секунды тоже входят в шаг
        prev, cur = self._undo_prev, self._undo_cur
        if prev is None:
            self.show_toast("Нечего отменять", "#f59e0b", 900)
            return
        # Курсор — на первом отличии: именно там пользователь правил.
        n = len(os.path.commonprefix((prev, cur)))
        line = prev.count("\n", 0, n) + 1
        col = _tk_len(prev[prev.rfind("\n", 0, n) + 1:n])
        view = self.editor.yview()[0]
        self.is_saving_internal = True
        self._clear_all_rendered_tables()       # окна таблиц пересоздаст подсветка
        self._folded_headings.clear()
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", prev)
        self.is_saving_internal = False
        self._undo_prev, self._undo_cur = None, prev
        self.editor.mark_set(tk.INSERT, f"{line}.{col}")
        self.apply_markdown_highlighting(force=True)
        self.editor.yview_moveto(view)
        self.after_idle(lambda: self.editor.see(tk.INSERT))
        self.on_editor_key_release(None)
        self.show_toast("↶ Отменено", "#64748b", 900)

    def _on_editor_ctrl_key(self, event):
        """Ctrl+буква по коду клавиши (см. _ctrl_actions); всё остальное отдаётся Tk как обычно."""
        if event.state & 0x20000:               # Alt (AltGr = Ctrl+Alt) — не наше сочетание
            return None
        action = self._ctrl_actions.get((event.keycode, bool(event.state & 1)))
        if action is None:
            return None
        action()
        return "break"

    def _on_tree_ctrl_key(self, event):
        """Фокус остался на дереве после выбора заметки: Ctrl+V и Ctrl+Z относятся к редактору."""
        if event.state & 1 or event.state & 0x20000:
            return None
        if event.keycode == 86:                 # V
            self.editor.focus_set()
            self.menu_paste()
            return "break"
        if event.keycode == 90:                 # Z
            self.editor.focus_set()
            self.undo_last()
            return "break"
        return None

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
            self.editor.insert(cursor, f"\n{indent}☐ ")
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
            if m_bul.group(2) in ("*", "+"):
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
        self._center_window(dialog, S(420), S(178))
        # Метки Tk сохраняют позицию вставки независимо от фокуса диалога.
        self.editor.mark_set("_link_dialog_start", start)
        self.editor.mark_set("_link_dialog_end", end)
        self.editor.mark_gravity("_link_dialog_start", tk.LEFT)
        self.editor.mark_gravity("_link_dialog_end", tk.RIGHT)
        tk.Label(dialog, text="Текст ссылки:", bg=self.colors["bg_editor"], fg=self.colors["text_main"], font=(FONT_UI, 9)).pack(anchor="w", padx=12, pady=(10, 2))
        entry_text = tk.Entry(dialog, font=(FONT_UI, 9), bg=self.colors["bg_sidebar"], fg=self.colors["text_main"], width=48)
        entry_text.pack(fill=tk.X, padx=12)
        entry_text.insert(0, selected)
        tk.Label(dialog, text="Адрес URL или [[Название заметки]]:", bg=self.colors["bg_editor"], fg=self.colors["text_main"], font=(FONT_UI, 9)).pack(anchor="w", padx=12, pady=(6, 2))
        entry_url = tk.Entry(dialog, font=(FONT_UI, 9), bg=self.colors["bg_sidebar"], fg=self.colors["text_main"], width=48)
        entry_url.pack(fill=tk.X, padx=12)
        # Контекстное меню ввода доступно в обоих полях диалога ссылки.
        entry_context_menu = tk.Menu(dialog, tearoff=0, font=(FONT_UI, 9))
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
            if target.startswith("[[") and target.endswith("]]"):
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
        self.editor.tag_raise("sel")
        if len(query) < 1:
            return
        start = "1.0"
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
        self.context_menu = tk.Menu(self, tearoff=0, font=(FONT_UI, 9))
        self.context_menu.add_command(label="Вырезать", accelerator="Ctrl+X", command=self.menu_cut)
        self.context_menu.add_command(label="Копировать", accelerator="Ctrl+C", command=self.menu_copy)
        self.context_menu.add_command(label="Вставить", accelerator="Ctrl+V", command=self.menu_paste)
        self.context_menu.add_command(label="Удалить", command=self.menu_delete)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Выбрать всё", accelerator="Ctrl+A", command=self.menu_select_all)
        self.editor.bind("<Button-3>", self.show_editor_menu)
        self.title_entry.bind("<Button-3>", self.show_editor_menu)
        self.tree_menu = tk.Menu(self, tearoff=0, font=(FONT_UI, 9))
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
        self._indent_tag_cache.clear()  # отступы списков зависят от размера шрифта
        self.editor.config(font=(FONT_UI, self._editor_font_size))
        self._setup_markdown_tags()
        self.apply_markdown_highlighting(force=True)
        self.show_toast(f"Размер шрифта: {self._editor_font_size} pt")

    def menu_cut(self):
        focused = self.focus_get()
        if focused == self.editor:
            self.menu_copy()      # через Win32-буфер (как Ctrl+C), затем удаляем выделение
            self.menu_delete()
        elif focused == self.title_entry:
            focused.event_generate("<<Cut>>")

    def menu_copy(self):
        focused = self.focus_get()
        if focused == self.editor:
            try:
                start, end = self.editor.index("sel.first"), self.editor.index("sel.last")
            except tk.TclError:
                return
            text = self.editor.get(start, end)
            self._set_clipboard_text(_markdown_bullets(text))
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
        self._center_window(dialog, S(320), S(120))
        tk.Label(
            dialog, text="Имя новой папки:", bg=self.colors["bg_editor"],
            fg=self.colors["text_main"], font=(FONT_UI, 9)
        ).pack(anchor="w", padx=12, pady=(10, 2))
        entry = tk.Entry(dialog, font=(FONT_UI, 9), bg=self.colors["bg_sidebar"], fg=self.colors["text_main"])
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
        frame = tk.Frame(dialog, bg=self.colors["bg_editor"])
        frame.pack(padx=10, pady=10)
        tk.Label(frame, text="Новое имя:", bg=self.colors["bg_editor"], fg=self.colors["text_main"], font=(FONT_UI, 10)).pack(anchor="w")
        entry = tk.Entry(
            frame, font=(FONT_UI, 10), width=30,
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
        self._center_window(dialog)   # размер по содержимому: рамка уже упакована

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
                self._undo_reset()
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

        MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), ctypes.c_long)
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
        self.icon_size = S(56)
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
        """Справка: простой текст (без «объёмных» плашек), содержимое — данные, отрисовка — один цикл."""
        if self.help_window is not None and self.help_window.winfo_exists():
            self.help_window.destroy()
            self.help_window = None
            return
        c = self.colors
        win = self.help_window = tk.Toplevel(self)
        win.title("Справка")
        self._center_window(win, S(700), S(720))
        win.transient(self)
        win.configure(bg=c["bg_editor"])
        win.bind("<Escape>", lambda e: win.destroy())
        scroll = ttk.Scrollbar(win, orient=tk.VERTICAL, style="Editor.Vertical.TScrollbar")
        txt = tk.Text(
            win, wrap=tk.WORD, bd=0, highlightthickness=0, cursor="arrow", bg=c["bg_editor"], fg=c["text_main"],
            font=(FONT_UI, 10), padx=S(30), pady=S(22), spacing1=S(2), spacing3=S(2), yscrollcommand=scroll.set)
        scroll.config(command=txt.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(fill=tk.BOTH, expand=True)
        col = S(190)  # колонка слева; перенесённые строки описания выравниваются по ней
        txt.tag_configure("title", font=(FONT_UI, 20, "bold"), spacing3=S(2))
        txt.tag_configure("sub", foreground=c["text_muted"], spacing3=S(4))
        txt.tag_configure("h", font=(FONT_UI, 10, "bold"), foreground=c["accent"], spacing1=S(22), spacing3=S(6))
        txt.tag_configure("row", tabs=(col,), lmargin1=S(2), lmargin2=col, spacing1=S(3), spacing3=S(3))
        txt.tag_configure("key", font=(FONT_UI, 10, "bold"))                 # клавиши — просто жирным текстом
        txt.tag_configure("code", font=(FONT_MONO, 10), foreground=c["tag_code"])
        txt.tag_configure("dim", foreground=c["text_muted"], spacing1=S(16))
        # Примечания: метка типа — цветом типа, как в редакторе; тот же словарь цветов (_callout_palette)
        pal = self._callout_palette()
        for kind, (fg, _bg) in pal.items():
            txt.tag_configure("k_" + kind, foreground=fg, font=(FONT_UI, 10, "bold"))
        keys = (
            ("Ctrl+N", "Новая заметка в выбранной папке"), ("Ctrl+D", "Ежедневная заметка"),
            ("Ctrl+S", "Сохранить"), ("Ctrl+F", "Поиск по названиям и тексту"),
            ("Ctrl+Z", "Отменить последнее действие (глубина — 1 шаг)"),
            ("Ctrl+K", "Вставить ссылку"), ("Ctrl+B / I / U", "Жирный / курсив / подчёркнутый"),
            ("Ctrl+H", "Маркер ==текст=="), ("Ctrl+Shift+S", "Зачёркивание"),
            ("Ctrl+Shift+C", "Инлайн-код"),
            ("Ctrl+Shift+T", "Выровнять исходный текст таблицы под курсором"),
            ("Ctrl+Enter", "Чекбокс ☐ ↔ ☑ или превратить строку в задачу"),
            ("Tab / Shift+Tab", "Отступ списка"), ("Ctrl+W", "Закрыть заметку"),
            ("Delete", "Удалить выбранное в дереве"), ("F1", "Эта справка"))
        table = (
            ("Enter / Tab", "Сохранить ячейку и перейти ниже / вправо; в последней строке Enter добавляет строку"),
            ("Shift+Enter", "Новая строка внутри ячейки (в файле хранится как <br>)"),
            ("Esc", "Отменить правку ячейки"),
            ("Правая кнопка", "Меню: строки и столбцы (добавить, удалить), выравнивание, правка как текст"))
        paste = (
            ("Из браузера", "Edge и Chrome: заголовки, жирный и курсив, код с языком, списки, таблицы, цитаты, "
                            "формулы, примечания GitHub и Microsoft Learn."),
            ("Ссылка", "Одиночный URL → [Название](url); для YouTube название подтягивается в фоне."),
            ("Текст + ссылка", "Выделите текст и вставьте URL — получится [текст](url)."),
            ("Ответы ИИ", "ChatGPT, Gemini, Claude: источники [1] и формулы \\( … \\) приводятся к Markdown."))
        syntax = (
            ("Заголовки", "# H1 … ###### H6"), ("Стили", "**жирный**  *курсив*  ~~зачёркнутый~~"),
            ("Подчёркивание", "<u>текст</u>"), ("Линия", "---"),
            ("Списки", "*  →  •      +  →  ◦      -  тире"),
            ("Маркер, код", "==маркер==  `код`"), ("Блок кода", "```язык … ```"),
            ("Задачи", "- [ ] дело  → ☐     - [x] готово  → ☑"), ("Ссылки", "[текст](url)   [[Заметка]]"),
            ("Таблица", "| A | B |  — вторая строка | --- | --- |"),
            ("Формулы", "$E=mc^2$   $H_2O$   $$ … $$   (также \\( … \\))"),
            ("Перенос в ячейке", "текст<br>текст"))
        callouts = (("NOTE", "Заметка"), ("TIP", "Совет"), ("IMPORTANT", "Важно"), ("WARNING", "Внимание"),
                    ("CAUTION", "Осторожно"))

        def section(title, rows, style):
            txt.insert(tk.END, title.upper() + "\n", "h")
            for name, desc in rows:
                txt.insert(tk.END, name, ("key", "row"))
                txt.insert(tk.END, "\t", "row")
                txt.insert(tk.END, desc + "\n", (("code", "row") if style == "code" else "row"))

        txt.insert(tk.END, "Быстрый Заметчик\n", "title")
        txt.insert(tk.END, "Лёгкие заметки в стиле Obsidian · Markdown на диске, красивый вид в редакторе\n", "sub")
        section("Горячие клавиши", keys, "key")
        section("Таблицы", table, "key")
        section("Умная вставка (Ctrl+V)", paste, "label")
        section("Разметка", syntax, "code")
        txt.insert(tk.END, "ПРИМЕЧАНИЯ\n", "h")
        txt.insert(tk.END, "Пишутся цитатой: первая строка ", "row")
        txt.insert(tk.END, "> [!NOTE] Заголовок", ("code", "row"))
        txt.insert(tk.END, ", далее строки с «>». Типы:\n", "row")
        for kind, ru in callouts:
            txt.insert(tk.END, kind, ("k_" + kind, "row"))
            txt.insert(tk.END, "\t" + ru + "\n", "row")
        txt.insert(tk.END, "\nEsc — закрыть", "dim")
        txt.config(state=tk.DISABLED)    # ==========================================================================
    # ПОДСВЕТКА MARKDOWN, LIVE PREVIEW И ЕСТЕСТВЕННЫЕ ЭМОДЗИ
    # ==========================================================================
    def _display_current_star_list_marker(self):
        """Показывает маркер Markdown-списка * как типографский •, не меняя файл на диске."""
        try:
            line_num = int(self.editor.index(tk.INSERT).split(".")[0])
            line = self.editor.get(f"{line_num}.0", f"{line_num}.end")
            if not re.match(r"^(\s*)[*+]\s", line):
                return
            # Не трогаем строки внутри fenced code block.
            before = self.editor.get("1.0", f"{line_num}.0").splitlines()
            in_fence = sum(1 for item in before if item.startswith("```")) % 2 == 1
            if in_fence:
                return
            m = re.match(r"^(\s*)([*+])(\s)", line)
            if not m:
                return
            start = f"{line_num}.0+{len(m.group(1))}c"
            self.editor.delete(start, f"{start}+1c")
            self.editor.insert(start, BULLET_VIEW[m.group(2)])
        except (tk.TclError, ValueError):
            pass

    def _display_current_task_marker(self):
        """Набранное вручную «- [ ]» сразу показывается как ☐ (на диск уйдёт обычный Markdown)."""
        try:
            line_num = int(self.editor.index(tk.INSERT).split(".")[0])
            m = RE_TASK_MD.match(self.editor.get(f"{line_num}.0", f"{line_num}.end"))
            if m:
                self.editor.delete(f"{line_num}.0", f"{line_num}.{len(m.group(0))}")
                self.editor.insert(f"{line_num}.0", m.group(1) + TASK_GLYPH[m.group(2)])
        except (tk.TclError, ValueError):
            pass

    def on_editor_key_release(self, event):
        if self.is_saving_internal:
            return
        self._display_current_star_list_marker()
        self._display_current_task_marker()
        self.is_modified = True
        self._update_status_bar()
        if self._save_timer:
            self.after_cancel(self._save_timer)
        self._save_timer = self.after(1000, self._autosave_tick)
        if self._highlight_timer:
            self.after_cancel(self._highlight_timer)
        self._highlight_timer = self.after(250, self.apply_markdown_highlighting)

    def _get_indent_tag(self, base, indent_spaces):
        depth = min(indent_spaces // 2, 8)
        tag_name = f"{base}_{depth}"
        if tag_name not in self._indent_tag_cache:
            margin = S(8) + depth * S(20)
            # Висячий отступ: перенесённые строки выравниваются по тексту, а не по маркеру.
            try:
                probe = tkfont.Font(font=(FONT_UI, self._editor_font_size))
                hang = probe.measure("\u2022 " if base == "bullet_list" else "0. ")
            except tk.TclError:
                hang = S(14)
            self.editor.tag_configure(
                tag_name, foreground=self.colors["text_main"],
                lmargin1=margin, lmargin2=margin + hang
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
        # Оптимизация 1: сброс всех тегов одним вызовом Tcl вместо ~80 отдельных tag_remove.
        self.tk.eval("foreach t {%s %s} {%s tag remove $t 1.0 end}" % (
            _STATIC_TAGS_STR, " ".join(self._indent_tag_cache), self.editor))
        # Оптимизация 2: диапазоны копятся в словаре и применяются одним tag_add на тег.
        acc = {}

        def add(tag, start, end):
            acc.setdefault(tag, []).extend((start, end))

        lines = text_content.split("\n")
        try:
            cursor_line = int(self.editor.index(tk.INSERT).split(".")[0])
        except Exception:
            cursor_line = -1
        in_code_block = False
        in_frontmatter = False
        in_math_block = False
        code_blocks = []   # [строка открывающего ограждения, строка закрывающего | None] — для кнопок «Копировать»
        fold_skip = []     # диапазоны строк, где «#» — не заголовок (frontmatter, $$-формулы; код — из code_blocks)
        math_open = 0
        for idx, line in enumerate(lines, start=1):
            line_start = f"{idx}.0"
            line_end = f"{idx}.end"
            full_line_end = f"{idx}.end + 1c"
            is_active = (idx == cursor_line) or (not self.live_preview_enabled)
            # ИНЛАЙН СКАНИРОВАНИЕ С КОРРЕКЦИЕЙ СУРРОГАТОВ UTF-16 (для эмодзи 🚀, 🛠)
            if not line.isascii() and any(ord(c) > 0xFFFF for c in line):
                tk_offset = 0
                py_to_tk = []
                for ch in line:
                    py_to_tk.append(tk_offset)
                    tk_offset += 2 if ord(ch) > 0xFFFF else 1
                py_to_tk.append(tk_offset)

                def tk_p(pos):
                    return py_to_tk[pos] if pos < len(py_to_tk) else tk_offset
            else:
                tk_p = _identity
            # YAML Frontmatter в начале файла
            if idx == 1 and line.strip() == "---":
                in_frontmatter = True
                add("frontmatter", line_start, full_line_end)
                continue
            if in_frontmatter:
                add("frontmatter", line_start, full_line_end)
                if line.strip() == "---":
                    in_frontmatter = False
                    fold_skip.append((1, idx))
                continue
            # Блоки кода ```lang (цельная прямоугольная область со всеми строками)
            if line.startswith("```"):
                in_code_block = not in_code_block
                add("code_fence", line_start, full_line_end)
                add("code_block", line_start, full_line_end)
                lead = len(line) - len(line.lstrip("`"))
                if in_code_block:
                    code_blocks.append([idx, None])
                    lang_txt = line[lead:]
                    if lang_txt.strip():
                        # Название языка — другим цветом (как заголовок плашки в веб-чатах).
                        lang_s = lead + len(lang_txt) - len(lang_txt.lstrip())
                        add("code_lang", f"{idx}.{lang_s}", line_end)
                elif code_blocks and code_blocks[-1][1] is None:
                    code_blocks[-1][1] = idx
                if not is_active:
                    if in_code_block and len(line) > lead:
                        # Открывающее ограждение с языком: прячем только ```, подпись языка
                        # остаётся мелким заголовком плашки (как в веб-чатах).
                        add("hide_markup", line_start, f"{idx}.{lead}")
                    else:
                        add("hide_markup", line_start, line_end)
                continue
            if in_code_block:
                add("code_block", line_start, full_line_end)
                continue
            # Блоки формул $$
            if RE_MATH_BLOCK.match(line):
                in_math_block = not in_math_block
                if in_math_block:
                    math_open = idx
                else:
                    fold_skip.append((math_open, idx))
                add("math", line_start, full_line_end)
                if not is_active:
                    add("hide_markup", line_start, line_end)
                continue
            if in_math_block:
                add("math", line_start, full_line_end)
                continue
            # Заголовки H1..H6
            if line.startswith("# "):
                add("h1", line_start, line_end)
                if not is_active:
                    add("hide_markup", line_start, f"{idx}.2")
            elif line.startswith("## "):
                add("h2", line_start, line_end)
                if not is_active:
                    add("hide_markup", line_start, f"{idx}.3")
            elif line.startswith("### "):
                add("h3", line_start, line_end)
                if not is_active:
                    add("hide_markup", line_start, f"{idx}.4")
            elif line.startswith("#### "):
                add("h4", line_start, line_end)
                if not is_active:
                    add("hide_markup", line_start, f"{idx}.5")
            elif line.startswith("##### "):
                add("h5", line_start, line_end)
                if not is_active:
                    add("hide_markup", line_start, f"{idx}.6")
            elif line.startswith("###### "):
                add("h6", line_start, line_end)
                if not is_active:
                    add("hide_markup", line_start, f"{idx}.7")
            # Разделительная линия: вне активной строки текст «---» скрыт, а перевод строки с крошечным шрифтом
            # и цветным фоном рисует сплошную полосу на всю ширину (фон перевода строки Tk тянет до края
            # окна — так же устроены плашки кода). Под курсором показывается исходный «---».
            if RE_HR.match(line):
                if is_active:
                    add("hr_src", line_start, line_end)
                else:
                    add("hr", line_start, full_line_end)
                    add("hide_markup", line_start, line_end)
            # Коллауты Obsidian: мягкая цветовая подсветка по типу [!NOTE]/[!WARNING]/[!DANGER]...
            m_callout = RE_CALLOUT_START.match(line)
            if m_callout:
                kind = m_callout.group(1).upper()
                known = CALLOUT_KINDS
                suffix = kind if kind in known else "default"
                add(f"callout_header_{suffix}", line_start, full_line_end)
                if not is_active:
                    # «> [!TIP] Заголовок» -> «Заголовок»: метка типа целиком скрыта (цвет плашки
                    # уже несёт тип); одним диапазоном вместо двух — меньше вызовов tag_add.
                    add("hide_markup", line_start, f"{idx}.{m_callout.start(2)}")
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
                    known = CALLOUT_KINDS
                    suffix = callout_kind if callout_kind in known else "default"
                    add(f"callout_body_{suffix}", line_start, full_line_end)
                else:
                    add("quote", line_start, full_line_end)
                if not is_active:
                    mq = RE_BLOCKQUOTE.match(line)
                    if mq:
                        add("hide_markup", line_start, f"{idx}.{mq.end()}")
            stripped = line.strip()
            # Таблицы GFM (цельные прямоугольные блоки со столбцами)
            if not in_code_block and not in_frontmatter and "|" in stripped:
                add("table_block", line_start, full_line_end)
                if RE_TABLE_SEP.match(stripped):
                    add("table_sep", line_start, full_line_end)
                elif idx < len(lines) and RE_TABLE_SEP.match(lines[idx].strip()):
                    add("table_header", line_start, full_line_end)
                else:
                    if idx % 2 == 0:
                        add("table_row_alt", line_start, full_line_end)
                    else:
                        add("table_row", line_start, full_line_end)
            # Чекбоксы задач
            m_task = RE_CHECKBOX_LINE.match(line)
            if m_task:
                state = GLYPH_STATE[m_task.group(2)].lower()
                marker_start = f"{idx}.{m_task.start(2)}"
                marker_end = f"{idx}.{m_task.end(2)}"
                add("task_marker", marker_start, marker_end)
                if state == "x":
                    add("checkbox_done", line_start, line_end)
                    add("task_marker_done", marker_start, marker_end)
                elif state == "-":
                    add("checkbox_cancel", line_start, line_end)
                    add("task_marker_cancel", marker_start, marker_end)
                elif state == "/":
                    add("checkbox_progress", line_start, line_end)
                    add("task_marker_progress", marker_start, marker_end)
                else:
                    add("checkbox_todo", line_start, line_end)
                    add("task_marker_todo", marker_start, marker_end)
            else:
                m_bullet = RE_BULLET.match(line)
                m_number = RE_NUM_LIST.match(line)
                if m_bullet:
                    tag = self._get_indent_tag("bullet_list", len(m_bullet.group(1)))
                    add(tag, line_start, line_end)
                    mk = len(m_bullet.group(1))
                    add("bullet_mark", f"{idx}.{mk}", f"{idx}.{mk + 1}")
                elif m_number:
                    tag = self._get_indent_tag("number_list", len(m_number.group(1)))
                    add(tag, line_start, line_end)
                    add("number_mark", f"{idx}.{len(m_number.group(1))}", f"{idx}.{m_number.end() - 1}")
            # Маска для стилей (см. RE_MASK): URL и `код` не участвуют в разборе **, *, ==, ~~, $.
            # Условие-предфильтр экономит regex на строках без ссылок и кода (большинство строк).
            mline = RE_MASK.sub(_mask_blank, line) if ("](" in line or "http" in line or "`" in line or "<" in line) else line
            # Для **/*/==/~~ формулы тоже маскируются: «_» в $H_2SiO_3$ — индекс, а не курсив.
            sline = RE_MATH_INLINE.sub(_mask_blank, mline) if ("$" in mline or "\\(" in mline) else mline
            # 1. Вики-ссылки [[Note|Alias]]
            for m in RE_WIKILINK.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                text_s_idx = f"{idx}.{tk_p(m.start() + 2)}"
                text_e_idx = f"{idx}.{tk_p(m.end() - 2)}"
                add("wikilink", text_s_idx, text_e_idx)
                if not is_active:
                    add("hide_markup", s_idx, text_s_idx)
                    add("hide_markup", text_e_idx, e_idx)
            # 2. Изображения ![Alt](URL)
            for m in RE_IMAGE.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                label_s_idx = f"{idx}.{tk_p(m.start() + 2)}"
                label_e_idx = f"{idx}.{tk_p(m.start() + 2 + len(m.group(1)))}"
                add("md_image", label_s_idx, label_e_idx)
                if not is_active:
                    add("hide_markup", s_idx, label_s_idx)
                    add("hide_markup", label_e_idx, e_idx)
            # 3. Markdown ссылки [Text](URL) — скрытие URL в Live Preview
            for m in RE_MDLINK.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                label_s_idx = f"{idx}.{tk_p(m.start() + 1)}"
                label_e_idx = f"{idx}.{tk_p(m.start() + 1 + len(m.group(1)))}"
                add("md_link", label_s_idx, label_e_idx)
                if m.group(1).isdigit() and len(m.group(1)) <= 3:
                    add("cite", label_s_idx, label_e_idx)  # [1](url) -> «кнопка» источника
                if not is_active:
                    add("hide_markup", s_idx, label_s_idx)
                    add("hide_markup", label_e_idx, e_idx)
            # 4. Ссылки авто и bare URL
            for m in RE_AUTOLINK.finditer(line):
                add("md_link", f"{idx}.{tk_p(m.start() + 1)}", f"{idx}.{tk_p(m.end() - 1)}")
            for m in RE_BARE_URL.finditer(line):
                add("md_link", f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}")
            # 5. Жирный курсив ***текст*** или ___текст___
            for m in RE_BOLD_ITALIC.finditer(sline):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                add("bold_italic", s_idx, e_idx)
                if not is_active:
                    add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 3)}")
                    add("hide_markup", f"{idx}.{tk_p(m.end() - 3)}", e_idx)
            # 6. Жирный **текст** или __текст__
            for m in RE_BOLD.finditer(sline):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                add("bold", s_idx, e_idx)
                if not is_active:
                    add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 2)}")
                    add("hide_markup", f"{idx}.{tk_p(m.end() - 2)}", e_idx)
            # 7. Курсив *текст* или _текст_
            for m in RE_ITALIC.finditer(sline):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                add("italic", s_idx, e_idx)
                if not is_active:
                    add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 1)}")
                    add("hide_markup", f"{idx}.{tk_p(m.end() - 1)}", e_idx)
            # 8. Код `code`
            for m in RE_CODE_INLINE.finditer(line):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                add("code", s_idx, e_idx)
                if not is_active:
                    add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 1)}")
                    add("hide_markup", f"{idx}.{tk_p(m.end() - 1)}", e_idx)
            # 9. Подсветка маркёром ==highlight==
            for m in RE_HIGHLIGHT.finditer(sline):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                add("highlight", s_idx, e_idx)
                if not is_active:
                    add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 2)}")
                    add("hide_markup", f"{idx}.{tk_p(m.end() - 2)}", e_idx)
            # 10. Зачёркивание ~~strike~~
            for m in RE_STRIKE.finditer(sline):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                add("strike", s_idx, e_idx)
                if not is_active:
                    add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + 2)}")
                    add("hide_markup", f"{idx}.{tk_p(m.end() - 2)}", e_idx)
            # 10b. Подчёркивание <u>текст</u>: теги скрываются вне активной строки, текст подчёркивается.
            if "<u>" in mline:
                for m in RE_UNDERLINE.finditer(mline):
                    s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                    in_s, in_e = f"{idx}.{tk_p(m.start() + 3)}", f"{idx}.{tk_p(m.end() - 4)}"
                    add("underline", in_s, in_e)
                    if not is_active:
                        add("hide_markup", s_idx, in_s)
                        add("hide_markup", in_e, e_idx)
            # 11. Инлайн математика $math$ — маркеры скрываются после завершения редактирования.
            for m in RE_MATH_INLINE.finditer(mline):
                s_idx, e_idx = f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}"
                add("math", s_idx, e_idx)
                body, base = (m.group(1), m.start(1)) if m.group(1) is not None else (m.group(2), m.start(2))
                dl = base - m.start()      # длина разделителя: 1 для $…$, 2 для \(…\)
                if not is_active:
                    add("hide_markup", s_idx, f"{idx}.{tk_p(m.start() + dl)}")
                    add("hide_markup", f"{idx}.{tk_p(m.end() - dl)}", e_idx)
                # Индексы формулы (Tk не умеет подставлять символы, но умеет сдвигать и уменьшать текст):
                # «_2» и «^{-}» -> цифра ниже/выше строки, служебные _ ^ { } скрываются.
                for mw in RE_TEX_WRAP.finditer(body):      # \mathrm{...}: прячем обёртку, оставляем текст
                    ws, we = base + mw.start(), base + mw.end()
                    if not is_active:
                        add("hide_markup", f"{idx}.{tk_p(ws)}", f"{idx}.{tk_p(base + mw.start(1))}")
                        add("hide_markup", f"{idx}.{tk_p(we - 1)}", f"{idx}.{tk_p(we)}")
                for ms in RE_TEX_SCRIPT.finditer(body):
                    kind = "math_sub" if ms.group(1) == "_" else "math_sup"
                    if ms.group(2) is not None:            # _{...}: текст внутри скобок
                        a0, a1 = base + ms.start(2), base + ms.end(2)
                        if not is_active:
                            add("hide_markup", f"{idx}.{tk_p(base + ms.start())}", f"{idx}.{tk_p(a0)}")
                            add("hide_markup", f"{idx}.{tk_p(a1)}", f"{idx}.{tk_p(base + ms.end())}")
                    else:                                  # _2: один символ
                        a0, a1 = base + ms.start(3), base + ms.end(3)
                        if not is_active:
                            add("hide_markup", f"{idx}.{tk_p(base + ms.start())}", f"{idx}.{tk_p(a0)}")
                    add(kind, f"{idx}.{tk_p(a0)}", f"{idx}.{tk_p(a1)}")
            # 11b. HTML-индексы <sub>x</sub> / <sup>x</sup> (GitHub): теги скрываются, текст сдвигается
            if "<su" in mline:
                for m in RE_HTML_SCRIPT.finditer(mline):
                    open_len = 5                           # длина «<sub>» и «<sup>»
                    add("html_sub" if m.group(1) == "sub" else "html_sup",
                        f"{idx}.{tk_p(m.start() + open_len)}", f"{idx}.{tk_p(m.end() - open_len - 1)}")
                    if not is_active:
                        add("hide_markup", f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.start() + open_len)}")
                        add("hide_markup", f"{idx}.{tk_p(m.end() - open_len - 1)}", f"{idx}.{tk_p(m.end())}")
            # 12. Теги #tag
            for m in RE_TAG.finditer(line):
                add("tag", f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}")
            # 13. Смайлики и пиктограммы (естественные цвета, полный охват суррогатов)
            for m in RE_EMOJI.finditer(line):
                if m.group() in GLYPH_STATE:  # ☐ ☑ ☒ красит тег чекбокса, а не emoji
                    continue
                add("emoji", f"{idx}.{tk_p(m.start())}", f"{idx}.{tk_p(m.end())}")
        self._code_blocks = code_blocks
        if in_frontmatter:
            fold_skip.append((1, 10 ** 9))
        if in_math_block:
            fold_skip.append((math_open, 10 ** 9))
        self._no_fold = fold_skip + [(a, b or 10 ** 9) for a, b in code_blocks]
        for tag, rng in acc.items():
            self.editor.tag_add(tag, *rng)
        # Гарантируем наивысший приоритет тега emoji, чтобы смайлики не перекрашивались и не подчёркивались ссылками
        for tag in ("math_sub", "math_sup", "html_sub", "html_sup", "code_lang", "cite", "bullet_mark", "number_mark", "task_marker", "task_marker_todo", "task_marker_done",
                    "task_marker_cancel", "task_marker_progress"):
            self.editor.tag_raise(tag)
        self.editor.tag_raise("emoji")
        # Выделение мышью — поверх плашек кода, цитат и таблиц: у них задан background, и у «sel»
        # (создан раньше всех, приоритет самый низкий) он перекрывал выделение — его не было видно.
        self.editor.tag_raise("sel")
        # Интерактивное отображение таблиц в стиле Obsidian Live Preview
        self._update_rendered_tables(lines, cursor_line, force)
        self._refresh_fold_markers()
        self._schedule_code_buttons()

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

    # ------------------------------------------------------------------ таблицы
    def _tbl_font(self, fs, is_hdr, flags):
        """Шрифт ячейки по флагам сегмента (кэш: Font создаётся один раз на сочетание)."""
        key = (fs, is_hdr, flags)
        f = self._tbl_fonts.get(key)
        if f is None:
            small = "u" in flags or "p" in flags
            if "c" in flags:
                f = tkfont.Font(family=FONT_MONO, size=max(7, fs - 2 - (2 if small else 0)),
                                weight="bold" if "b" in flags else "normal")
            else:
                # Формула (x) — курсив Segoe UI, как в редакторе; индексы мельче и сдвигаются тегом.
                f = tkfont.Font(family=FONT_UI, size=max(7, fs - 1 - (3 if small else 0)),
                                weight="bold" if (is_hdr or "b" in flags) else "normal",
                                slant="italic" if ("i" in flags or "x" in flags) else "roman")
            self._tbl_fonts[key] = f
        return f

    @staticmethod
    def _displaylines(w):
        """Число экранных строк Text-виджета с учётом переноса по словам (None — неизвестно)."""
        try:
            r = w.count("1.0", "end", "displaylines")
        except tk.TclError:
            return None
        if isinstance(r, (tuple, list)):
            r = r[0] if r else 0
        try:
            return max(1, int(r or 0))
        except (TypeError, ValueError):
            return None

    def _fit_text_height(self, w):
        """Подгоняет высоту Text-ячейки под реальное число строк: строки таблицы растут сами."""
        n = self._displaylines(w)
        try:
            if n and int(w.cget("height")) != n:
                w.configure(height=n)
        except tk.TclError:
            pass

    def _cell_segments(self, raw):
        """(сегменты | None, есть ли разметка, простой текст) для сырого текста ячейки."""
        segs = parse_inline_segments(raw) if any(ch in raw for ch in "*_`[~=\\$<") else None
        rich = segs is not None and any(f or u for _, f, u in segs)
        plain = raw if segs is None else "".join(t for t, _, _ in segs)
        return segs, rich, plain

    def _measure_segments(self, segs, fs, is_hdr):
        """(ширина без переносов, ширина самого длинного слова) в пикселях; «\\n» (<br>) — новая строка."""
        total = longest = line_w = 0
        for text, flags, _url in segs:
            f = self._tbl_font(fs, is_hdr, flags)
            for k, part in enumerate(text.split("\n")):
                if k:                      # перенос: ширина ячейки — по самой длинной из строк
                    total, line_w = max(total, line_w), 0
                line_w += f.measure(part)
                for word in part.split():
                    longest = max(longest, f.measure(word))
        return max(total, line_w), longest

    def _segment_items(self, segs, fs, is_hdr):
        items = []
        for text, flags, _url in segs:
            f = self._tbl_font(fs, is_hdr, flags)
            for k, part in enumerate(text.split("\n")):
                if k:
                    items.append((-1, True))   # принудительный перенос строки (см. count_wrapped_lines)
                for tok in re.findall(r"\s+|\S+", part):
                    items.append((f.measure(tok), tok.isspace()))
        return items

    def _table_avail_px(self):
        """Ширина под таблицу: видимая ширина редактора минус поля и запас на полосу прокрутки."""
        w = self.editor.winfo_width()
        if w < 200:      # окно ещё не показано
            w = 900
        return max(S(260), w - 2 * S(6) - S(28))

    def _make_cell(self, tbl, entry, r, ci, is_hdr, data, align, inner_px, fg, bg, fs):
        segs, rich, plain, _mseg = data

        def edit(en=entry, rr=r, cc=ci):
            self._begin_cell_edit(en, rr, cc)

        if rich:
            cell = self._make_rich_cell(tbl, segs, fs, is_hdr, fg, bg, align, inner_px, edit)
        else:
            # Оптимизация: Label дешевле Text, поэтому ячейки без разметки (их большинство)
            # остаются Label; wraplength сам переносит длинный текст по словам.
            cell = tk.Label(tbl, text=plain or " ", font=self._tbl_font(fs, is_hdr, ""), fg=fg, bg=bg,
                            anchor={"center": "center", "right": "e"}.get(align, "w"), justify=align,
                            padx=_TBL_PADX, pady=5, wraplength=inner_px)
            cell.bind("<Button-1>", lambda e, f=edit: (f(), "break")[1])
        cell.bind("<Button-3>", lambda e, en=entry, rr=r, cc=ci: self._table_menu(e, en, rr, cc))
        cell.bind("<MouseWheel>", self._on_mousewheel)  # иначе колесо над таблицей «залипает»
        return cell

    def _make_rich_cell(self, parent, segs, fs, is_hdr, fg, bg, align, inner_px, on_edit):
        """Ячейка со смешанным форматированием: жирный, курсив, `код`, ссылки, формулы, индексы.
        Label не умеет менять шрифт внутри текста, поэтому берётся Text без рамки и курсора.
        Высота сначала оценивается переносом по метрикам шрифтов (нет «прыжка» при показе),
        затем уточняется самим Tk (<Configure> -> count -displaylines)."""
        c = self.colors
        base = self._tbl_font(fs, is_hdr, "")
        lines = count_wrapped_lines(self._segment_items(segs, fs, is_hdr), inner_px)
        txt = tk.Text(parent, font=base, fg=fg, bg=bg, bd=0, relief=tk.FLAT, highlightthickness=0,
                      wrap=tk.WORD, height=lines, width=max(1, inner_px // (base.measure("0") or 8)),
                      padx=_TBL_PADX, pady=5, cursor="arrow", takefocus=0,
                      exportselection=False, insertwidth=0)
        links = {}        # имя тега ссылки -> URL
        made = set()
        for text_, flags, url in segs:
            name = "t_" + (flags or "n") + ("_l" if url else "")
            link_tag = None
            if url:
                if url not in links.values():
                    links["lk%d" % len(links)] = url
                link_tag = next(k for k, v in links.items() if v == url)
            if name not in made:
                made.add(name)
                kw = {"font": self._tbl_font(fs, is_hdr, flags)}
                if "c" in flags:
                    kw.update(foreground=c["tag_code"], background=c["tag_code_bg"])
                if "x" in flags:
                    kw["foreground"] = c["tag_math"]
                if "m" in flags:
                    kw.update(background=c["tag_highlight"], foreground=c["tag_highlight_fg"])
                if "s" in flags:
                    kw["overstrike"] = True
                if "n" in flags:
                    kw["underline"] = True
                if "u" in flags:
                    kw["offset"] = -S(3)
                if "p" in flags:
                    kw["offset"] = S(5)
                if url:
                    kw.update(foreground=c["accent"], underline=True)
                txt.tag_configure(name, **kw)
            # Тег lkN привязывает клик/курсор к конкретному URL, tag_names в обработчике его вернёт.
            txt.insert("end", text_, (name, link_tag) if link_tag else (name,))
        for link_tag in links:
            txt.tag_bind(link_tag, "<Enter>", lambda e, w=txt: w.config(cursor="hand2"))
            txt.tag_bind(link_tag, "<Leave>", lambda e, w=txt: w.config(cursor="arrow"))
        txt.tag_configure("al", justify=align)
        txt.tag_add("al", "1.0", "end")

        def on_click(e):
            for tg in txt.tag_names(f"@{e.x},{e.y}"):
                if tg in links:
                    self._open_url(links[tg])
                    return "break"
            on_edit()
            return "break"

        txt.bind("<Button-1>", on_click)
        txt.bind("<B1-Motion>", lambda e: "break")
        txt.bind("<Double-Button-1>", lambda e: "break")
        txt.bind("<Configure>", lambda e, w=txt: self._fit_text_height(w))
        txt.configure(state=tk.DISABLED)
        return txt

    def _build_table_entry(self, tbl_lines, avail):
        """Создаёт Frame-таблицу и запись о ней: ширины столбцов подбираются под avail пикселей."""
        alignments, rows = self._parse_table_data(tbl_lines)
        if not alignments:
            return None
        c = self.colors
        fs = self._editor_font_size
        n_cols = len(alignments)
        tbl = tk.Frame(self.editor, bg=c.get("table_border", "#333333"), bd=0)
        cells = [[(cols[i] if i < len(cols) else "") for i in range(n_cols)] for cols, _ in rows]
        entry = {"widget": tbl, "aligns": alignments, "cells": cells, "grid": {}, "fs": fs,
                 "theme": self.current_theme, "avail": avail, "lines": None, "nlines": len(tbl_lines),
                 "line": 0, "idx": ""}
        pad2 = 2 * _TBL_PADX
        data = {}
        max_w = [0] * n_cols
        min_w = [0] * n_cols
        for r, (_, is_hdr) in enumerate(rows):
            for ci in range(n_cols):
                segs, rich, plain = self._cell_segments(cells[r][ci])
                mseg = segs if rich else [(plain, "", "")]
                total, longest = self._measure_segments(mseg, fs, is_hdr)
                data[(r, ci)] = (segs, rich, plain, mseg)
                max_w[ci] = max(max_w[ci], total + pad2)
                min_w[ci] = max(min_w[ci], longest + pad2)
        floor = S(56)
        min_w = [min(mx, max(mn, floor)) for mx, mn in zip(max_w, min_w)]
        col_px = layout_columns(max_w, min_w, max(avail - 2 * n_cols, n_cols * floor))
        for r, (_, is_hdr) in enumerate(rows):
            bg = c.get("tag_table_header_bg", "#18181c") if is_hdr else c.get("tag_table_bg", "#18181c")
            fg = c.get("accent", "#60a5fa") if is_hdr else c.get("text_main", "#e4e4e7")
            for ci in range(n_cols):
                inner = max(S(24), col_px[ci] - pad2)
                cell = self._make_cell(tbl, entry, r, ci, is_hdr, data[(r, ci)], alignments[ci], inner, fg, bg, fs)
                cell.grid(row=r, column=ci, sticky="nsew", padx=1, pady=1)
                entry["grid"][(r, ci)] = cell
        for ci in range(n_cols):
            tbl.grid_columnconfigure(ci, minsize=col_px[ci], weight=0)
        return entry

    # ------------------------------------------------------------------ правка ячеек на месте
    def _table_start_line(self, entry):
        """Строка, в которой лежит окно таблицы (по факту, а не по запомненному номеру)."""
        name = str(entry["widget"])
        try:
            for _k, val, idx in self.editor.dump("1.0", "end", window=True):
                if val == name:
                    return int(idx.split(".")[0])
        except tk.TclError:
            pass
        return None

    def _replace_table_line(self, start_line, row, text):
        """Подменяет строку таблицы в тексте: заголовок — строка start, дальше +2 (после разделителя)."""
        ln = start_line + (0 if row == 0 else row + 1)
        a = f"{ln}.1" if row == 0 else f"{ln}.0"      # в начале первой строки лежит символ окна
        self.editor.delete(a, f"{ln}.end")
        self.editor.insert(a, text)

    @staticmethod
    def _next_cell(entry, r, ci, step):
        n_rows, n_cols = len(entry["cells"]), len(entry["aligns"])
        if step > 0:
            if ci + 1 < n_cols:
                return (r, ci + 1)
            return (r + 1, 0) if r + 1 < n_rows else "addrow"
        if ci > 0:
            return (r, ci - 1)
        return (r - 1, n_cols - 1) if r > 0 else None

    def _begin_cell_edit(self, entry, r, ci):
        """Превращает ячейку в поле ввода прямо в таблице: границы и ширины столбцов сохраняются."""
        ed = self._tbl_edit
        if ed:
            if ed["entry"] is entry and (ed["r"], ed["c"]) == (r, ci):
                return
            self._finish_cell_edit(move=(r, ci) if ed["entry"] is entry else None)
            return
        orig = entry["grid"].get((r, ci))
        if orig is None:
            return
        try:
            if not orig.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.colors
        is_hdr = (r == 0)
        w = tk.Text(entry["widget"], font=self._tbl_font(entry["fs"], is_hdr, ""), fg=c["text_main"],
                    bg=c["bg_editor"], insertbackground=c["text_main"], selectbackground=c["accent"],
                    selectforeground="#ffffff", bd=0, relief=tk.FLAT, highlightthickness=1,
                    highlightbackground=c["accent"], highlightcolor=c["accent"], wrap=tk.WORD,
                    height=1, padx=_TBL_PADX - 1, pady=4, undo=True)
        w.insert("1.0", re.sub(r"<br\s*/?>", "\n", entry["cells"][r][ci]))   # <br> -> настоящий перенос строки
        orig.grid_remove()
        w.grid(row=r, column=ci, sticky="nsew", padx=1, pady=1)
        nxt_row = (r + 1, ci) if r + 1 < len(entry["cells"]) else None
        w.bind("<Return>", lambda e: (self._finish_cell_edit(move=nxt_row), "break")[1])
        # Shift+Enter — новая строка внутри ячейки (более точная привязка перебивает <Return>).
        w.bind("<Shift-Return>", lambda e, t=w: (t.insert("insert", "\n"), self._fit_text_height(t), "break")[2])
        w.bind("<Tab>", lambda e: (self._finish_cell_edit(move=self._next_cell(entry, r, ci, 1)), "break")[1])
        for seq in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            w.bind(seq, lambda e: (self._finish_cell_edit(move=self._next_cell(entry, r, ci, -1)), "break")[1])
        w.bind("<Escape>", lambda e: (self._finish_cell_edit(cancel=True), "break")[1])
        w.bind("<FocusOut>", lambda e: self._finish_cell_edit())
        w.bind("<KeyRelease>", lambda e, t=w: self._fit_text_height(t))
        w.bind("<MouseWheel>", self._on_mousewheel)
        self._tbl_edit = {"entry": entry, "r": r, "c": ci, "w": w, "orig": orig}
        w.focus_set()
        w.mark_set("insert", "end-1c")
        self.after_idle(lambda t=w: self._fit_text_height(t))

    def _finish_cell_edit(self, move=None, cancel=False):
        """Завершает правку ячейки: текст записывается в строку таблицы, затем переход к следующей ячейке."""
        ed = self._tbl_edit
        if not ed:
            return
        self._tbl_edit = None
        entry, r, ci, w, orig = ed["entry"], ed["r"], ed["c"], ed["w"], ed["orig"]
        try:
            raw = w.get("1.0", "end-1c")
        except tk.TclError:
            raw = None           # таблицу уже перерисовали, виджет уничтожен
        try:
            w.destroy()
        except tk.TclError:
            pass
        try:
            orig.grid()
        except tk.TclError:
            pass
        if raw is None:
            return
        raw = self._cell_raw(raw)       # перенос строки -> <br>, «|» экранируется (не режет столбец)
        start = self._table_start_line(entry)
        if start is None:
            return
        changed = (not cancel) and raw != entry["cells"][r][ci]
        add_row = (move == "addrow") and not cancel
        n_rows = len(entry["cells"])
        if changed:
            entry["cells"][r][ci] = raw
            self._replace_table_line(start, r, "| " + " | ".join(entry["cells"][r]) + " |")
        target = None
        if add_row:
            end_line = start + entry["nlines"] - 1
            self.editor.insert(f"{end_line}.end", "\n|" + "  |" * len(entry["aligns"]))
            target = (n_rows, 0)
        elif isinstance(move, tuple) and not cancel:
            target = move
        if changed or add_row:
            entry["lines"] = None                      # принудительная перерисовка этой таблицы
            self._tbl_pending_edit = (start, target) if target else None
            self.apply_markdown_highlighting(force=True)
            self.on_editor_key_release(None)
        elif target:
            self._begin_cell_edit(entry, *target)

    @staticmethod
    def _cell_raw(text):
        """Текст поля ввода -> Markdown ячейки: перенос строки = <br> (GFM/Obsidian), «|» экранируется."""
        text = re.sub(r"[ \t]*\n[ \t]*", "<br>", text.strip())
        return re.sub(r"(?<!\\)\|", r"\\|", text)

    def _table_edit_struct(self, entry, op, i=0, arg=None):
        """Строки и столбцы: операция над копией ячеек, затем ОДНА запись таблицы в текст.
        Таблица пересобирается целиком из entry, а не правится построчно: строки, столбцы и разделитель
        с выравниванием всегда согласованы, перерисовка происходит один раз."""
        ed = self._tbl_edit
        if ed and ed["entry"] is entry:        # недописанная ячейка не должна пропасть при перерисовке
            try:
                entry["cells"][ed["r"]][ed["c"]] = self._cell_raw(ed["w"].get("1.0", "end-1c"))
            except tk.TclError:
                pass
        start = self._table_start_line(entry)
        if start is None:
            return
        cells, aligns = [row[:] for row in entry["cells"]], entry["aligns"][:]
        if op == "row":                        # i — позиция новой строки
            cells.insert(i, [""] * len(aligns))
        elif op == "delrow":
            del cells[i]
        elif op == "col":                      # i — позиция нового столбца
            for row in cells:
                row.insert(i, "")
            aligns.insert(i, "left")
        elif op == "delcol":
            for row in cells:
                del row[i]
            del aligns[i]
        elif op == "align":
            aligns[i] = arg
        sep = [{"center": ":---:", "right": "---:"}.get(a, "---") for a in aligns]
        lines = ["| " + " | ".join(r) + " |" for r in cells[:1] + [sep] + cells[1:]]
        if op == "fmt":                        # Ctrl+Shift+T: выровнять исходный текст по ширине столбцов
            lines = format_markdown_table_lines(lines)
        end_line = start + entry["nlines"] - 1
        self.editor.delete(f"{start}.1", f"{end_line}.end")   # в столбце 0 первой строки лежит символ окна таблицы
        self.editor.insert(f"{start}.1", "\n".join(lines))
        entry["lines"] = None                  # принудительная перерисовка этой таблицы
        self.apply_markdown_highlighting(force=True)
        self.on_editor_key_release(None)

    def _table_menu(self, event, entry, r, ci):
        """Контекстное меню ячейки: строки, столбцы, выравнивание, исходный текст (как в Typora/Notion)."""
        start = self._table_start_line(entry)
        if start is None:
            return "break"
        st = self._table_edit_struct
        ok = lambda cond: tk.NORMAL if cond else tk.DISABLED     # шапку нельзя удалить и «подвинуть» вверх
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Добавить строку выше", state=ok(r > 0), command=lambda: st(entry, "row", r))
        m.add_command(label="Добавить строку ниже", command=lambda: st(entry, "row", r + 1))
        m.add_command(label="Удалить строку", state=ok(r > 0), command=lambda: st(entry, "delrow", r))
        m.add_separator()
        m.add_command(label="Добавить столбец слева", command=lambda: st(entry, "col", ci))
        m.add_command(label="Добавить столбец справа", command=lambda: st(entry, "col", ci + 1))
        m.add_command(label="Удалить столбец", state=ok(len(entry["aligns"]) > 1),
                      command=lambda: st(entry, "delcol", ci))
        al = tk.Menu(m, tearoff=0)
        for label, a in (("По левому краю", "left"), ("По центру", "center"), ("По правому краю", "right")):
            al.add_command(label=label, command=lambda a=a: st(entry, "align", ci, a))
        m.add_cascade(label="Выравнивание столбца", menu=al)
        m.add_separator()
        m.add_command(label="Выровнять исходный текст  (Ctrl+Shift+T)", command=lambda: st(entry, "fmt"))
        m.add_command(label="Править как Markdown-текст",
                      command=lambda: self._on_rendered_table_click(start + (0 if r == 0 else r + 1)))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()
        return "break"

    def _on_rendered_table_click(self, line_num):
        """Переводит курсор на строку таблицы и разворачивает её исходный код для редактирования."""
        self.editor.focus_set()
        self.editor.mark_set(tk.INSERT, f"{line_num}.0")
        self.apply_markdown_highlighting(force=True)
        return "break"

    def _clear_all_rendered_tables(self):
        """Уничтожает виджеты таблиц при переключении заметки (текст удаляет вызывающий код)."""
        for e in self._rendered_tables:
            try:
                e["widget"].destroy()
            except tk.TclError:
                pass
        self._rendered_tables = []
        self._tbl_edit = None
        self._tbl_pending_edit = None

    def _update_rendered_tables(self, lines, cursor_line, force=False):
        """Показывает таблицы виджетами в Live Preview и сверяет их с текстом.
        Раньше записи были привязаны к номерам строк: вставка или удаление текста выше таблицы
        сдвигала номера, старое окно оставалось в тексте, а исходный текст таблицы показывался
        заново — отсюда «рассыпавшаяся» дублирующая таблица. Теперь сверка идёт по фактической
        позиции окна (оно перемещается вместе с текстом): окно на нужном месте с тем же
        содержимым не трогается, поэтому таблица не перерисовывается и не дёргается. Параметр
        force больше не пересоздаёт таблицы — этим занимаются тема, размер шрифта и ширина."""
        blocks = []
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
                blocks.append((start_line, j, tbl_lines))   # j — последняя строка таблицы (1-based)
                i = j
            else:
                i += 1
        if not blocks and not self._rendered_tables:
            return
        editor = self.editor
        fs, theme, avail = self._editor_font_size, self.current_theme, self._table_avail_px()
        # 1. Где окна таблиц лежат на самом деле (Tk сам сдвигает их вместе с текстом).
        try:
            win_idx = {val: idx for _k, val, idx in editor.dump("1.0", "end", window=True) if val}
        except tk.TclError:
            win_idx = {}
        alive, stale = [], []
        for e in self._rendered_tables:
            idx = win_idx.pop(str(e["widget"]), None)
            if idx is None:
                stale.append(e)          # символ окна удалён правкой пользователя
            else:
                e["idx"] = idx
                e["line"] = int(idx.split(".")[0])
                alive.append(e)
        orphans = list(win_idx.values())  # окна вне учёта (следы прежних сбоев) — убираем
        # 2. Что оставить как есть: окно на своём месте, тот же текст, размер, тема и ширина.
        used, keep, hidden, to_create = set(), [], [], []
        for start_line, end_line, tbl_lines in blocks:
            if not self.live_preview_enabled or start_line <= cursor_line <= end_line:
                continue                  # под курсором — исходный Markdown
            lt = tuple(tbl_lines)
            hit = None
            for e in alive:
                if (id(e) not in used and e["line"] == start_line and e["lines"] == lt and e["fs"] == fs
                        and e["theme"] == theme and abs(e["avail"] - avail) < S(12)):
                    hit = e
                    break
            if hit is not None:
                used.add(id(hit))
                keep.append(hit)
                hidden.append((start_line, end_line))
            else:
                to_create.append((start_line, end_line, lt, tbl_lines))
        drop = [e for e in alive if id(e) not in used]
        ed = self._tbl_edit
        if ed and any(e is ed["entry"] for e in drop + stale):
            self._tbl_edit = None         # таблицу с редактируемой ячейкой убрали — поле ввода исчезнет с ней
        # 3. Удаление лишних окон и создание недостающих — одним проходом с выключенным undo.
        if drop or stale or orphans or to_create:
            editor.configure(undo=False)
            try:
                for idx in [e["idx"] for e in drop] + orphans:
                    try:
                        editor.delete(idx)   # символ окна лежит в столбце 0 своей строки: строки не сдвигаются
                    except tk.TclError:
                        pass
                for e in drop + stale:
                    try:
                        e["widget"].destroy()
                    except tk.TclError:
                        pass
                for start_line, end_line, lt, tbl_lines in to_create:
                    entry = self._build_table_entry(tbl_lines, avail)
                    if entry is None:
                        continue
                    try:
                        editor.window_create(f"{start_line}.0", window=entry["widget"])
                    except tk.TclError:
                        entry["widget"].destroy()
                        continue
                    entry.update(lines=lt, line=start_line, idx=f"{start_line}.0")
                    keep.append(entry)
                    hidden.append((start_line, end_line))
            finally:
                editor.configure(undo=False)   # Tk-undo остаётся выключенным (см. _undo_checkpoint)
        self._rendered_tables = keep
        self._tbl_avail_used = avail
        # 4. Скрываем исходный текст таблиц; тег пересобирается только если диапазоны изменились.
        hidden.sort()
        want = []
        for s_, e_ in hidden:
            want += [editor.index(f"{s_}.1"), editor.index(f"{e_}.end")]
        cur = [str(x) for x in editor.tag_ranges("hide_table")]
        if cur != want:
            editor.tag_remove("hide_table", "1.0", "end")
            for k in range(0, len(want), 2):
                editor.tag_add("hide_table", want[k], want[k + 1])
        # Строка-хозяин окна таблицы не должна краситься «плашкой» table_*: фон перевода строки Tk тянет
        # до края окна, и тёмная полоса торчала слева и справа от виджета.
        for s_, e_ in hidden:
            for tg in ("table_block", "table_header", "table_sep", "table_row", "table_row_alt"):
                editor.tag_remove(tg, f"{s_}.0", f"{e_}.end+1c")
        # 5. После перерисовки (Tab/Enter в ячейке) открываем следующую ячейку для правки.
        if self._tbl_pending_edit:
            start, (r2, c2) = self._tbl_pending_edit
            self._tbl_pending_edit = None
            for e in keep:
                if e["line"] == start:
                    self.after_idle(lambda en=e, a=r2, b=c2: self._begin_cell_edit(en, a, b))
                    break

    # ------------------------------------------------------------------ кнопки «Копировать»
    def _make_copy_button(self, i):
        """Кнопка «Копировать» в шапке блока кода: значок MDL2 + подпись (или только подпись)."""
        c = self.colors
        bg, fg, hover = c["tag_code_fence_bg"], c["text_muted"], c["text_main"]
        fr = tk.Frame(self.editor, bg=bg, cursor="hand2", bd=0, highlightthickness=0)
        ic = None
        if HAS_ICON_FONT:
            ic = tk.Label(fr, text="\uE8C8", font=(FONT_ICON, 10), bg=bg, fg=fg, cursor="hand2")
            ic.pack(side=tk.LEFT, padx=(S(4), S(3)), pady=S(2))
        tx = tk.Label(fr, text="Копировать", font=(FONT_UI, 9), bg=bg, fg=fg, cursor="hand2")
        tx.pack(side=tk.LEFT, padx=(0 if ic else S(6), S(6)), pady=S(2))
        fr._ic, fr._tx = ic, tx

        def on_click(e, i=i):
            self._copy_code_block(i)
            return "break"

        def on_enter(e):
            for w in (ic, tx):
                if w:
                    w.config(fg=hover)

        def on_leave(e):
            for w in (ic, tx):
                if w:
                    w.config(fg=fg)

        for w in (fr, ic, tx):
            if w:
                w.bind("<Button-1>", on_click)
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
                w.bind("<MouseWheel>", self._on_mousewheel)
        return fr

    def _schedule_code_buttons(self):
        """Откладывает расстановку кнопок до простоя: за одну перерисовку — один проход."""
        if not self._code_btn_pending:
            self._code_btn_pending = True
            self.after_idle(self._place_code_buttons)

    def _place_code_buttons(self):
        """Ставит кнопки «Копировать» поверх строк-ограждений видимых блоков кода.
        Оптимизация: кнопки — накладки (place), а не встроенные окна Text: содержимое заметки,
        индексы и undo не меняются. Проход — по числу блоков (единицы), dlineinfo возвращает
        None для невидимых строк, и такие кнопки просто прячутся."""
        if self._code_btn_busy:
            return
        self._code_btn_busy = True
        self._code_btn_pending = False
        try:
            pool = self._code_btns
            if self._code_btn_theme != self.current_theme:
                for b in pool:           # смена темы — пересоздаём с новыми цветами
                    b.destroy()
                pool.clear()
                self._code_btn_theme = self.current_theme
            blocks = self._code_blocks
            while len(pool) < len(blocks):
                pool.append(self._make_copy_button(len(pool)))
            right = self.editor.winfo_width() - S(14)
            for i, btn in enumerate(pool):
                info = self.editor.dlineinfo(f"{blocks[i][0]}.end") if i < len(blocks) else None
                if info:
                    btn.place(x=right, y=info[1] + info[3] // 2, anchor="e")
                else:
                    btn.place_forget()
        except tk.TclError:
            pass
        finally:
            self._code_btn_busy = False

    def _copy_code_block(self, i):
        """Копирует содержимое блока кода (без ограждений ```) в буфер обмена."""
        try:
            start, end = self._code_blocks[i]
        except IndexError:
            return
        if end:
            code = self.editor.get(f"{start + 1}.0", f"{end}.0")
            if code.endswith("\n"):
                code = code[:-1]
        else:
            code = self.editor.get(f"{start + 1}.0", "end-1c")
        self._set_clipboard_text(code)
        btn = self._code_btns[i]
        btn._tx.config(text="Скопировано")
        if btn._ic:
            btn._ic.config(text="\uE73E")   # галочка MDL2
        self.after(1400, lambda b=btn: self._reset_copy_button(b))

    def _reset_copy_button(self, btn):
        try:
            btn._tx.config(text="Копировать")
            if btn._ic:
                btn._ic.config(text="\uE8C8")
        except tk.TclError:
            pass  # кнопку успели пересоздать (смена темы)

    def _cfg_block(self, tag, bg, **kw):
        """Блочный тег с закрашенными полями; на старом Tk без *margincolor — обычный фон."""
        try:
            self.editor.tag_configure(tag, background=bg, lmargincolor=bg, rmargincolor=bg, **kw)
        except tk.TclError:
            self.editor.tag_configure(tag, background=bg, **kw)

    def _callout_palette(self):
        """Цвета примечаний: тип -> (цвет метки, цвет плашки) для текущей темы; общие для редактора и справки."""
        dark = self.current_theme == "dark"
        return {
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

    def _configure_callout_tags(self, fs):
        """Настраивает мягкие цвета Obsidian-callout по типу [!TYPE]."""
        palette = self._callout_palette()
        default_fg = self.colors["accent"]
        default_bg = self.colors["tag_quote"]
        for kind, (fg, bg) in palette.items():
            self._cfg_block(f"callout_header_{kind}", bg, font=(FONT_UI, fs, "bold"), foreground=fg,
                            lmargin1=S(16), lmargin2=S(16), rmargin=S(12), spacing1=S(2), spacing3=0)
            self._cfg_block(f"callout_body_{kind}", bg, foreground=self.colors["text_main"],
                            lmargin1=S(16), lmargin2=S(16), rmargin=S(12), spacing1=0, spacing3=0)
        self._cfg_block("callout_header_default", default_bg, font=(FONT_UI, fs, "bold"), foreground=default_fg,
                        lmargin1=S(16), lmargin2=S(16), rmargin=S(12), spacing1=S(2), spacing3=0)
        self._cfg_block("callout_body_default", default_bg, foreground=self.colors["text_main"],
                        lmargin1=S(16), lmargin2=S(16), rmargin=S(12), spacing1=0, spacing3=0)

    def _setup_markdown_tags(self):
        """Конфигурация визуальных стилей тегов (соответствие CHARFORMAT2 / RichEdit)."""
        fs = self._editor_font_size
        # Оставляем свободную полосу слева для кнопки сворачивания заголовка.
        heading_indent = 0
        self.editor.tag_configure("h1", font=(FONT_UI, fs + 6, "bold"), foreground=self.colors["tag_header"], lmargin1=heading_indent, lmargin2=heading_indent, spacing1=S(16), spacing3=S(4))
        self.editor.tag_configure("h2", font=(FONT_UI, fs + 4, "bold"), foreground=self.colors["tag_header"], lmargin1=heading_indent, lmargin2=heading_indent, spacing1=S(14), spacing3=S(4))
        self.editor.tag_configure("h3", font=(FONT_UI, fs + 2, "bold"), foreground=self.colors["tag_header"], lmargin1=heading_indent, lmargin2=heading_indent, spacing1=S(12), spacing3=S(4))
        self.editor.tag_configure("h4", font=(FONT_UI, fs + 1, "bold"), foreground=self.colors["text_muted"], lmargin1=heading_indent, lmargin2=heading_indent, spacing1=S(10), spacing3=S(4))
        self.editor.tag_configure("h5", font=(FONT_UI, fs, "bold"), foreground=self.colors["text_muted"], lmargin1=heading_indent, lmargin2=heading_indent, spacing1=S(8), spacing3=S(4))
        self.editor.tag_configure("h6", font=(FONT_UI, fs, "italic"), foreground=self.colors["text_muted"], lmargin1=heading_indent, lmargin2=heading_indent, spacing1=S(8), spacing3=S(4))
        self.editor.tag_configure("bold", font=(FONT_UI, fs, "bold"), foreground=self.colors["tag_bold"])
        self.editor.tag_configure("italic", font=(FONT_UI, fs, "italic"), foreground=self.colors["text_main"])
        self.editor.tag_configure("bold_italic", font=(FONT_UI, fs, "bold italic"), foreground=self.colors["tag_bold"])
        self.editor.tag_configure(
            "code", font=(FONT_MONO, fs - 1), foreground=self.colors["tag_code"],
            background=self.colors["tag_code_bg"]
        )
        # Блоки кода: тёмная «плашка» с внутренними отступами (как в ChatGPT / веб-чатах).
        # lmargincolor/rmargincolor (Tk 8.6.10+) закрашивают поля — получается ровный прямоугольник.
        self._cfg_block("code_block", self.colors["tag_code_fence_bg"], font=(FONT_MONO, fs - 1),
                        foreground=self.colors["text_main"], lmargin1=S(16), lmargin2=S(16),
                        rmargin=S(16), spacing1=0, spacing3=0)
        # Строка-ограждение — «шапка» плашки: выше и просторнее, справа на ней лежит кнопка «Копировать».
        self._cfg_block("code_fence", self.colors["tag_code_fence_bg"], font=(FONT_UI, fs - 1, "bold"),
                        foreground=self.colors["text_muted"], lmargin1=S(16), lmargin2=S(16),
                        rmargin=S(16), spacing1=S(8), spacing3=S(6))
        # Название языка — акцентным цветом (отдельный тег поверх code_fence).
        self.editor.tag_configure("code_lang", foreground=self.colors["accent"],
                                  font=(FONT_UI, fs - 1, "bold"))
        self.editor.tag_configure("checkbox_todo", foreground=self.colors["text_main"])
        # Чекбокс — символ ☐/☑ из Segoe UI Symbol: крупнее текста, цвет по состоянию.
        self.editor.tag_configure("task_marker", font=("Segoe UI Symbol", fs + 3), overstrike=False)
        self.editor.tag_configure("task_marker_todo", foreground=self.colors["text_muted"])
        self.editor.tag_configure("task_marker_done", foreground=self.colors["accent"])
        self.editor.tag_configure("task_marker_cancel", foreground=self.colors["tag_done"])
        self.editor.tag_configure("task_marker_progress", foreground=self.colors["accent"])
        self.editor.tag_configure("checkbox_done", foreground="#9ca3af", overstrike=True)
        self.editor.tag_configure("checkbox_cancel", foreground=self.colors["tag_done"], overstrike=True)
        self.editor.tag_configure("checkbox_progress", foreground=self.colors["accent"])
        self.editor.tag_configure("bullet_list", foreground=self.colors["text_main"], lmargin1=S(8), lmargin2=S(22))
        self.editor.tag_configure("number_list", foreground=self.colors["text_main"], lmargin1=S(8), lmargin2=S(26))
        self.editor.tag_configure("bullet_mark", foreground=self.colors["accent"], font=(FONT_UI, fs, "bold"))
        self.editor.tag_configure("number_mark", foreground=self.colors["text_muted"], font=(FONT_UI, fs, "bold"))
        self.editor.tag_configure("wikilink", foreground=self.colors["accent"], underline=True)
        self.editor.tag_configure("md_link", foreground=self.colors["accent"], underline=True)
        self.editor.tag_configure("md_image", foreground=self.colors["accent"], font=(FONT_UI, fs, "italic"))
        # Сноска-источник [1](url): маленькая приподнятая «таблетка»; клик работает как у md_link.
        self.editor.tag_configure("cite", font=(FONT_UI, max(7, fs - 3), "bold"), foreground=self.colors["accent"],
                                  background=self.colors["accent_light"], offset=S(4), underline=False)
        # Линия «---»: толщина = высота строки шрифта 1 pt + spacing1 + spacing3 (при желании подстройте).
        self.editor.tag_configure("hr", font=(FONT_UI, 1), background=self.colors["scroll_thumb"],
                                  foreground=self.colors["scroll_thumb"], spacing1=S(1), spacing3=S(1))
        self.editor.tag_configure("hr_src", foreground=self.colors["text_muted"])
        self.editor.tag_configure(
            "highlight", font=(FONT_UI, fs, "bold"),
            background=self.colors["tag_highlight"], foreground=self.colors["tag_highlight_fg"]
        )
        self.editor.tag_configure("strike", foreground=self.colors["tag_strike"], overstrike=True)
        self.editor.tag_configure("underline", underline=True)
        self._cfg_block("quote", self.colors["tag_quote"], foreground=self.colors["text_muted"],
                        lmargin1=S(16), lmargin2=S(16), rmargin=S(12))
        self._configure_callout_tags(fs)
        # Таблицы GFM: цельные прямоугольные таблицы со столбцами
        self.editor.tag_configure(
            "table_block", font=(FONT_MONO, fs - 1),
            background=self.colors["tag_table_bg"], lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure(
            "table_header", font=(FONT_MONO, fs - 1, "bold"),
            foreground=self.colors["accent"], background=self.colors["tag_table_header_bg"],
            lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure(
            "table_sep", font=(FONT_MONO, fs - 1),
            foreground=self.colors["text_muted"], background=self.colors["tag_table_sep_bg"],
            lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure(
            "table_row", font=(FONT_MONO, fs - 1),
            background=self.colors["tag_table_bg"], lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure(
            "table_row_alt", font=(FONT_MONO, fs - 1),
            background=self.colors["tag_table_alt_bg"], lmargin1=20, lmargin2=20, rmargin=20
        )
        self.editor.tag_configure("tag", foreground=self.colors["tag_tag"], font=(FONT_UI, fs, "bold"))
        # Формулы — курсив Segoe UI, как у отрисованной математики в Obsidian/GitHub, а не моноширинный «код».
        self.editor.tag_configure("math", foreground=self.colors["tag_math"], font=(FONT_UI, fs, "italic"))
        # Индексы формул и <sub>/<sup>: меньший кегль и сдвиг относительно базовой линии.
        self.editor.tag_configure("math_sub", font=(FONT_UI, max(7, fs - 3), "italic"), offset=-S(3))
        self.editor.tag_configure("math_sup", font=(FONT_UI, max(7, fs - 3), "italic"), offset=S(5))
        self.editor.tag_configure("html_sub", font=(FONT_UI, max(7, fs - 3)), offset=-S(3))
        self.editor.tag_configure("html_sup", font=(FONT_UI, max(7, fs - 3)), offset=S(5))
        self.editor.tag_configure("frontmatter", foreground=self.colors["text_muted"], font=(FONT_MONO, fs - 1))
        # Естественные цвета эмодзи (отдельный шрифт Segoe UI Emoji, теплый естественный оттенок)
        self.editor.tag_configure("emoji", font=("Segoe UI Emoji", fs), foreground=self.colors["tag_emoji"], underline=False)
        # Настоящий Live Preview: elide=True схлопывает символы до нулевой ширины!
        self.editor.tag_configure("hide_table", elide=True)
        if self.live_preview_enabled:
            self.editor.tag_configure("hide_markup", elide=True)
        else:
            self.editor.tag_configure("hide_markup", elide=False, foreground=self.colors["text_muted"])
        self.editor.tag_raise("sel")

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
            self._undo_reset()
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
        if self.current_note_path is not None:    # курсор уходящей заметки — в память сеанса
            self._cursor_mem[str(self.current_note_path)] = self.editor.index(tk.INSERT)
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
            self._folded_headings.clear()         # теги свёртки ушли вместе со старым текстом
            self._undo_reset(self.editor.get("1.0", "end-1c"))
            saved = self._cursor_mem.get(str(note_path))
            if saved:
                try:
                    self.editor.mark_set(tk.INSERT, saved)   # до подсветки: строка под курсором — исходником
                except tk.TclError:
                    saved = None
            self.apply_markdown_highlighting(force=True)
            if saved:
                self.after_idle(lambda: self.editor.see(tk.INSERT))
            self.highlight_search_matches()
            self._update_status_bar()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{e}")

    def close_current_note(self):
        if self.current_note_path:
            self.save_current_note()
            self._cursor_mem[str(self.current_note_path)] = self.editor.index(tk.INSERT)
            self.current_note_path = None
            self._clear_all_rendered_tables()
            self.editor.delete("1.0", tk.END)
            self._undo_reset()
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
`Создано: {date_str} {time_str}`
Задачи
[ ] 
Заметки
Журнал дня
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
        """Прокрутка по виджету ПОД указателем (редактор, дерево, ячейки таблицы).

        Tk 8.6 на Windows доставляет колесо виджету с фокусом, а ячейки таблицы — это отдельные
        Label внутри Text: поэтому привязка к самим виджетам ненадёжна. Один bind_all + подъём
        по цепочке master до editor/tree работает над любой частью интерфейса.
        """
        try:
            w = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            w = None
        while w is not None and w is not self.editor and w is not self.tree:
            w = w.master
        if w is None:
            return "break" if event.widget in (self.editor, self.tree) else None
        w.yview_scroll(int(-3 * (event.delta / 120)), "units")
        return "break"  # иначе штатный обработчик класса прокрутит второй раз


# ==============================================================================
# ТОЧКА ВХОДА
# ==============================================================================
if __name__ == "__main__":
    app = QuickObsidianNotesApp()
    app.mainloop()
