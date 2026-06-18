import time
from collections import defaultdict
from typing import Optional

import mss
import numpy as np
from PyQt6.QtCore import QRect, QThread, pyqtSignal


class MonitorThread(QThread):
    color_matched = pyqtSignal(int)   # ルールインデックス
    error_occurred = pyqtSignal(str)
    thread_started = pyqtSignal()     # スレッド起動確認用

    def __init__(self, region: QRect, rules: list[tuple], interval_ms: int):
        super().__init__()
        self.region = region
        # rules: list of ((r, g, b), cooldown_secs, ocr_enabled, tolerance)
        self.rules = rules
        self.interval_ms = interval_ms
        self._running = False
        self._last_triggered: dict[int, float] = defaultdict(float)
        # OCR 変化検知用
        self._last_img: dict[int, Optional[np.ndarray]] = {}
        self._last_text: dict[int, str] = {}

    def run(self):
        self._running = True
        monitor = {
            "left": self.region.x(),
            "top": self.region.y(),
            "width": max(1, self.region.width()),
            "height": max(1, self.region.height()),
        }

        try:
            sct = mss.MSS()
        except Exception as e:
            self.error_occurred.emit(f"mss初期化エラー: {e}")
            return

        self.thread_started.emit()

        with sct:
            while self._running:
                t0 = time.perf_counter()
                try:
                    shot = sct.grab(monitor)
                    img = np.array(shot)           # BGRA (H, W, 4)
                    img_rgb = img[:, :, [2, 1, 0]] # RGB

                    now = time.time()
                    for i, (target_rgb, cooldown, ocr_enabled, tolerance) in enumerate(self.rules):
                        if now - self._last_triggered[i] < cooldown:
                            continue

                        t = np.array(target_rgb, dtype=np.uint8)
                        if tolerance == 0:
                            found = np.any(np.all(img_rgb == t, axis=2))
                        else:
                            diff = np.abs(img_rgb.astype(np.int16) - t.astype(np.int16))
                            found = np.any(np.all(diff <= tolerance, axis=2))
                        if not found:
                            continue  # 色が見つからない

                        # OCR 変化検知
                        if ocr_enabled:
                            if not self._has_text_changed(i, img):
                                continue  # テキスト変化なし→スキップ

                        self._last_triggered[i] = now
                        self.color_matched.emit(i)

                except Exception as e:
                    self.error_occurred.emit(str(e))

                elapsed = time.perf_counter() - t0
                time.sleep(max(0.005, self.interval_ms / 1000.0 - elapsed))

    def _has_text_changed(self, rule_index: int, img_bgra: np.ndarray) -> bool:
        """
        OCR でテキストを読み取り、前回と変化があれば True を返す。
        画像が前回と同一なら OCR をスキップして False を返す。
        """
        from ocr_utils import ocr_text, OCR_AVAILABLE
        if not OCR_AVAILABLE:
            return True  # OCR が使えない場合は常に通知

        prev_img = self._last_img.get(rule_index)
        if prev_img is not None and np.array_equal(img_bgra, prev_img):
            return False  # 画面が変化していないのでテキストも同じ

        text = ocr_text(img_bgra)
        prev_text = self._last_text.get(rule_index)

        # テキストが変化していなければスキップ
        if text == prev_text:
            self._last_img[rule_index] = img_bgra.copy()
            return False

        # 変化あり → 更新
        self._last_img[rule_index] = img_bgra.copy()
        self._last_text[rule_index] = text
        return True

    def stop(self):
        self._running = False
