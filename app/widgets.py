"""Custom animated widgets for the futuristic-minimal UI."""
import math
from collections import deque

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QCheckBox, QGraphicsOpacityEffect, QPushButton, QStyle,
                               QStyledItemDelegate, QWidget)

from . import theme


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


def _anim(parent, ms, on_value, easing=QEasingCurve.OutCubic) -> QVariantAnimation:
    a = QVariantAnimation(parent)
    a.setDuration(ms)
    a.setEasingCurve(easing)
    a.valueChanged.connect(on_value)
    return a


def _glide(anim: QVariantAnimation, current: float, target: float) -> None:
    anim.stop()
    anim.setStartValue(float(current))
    anim.setEndValue(float(target))
    anim.start()


# ---------------------------------------------------------------- fades
def fade_in(w: QWidget, ms: int = 260) -> None:
    """Fade a child widget in. Effect is removed afterwards (effects slow text rendering)."""
    old = getattr(w, "_fade", None)
    if old is not None:
        old.stop()
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", w)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.finished.connect(lambda: w.setGraphicsEffect(None))
    w._fade = a
    a.start()


def fade_window(w: QWidget, ms: int = 380) -> None:
    w.setWindowOpacity(0.0)
    a = QPropertyAnimation(w, b"windowOpacity", w)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)
    w._wfade = a
    a.start()


# ---------------------------------------------------------------- button
class GlowButton(QPushButton):
    """kind: 'primary' (gradient), 'ghost' (outlined), 'danger'. dot=True adds a red record dot.
    setLive(True): stays fully opaque even if disabled and pulses (used while recording)."""

    def __init__(self, text="", kind="ghost", dot=False, parent=None):
        super().__init__(text, parent)
        self._kind, self._dot = kind, dot
        self._h = 0.0
        self._pulse = 0.0
        self._live = False
        self._hover = _anim(self, 170, self._set_h)
        self._pulse_anim = _anim(self, 1400, self._set_pulse, QEasingCurve.OutQuad)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setFocusPolicy(Qt.TabFocus)
        f = QFont(self.font())
        f.setWeight(QFont.DemiBold)
        self.setFont(f)

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def _set_pulse(self, v):
        self._pulse = float(v)
        self.update()

    def setLive(self, live: bool):
        self._live = live
        if live:
            self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse = 0.0
        self.update()

    def enterEvent(self, e):
        _glide(self._hover, self._h, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        _glide(self._hover, self._h, 0.0)
        super().leaveEvent(e)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self.text()) + 40 + (18 if self._dot or self._live else 0)
        return QSize(max(w, 64), 40)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        active = self.isEnabled() or self._live
        p.setOpacity(1.0 if active else 0.38)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        if self.isDown():
            r = r.adjusted(0.8, 0.8, -0.8, -0.8)
        rad = r.height() / 2
        h = self._h if active else 0.0
        accent, accent2 = QColor(theme.ACCENT), QColor(theme.ACCENT2)
        text_col = QColor(theme.TEXT)

        if self._kind in ("primary", "danger"):
            if self._kind == "primary":
                c1, c2 = mix(accent, QColor("#ffffff"), 0.12 * h), accent2
                glow = accent
                text_col = QColor("#07090d")
            else:
                c1, c2 = QColor(theme.DANGER), QColor("#ff8a5c")
                glow = c1
                text_col = QColor("#ffffff")
            for i in range(1, 5):  # soft outer glow on hover
                g = QColor(glow)
                g.setAlphaF(0.10 * h * (5 - i) / 4)
                p.setPen(QPen(g, 1.4))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-i, -i, i, i), rad + i, rad + i)
            grad = QLinearGradient(r.topLeft(), r.topRight())
            grad.setColorAt(0, c1)
            grad.setColorAt(1, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(r, rad, rad)
        else:
            fill = mix(QColor(theme.CARD), QColor(theme.CARD_HI), h)
            border = mix(QColor(theme.BORDER), accent, 0.9 * h)
            if self._live:
                fill = mix(QColor(theme.CARD), QColor(theme.DANGER), 0.14)
                border = mix(QColor(theme.BORDER), QColor(theme.DANGER), 0.65)
            p.setPen(QPen(border, 1))
            p.setBrush(fill)
            p.drawRoundedRect(r, rad, rad)

        text_rect = r
        if self._dot or self._live:
            cx, cy = r.left() + 20, r.center().y()
            dot = QColor(theme.DANGER)
            if self._live:
                ring = QColor(dot)
                ring.setAlphaF(max(0.0, 0.55 * (1 - self._pulse)))
                p.setPen(Qt.NoPen)
                p.setBrush(ring)
                rr = 4.5 + 8 * self._pulse
                p.drawEllipse(QPointF(cx, cy), rr, rr)
            p.setPen(Qt.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
            text_rect = QRectF(r.left() + 14, r.top(), r.width() - 14, r.height())
        p.setPen(text_col)
        p.setFont(self.font())
        p.drawText(text_rect, Qt.AlignCenter, self.text())


# ---------------------------------------------------------------- toggle switch
class Toggle(QCheckBox):
    """Animated switch with a label; same API as QCheckBox."""
    TW, TH = 38, 20

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._t = 0.0
        self._anim = _anim(self, 200, self._set_t)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._on_toggled)

    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def _on_toggled(self, on):
        if self.isVisible():
            _glide(self._anim, self._t, 1.0 if on else 0.0)
        else:
            self._t = 1.0 if on else 0.0

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(self.TW + 10 + fm.horizontalAdvance(self.text()) + 4, 30)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - self.TH) / 2
        track = QRectF(1, y, self.TW, self.TH)
        off = QColor("#33241e")
        grad = QLinearGradient(track.topLeft(), track.topRight())
        grad.setColorAt(0, mix(off, QColor(theme.ACCENT), self._t))
        grad.setColorAt(1, mix(off, QColor(theme.ACCENT2), self._t))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(track, self.TH / 2, self.TH / 2)
        kx = track.left() + 3 + (self.TW - self.TH) * self._t + (self.TH - 6) / 2
        p.setBrush(QColor("#ffffff") if self._t > 0.5 else QColor("#a08f88"))
        p.drawEllipse(QPointF(kx, track.center().y()), 7, 7)
        p.setPen(mix(QColor(theme.MUTED), QColor(theme.TEXT), self._t))
        p.drawText(QRectF(self.TW + 12, 0, self.width() - self.TW - 12, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text())


# ---------------------------------------------------------------- level meter
class LevelMeter(QWidget):
    """Scrolling audio-level bars. setActive(True) + setLevel(rms) while recording; idle = gentle breathing."""
    STEP = 6  # bar width + gap

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self._vals = deque([0.0] * 400, maxlen=400)
        self._level = 0.0
        self._active = False
        self._phase = 0.0
        self._n = 0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def setActive(self, on: bool):
        self._active = on
        if not on:
            self._level = 0.0

    def setLevel(self, rms: float):
        self._level = rms

    def showEvent(self, e):
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _tick(self):
        self._phase += 0.1
        self._n += 1
        if self._n % 2:
            return
        if self._active:
            target = min(1.0, (self._level * 9) ** 0.8)
            prev = self._vals[-1]
            v = prev * 0.45 + target * 0.55
        else:
            v = 0.05 + 0.035 * math.sin(self._phase)
        self._vals.append(v)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = max(1, w // self.STEP)
        vals = list(self._vals)[-n:]
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, QColor(theme.ACCENT))
        grad.setColorAt(1, QColor(theme.ACCENT2))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.setOpacity(0.95 if self._active else 0.35)
        x = w - len(vals) * self.STEP
        for v in vals:
            bh = max(3.0, v * (h - 4))
            p.drawRoundedRect(QRectF(x, (h - bh) / 2, 3, bh), 1.5, 1.5)
            x += self.STEP


# ---------------------------------------------------------------- busy bar
class BusyBar(QWidget):
    """Thin glowing bar that slides while busy and fades out when idle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self._op = 0.0
        self._pos = 0.0
        self._fade = _anim(self, 300, self._set_op, QEasingCurve.InOutQuad)
        self._slide = _anim(self, 1300, self._set_pos, QEasingCurve.InOutSine)
        self._slide.setStartValue(0.0)
        self._slide.setEndValue(1.0)
        self._slide.setLoopCount(-1)

    def _set_op(self, v):
        self._op = float(v)
        self.update()

    def _set_pos(self, v):
        self._pos = float(v)
        self.update()

    def setBusy(self, busy: bool):
        _glide(self._fade, self._op, 1.0 if busy else 0.0)
        if busy:
            if self._slide.state() != QVariantAnimation.Running:
                self._slide.start()
        else:
            QTimer.singleShot(320, lambda: self._slide.stop() if self._op < 0.01 else None)

    def paintEvent(self, _e):
        if self._op <= 0.01:
            return
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.setOpacity(self._op)
        seg = w * 0.32
        x = -seg + (w + seg) * self._pos
        grad = QLinearGradient(x, 0, x + seg, 0)
        c0 = QColor(theme.ACCENT)
        c0.setAlpha(0)
        c1, c2 = QColor(theme.ACCENT), QColor(theme.ACCENT2)
        grad.setColorAt(0, c0)
        grad.setColorAt(0.5, c1)
        grad.setColorAt(1, c2)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(x, 0, seg, h), h / 2, h / 2)


# ---------------------------------------------------------------- list rows
ROLE_META = Qt.UserRole + 1


class NoteDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 62)

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(8, 3, -8, -3)
        sel = bool(option.state & QStyle.State_Selected)
        hov = bool(option.state & QStyle.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        if sel:
            g = QLinearGradient(r.topLeft(), r.topRight())
            a, b = QColor(theme.ACCENT), QColor(theme.ACCENT2)
            a.setAlpha(34)
            b.setAlpha(22)
            g.setColorAt(0, a)
            g.setColorAt(1, b)
            p.fillPath(path, QBrush(g))
            bc = QColor(theme.ACCENT)
            bc.setAlpha(90)
            p.setPen(QPen(bc, 1))
            p.drawPath(path)
            bar = QPainterPath()
            bar.addRoundedRect(QRectF(r.left() + 1, r.top() + 14, 3, r.height() - 28), 1.5, 1.5)
            p.fillPath(bar, QColor(theme.ACCENT))
        elif hov:
            p.fillPath(path, QColor("#1a1210"))
        tx = r.left() + 16
        tw = r.width() - 28
        tf = QFont(option.font)
        tf.setPointSizeF(10.5)
        tf.setWeight(QFont.DemiBold)
        p.setFont(tf)
        p.setPen(QColor(theme.TEXT))
        title = QFontMetrics(tf).elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, int(tw))
        p.drawText(QRectF(tx, r.top() + 9, tw, 22), Qt.AlignVCenter | Qt.AlignLeft, title)
        mf = QFont(option.font)
        mf.setPointSizeF(8.5)
        p.setFont(mf)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(tx, r.top() + 31, tw, 20), Qt.AlignVCenter | Qt.AlignLeft,
                   index.data(ROLE_META) or "")
        p.restore()
