import ctypes
import json
import os
import sys
import time
import urllib.request
from typing import Optional

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from monitor_thread import MonitorThread
from region_selector import RegionSelector

APP_NAME    = "chan Tools for TBH"
VERSION     = "1.0.2"
GITHUB_OWNER = "chanS271999"
GITHUB_REPO  = "chan-tools-tbh"

DEFAULT_RARITIES = [
    ("コズミック",     "#B266FF"),
    ("ディバイン",     "#FFD700"),
    ("セレスティアル", "#00BFFF"),
    ("ビヨンド",       "#FF66FF"),
    ("アルカナ",       "#FF4500"),
    ("イモータル",     "#FF8C00"),
]

# Webhook URL は内部管理（UI 非表示）
_WEBHOOK_URL = "https://discord.com/api/webhooks/1517114446714114139/NWhZ1FcZoCs9mkA3wvjvC7VfMBrjf0IJ3N_n00fjgx77f3ZdMfrUA5J05RfiYENaogNK"

if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(sys.executable)
    _RES_DIR = sys._MEIPASS  # type: ignore[attr-defined]
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
    _RES_DIR = _APP_DIR

SETTINGS_PATH = os.path.join(_APP_DIR, "settings.json")

_BTN = (
    "QPushButton{background:#383838;color:#ddd;border:1px solid #555;"
    "border-radius:4px;padding:4px 10px;}"
    "QPushButton:hover{background:#484848;}"
    "QPushButton:pressed{background:#282828;}"
)
_BTN_ACCENT = (
    "QPushButton{background:#1565C0;color:#fff;border:none;"
    "border-radius:4px;padding:4px 10px;}"
    "QPushButton:hover{background:#1976D2;}"
    "QPushButton:pressed{background:#0D47A1;}"
)


# ---------------------------------------------------------------------------
class UpdateChecker(QThread):
    update_available = pyqtSignal(str, str)  # latest_version, download_url

    def run(self):
        try:
            api = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(api, headers={"User-Agent": "chan-tools-tbh"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            latest = data["tag_name"].lstrip("v")
            if self._newer(latest, VERSION):
                for asset in data.get("assets", []):
                    if asset["name"].endswith(".zip"):
                        self.update_available.emit(latest, asset["browser_download_url"])
                        return
        except Exception:
            pass

    @staticmethod
    def _newer(a: str, b: str) -> bool:
        try:
            return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
        except Exception:
            return False


class DownloadWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)   # zip path or "" on error

    def __init__(self, url: str):
        super().__init__()
        self._url = url

    def run(self):
        import tempfile
        try:
            tmp = tempfile.mktemp(suffix=".zip", prefix="chantools_")
            req = urllib.request.Request(self._url, headers={"User-Agent": "chan-tools-tbh"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress.emit(int(downloaded / total * 100))
            self.finished.emit(tmp)
        except Exception:
            self.finished.emit("")


class UpdateDialog(QDialog):
    def __init__(self, version: str, url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("アップデート")
        self.setFixedSize(420, 160)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._url = url

        vbox = QVBoxLayout(self)
        vbox.addWidget(QLabel(f"新バージョン  v{version}  が利用可能です。今すぐ更新しますか？"))

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setVisible(False)
        vbox.addWidget(self._bar)

        self._status = QLabel("")
        vbox.addWidget(self._status)

        btn_row = QHBoxLayout()
        self._update_btn = QPushButton("今すぐ更新")
        self._update_btn.clicked.connect(self._start_download)
        self._later_btn = QPushButton("後で")
        self._later_btn.clicked.connect(self.close)
        btn_row.addWidget(self._update_btn)
        btn_row.addWidget(self._later_btn)
        vbox.addLayout(btn_row)

    def _start_download(self):
        self._update_btn.setEnabled(False)
        self._later_btn.setEnabled(False)
        self._bar.setVisible(True)
        self._status.setText("ダウンロード中...")

        self._dl_thread = QThread()
        self._dl_worker = DownloadWorker(self._url)
        self._dl_worker.moveToThread(self._dl_thread)
        self._dl_thread.started.connect(self._dl_worker.run)
        self._dl_worker.progress.connect(self._bar.setValue)
        self._dl_worker.finished.connect(self._on_downloaded)
        self._dl_thread.start()

    def _on_downloaded(self, zip_path: str):
        self._dl_thread.quit()
        if not zip_path:
            self._status.setText("ダウンロード失敗。手動で更新してください。")
            self._later_btn.setEnabled(True)
            return
        self._status.setText("適用中...")
        self._apply(zip_path)

    def _apply(self, zip_path: str):
        import subprocess, tempfile, zipfile
        tmp = tempfile.mkdtemp(prefix="chantools_upd_")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)
        os.remove(zip_path)

        if not getattr(sys, "frozen", False):
            self._status.setText("開発環境のためファイル置換をスキップしました")
            self._later_btn.setEnabled(True)
            return

        app_dir  = os.path.dirname(sys.executable)
        exe_name = os.path.basename(sys.executable)
        new_dir  = os.path.join(tmp, "chanToolsTBH")

        bat_path = os.path.join(tempfile.gettempdir(), "chantools_updater.bat")
        exe_full = os.path.join(app_dir, exe_name)
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(
                "@echo off\r\n"
                "timeout /t 2 /nobreak > nul\r\n"
                f'robocopy "{new_dir}" "{app_dir}" /E /XF settings.json /R:3 /W:1 > nul\r\n'
                f'start "" "{exe_full}"\r\n'
                'del "%~0"\r\n'
            )
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )
        QApplication.quit()


# ---------------------------------------------------------------------------
def _load_icon() -> QIcon:
    for name in ("icon.ico", "icon.png"):
        path = os.path.join(_RES_DIR, name)
        if os.path.exists(path):
            return QIcon(path)
    sz = 128
    px = QPixmap(sz, sz); px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#1b5e20")); p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 124, 124, 20, 20); p.end()
    return QIcon(px)


# ---------------------------------------------------------------------------
_winmm = ctypes.windll.winmm

class SoundPlayer:
    _SLOTS = 8
    def __init__(self): self._idx = 0
    def _mci(self, cmd): return _winmm.mciSendStringW(cmd, None, 0, None)
    def _alias(self, i): return f"tbhsnd{i}"
    def play(self, path: str) -> bool:
        path = os.path.abspath(path).replace("/", "\\")
        i = self._idx % self._SLOTS; self._idx += 1
        alias = self._alias(i)
        self._mci(f"close {alias}")
        if self._mci(f'open "{path}" alias {alias}') != 0: return False
        self._mci(f"play {alias}"); return True
    def stop_all(self):
        for i in range(self._SLOTS): self._mci(f"close {self._alias(i)}")


# ---------------------------------------------------------------------------
class ScreenColorPicker(QWidget):
    color_picked = pyqtSignal(QColor)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._captures: list[tuple] = []
        for screen in QApplication.screens():
            self._captures.append((screen.geometry(), screen.grabWindow(0).toImage(), screen.devicePixelRatio()))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor); self.setMouseTracking(True)
        vg = QRect()
        for s in QApplication.screens(): vg = vg.united(s.geometry())
        self.setGeometry(vg)
        self._current_color = QColor(0, 0, 0)
        self._preview = QLabel(self); self._preview.setFixedSize(175, 62)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self._preview.hide()
        hint = QLabel("クリックで色を取得  |  右クリック / Esc でキャンセル", self)
        hint.setStyleSheet("color:white;background:rgba(0,0,0,170);padding:6px 14px;border-radius:4px;")
        hint.adjustSize(); hint.move((self.width() - hint.width()) // 2, 24)

    def paintEvent(self, event): QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 35))

    def mouseMoveEvent(self, event):
        gpos = event.globalPosition().toPoint(); color = self._grab_color(gpos)
        self._current_color = color; hex_code = color.name().upper()
        br = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
        fg = "#000" if br > 128 else "#fff"
        self._preview.setStyleSheet(f"background:{hex_code};color:{fg};border:2px solid white;border-radius:5px;font-weight:bold;font-size:12px;")
        self._preview.setText(f"{hex_code}\nR:{color.red()}  G:{color.green()}  B:{color.blue()}")
        p = event.pos(); px, py = p.x() + 18, p.y() + 18
        if px + 175 > self.width(): px = p.x() - 193
        if py + 62 > self.height(): py = p.y() - 80
        self._preview.move(max(0, px), max(0, py)); self._preview.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            c = self._current_color; self.close(); self.color_picked.emit(c)
        elif event.button() == Qt.MouseButton.RightButton:
            self.close(); self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.close(); self.cancelled.emit()

    def closeEvent(self, event): self._captures.clear(); event.accept()

    def _grab_color(self, gpos: QPoint) -> QColor:
        for geom, img, dpr in self._captures:
            if geom.contains(gpos):
                rx, ry = gpos.x() - geom.x(), gpos.y() - geom.y()
                px = max(0, min(round(rx * dpr), img.width() - 1))
                py = max(0, min(round(ry * dpr), img.height() - 1))
                return QColor(img.pixel(px, py))
        return QColor(128, 128, 128)


# ---------------------------------------------------------------------------
class Rule:
    def __init__(self, color=None, sound_path="", cooldown=140, ocr_enabled=False,
                 tolerance=10, rarity_name="", discord_notify=False):
        self.color = color if color else QColor(255, 0, 0)
        self.sound_path = sound_path
        self.cooldown = cooldown
        self.ocr_enabled = ocr_enabled
        self.tolerance = tolerance
        self.rarity_name = rarity_name
        self.discord_notify = discord_notify


# ---------------------------------------------------------------------------
class ColorPickDialog(QDialog):
    """範囲キャプチャから1色を選ぶダイアログ（クリックで即適用）"""
    color_chosen = pyqtSignal(QColor)

    def __init__(self, colors: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("カラー取得 — 適用する色をクリック")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setFixedSize(360, 140)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("検出された色から適用するものをクリックしてください:"))
        grid = QHBoxLayout()
        for color in colors[:8]:
            btn = QPushButton(); btn.setFixedSize(56, 44)
            hex_c = color.name().upper()
            br = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
            fg = "#000" if br > 128 else "#fff"
            btn.setStyleSheet(f"QPushButton{{background:{hex_c};color:{fg};border:1px solid #666;border-radius:4px;font:7pt Consolas;}}")
            btn.setText(hex_c)
            btn.clicked.connect(lambda _, c=color: (self.color_chosen.emit(c), self.close()))
            grid.addWidget(btn)
        grid.addStretch()
        layout.addLayout(grid)
        cancel_row = QHBoxLayout(); cancel_row.addStretch()
        cancel_btn = QPushButton("キャンセル"); cancel_btn.clicked.connect(self.close)
        cancel_row.addWidget(cancel_btn); layout.addLayout(cancel_row)


# ---------------------------------------------------------------------------
class RuleDialog(QDialog):
    rule_accepted = pyqtSignal(object)

    def __init__(self, parent=None, rule: Optional[Rule] = None):
        super().__init__(parent)
        self.setWindowTitle("ルール設定")
        self.setFixedSize(520, 280)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        r = rule
        self._color       = r.color if r else QColor(255, 0, 0)
        self._sound_path  = r.sound_path if r else ""
        self._cooldown    = r.cooldown if r else 140
        self._ocr_enabled = r.ocr_enabled if r else False
        self._tolerance   = r.tolerance if r else 10
        self._rarity_name = r.rarity_name if r else ""
        self._discord_notify = r.discord_notify if r else False
        self._picker: Optional[ScreenColorPicker] = None
        self._player = SoundPlayer()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self); layout.setSpacing(10)

        row0 = QHBoxLayout(); row0.addWidget(QLabel("レアリティ名:"))
        self._rarity_edit = QLineEdit(self._rarity_name)
        self._rarity_edit.setPlaceholderText("例: コズミック、ディバイン …")
        row0.addWidget(self._rarity_edit); layout.addLayout(row0)

        row1 = QHBoxLayout(); row1.addWidget(QLabel("検知色:"))
        self._color_btn = QPushButton(); self._color_btn.setFixedSize(48, 28)
        self._color_btn.clicked.connect(self._pick_color)
        self._color_code = QLineEdit(self._color.name().upper()); self._color_code.setFixedWidth(90)
        self._color_code.setPlaceholderText("#RRGGBB"); self._color_code.editingFinished.connect(self._apply_hex_input)
        self._eyedrop_btn = QPushButton("🔍 スポイト"); self._eyedrop_btn.setFixedWidth(90)
        self._eyedrop_btn.clicked.connect(self._pick_from_screen)
        self._update_color_btn()
        row1.addWidget(self._color_btn); row1.addWidget(self._color_code); row1.addWidget(self._eyedrop_btn); row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout(); row2.addWidget(QLabel("サウンド:"))
        self._sound_edit = QLineEdit(self._sound_path)
        self._sound_edit.setPlaceholderText("MP3 / WAV / OGG ファイルを選択...")
        browse_btn = QPushButton("参照"); browse_btn.setFixedWidth(50); browse_btn.clicked.connect(self._browse_sound)
        test_btn = QPushButton("▶ テスト"); test_btn.setFixedWidth(70); test_btn.clicked.connect(self._test_sound)
        row2.addWidget(self._sound_edit); row2.addWidget(browse_btn); row2.addWidget(test_btn)
        layout.addLayout(row2)

        row3 = QHBoxLayout(); row3.addWidget(QLabel("クールダウン:"))
        self._cooldown_spin = QSpinBox()
        self._cooldown_spin.setRange(1, 600); self._cooldown_spin.setValue(self._cooldown); self._cooldown_spin.setSuffix(" 秒")
        row3.addWidget(self._cooldown_spin); row3.addSpacing(20); row3.addWidget(QLabel("色許容範囲:"))
        self._tolerance_spin = QSpinBox()
        self._tolerance_spin.setRange(0, 60); self._tolerance_spin.setValue(self._tolerance); self._tolerance_spin.setSuffix(" (±)")
        self._tolerance_spin.setToolTip("アンチエイリアス対策: 10〜20 推奨")
        row3.addWidget(self._tolerance_spin); row3.addStretch(); layout.addLayout(row3)

        row4 = QHBoxLayout()
        self._discord_check = QCheckBox("Discord通知"); self._discord_check.setChecked(self._discord_notify)
        self._ocr_check = QCheckBox("テキスト変化時のみ通知（OCR）"); self._ocr_check.setChecked(self._ocr_enabled)
        row4.addWidget(self._discord_check); row4.addSpacing(20); row4.addWidget(self._ocr_check); row4.addStretch()
        layout.addLayout(row4)

        row5 = QHBoxLayout(); row5.addStretch()
        ok_btn = QPushButton("OK"); ok_btn.setDefault(True); ok_btn.setFixedWidth(80); ok_btn.clicked.connect(self._validate_and_accept)
        cancel_btn = QPushButton("キャンセル"); cancel_btn.setFixedWidth(80); cancel_btn.clicked.connect(self.close)
        row5.addWidget(ok_btn); row5.addWidget(cancel_btn); layout.addLayout(row5)

    def _pick_color(self):
        color = QColorDialog.getColor(self._color, self, "検知色を選択")
        if color.isValid(): self._apply_color(color)

    def _apply_hex_input(self):
        text = self._color_code.text().strip()
        if not text.startswith("#"): text = "#" + text
        color = QColor(text)
        if color.isValid(): self._apply_color(color)

    def _apply_color(self, color: QColor):
        self._color = color; self._color_code.setText(color.name().upper()); self._update_color_btn()

    def _update_color_btn(self):
        c = self._color.name()
        br = self._color.red() * 0.299 + self._color.green() * 0.587 + self._color.blue() * 0.114
        fg = "#000000" if br > 128 else "#ffffff"
        self._color_btn.setStyleSheet(f"QPushButton{{background-color:{c};color:{fg};border:1px solid #888;border-radius:3px;}}")

    def _pick_from_screen(self):
        self.hide(); QTimer.singleShot(200, self._show_color_picker)

    def _show_color_picker(self):
        self._picker = ScreenColorPicker()
        self._picker.color_picked.connect(self._on_screen_color_picked)
        self._picker.cancelled.connect(self._on_picker_cancelled)
        self._picker.show(); self._picker.activateWindow(); self._picker.raise_()

    def _on_screen_color_picked(self, color: QColor):
        self._picker = None; self._apply_color(color); self.show(); self.activateWindow()

    def _on_picker_cancelled(self):
        self._picker = None; self.show(); self.activateWindow()

    def _browse_sound(self):
        path, _ = QFileDialog.getOpenFileName(self, "サウンドファイルを選択", "", "Audio Files (*.mp3 *.wav *.ogg)")
        if path: self._sound_edit.setText(path)

    def _test_sound(self):
        path = self._sound_edit.text().strip()
        if not path: QMessageBox.warning(self, "未選択", "サウンドファイルを先に選択してください。"); return
        if not os.path.isfile(path): QMessageBox.warning(self, "エラー", f"ファイルが見つかりません:\n{path}"); return
        if not self._player.play(path): QMessageBox.warning(self, "再生エラー", "ファイルを開けませんでした。")

    def _validate_and_accept(self):
        sound_path = self._sound_edit.text().strip()
        if not sound_path: QMessageBox.warning(self, "入力エラー", "サウンドファイルを選択してください。"); return
        if not os.path.isfile(sound_path): QMessageBox.warning(self, "ファイルエラー", f"ファイルが見つかりません:\n{sound_path}"); return
        self.rule_accepted.emit(self.get_rule()); self.close()

    def get_rule(self) -> Rule:
        return Rule(
            color=self._color, sound_path=self._sound_edit.text().strip(),
            cooldown=self._cooldown_spin.value(), ocr_enabled=self._ocr_check.isChecked(),
            tolerance=self._tolerance_spin.value(), rarity_name=self._rarity_edit.text().strip(),
            discord_notify=self._discord_check.isChecked(),
        )


# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(800, 680)
        self.rules: list[Rule] = []
        self.region: Optional[QRect] = None
        self._monitor_thread: Optional[MonitorThread] = None
        self._player = SoundPlayer()
        self._color_pick_target_row: int = -1
        self._build_ui()
        self._load_settings()
        self._append_log(f"chan Tools for TBH v{VERSION} 起動完了")
        QTimer.singleShot(3000, self._check_update)
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._check_update)
        self._update_timer.start(10 * 60 * 1000)  # 10分ごと

    def _check_update(self):
        self._update_checker = UpdateChecker()
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.start()

    def _on_update_available(self, version: str, url: str):
        self._append_log(f"新バージョン v{version} が利用可能です")
        dlg = UpdateDialog(version, url, self)
        dlg.show()

    # ── UI 構築 ─────────────────────────────────────────────────────────
    def _build_ui(self):
        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        monitor_widget = QWidget(); tabs.addTab(monitor_widget, "監視")
        self._build_monitor_tab(monitor_widget)
        settings_widget = QWidget(); tabs.addTab(settings_widget, "設定")
        self._build_settings_tab(settings_widget)
        self.statusBar().hide()

    def _build_monitor_tab(self, parent: QWidget):
        vbox = QVBoxLayout(parent); vbox.setContentsMargins(12, 12, 12, 8); vbox.setSpacing(8)

        # 監視範囲
        region_frame = QFrame()
        region_frame.setFrameShape(QFrame.Shape.StyledPanel)
        region_frame.setStyleSheet("QFrame{border:1px solid #3a3a3a;border-radius:5px;padding:6px;background:#2c2c2c;}")
        rh = QHBoxLayout(region_frame)
        lbl = QLabel("監視範囲:"); lbl.setStyleSheet("color:#bbb;background:transparent;font-weight:bold;"); rh.addWidget(lbl)
        self._region_label = QLabel("未設定  —  「範囲を選択」でドラッグ指定してください")
        self._region_label.setStyleSheet("color:#888;background:transparent;")
        rh.addWidget(self._region_label, 1)
        self._select_btn = QPushButton("📐 範囲を選択"); self._select_btn.setFixedWidth(120)
        self._select_btn.setStyleSheet(_BTN)
        self._select_btn.clicked.connect(self._start_region_select); rh.addWidget(self._select_btn)
        vbox.addWidget(region_frame)

        # ルールヘッダー
        rule_header = QHBoxLayout()
        rule_lbl = QLabel("検知ルール:"); rule_lbl.setStyleSheet("color:#bbb;font-weight:bold;")
        rule_header.addWidget(rule_lbl); rule_header.addStretch()
        add_btn = QPushButton("＋ ルール追加"); add_btn.setStyleSheet(_BTN_ACCENT)
        add_btn.clicked.connect(self._add_rule)
        rule_header.addWidget(add_btn); vbox.addLayout(rule_header)

        # テーブル（8列）
        # 色 | レアリティ | カラーコード | サウンドファイル | クールダウン | Discord | カラー取得 | 削除
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(["色", "レアリティ", "カラーコード", "サウンドファイル", "クールダウン", "Discord", "カラー取得", ""])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0,40),(1,100),(2,90),(4,76),(5,60),(6,76),(7,46)]:
            self._table.setColumnWidth(col, w)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setMouseTracking(True)
        self._table.setStyleSheet(
            "QTableWidget{background:#1e1e1e;gridline-color:#2e2e2e;color:#ddd;}"
            "QTableWidget::item{padding:2px;}"
            "QTableWidget::item:hover{background:#2a3a50;}"
            "QTableWidget::item:selected{background:#1a4a7a;color:#fff;}"
            "QHeaderView::section{background:#252525;color:#aaa;border:none;padding:4px;border-bottom:1px solid #3a3a3a;}"
        )
        self._table.doubleClicked.connect(lambda idx: self._edit_rule(idx.row()))
        vbox.addWidget(self._table)

        # コントロール行
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("検知間隔:"))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(100, 10000); self._interval_spin.setValue(500); self._interval_spin.setSuffix(" ms")
        self._interval_spin.setToolTip("検知間隔=何msおきに画面をスキャン\nクールダウン=鳴らした後の待機時間")
        ctrl.addWidget(self._interval_spin); ctrl.addStretch()
        self._check_btn = QPushButton("今すぐ検証"); self._check_btn.setFixedSize(100, 34)
        self._check_btn.setStyleSheet(_BTN)
        self._check_btn.setToolTip("現在の範囲をキャプチャし各ルールの色を検証")
        self._check_btn.clicked.connect(self._check_now); ctrl.addWidget(self._check_btn)
        self._toggle_btn = QPushButton("監視開始"); self._toggle_btn.setFixedSize(110, 36)
        self._toggle_btn.clicked.connect(self._toggle_monitoring); self._set_toggle_style(False)
        ctrl.addWidget(self._toggle_btn); vbox.addLayout(ctrl)

        # ログ
        log_header = QHBoxLayout()
        log_lbl = QLabel("ログ:"); log_lbl.setStyleSheet("color:#bbb;font-weight:bold;")
        log_header.addWidget(log_lbl); log_header.addStretch()
        clear_btn = QPushButton("クリア"); clear_btn.setFixedWidth(64); clear_btn.setStyleSheet(_BTN)
        clear_btn.clicked.connect(lambda: self._log_widget.clear()); log_header.addWidget(clear_btn)
        vbox.addLayout(log_header)
        self._log_widget = QPlainTextEdit(); self._log_widget.setReadOnly(True)
        self._log_widget.setMaximumBlockCount(300); self._log_widget.setFixedHeight(110)
        font = QFont("Consolas", 9)
        if not font.exactMatch(): font = QFont("Courier New", 9)
        self._log_widget.setFont(font)
        self._log_widget.setStyleSheet("QPlainTextEdit{background:#1a1a1a;color:#cccccc;border:1px solid #444;border-radius:3px;}")
        vbox.addWidget(self._log_widget)

    def _build_settings_tab(self, parent: QWidget):
        vbox = QVBoxLayout(parent); vbox.setContentsMargins(16, 16, 16, 16); vbox.setSpacing(16)

        discord_group = QGroupBox("Discord 通知設定")
        dl = QVBoxLayout(discord_group); dl.setSpacing(12)

        id_row = QHBoxLayout(); id_row.addWidget(QLabel("Discord ID:"))
        self._discord_id_edit = QLineEdit()
        self._discord_id_edit.setPlaceholderText("例: 123456789012345678  （18桁の数字）")
        self._discord_id_edit.setToolTip("Discordのユーザーメニュー「IDをコピー」で取得できます")
        id_row.addWidget(self._discord_id_edit); dl.addLayout(id_row)
        vbox.addWidget(discord_group)

        vbox.addStretch()
        save_row = QHBoxLayout(); save_row.addStretch()
        save_btn = QPushButton("設定を保存"); save_btn.setFixedWidth(130); save_btn.setStyleSheet(_BTN_ACCENT)
        save_btn.clicked.connect(self._save_with_dialog)
        save_row.addWidget(save_btn); vbox.addLayout(save_row)

    def _save_with_dialog(self):
        self._save_settings()
        self._append_log("設定を保存しました")
        msg = QMessageBox(self)
        msg.setWindowTitle("保存完了")
        msg.setText("設定を保存しました。")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()

    # ── ログ ─────────────────────────────────────────────────────────────
    def _append_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self._log_widget.appendPlainText(f"[{ts}] {msg}")
        sb = self._log_widget.verticalScrollBar(); sb.setValue(sb.maximum())

    # ── 範囲選択 ─────────────────────────────────────────────────────────
    def _start_region_select(self):
        self.showMinimized()
        QTimer.singleShot(300, self._show_selector)

    def _show_selector(self):
        self._sel = RegionSelector()
        self._sel.region_selected.connect(self._on_region_selected)
        self._sel.cancelled.connect(self._on_selection_cancelled)
        self._sel.show(); self._sel.activateWindow(); self._sel.raise_()

    def _on_region_selected(self, rect: QRect):
        self._sel = None
        self.region = rect
        self._region_label.setText(f"({rect.x()}, {rect.y()}) ～ ({rect.right()}, {rect.bottom()})   [{rect.width()} × {rect.height()} px]")
        self._region_label.setStyleSheet("color:#fff;background:transparent;")
        self.showNormal(); self.activateWindow()
        self._append_log(f"監視範囲を設定: {rect.width()}×{rect.height()}px")

    def _on_selection_cancelled(self):
        self._sel = None
        self.showNormal(); self.activateWindow()

    # ── ルール管理 ────────────────────────────────────────────────────────
    def _add_rule(self):
        dlg = RuleDialog(self); dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.rule_accepted.connect(lambda rule: (self.rules.append(rule), self._refresh_table()))
        dlg.show(); dlg.activateWindow()

    def _edit_rule(self, row: int):
        if not (0 <= row < len(self.rules)): return
        dlg = RuleDialog(self, self.rules[row]); dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        def _apply(rule, r=row):
            if 0 <= r < len(self.rules): self.rules[r] = rule; self._refresh_table()
        dlg.rule_accepted.connect(_apply); dlg.show(); dlg.activateWindow()

    @staticmethod
    def _style_discord_btn(btn: QPushButton, on: bool):
        if on:
            btn.setStyleSheet("QPushButton{background:#43a047;color:#fff;border:none;border-radius:3px;font-size:11px;}QPushButton:hover{background:#388e3c;}")
        else:
            btn.setStyleSheet("QPushButton{background:#444;color:#888;border:none;border-radius:3px;font-size:11px;}QPushButton:hover{background:#555;}")

    def _toggle_discord(self, row: int):
        if not (0 <= row < len(self.rules)): return
        self.rules[row].discord_notify = not self.rules[row].discord_notify
        btn = self._table.cellWidget(row, 5)
        if btn:
            on = self.rules[row].discord_notify
            btn.setText("ON" if on else "OFF")
            self._style_discord_btn(btn, on)

    def _delete_rule(self, row: int):
        if not (0 <= row < len(self.rules)): return
        name = self.rules[row].rarity_name or self.rules[row].color.name().upper()
        if QMessageBox.question(self, "削除確認", f"ルール {row+1}（{name}）を削除しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            del self.rules[row]; self._refresh_table()

    def _refresh_table(self):
        self._table.setRowCount(0)
        for i, rule in enumerate(self.rules):
            self._table.insertRow(i); self._table.setRowHeight(i, 32)
            swatch = QTableWidgetItem(); swatch.setBackground(rule.color); swatch.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._table.setItem(i, 0, swatch)
            self._table.setItem(i, 1, QTableWidgetItem(rule.rarity_name or "—"))
            self._table.setItem(i, 2, QTableWidgetItem(rule.color.name().upper()))
            fname = os.path.basename(rule.sound_path) if rule.sound_path else "（未設定）"
            self._table.setItem(i, 3, QTableWidgetItem(fname))
            self._table.setItem(i, 4, QTableWidgetItem(f"{rule.cooldown}秒"))
            dc_btn = QPushButton("ON" if rule.discord_notify else "OFF"); dc_btn.setFixedHeight(26)
            self._style_discord_btn(dc_btn, rule.discord_notify)
            dc_btn.clicked.connect(lambda _, r=i: self._toggle_discord(r))
            self._table.setCellWidget(i, 5, dc_btn)
            pick_btn = QPushButton("📷 取得"); pick_btn.setFixedHeight(26)
            pick_btn.setToolTip("範囲を選択してこのルールの色を取得")
            pick_btn.clicked.connect(lambda _, r=i: self._pick_color_for_rule(r))
            self._table.setCellWidget(i, 6, pick_btn)
            del_btn = QPushButton("削除"); del_btn.setFixedHeight(26)
            del_btn.clicked.connect(lambda _, r=i: self._delete_rule(r))
            self._table.setCellWidget(i, 7, del_btn)

    # ── ルールごとカラー取得 ─────────────────────────────────────────────
    def _pick_color_for_rule(self, row: int):
        self._color_pick_target_row = row
        self._append_log(f"カラー取得: ルール{row+1} — 範囲をドラッグしてください（Escでキャンセル）")
        # ボタンクリック処理が完全に終わってから非表示にする
        QTimer.singleShot(50, self._hide_for_color_pick)

    def _hide_for_color_pick(self):
        self.showMinimized()
        QTimer.singleShot(200, self._show_color_region_selector)

    def _show_color_region_selector(self):
        try:
            self._color_sel = RegionSelector()
            self._color_sel.region_selected.connect(self._on_color_pick_region)
            self._color_sel.cancelled.connect(self._on_color_pick_cancelled)
            self._color_sel.show()
            self._color_sel.activateWindow()
            self._color_sel.raise_()
        except Exception as e:
            self.showNormal(); self.activateWindow()
            self._append_log(f"RegionSelector エラー: {e}")

    def _on_color_pick_cancelled(self):
        self._color_sel = None
        self.showNormal(); self.activateWindow()
        self._append_log("カラー取得: キャンセル")

    def _on_color_pick_region(self, rect: QRect):
        self._color_sel = None
        self.showNormal(); self.activateWindow()
        row = self._color_pick_target_row
        if not (0 <= row < len(self.rules)): return
        try:
            import mss, numpy as np
            monitor = {"left": rect.x(), "top": rect.y(),
                       "width": max(1, rect.width()), "height": max(1, rect.height())}
            with mss.MSS() as sct:
                img_rgb = np.array(sct.grab(monitor))[:, :, [2, 1, 0]].astype(np.int32)

            pixels = img_rgb.reshape(-1, 3)
            r, g, b = pixels[:, 0], pixels[:, 1], pixels[:, 2]
            max_ch = np.maximum(np.maximum(r, g), b)
            min_ch = np.minimum(np.minimum(r, g), b)
            mask = ((max_ch - min_ch) >= 30) & (max_ch >= 20) & (max_ch <= 235)
            colorful = pixels[mask]

            if len(colorful) == 0:
                # カラフルな色がなければ全ピクセルから取得
                colorful = pixels

            quantized = ((colorful // 24) * 24).astype(np.uint8)
            unique, counts = np.unique(quantized, axis=0, return_counts=True)
            sorted_idx = np.argsort(-counts)
            colors = [QColor(int(unique[i][0]), int(unique[i][1]), int(unique[i][2]))
                      for i in sorted_idx[:8]]

            name = self.rules[row].rarity_name or f"ルール{row+1}"
            dlg = ColorPickDialog(colors, self)
            dlg.color_chosen.connect(lambda c, r=row, n=name: self._apply_color_to_rule(r, c, n))
            dlg.exec()
        except Exception as e:
            self._append_log(f"カラー取得エラー: {e}")

    def _apply_color_to_rule(self, row: int, color: QColor, name: str):
        if 0 <= row < len(self.rules):
            self.rules[row].color = color
            self._refresh_table()
            self._append_log(f"カラー更新: {name} → {color.name().upper()}")

    # ── 監視制御 ─────────────────────────────────────────────────────────
    def _toggle_monitoring(self):
        if self._monitor_thread and self._monitor_thread.isRunning():
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self):
        if not self.region:
            QMessageBox.warning(self, "設定不足", "監視範囲を先に選択してください。"); return
        if not self.rules:
            QMessageBox.warning(self, "設定不足", "ルールを1つ以上追加してください。"); return
        thread_rules = [
            ((r.color.red(), r.color.green(), r.color.blue()), r.cooldown, r.ocr_enabled, r.tolerance)
            for r in self.rules
        ]
        self._monitor_thread = MonitorThread(self.region, thread_rules, self._interval_spin.value())
        self._monitor_thread.color_matched.connect(self._on_color_matched)
        self._monitor_thread.error_occurred.connect(lambda msg: self._append_log(f"エラー: {msg}"))
        self._monitor_thread.thread_started.connect(lambda: self._append_log("スレッド起動確認 ── 監視中"))
        self._monitor_thread.start()
        self._set_toggle_style(True)
        self._select_btn.setEnabled(False); self._interval_spin.setEnabled(False)
        self._append_log("監視開始")

    def _stop_monitoring(self):
        if self._monitor_thread:
            self._monitor_thread.stop(); self._monitor_thread.wait(3000); self._monitor_thread = None
        self._set_toggle_style(False)
        self._select_btn.setEnabled(True); self._interval_spin.setEnabled(True)
        self._append_log("監視停止")

    def _on_color_matched(self, rule_index: int):
        if rule_index >= len(self.rules): return
        rule = self.rules[rule_index]
        ok = self._player.play(rule.sound_path) if rule.sound_path else False
        ts = time.strftime("%H:%M:%S")
        name = rule.rarity_name or rule.color.name().upper()
        self._append_log(f"検知: {name}  →  {os.path.basename(rule.sound_path or '')}{'（再生失敗）' if not ok else ''}")
        if rule.discord_notify:
            self._send_discord(name, ts)

    def _set_toggle_style(self, running: bool):
        if running:
            self._toggle_btn.setText("監視停止")
            self._toggle_btn.setStyleSheet("QPushButton{background:#e53935;color:white;font-weight:bold;border-radius:4px;}QPushButton:hover{background:#c62828;}")
        else:
            self._toggle_btn.setText("監視開始")
            self._toggle_btn.setStyleSheet("QPushButton{background:#43a047;color:white;font-weight:bold;border-radius:4px;}QPushButton:hover{background:#2e7d32;}")

    # ── Discord通知 ─────────────────────────────────────────────────────
    def _send_discord(self, rarity_name: str, ts: str):
        discord_id = self._discord_id_edit.text().strip()
        if not _WEBHOOK_URL:
            self._append_log("Discord: Webhook URLが設定されていません"); return
        try:
            mention = f"<@{discord_id}> " if discord_id else ""
            content = f"{mention}`{rarity_name}のアイテムをドロップしました［{ts}］`"
            data = json.dumps({"content": content}).encode("utf-8")
            req = urllib.request.Request(_WEBHOOK_URL, data=data,
                headers={"Content-Type": "application/json",
                         "User-Agent": "DiscordBot (chan-tools, 1.0)"}, method="POST")
            with urllib.request.urlopen(req, timeout=8) as resp:
                code = resp.status
            if code in (200, 204):
                self._append_log(f"Discord通知送信: {rarity_name}")
            else:
                self._append_log(f"Discord通知失敗: HTTP {code}")
        except Exception as e:
            self._append_log(f"Discord通知エラー: {e}")

    def _test_discord(self):
        self._append_log("Discord テスト通知を送信中...")
        self._send_discord("テスト", time.strftime("%H:%M:%S"))

    # ── 検証 ─────────────────────────────────────────────────────────────
    def _check_now(self):
        if not self.region: self._append_log("検証: 監視範囲が未設定です"); return
        if not self.rules: self._append_log("検証: ルールが未設定です"); return
        try:
            import mss, numpy as np
            monitor = {"left": self.region.x(), "top": self.region.y(),
                       "width": max(1, self.region.width()), "height": max(1, self.region.height())}
            with mss.MSS() as sct:
                img_rgb = np.array(sct.grab(monitor))[:, :, [2, 1, 0]]
            h, w = img_rgb.shape[:2]
            self._append_log(f"検証: {w}×{h}px @ ({self.region.x()},{self.region.y()})")
            for i, rule in enumerate(self.rules):
                name = rule.rarity_name or rule.color.name().upper()
                t = np.array([rule.color.red(), rule.color.green(), rule.color.blue()], dtype=np.uint8)
                exact = int(np.sum(np.all(img_rgb == t, axis=2)))
                diff = np.abs(img_rgb.astype(np.int16) - t.astype(np.int16))
                tol_count = int(np.sum(np.all(diff <= rule.tolerance, axis=2)))
                self._append_log(f"  {name}: 完全={exact}px  許容(±{rule.tolerance})={tol_count}px")
        except Exception as e:
            self._append_log(f"検証エラー: {e}")

    # ── 設定保存・読み込み ───────────────────────────────────────────────
    def _save_settings(self):
        data = {
            "interval_ms": self._interval_spin.value(),
            "region": [self.region.x(), self.region.y(), self.region.width(), self.region.height()] if self.region else None,
            "discord_id": self._discord_id_edit.text().strip(),
            "rules": [
                {"color": r.color.name(), "sound_path": r.sound_path, "cooldown": r.cooldown,
                 "ocr_enabled": r.ocr_enabled, "tolerance": r.tolerance,
                 "rarity_name": r.rarity_name, "discord_notify": r.discord_notify}
                for r in self.rules
            ],
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception: pass

    def _load_settings(self):
        if not os.path.exists(SETTINGS_PATH):
            # 初回起動: デフォルトレアリティを表示
            for name, hex_color in DEFAULT_RARITIES:
                self.rules.append(Rule(color=QColor(hex_color), rarity_name=name))
            self._refresh_table()
            return
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._interval_spin.setValue(data.get("interval_ms", 500))
            if data.get("discord_id"): self._discord_id_edit.setText(data["discord_id"])
            r = data.get("region")
            if r:
                self.region = QRect(r[0], r[1], r[2], r[3])
                self._region_label.setText(f"({r[0]}, {r[1]}) ～ ({r[0]+r[2]}, {r[1]+r[3]})   [{r[2]} × {r[3]} px]")
                self._region_label.setStyleSheet("color:#fff;background:transparent;")
            rule_list = data.get("rules", [])
            for rd in rule_list:
                self.rules.append(Rule(
                    color=QColor(rd["color"]), sound_path=rd.get("sound_path", ""),
                    cooldown=rd.get("cooldown", 140), ocr_enabled=rd.get("ocr_enabled", False),
                    tolerance=rd.get("tolerance", 10), rarity_name=rd.get("rarity_name", ""),
                    discord_notify=rd.get("discord_notify", False),
                ))
            # 保存済みルールが空の場合もデフォルトを表示
            if not self.rules:
                for name, hex_color in DEFAULT_RARITIES:
                    self.rules.append(Rule(color=QColor(hex_color), rarity_name=name))
            self._refresh_table()
            self._append_log(f"設定を読み込みました（ルール {len(self.rules)} 件）")
        except Exception as e:
            self._append_log(f"設定読み込みエラー: {e}")

    def closeEvent(self, event):
        self._stop_monitoring(); self._player.stop_all(); self._save_settings(); event.accept()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("chan.tools.tbh.1")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon = _load_icon()
    app.setWindowIcon(icon)
    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())
