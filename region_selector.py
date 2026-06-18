from PyQt6.QtWidgets import QWidget, QApplication, QRubberBand, QLabel
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QCursor


class RegionSelector(QWidget):
    region_selected = pyqtSignal(QRect)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        # 全モニター範囲をカバー
        virtual_geom = QRect()
        for screen in QApplication.screens():
            virtual_geom = virtual_geom.united(screen.geometry())
        self.setGeometry(virtual_geom)

        self._origin_local = QPoint()   # ラバーバンド描画用（widget相対）
        self._origin_global = QPoint()  # mss用（仮想デスクトップ絶対座標）
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._selecting = False

        self._hint = QLabel("ドラッグして監視範囲を選択 | Esc でキャンセル", self)
        self._hint.setStyleSheet(
            "color: white; background: rgba(0,0,0,160); "
            "padding: 6px 12px; border-radius: 4px;"
        )
        self._hint.adjustSize()
        self._hint.move(
            (self.width() - self._hint.width()) // 2,
            30,
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin_local = event.pos()
            self._origin_global = event.globalPosition().toPoint()
            self._rubber_band.setGeometry(QRect(self._origin_local, QSize()))
            self._rubber_band.show()
            self._selecting = True
            self._hint.hide()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._rubber_band.setGeometry(
                QRect(self._origin_local, event.pos()).normalized()
            )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            # グローバル座標でrectを作成（サブモニター対応）
            end_global = event.globalPosition().toPoint()
            rect = QRect(self._origin_global, end_global).normalized()
            self._rubber_band.hide()
            self.close()
            if rect.width() > 5 and rect.height() > 5:
                self.region_selected.emit(rect)
            else:
                self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()
