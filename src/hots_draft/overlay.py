"""A compact desktop draft helper with quick selection and explained suggestions."""

from __future__ import annotations

import argparse
import html
import json
import logging
import sys
import unicodedata
import zlib
from pathlib import Path

import httpx
from PySide6.QtCore import QEvent, QRect, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPixmap,
    QShortcut,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizeGrip,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from hots_draft._version import VERSION
from hots_draft.draft import DraftState
from hots_draft.portraits import download_portraits
from hots_draft.recommendations import rank_heroes, rank_picked_heroes
from hots_draft.scraper import (
    DEFAULT_DATA_DIR,
    atomic_write,
    encoded,
    ensure_data_ready,
    load_heroes,
)
from hots_draft.talent_icons import download_talent_icons, icon_path
from hots_draft.updater import download_update, launch_update

STYLE = """
QWidget { background: #10151e; color: #dce4ed; font-family: 'Segoe UI'; font-size: 12px; }
QFrame#titleBar, QFrame#compactBar { background: #151d29; }
QLabel { background: transparent; }
QLabel#brand { font-weight: 700; font-size: 14px; color: #eff5fc; }
QLabel#muted, QLabel#status { color: #8696ab; font-size: 11px; }
QLabel#section { color: #e7eef8; font-size: 15px; font-weight: 600; }
QLabel#reason { color: #97a9bf; font-size: 11px; }
QLabel#warning { color: #dfa17f; font-size: 11px; }
QPushButton, QToolButton { background: #1a2533; border: 1px solid #2a384b; border-radius: 7px; padding: 6px 10px; }
QPushButton:hover, QToolButton:hover { background: #26364a; border-color: #5884a4; }
QPushButton:checked { background: #193d50; border-color: #5ebad4; }
QPushButton:disabled { color: #63748a; }
QPushButton#card { background: #17212e; text-align: left; border: 1px solid #263649; }
QPushButton#card:hover { background: #1c3040; border-color: #5ebad4; }
QPushButton#primary { background: #286c85; color: #f5fbff; border: none; font-weight: 600; }
QPushButton[enemy=true]:checked { background: #3e2932; border-color: #d3879e; }
QToolButton#iconButton { background: transparent; border: none; padding: 4px; }
QToolButton#iconButton:hover { background: #29384b; }
QLineEdit, QComboBox { background: #192330; border: 1px solid #2b394b; border-radius: 7px; padding: 8px; }
QLineEdit:focus { border-color: #5ebad4; }
QComboBox::drop-down { border: none; width: 20px; }
QListWidget { background: #131c28; border: none; border-radius: 7px; outline: none; }
QListWidget::item { padding: 6px; border-bottom: 1px solid #202d3d; }
QListWidget::item:selected { background: #204456; }
QListWidget::item:hover { background: #1c2c3b; }
QMenu { background: #1a2533; border: 1px solid #3a4a60; padding: 5px; }
QMenu::item { padding: 7px 22px; }
QMenu::item:selected { background: #28465b; }
QTextBrowser { background: #131c28; border: none; padding: 12px; }
QScrollBar:vertical { width: 6px; background: #131c28; }
QScrollBar::handle:vertical { background: #3b5068; min-height: 24px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

SYMBOLS = {
    "all_roles": '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
    "tank": '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z"/>',
    "healer": '<path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6Z"/>',
    "bruiser": '<path d="m5 4 14 14M4 8l4-4m8 16 4-4M19 4 5 18m15-10-4-4M8 20l-4-4"/>',
    "melee": '<path d="m17 3 4 4-11 11-4-4Zm-13 9 8 8m-5-3-4 4"/>',
    "ranged": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>',
    "support": '<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "close": '<path d="m6 6 12 12M18 6 6 18"/>',
    "collapse": '<path d="M4 8h16M4 16h16m-12-4 4-4 4 4"/>',
    "expand": '<path d="m8 4 4 4 4-4M8 20l4-4 4 4M4 12h16"/>',
    "settings": '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "clear": '<path d="m5 7 5-4h9v18h-9l-5-4Z"/><path d="m12 9 5 6m0-6-5 6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/>',
    "logo": '<path d="m12 3 8 9-8 9-8-9Z"/><path d="m12 7 4 5-4 5-4-5Z"/>',
}


ROLE_ICONS = {
    "Tank": "tank",
    "Bruiser": "bruiser",
    "Healer": "healer",
    "Support": "support",
    "Melee Assassin": "melee",
    "Ranged Assassin": "ranged",
}


def symbol(name: str, color: str = "#a9bdcf") -> QIcon:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{SYMBOLS[name]}</g></svg>'
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    return QIcon(pixmap)


def normalized(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if char.isalnum()
    )


def draft_fit_colors(score: float) -> tuple[str, str]:
    """Blend from a neutral slate toward green or warm red as fit changes."""
    amount = min(abs(score) / (20 if score > 0 else 12), 1)
    target = (28, 91, 72) if score > 0 else (101, 46, 51)
    neutral = (26, 37, 51)
    background = QColor(*(round(a + (b - a) * amount) for a, b in zip(neutral, target)))
    border = "#53b394" if score > 0 else "#cf7f86" if score < 0 else "#43546b"
    return background.name(), border


class HeroListDelegate(QStyledItemDelegate):
    """Keep the role glyph large and separate from the hero portrait and text."""

    def paint(self, painter, option, index):
        text_option = QStyleOptionViewItem(option)
        text_option.rect.adjust(40, 0, 0, 0)
        super().paint(painter, text_option, index)
        role = index.data(Qt.ItemDataRole.UserRole + 1)
        if role in ROLE_ICONS:
            rect = QRect(option.rect.left() + 6, option.rect.center().y() - 14, 28, 28)
            symbol(ROLE_ICONS[role], "#9ce0ef").paint(painter, rect)


class DataLoader(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, data_dir: Path, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir

    def run(self):
        try:
            self.ready.emit(load_heroes(ensure_data_ready(self.data_dir)))
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self.failed.emit(str(error))


class PortraitLoader(QThread):
    ready = Signal(str)

    def __init__(self, directory, hero_ids, parent=None):
        super().__init__(parent)
        self.directory, self.hero_ids = directory, hero_ids

    def run(self):
        try:
            download_portraits(
                self.directory,
                self.hero_ids,
                self.ready.emit,
                self.isInterruptionRequested,
            )
        except (OSError, ValueError, RuntimeError):
            pass  # Optional artwork never blocks drafting; initials remain usable.


class TalentIconLoader(QThread):
    ready = Signal(str)

    def __init__(self, directory, hero_id, hero, parent):
        super().__init__(parent)
        self.directory, self.hero_id, self.hero = directory, hero_id, hero

    def run(self):
        try:
            download_talent_icons(
                self.directory, self.hero, self.isInterruptionRequested
            )
        except (OSError, ValueError, RuntimeError):
            pass
        self.ready.emit(self.hero_id)


class UpdateLoader(QThread):
    ready = Signal(object, str)

    def __init__(self, directory, parent):
        super().__init__(parent)
        self.directory = directory

    def run(self):
        try:
            result = download_update(self.directory, self.isInterruptionRequested)
            if result and not self.isInterruptionRequested():
                self.ready.emit(*result)
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as error:
            logging.getLogger(__name__).debug("Update check failed: %s", error)


class TitleBar(QFrame):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
        super().mousePressEvent(event)


class OverlayWindow(QWidget):
    def __init__(
        self, data_dir: Path = DEFAULT_DATA_DIR, *, portrait_dir: Path | None = None
    ):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.portrait_dir = (
            Path(portrait_dir) if portrait_dir else self.data_dir / "portraits"
        )
        self.heroes, self.maps = {}, {}
        self.draft = DraftState()
        self.active_slot = ("allies", 0)
        self.selected_hero = None
        self.loader = self.portrait_loader = self.talent_loader = self.update_loader = (
            None
        )
        self.talent_icon_dir = self.data_dir / "talent-icons"
        self.talent_pending = []
        self.talent_attempted = set()
        self.closing = self.compact = False
        self.expanded_size = QSize(780, 740)
        self.flow_configured = None
        self.recommendations = []
        self.icon_cache = {}
        self.setWindowTitle("Nexus Draft")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMinimumSize(720, 580)
        self.resize(self.expanded_size)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        self.title_bar = TitleBar()
        self.title_bar.setObjectName("titleBar")
        title = QHBoxLayout(self.title_bar)
        title.setContentsMargins(14, 8, 10, 8)
        logo = QLabel()
        logo.setPixmap(symbol("logo", "#70d2df").pixmap(24, 24))
        title.addWidget(logo)
        brand = QLabel("Nexus Draft")
        brand.setObjectName("brand")
        title.addWidget(brand)
        title.addStretch()
        self.settings = self.icon_button("settings", "Window settings")
        menu = QMenu(self)
        self.pin = menu.addAction("Always on top")
        self.pin.setCheckable(True)
        self.pin.setChecked(True)
        self.pin.toggled.connect(self.set_pinned)
        opacity = menu.addMenu("Opacity")
        for percent in (100, 90, 80, 70):
            opacity.addAction(
                f"{percent}%", lambda p=percent: self.setWindowOpacity(p / 100)
            )
        menu.addSeparator()
        menu.addAction("Reset draft", self.reset_draft)
        menu.addAction("Minimize to taskbar", self.showMinimized)
        self.settings.setMenu(menu)
        self.settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        title.addWidget(self.settings)
        title.addWidget(
            self.icon_button(
                "collapse", "Reduce to floating strip · Ctrl+Space", self.toggle_compact
            )
        )
        title.addWidget(self.icon_button("close", "Close", self.close))
        root.addWidget(self.title_bar)

        self.compact_bar = TitleBar()
        self.compact_bar.setObjectName("compactBar")
        tiny = QHBoxLayout(self.compact_bar)
        tiny.setContentsMargins(8, 5, 5, 5)
        self.compact_portrait = QLabel()
        self.compact_portrait.setFixedSize(32, 32)
        tiny.addWidget(self.compact_portrait)
        self.compact_text = QLabel("Nexus Draft")
        self.compact_text.setObjectName("brand")
        tiny.addWidget(self.compact_text, 1)
        tiny.addWidget(
            self.icon_button("expand", "Expand overlay", self.toggle_compact)
        )
        tiny.addWidget(self.icon_button("close", "Close", self.close))
        root.addWidget(self.compact_bar)
        self.compact_bar.hide()

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(16, 12, 16, 10)
        body.setSpacing(10)
        self.setup_panel = QWidget()
        setup = QVBoxLayout(self.setup_panel)
        setup.setContentsMargins(0, 0, 0, 0)
        self.setup_panel.setMaximumHeight(270)
        intro = QLabel("Set up your draft")
        intro.setObjectName("section")
        setup.addWidget(intro)
        setup.addWidget(
            QLabel("Choose the battleground, then tell us who picks first.")
        )
        setup.addWidget(QLabel("1 · BATTLEGROUND"))
        self.map_combo = QComboBox()
        self.map_combo.addItem("Choose battleground", None)
        self.map_combo.currentIndexChanged.connect(self.change_map)
        setup.addWidget(self.map_combo)
        setup.addWidget(QLabel("2 · FIRST PICK"))
        self.first_combo = QComboBox()
        self.first_combo.addItem("Who picks first?", None)
        self.first_combo.addItem("Your team", True)
        self.first_combo.addItem("Enemy team", False)
        self.first_combo.currentIndexChanged.connect(self.setup_changed)
        setup.addWidget(self.first_combo)
        self.start_button = QPushButton("Start draft →")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.begin_draft)
        setup.addWidget(self.start_button)
        body.addWidget(self.setup_panel)

        self.flow_panel = QWidget()
        flow = QVBoxLayout(self.flow_panel)
        flow.setContentsMargins(0, 0, 0, 0)
        flow.setSpacing(8)
        self.flow_context = QLabel()
        self.flow_context.setObjectName("muted")
        flow.addWidget(self.flow_context)
        self.progress = QProgressBar()
        self.progress.setRange(0, 16)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setStyleSheet(
            "QProgressBar { border: none; background: #263445; } QProgressBar::chunk { background: #70d2df; }"
        )
        flow.addWidget(self.progress)
        current = QHBoxLayout()
        self.target = QLabel()
        self.target.setObjectName("section")
        current.addWidget(self.target, 1)
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo_action)
        current.addWidget(self.undo_button)
        self.skip_button = QPushButton("Skip ban")
        self.skip_button.clicked.connect(self.skip_ban)
        current.addWidget(self.skip_button)
        flow.addLayout(current)
        self.next_action = QLabel()
        self.next_action.setObjectName("muted")
        flow.addWidget(self.next_action)
        self.slot_buttons = {}
        for group, label in (("allies", "YOU"), ("enemies", "ENEMY")):
            row = QHBoxLayout()
            team = QLabel(label)
            team.setObjectName("muted")
            team.setFixedWidth(48)
            row.addWidget(team)
            for index in range(5):
                row.addWidget(self.make_slot(group, index), 1)
            row.addSpacing(12)
            for index in range(3):
                row.addWidget(
                    self.make_slot(
                        "ally_bans" if group == "allies" else "enemy_bans", index
                    )
                )
            flow.addLayout(row)
        body.addWidget(self.flow_panel)

        self.finder_panel = QWidget()
        finder = QHBoxLayout(self.finder_panel)
        finder.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a hero…  type, then Enter")
        self.search.addAction(
            symbol("search"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_list)
        self.search.returnPressed.connect(self.assign_selected)
        self.search.installEventFilter(self)
        finder.addWidget(self.search, 1)
        self.selected_role = None
        self.role_buttons = {}
        for role, icon in [(None, "all_roles"), *ROLE_ICONS.items()]:
            button = QPushButton()
            button.setIcon(symbol(icon))
            button.setIconSize(QSize(22, 22))
            button.setFixedSize(36, 36)
            button.setStyleSheet("padding: 5px;")
            button.setCheckable(True)
            button.setChecked(role is None)
            button.setToolTip(role or "All roles")
            button.setAccessibleName(role or "All roles")
            button.clicked.connect(lambda checked=False, r=role: self.choose_role(r))
            self.role_buttons[role] = button
            finder.addWidget(button)
        body.addWidget(self.finder_panel)

        self.count = QLabel("Ranked by draft fit")
        self.count.setObjectName("muted")
        body.addWidget(self.count)
        self.hero_list = QListWidget()
        self.hero_list.setIconSize(QSize(42, 42))
        self.hero_list.setItemDelegate(HeroListDelegate(self.hero_list))
        self.hero_list.currentItemChanged.connect(self.select_hero)
        self.hero_list.itemDoubleClicked.connect(lambda _: self.assign_selected())
        self.hero_list.installEventFilter(self)
        self.hero_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hero_list.customContextMenuRequested.connect(self.list_build_popup)
        body.addWidget(self.hero_list, 1)
        self.build_panel = self.make_build_panel()
        body.addWidget(self.build_panel)
        self.build_panel.hide()

        self.selection = QWidget()
        selected = QHBoxLayout(self.selection)
        selected.setContentsMargins(0, 0, 0, 0)
        self.selection_name = QLabel()
        self.selection_name.setObjectName("section")
        selected.addWidget(self.selection_name, 1)
        self.why_button = QPushButton("Why this match?")
        self.why_button.clicked.connect(self.explain_selected)
        selected.addWidget(self.why_button)
        self.details_button = self.icon_button(
            "info", "Hero details", self.show_details
        )
        selected.addWidget(self.details_button)
        self.assign_button = QPushButton("Pick")
        self.assign_button.setObjectName("primary")
        self.assign_button.clicked.connect(self.assign_selected)
        selected.addWidget(self.assign_button)
        body.addWidget(self.selection)
        footer = QHBoxLayout()
        self.status = QLabel("Preparing hero data…")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.retry = QPushButton("Retry")
        self.retry.clicked.connect(self.start_loading)
        self.retry.hide()
        footer.addWidget(self.retry)
        footer.addWidget(QSizeGrip(self))
        body.addLayout(footer)
        root.addWidget(self.body)
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self.focus_search)
        self.collapse_shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        self.collapse_shortcut.activated.connect(self.toggle_compact)
        self.update_slots()

    def icon_button(self, name, tooltip, callback=None):
        button = QToolButton()
        button.setObjectName("iconButton")
        button.setIcon(symbol(name))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(28, 28)
        if callback:
            button.clicked.connect(callback)
        return button

    def portrait(self, id_, size=40, ban=False):
        key = (id_, size, ban)
        if key in self.icon_cache:
            return self.icon_cache[key]
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(0, 0, size, size, 6, 6)
        painter.setClipPath(clip)
        source = QPixmap(str(self.portrait_dir / f"{id_}.jpg")) if id_ else QPixmap()
        if not source.isNull():
            painter.drawPixmap(
                0,
                0,
                source.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )
        else:
            color = QColor.fromHsv(zlib.crc32((id_ or "empty").encode()) % 360, 90, 85)
            painter.fillPath(clip, color if id_ else QColor("#202d3d"))
            name = self.heroes.get(id_, {}).get("name", "")
            initials = "".join(word[0] for word in name.split()[:2]) or (
                "×" if ban else "+"
            )
            painter.setPen(QColor("#bfd1df"))
            painter.setFont(QFont("Segoe UI", max(10, size // 4), QFont.Weight.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, initials)
        if ban and id_:
            painter.setPen(QColor("#f498ab"))
            painter.drawLine(4, size - 4, size - 4, 4)
        painter.end()
        self.icon_cache[key] = QIcon(pixmap)
        self.icon_cache[key].addPixmap(pixmap, QIcon.Mode.Disabled)
        return self.icon_cache[key]

    def make_slot(self, group, index):
        button = QPushButton()
        button.setCheckable(True)
        button.setProperty("enemy", group in ("enemies", "enemy_bans"))
        button.setIconSize(QSize(66, 34) if "bans" not in group else QSize(26, 26))
        button.setFixedHeight(46)
        if "bans" in group:
            button.setFixedWidth(38)
        else:
            button.setMinimumWidth(76)
        button.setStyleSheet("padding: 4px;")
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda pos, g=group, i=index: self.show_build_popup(self.draft.slots[g][i])
        )
        button.clicked.connect(
            lambda checked=False, g=group, i=index: self.select_picked(g, i)
        )
        self.slot_buttons[group, index] = button
        return button

    def pick_slot_icon(self, hero_id):
        role = self.heroes.get(hero_id, {}).get("role")
        pixmap = QPixmap(66, 34)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.portrait(hero_id, 34).paint(painter, QRect(0, 0, 34, 34))
        if role in ROLE_ICONS:
            symbol(ROLE_ICONS[role], "#9ce0ef").paint(painter, QRect(38, 3, 28, 28))
        painter.end()
        icon = QIcon(pixmap)
        icon.addPixmap(pixmap, QIcon.Mode.Disabled)
        return icon

    def slot_label(self, group, index):
        team = "Your" if group in ("allies", "ally_bans") else "Enemy"
        return f"{team} {'ban' if 'bans' in group else 'pick'} {index + 1}"

    def update_slots(self):
        action = self.draft.current_action
        if self.flow_configured != self.draft.configured and not self.compact:
            self.flow_configured = self.draft.configured
            if self.draft.configured:
                self.setMinimumSize(720, 580)
                self.resize(780, 740)
            else:
                self.setMinimumSize(620, 340)
                self.resize(680, 400)
        self.active_slot = (action.group, action.index) if action else None
        picked = {
            result.hero_id: result
            for result in rank_picked_heroes(self.heroes, self.draft)
        }
        for (group, index), button in self.slot_buttons.items():
            id_ = self.draft.slots[group][index]
            fit = picked.get(id_) if "bans" not in group else None
            button.setStyleSheet("padding: 4px;")
            if fit:
                background, border = draft_fit_colors(fit.score)
                button.setStyleSheet(
                    f"QPushButton {{ padding: 4px; background: {background}; border: 1px solid {border}; }}"
                    f"QPushButton:hover {{ background: {background}; border: 1px solid #a2cede; }}"
                )
            button.setIcon(
                self.pick_slot_icon(id_)
                if id_ and "bans" not in group
                else self.portrait(id_, 26 if "bans" in group else 34, "bans" in group)
            )
            button.setText(str(index + 1) if not id_ and "bans" not in group else "")
            button.setChecked(self.active_slot == (group, index))
            button.setEnabled(bool(id_))
            button.setToolTip(
                self.slot_label(group, index)
                + (
                    ": "
                    + (
                        self.heroes[id_]["name"]
                        + " · "
                        + (self.heroes[id_]["role"] or "Unknown role")
                    )
                    if id_ in self.heroes
                    else ""
                )
            )
            if fit:
                hint = (
                    "Strong fit"
                    if fit.score >= 5
                    else "Good fit"
                    if fit.score > 0
                    else "Neutral fit"
                    if fit.score == 0
                    else "Difficult matchup"
                )
                evidence = fit.reasons + fit.warnings or ["No specific guide advantage"]
                button.setToolTip(
                    button.toolTip()
                    + f"\nDraft fit: {fit.score:+g} · {hint}\n"
                    + "\n".join(evidence)
                )
        self.setup_panel.setVisible(not self.draft.configured)
        self.flow_panel.setVisible(self.draft.configured)
        self.finder_panel.setVisible(bool(action))
        self.hero_list.setVisible(bool(action) or self.draft.completed)
        self.count.setVisible(bool(action) or self.draft.completed)
        self.build_panel.setVisible(self.draft.completed)
        self.selection.setVisible(bool(action))
        self.progress.setValue(len(self.draft.history))
        self.undo_button.setEnabled(bool(self.draft.history))
        self.skip_button.setVisible(bool(action and action.mode == "ban"))
        if action:
            team = "Your team" if action.side == "allies" else "Enemy team"
            verb = "Ban a hero" if action.mode == "ban" else "Pick a hero"
            self.target.setText(f"{team} · {verb}")
            self.assign_button.setText(
                ("Ban " if action.mode == "ban" else "Lock ")
                + (
                    self.heroes[self.selected_hero]["name"]
                    if self.selected_hero in self.heroes
                    else "hero"
                )
            )
            next_index = len(self.draft.history) + 1
            next_ = self.draft.actions[next_index] if next_index < 16 else None
            self.next_action.setText(
                "Next: " + self.slot_label(next_.group, next_.index)
                if next_
                else "Next: Draft complete"
            )
        else:
            self.target.setText("Draft complete · Your teams are ready")
            self.next_action.setText(
                "Click a picked hero to view their builds. Undo to correct the last action."
            )
        first = "You pick first" if self.draft.first_pick else "Enemy picks first"
        self.flow_context.setText(
            f"{self.maps.get(self.draft.map_id, '')}  ·  {first}  ·  {min(len(self.draft.history) + 1, 16)} / 16"
        )
        self.why_button.setEnabled(bool(self.selected_hero))
        self.assign_button.setEnabled(
            bool(
                action
                and self.selected_hero
                and self.selected_hero not in self.draft.unavailable
            )
        )
        self.setup_changed()

    def set_pinned(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

    def toggle_compact(self):
        self.compact = not self.compact
        if self.compact:
            self.expanded_size = self.size()
            self.title_bar.hide()
            self.body.hide()
            self.compact_bar.show()
            self.setFixedSize(280, 48)
        else:
            self.compact_bar.hide()
            self.title_bar.show()
            self.body.show()
            self.setMaximumSize(16777215, 16777215)
            self.setMinimumSize(
                720, 580
            ) if self.draft.configured else self.setMinimumSize(620, 340)
            self.resize(self.expanded_size)

    def focus_search(self):
        if self.compact:
            self.toggle_compact()
        self.search.setFocus()
        self.search.selectAll()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if (
                watched == self.search
                and event.key() == Qt.Key.Key_Down
                and self.hero_list.count()
            ):
                self.hero_list.setFocus()
                return True
            if watched == self.hero_list and event.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                self.assign_selected()
                return True
            if (
                watched in (self.search, self.hero_list)
                and event.key() == Qt.Key.Key_Escape
            ):
                self.search.clear()
                self.search.setFocus()
                return True
        return super().eventFilter(watched, event)

    def start_loading(self):
        if self.loader and self.loader.isRunning():
            return
        self.retry.hide()
        self.status.setText("Preparing hero data…")
        self.loader = DataLoader(self.data_dir, self)
        self.loader.ready.connect(self.data_loaded)
        self.loader.failed.connect(self.loading_failed)
        self.loader.finished.connect(self.loading_finished)
        self.loader.start()

    def data_loaded(self, heroes):
        self.set_heroes(heroes)
        if not self.closing:
            self.portrait_loader = PortraitLoader(self.portrait_dir, set(heroes), self)
            self.portrait_loader.ready.connect(self.portrait_ready)
            self.portrait_loader.finished.connect(self.loading_finished)
            self.portrait_loader.start()

    def portrait_ready(self, id_):
        self.icon_cache = {
            key: value for key, value in self.icon_cache.items() if key[0] != id_
        }
        self.update_slots()
        for index in range(self.hero_list.count()):
            item = self.hero_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == id_:
                item.setIcon(self.portrait(id_))
        self.refresh_cards()

    def loading_failed(self, message):
        self.status.setText("Could not load data: " + message)
        self.retry.show()

    def loading_finished(self):
        if self.closing and not any(
            worker and worker.isRunning()
            for worker in (
                self.loader,
                self.portrait_loader,
                self.talent_loader,
                self.update_loader,
            )
        ):
            self.close()

    def set_heroes(self, heroes):
        self.heroes = heroes
        self.icon_cache.clear()
        self.maps = {
            ref["id"]: ref["name"]
            for hero in heroes.values()
            for rating in ("stronger", "average", "weaker")
            for ref in hero["maps"][rating]
        }
        self.map_combo.blockSignals(True)
        self.map_combo.clear()
        self.map_combo.addItem("Choose battleground", None)
        for id_, name in sorted(self.maps.items(), key=lambda pair: pair[1]):
            self.map_combo.addItem(name, id_)
        message = "Choose a battleground and who picks first."
        session = self.data_dir / "draft-session.json"
        if session.exists():
            try:
                self.draft = DraftState.from_dict(
                    json.loads(session.read_text(encoding="utf-8")),
                    set(heroes),
                    set(self.maps),
                )
                if self.draft.configured:
                    message = "Saved draft restored · Continue the current action."
                if self.draft.completed:
                    message = "Saved completed draft restored."
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                message = "Saved draft could not be restored"
        self.map_combo.setCurrentIndex(
            max(0, self.map_combo.findData(self.draft.map_id))
        )
        self.map_combo.blockSignals(False)
        self.first_combo.setCurrentIndex(
            self.first_combo.findData(self.draft.first_pick)
        )
        self.refresh_list()
        self.status.setText(message)

    def persist(self):
        try:
            atomic_write(
                self.data_dir / "draft-session.json", encoded(self.draft.to_dict())
            )
        except OSError as error:
            self.status.setText(f"Could not save draft: {error}")

    def change_map(self, _=None):
        if not self.draft.configured:
            self.draft.map_id = self.map_combo.currentData()
            self.setup_changed()
            if self.heroes:
                self.persist()

    def setup_changed(self, _=None):
        self.first_combo.setEnabled(bool(self.map_combo.currentData()))
        self.start_button.setEnabled(
            bool(
                self.heroes
                and self.map_combo.currentData()
                and self.first_combo.currentData() is not None
            )
        )

    def begin_draft(self):
        if (
            not self.heroes
            or not self.map_combo.currentData()
            or self.first_combo.currentData() is None
        ):
            return
        self.draft = DraftState(
            map_id=self.map_combo.currentData(),
            first_pick=self.first_combo.currentData(),
        )
        self.persist()
        self.status.setText(
            "Record each team's action. Enter or double-click locks the selected hero."
        )
        self.refresh_list()
        self.focus_search()

    def undo_action(self):
        self.draft.undo()
        self.persist()
        self.search.clear()
        self.refresh_list()

    def skip_ban(self):
        action = self.draft.current_action
        if action and action.mode == "ban":
            self.draft.commit(None)
            self.persist()
            self.search.clear()
            self.choose_role(None, refresh=False)
            self.refresh_list()

    def choose_role(self, role, *, refresh=True):
        self.selected_role = None if role == self.selected_role else role
        for value, button in self.role_buttons.items():
            button.setChecked(value == self.selected_role)
        if refresh:
            self.refresh_list()

    def refresh_list(self, *_):
        previous = self.selected_hero
        action = self.draft.current_action
        self.recommendations = (
            rank_heroes(
                self.heroes,
                self.draft,
                mode=action.mode,
                side=action.side,
                include_all=True,
            )
            if action
            else rank_picked_heroes(self.heroes, self.draft)
            if self.draft.completed
            else []
        )
        query = "" if self.draft.completed else normalized(self.search.text())
        role = None if self.draft.completed else self.selected_role
        self.hero_list.blockSignals(True)
        self.hero_list.clear()
        for rank, result in enumerate(self.recommendations, 1):
            hero = self.heroes[result.hero_id]
            if (
                query not in normalized(hero["name"])
                and query not in normalized(result.hero_id)
            ) or (role is not None and hero["role"] != role):
                continue
            evidence = (
                " · ".join(result.reasons[:2])
                if result.reasons
                else "No specific guide advantage"
            )
            if result.warnings:
                evidence += " · " + result.warnings[0]
            if self.draft.completed:
                strength = (
                    "Strong fit"
                    if result.score >= 5
                    else "Good fit"
                    if result.score > 0
                    else "Neutral fit"
                    if result.score == 0
                    else "Difficult matchup"
                )
                team = (
                    "You" if result.hero_id in self.draft.slots["allies"] else "Enemy"
                )
                evidence = f"{team} · {strength} ({result.score:+g}) · {evidence}"
            item = QListWidgetItem(
                self.portrait(result.hero_id),
                f"{rank:02d}  {hero['name']}\n{evidence}",
            )
            item.setData(Qt.ItemDataRole.UserRole, result.hero_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, hero["role"])
            item.setToolTip(
                f"{hero['role'] or 'Unknown role'}\nGuide match score: {result.score:+g} \n"
                + "\n".join(result.reasons + result.warnings)
            )
            item.setSizeHint(QSize(0, 64))
            if result.score < 0:
                item.setForeground(QColor("#d6a791"))
            self.hero_list.addItem(item)
            if result.hero_id == previous:
                self.hero_list.setCurrentItem(item)
        self.hero_list.blockSignals(False)
        self.count.setText(
            f"{self.hero_list.count()} matches / {len(self.recommendations)} available · Ranked by draft fit"
        )
        if self.hero_list.currentItem() is None and self.hero_list.count():
            self.hero_list.setCurrentRow(0)
        else:
            self.select_hero(self.hero_list.currentItem())
        self.refresh_cards()
        self.update_slots()

    def refresh_cards(self):
        action = self.draft.current_action
        best = self.recommendations[0] if self.recommendations else None
        if action and best:
            team = "You" if action.side == "allies" else "Enemy"
            name = self.heroes[best.hero_id]["name"]
            self.compact_text.setText(
                self.compact_text.fontMetrics().elidedText(
                    f"{team} {action.mode} · {name}", Qt.TextElideMode.ElideRight, 162
                )
            )
            self.compact_text.setToolTip("\n".join(best.reasons + best.warnings))
            self.compact_portrait.setPixmap(
                self.portrait(best.hero_id, 32).pixmap(32, 32)
            )
        else:
            self.compact_text.setText(
                "Draft complete" if self.draft.completed else "Set up draft"
            )
            self.compact_portrait.setPixmap(symbol("logo", "#70d2df").pixmap(24, 24))

    def select_hero(self, item, _previous=None):
        self.selected_hero = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.update_selection()
        if self.draft.completed and self.selected_hero:
            self.load_builds(self.build_panel, self.selected_hero)

    def update_selection(self):
        self.selection_name.setText(
            self.heroes[self.selected_hero]["name"] if self.selected_hero else ""
        )
        self.details_button.setEnabled(bool(self.selected_hero))
        self.update_slots()

    def assign_selected(self):
        if self.selected_hero and not self.draft.completed:
            self.assign_hero(self.selected_hero)

    def assign_hero(self, id_):
        if id_ not in self.heroes:
            return
        try:
            self.draft.commit(id_)
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.status.setText(
            "Draft complete. Ready to play."
            if self.draft.completed
            else "Locked " + self.heroes[id_]["name"]
        )
        self.persist()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.choose_role(None, refresh=False)
        self.selected_hero = None
        self.refresh_list()
        self.search.setFocus()

    def clear_slot(self):
        self.undo_action()

    def reset_draft(self):
        self.draft = DraftState(map_id=self.draft.map_id)
        self.first_combo.setCurrentIndex(0)
        self.search.clear()
        self.persist()
        self.refresh_list()

    def explain_selected(self):
        result = next(
            (
                result
                for result in self.recommendations
                if result.hero_id == self.selected_hero
            ),
            None,
        )
        if result:
            self.show_reasons(result)

    def show_reasons(self, recommendation):
        hero = self.heroes[recommendation.hero_id]
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Why {hero['name']}?")
        dialog.resize(420, 250)
        layout = QVBoxLayout(dialog)
        heading = QLabel(hero["name"])
        heading.setObjectName("section")
        layout.addWidget(heading)
        for reason in recommendation.reasons or [
            "No specific guide advantage for this draft."
        ]:
            label = QLabel("• " + reason)
            label.setWordWrap(True)
            layout.addWidget(label)
        for warning in recommendation.warnings:
            label = QLabel("• " + warning)
            label.setObjectName("warning")
            label.setWordWrap(True)
            layout.addWidget(label)
        note = QLabel("Based on guide matchups, battleground fit and team roles.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        guide = QPushButton("Hero guide")
        guide.clicked.connect(lambda: self.show_details(hero_id=recommendation.hero_id))
        layout.addWidget(guide)
        done = QPushButton("Done")
        done.clicked.connect(dialog.accept)
        layout.addWidget(done)
        dialog.exec()

    def list_build_popup(self, position):
        item = self.hero_list.itemAt(position)
        if item:
            self.show_build_popup(item.data(Qt.ItemDataRole.UserRole))

    def select_picked(self, group, index):
        if not self.draft.completed:
            self.update_slots()
            return
        hero_id = self.draft.slots[group][index]
        for row in range(self.hero_list.count()):
            item = self.hero_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == hero_id:
                self.hero_list.setCurrentItem(item)
                self.hero_list.scrollToItem(item)
                return

    def make_build_panel(self):
        panel = QWidget()
        panel.setObjectName("buildPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        panel.heading = QLabel()
        panel.heading.setObjectName("section")
        layout.addWidget(panel.heading)
        panel.selector = QComboBox()
        layout.addWidget(panel.selector)
        panel.browser = QTextBrowser()
        panel.browser.setOpenExternalLinks(True)
        panel.browser.setFixedHeight(190)
        layout.addWidget(panel.browser)
        panel.selector.currentIndexChanged.connect(lambda _: self.render_build(panel))
        return panel

    def load_builds(self, panel, hero_id):
        panel.hero_id = hero_id
        hero = self.heroes[hero_id]
        panel.heading.setText(hero["name"] + " · Builds")
        panel.selector.blockSignals(True)
        panel.selector.clear()
        for build in hero["builds"]:
            panel.selector.addItem(build["name"])
        panel.selector.blockSignals(False)
        panel.selector.setVisible(len(hero["builds"]) > 1)
        self.render_build(panel)
        self.request_talent_icons(hero_id)

    def render_build(self, panel):
        hero = self.heroes[panel.hero_id]
        index = panel.selector.currentIndex()
        e = html.escape
        content = "<p>No builds listed in the guide.</p>"
        if index >= 0:
            build = hero["builds"][index]
            content = '<table cellspacing="6" width="95%"><tr>'
            for tier in build["talent_tiers"]:
                talent = next(t for t in tier["talents"] if t["recommended"])
                path = icon_path(self.talent_icon_dir, talent["id"])
                if path.exists():
                    url = e(
                        QUrl.fromLocalFile(str(path.resolve())).toString(), quote=True
                    )
                    visual = f'<img src="{url}" width="40" height="40">'
                else:
                    visual = f'<span style="color:#9ce0ef;font-size:20px">{e(talent["name"][:2].upper())}</span>'
                content += f'<td align="center"><b>{tier["level"]}</b><br>{visual}</td>'
            content += '</tr></table><table cellspacing="5" width="95%">'
            for tier in build["talent_tiers"]:
                talents = ", ".join(
                    t["name"] + (" (alternative)" if not t["recommended"] else "")
                    for t in tier["talents"]
                )
                content += f"<tr><td width='30'><b>{tier['level']}</b></td><td>{e(talents)}</td></tr>"
            content += f"</table><p>{e(build.get('description', ''))}</p>"
        content += f"<p><a href='{e(hero['source']['url'], quote=True)}'>Icy Veins guide ↗</a></p>"
        panel.browser.setHtml(content)

    def request_talent_icons(self, hero_id):
        if hero_id in self.talent_attempted or self.closing:
            return
        self.talent_attempted.add(hero_id)
        self.talent_pending.append(hero_id)
        self.start_next_talent_icons()

    def start_next_talent_icons(self):
        if (
            self.closing
            or not self.talent_pending
            or (self.talent_loader and self.talent_loader.isRunning())
        ):
            return
        hero_id = self.talent_pending.pop(0)
        self.talent_loader = TalentIconLoader(
            self.talent_icon_dir, hero_id, self.heroes[hero_id], self
        )
        self.talent_loader.ready.connect(self.talent_icons_ready)
        self.talent_loader.finished.connect(self.start_next_talent_icons)
        self.talent_loader.finished.connect(self.loading_finished)
        self.talent_loader.start()

    def talent_icons_ready(self, hero_id):
        for panel in self.findChildren(QWidget, "buildPanel"):
            if getattr(panel, "hero_id", None) == hero_id:
                scroll = panel.browser.verticalScrollBar().value()
                self.render_build(panel)
                panel.browser.verticalScrollBar().setValue(scroll)

    def show_build_popup(self, hero_id):
        if hero_id not in self.heroes:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.heroes[hero_id]["name"] + " builds")
        dialog.resize(480, 400)
        layout = QVBoxLayout(dialog)
        panel = self.make_build_panel()
        self.load_builds(panel, hero_id)
        layout.addWidget(panel)
        done = QPushButton("Done")
        done.clicked.connect(dialog.accept)
        layout.addWidget(done)
        dialog.exec()

    def show_details(self, checked=False, *, hero_id=None):
        id_ = hero_id or self.selected_hero
        if not id_:
            return
        hero = self.heroes[id_]
        dialog = QDialog(self)
        dialog.setWindowTitle(hero["name"])
        dialog.resize(560, 530)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        e = html.escape
        content = f"<h2>{e(hero['name'])}</h2><p>{e(hero['overview'])}</p>"
        for label, values in (
            ("Strengths", hero["strengths"]),
            ("Weaknesses", hero["weaknesses"]),
        ):
            content += (
                f"<h3>{label}</h3><ul>"
                + "".join(f"<li>{e(value)}</li>" for value in values)
                + "</ul>"
            )
        for field, label in (
            ("synergies", "Synergizes with"),
            ("counters", "Countered by"),
        ):
            content += f"<h3>{label}</h3><p>{e(', '.join(ref['name'] for ref in hero[field]['heroes']))}</p><p>{e(hero[field]['explanation'])}</p>"
        for build in hero["builds"]:
            content += f"<h3>{e(build['name'])}</h3>"
            for tier in build["talent_tiers"]:
                talents = ", ".join(
                    t["name"] + (" (alternative)" if not t["recommended"] else "")
                    for t in tier["talents"]
                )
                content += f"<p>Level {tier['level']}: {e(talents)}</p>"
        content += f"<p><a href='{e(hero['source']['url'], quote=True)}'>Icy Veins guide ↗</a></p>"
        browser.setHtml(content)
        layout.addWidget(browser)
        done = QPushButton("Done")
        done.clicked.connect(dialog.accept)
        layout.addWidget(done)
        dialog.exec()

    def start_update_check(self):
        self.update_loader = UpdateLoader(self.data_dir.parent / "updates", self)
        self.update_loader.ready.connect(self.install_update)
        self.update_loader.finished.connect(self.loading_finished)
        self.update_loader.start()

    def install_update(self, candidate, version):
        if self.closing:
            return
        try:
            launch_update(
                candidate,
                Path(sys.executable),
                sys.argv[1:],
                self.data_dir.parent / "updates",
            )
        except OSError as error:
            self.status.setText(f"Update could not restart: {error}")
            return
        self.status.setText(f"Updating to {version} · Restarting…")
        self.persist()
        self.close()

    def closeEvent(self, event):
        if self.portrait_loader:
            self.portrait_loader.requestInterruption()
        if self.talent_loader:
            self.talent_loader.requestInterruption()
        if self.update_loader:
            self.update_loader.requestInterruption()
        if any(
            worker and worker.isRunning()
            for worker in (
                self.loader,
                self.portrait_loader,
                self.talent_loader,
                self.update_loader,
            )
        ):
            self.closing = True
            self.hide()
            event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="Heroes of the Storm draft overlay")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--no-update", action="store_true", help="Skip the startup release check"
    )
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Nexus Draft")
    window = OverlayWindow(args.data_dir)
    window.show()
    window.start_loading()
    if getattr(sys, "frozen", False) and sys.platform == "win32" and not args.no_update:
        window.start_update_check()
    raise SystemExit(app.exec())
