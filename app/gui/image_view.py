"""Khung xem ảnh trang PDF: phóng to, thu nhỏ, kéo ảnh, tô sáng ô/dòng."""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView)


def ndarray_to_qimage(img: np.ndarray) -> QImage:
    if img.ndim == 2:
        h, w = img.shape
        return QImage(img.data, w, h, w, QImage.Format_Grayscale8).copy()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()


class ImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix = QGraphicsPixmapItem()
        self._scene.addItem(self._pix)
        self._hl = QGraphicsRectItem()
        self._hl.setPen(QPen(QColor(230, 160, 0), 3))
        self._hl.setBrush(QColor(255, 210, 0, 70))
        self._hl.setZValue(10)
        self._hl.hide()
        self._scene.addItem(self._hl)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(245, 245, 245))

    def set_image(self, qimage: QImage):
        from PySide6.QtGui import QPixmap
        self._pix.setPixmap(QPixmap.fromImage(qimage))
        self._scene.setSceneRect(QRectF(self._pix.pixmap().rect()))
        self.fit()

    def fit(self):
        if not self._pix.pixmap().isNull():
            self.fitInView(self._pix, Qt.KeepAspectRatio)

    def zoom_in(self):
        self.scale(1.25, 1.25)

    def zoom_out(self):
        self.scale(0.8, 0.8)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def highlight(self, rect, ensure_visible=True, center=False):
        if rect is None:
            self._hl.hide()
            return
        self._hl.setRect(QRectF(rect.x0, rect.y0, rect.x1 - rect.x0, rect.y1 - rect.y0))
        self._hl.show()
        if center:
            self.centerOn(self._hl.rect().center())
        elif ensure_visible:
            vp = self.viewport()
            ymargin = max(60, int(vp.height() * 0.28))
            xmargin = max(40, int(vp.width() * 0.10))
            self.ensureVisible(self._hl.rect(), xmargin, ymargin)