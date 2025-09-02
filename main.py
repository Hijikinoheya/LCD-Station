#"delay_secs": 20
import sys
import typing
import json
from pathlib import Path
from datetime import datetime, timedelta

from PyQt5.QtCore import Qt, QTimer, QSize, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QFont, QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)


def _parse_today_or_tomorrow_time(hhmm: str) -> datetime:
    try:
        hour, minute = [int(x) for x in hhmm.split(":", 1)]
    except Exception:
        hour, minute = 0, 0
    now = datetime.now()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate < now - timedelta(hours=12):
        candidate += timedelta(days=1)
    return candidate

class OutlineLabel(QLabel):
    """Label that draws bold text with an outline for better readability."""

    def __init__(self, text: str = "", parent: typing.Optional[QWidget] = None):
        super().__init__(text, parent)
        self._outline_color = QColor(15, 17, 23)
        self._outline_width = 2

    def paintEvent(self, event):  # noqa: N802 - PyQt API compatibility
        from PyQt5.QtGui import QPainter, QPainterPath, QPainterPathStroker

        painter = QPainter(self)
        try:
            painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            text = self.text()
            if not text:
                return
            metrics = self.fontMetrics()
            y = (self.height() + metrics.ascent() - metrics.descent()) // 2

            path = QPainterPath()
            path.addText(0, y, self.font(), text)

            # Outline using QPainterPathStroker
            stroker = QPainterPathStroker()
            stroker.setWidth(max(1.0, float(self._outline_width)))
            outline_path = stroker.createStroke(path)
            painter.fillPath(outline_path, self._outline_color)

            # Fill text
            painter.fillPath(path, self.palette().text())
        finally:
            painter.end()


class MarqueeLabel(QLabel):
    """A single-line label that smoothly scrolls long text horizontally."""

    def __init__(self, text: str = "", parent: typing.Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(28)
        self._offset_px: int = 0
        self._speed_px_per_tick: int = 2
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._on_tick)
        self._should_scroll: bool = False
        self._direction: int = -1  # use leftward continuous marquee
        self.setText(text)

    def sizeHint(self) -> QSize:  # avoid width based on text length to prevent layout shift
        return QSize(0, max(20, self.minimumHeight()))

    def setText(self, text: str) -> None:  # noqa: N802 - PyQt API compatibility
        super().setText(text)
        self._evaluate_scroll()

    def resizeEvent(self, event):  # noqa: N802 - PyQt API compatibility
        super().resizeEvent(event)
        self._evaluate_scroll()

    def _evaluate_scroll(self) -> None:
        metrics = self.fontMetrics()
        text_width = max(1, metrics.horizontalAdvance(self.text()))
        available = max(1, self.width())
        need_scroll = text_width > available
        if need_scroll and not self._should_scroll:
            self._should_scroll = True
            self._timer.start()
        elif not need_scroll and self._should_scroll:
            self._should_scroll = False
            self._timer.stop()
            self._offset_px = 0
            self.update()

    def _on_tick(self) -> None:
        if not self._should_scroll:
            return
        metrics = self.fontMetrics()
        text_width = max(1, metrics.horizontalAdvance(self.text()))
        available = max(1, self.width())
        if text_width <= available:
            self._offset_px = 0
            self._should_scroll = False
            self._timer.stop()
            return
        gap = 50
        total = text_width + gap
        self._offset_px = (self._offset_px + self._speed_px_per_tick) % total
        self.update()

    def paintEvent(self, event):  # noqa: N802 - PyQt API compatibility
        # Custom paint: continuous right-to-left marquee by drawing two copies
        painter = typing.cast("QPainter", None)
        from PyQt5.QtGui import QPainter  # local import to speed startup

        painter = QPainter(self)
        try:
            painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            text = self.text()
            if not text:
                return
            metrics = self.fontMetrics()
            y = (self.height() + metrics.ascent() - metrics.descent()) // 2
            painter.setClipRect(0, 0, self.width(), self.height())
            text_width = max(1, metrics.horizontalAdvance(text))
            # If not scrolling, draw left-aligned
            if not self._should_scroll:
                painter.drawText(0, y, text)
                return
            gap = 50
            total = text_width + gap
            # Head starts at right edge moving left
            start_x = self.width() - self._offset_px
            painter.drawText(start_x, y, text)
            # Second copy to cover wrap-around
            painter.drawText(start_x - total, y, text)
        finally:
            painter.end()


class DepartureRow(QWidget):
    """Row for a departure: time, destination, line, platform, status."""

    def __init__(
        self,
        departure_time: str,
        destination: str,
        line_name: str,
        platform: str,
        status: str,
        parent: typing.Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        # Time (main + sub for delay/original)
        self.time_main = QLabel(departure_time)
        self.time_main.setObjectName("timeLabel")
        self.time_main.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_sub = QLabel("")
        self.time_sub.setObjectName("timeSubLabel")
        self.time_sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_box = QVBoxLayout()
        time_box.setContentsMargins(0, 0, 0, 0)
        time_box.setSpacing(0)
        time_box.addWidget(self.time_main)
        time_box.addWidget(self.time_sub)
        self.time_container = QWidget()
        self.time_container.setLayout(time_box)
        self.time_container.setFixedWidth(112)

        # Type badge
        self.type_badge = QLabel("")
        self.type_badge.setObjectName("typeBadge")

        # Service badges (first/last/next)
        self.first_badge = QLabel("")
        self.first_badge.setObjectName("firstBadge")
        self.first_badge.setVisible(False)
        self.last_badge = QLabel("")
        self.last_badge.setObjectName("lastBadge")
        self.last_badge.setVisible(False)
        self.next_badge = QLabel("")
        self.next_badge.setObjectName("nextBadge")
        self.next_badge.setVisible(False)
        # Attention badge (for pass-through)
        self.attention_badge = QLabel("")
        self.attention_badge.setObjectName("attentionBadge")
        self.attention_badge.setVisible(False)

        # Destination (outlined marquee)
        self.destination_label = MarqueeLabel(destination)
        self.destination_label.setObjectName("destinationLabel")
        self.destination_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Via (small, optional)
        self.via_label = QLabel("")
        self.via_label.setObjectName("viaLabel")

        # Stops (small, optional)
        self.stops_label = MarqueeLabel("")
        self.stops_label.setObjectName("stopsLabel")
        self.stops_label.setFixedHeight(20)

        # Line name (marquee)
        self.line_label = MarqueeLabel(line_name)
        self.line_label.setObjectName("lineLabel")
        self.line_label.setFixedWidth(220)
        self.line_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.line_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Platform
        self.platform_label = QLabel(platform)
        self.platform_label.setObjectName("platformLabel")
        self.platform_label.setAlignment(Qt.AlignCenter)
        self.platform_label.setFixedWidth(60)

        # Status
        self.status_label = QLabel(status)
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setFixedWidth(120)

        # Blink timer for attention-grabbing statuses (e.g., 通過)
        self._blink_timer = QTimer(self)
        self._blink_on = False
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._on_blink)
        self._blinking_enabled = False

        # Pass-through presentation toggle
        self._pass_active = False

        layout = QHBoxLayout()
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(16)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        row_top = QHBoxLayout()
        row_top.setContentsMargins(0, 0, 0, 0)
        row_top.setSpacing(8)
        # Delay badge (marquee when delayed)
        self.delay_badge = MarqueeLabel("")
        self.delay_badge.setObjectName("delayBadge")
        self.delay_badge.setVisible(False)

        row_top.addWidget(self.type_badge, 0)
        row_top.addWidget(self.first_badge, 0)
        row_top.addWidget(self.last_badge, 0)
        row_top.addWidget(self.next_badge, 0)
        row_top.addWidget(self.attention_badge, 0)
        row_top.addWidget(self.delay_badge, 0)
        row_top.addWidget(self.destination_label, 1)
        text_box.addLayout(row_top)
        text_box.addWidget(self.via_label, 0)
        text_box.addWidget(self.stops_label, 0)

        layout.addWidget(self.time_container, 0)
        content_container = QWidget()
        content_container.setLayout(text_box)
        content_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(content_container, 5)
        layout.addWidget(self.line_label, 0)
        layout.addWidget(self.platform_label, 0)
        layout.addWidget(self.status_label, 0)

        self.setLayout(layout)
        self.setObjectName("departureRow")

    def sizeHint(self) -> QSize:  # noqa: D401
        return QSize(1280, 56)

    def update_status(self, status_text: str) -> None:
        self.status_label.setText(status_text)

    def set_blinking(self, enabled: bool) -> None:
        self._blinking_enabled = enabled
        if enabled:
            self._blink_on = True
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self._blink_on = False
            self.status_label.setVisible(True)

    def _on_blink(self) -> None:
        if not self._blinking_enabled:
            if self._blink_timer.isActive():
                self._blink_timer.stop()
            self.status_label.setVisible(True)
            return
        self._blink_on = not self._blink_on
        self.status_label.setVisible(self._blink_on)

    def set_pass_presentation(self, active: bool) -> None:
        # Hide everything except: type badge, time, platform, status, and show attention badge
        self._pass_active = active
        if active:
            # keep type, time, platform, status visible
            if self.type_badge.text().strip():
                self.type_badge.setVisible(True)
            self.platform_label.setVisible(True)
            self.status_label.setVisible(True)
            try:
                self.time_container.setVisible(True)
            except Exception:
                pass
            self.destination_label.setVisible(False)
            self.next_badge.setVisible(False)
            self.line_label.setVisible(False)
            self.via_label.setVisible(False)
            self.stops_label.setVisible(False)
            self.first_badge.setVisible(False)
            self.last_badge.setVisible(False)
            self.delay_badge.setVisible(False)
            # Attention badge
            self.attention_badge.setText("ご注意ください")
            self.attention_badge.setVisible(True)
            self.attention_badge.setStyleSheet("background: #ff9900; color: #0b111a; padding: 2px 8px; border-radius: 6px; font-weight: 800;")
        else:
            if self.type_badge.text().strip():
                self.type_badge.setVisible(True)
            try:
                self.time_container.setVisible(True)
            except Exception:
                pass
            self.destination_label.setVisible(True)
            # next_badge visibility will be controlled by board; if it has text, show
            if self.next_badge.text().strip():
                self.next_badge.setVisible(True)
            self.line_label.setVisible(True)
            if self.via_label.text().strip():
                self.via_label.setVisible(True)
            if self.stops_label.text().strip():
                self.stops_label.setVisible(True)
            # first/last/delay badges restored only if text set
            if self.first_badge.text().strip():
                self.first_badge.setVisible(True)
            if self.last_badge.text().strip():
                self.last_badge.setVisible(True)
            if self.delay_badge.text().strip():
                self.delay_badge.setVisible(True)
            self.attention_badge.setVisible(False)


class HeaderRow(QWidget):
    def __init__(self, parent: typing.Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(16, 12, 16, 6)
        layout.setSpacing(16)

        def h(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("headerCell")
            return lbl

        time_h = h("時刻")
        time_h.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_h.setFixedWidth(96)
        dest_h = h("行先")
        line_h = h("路線")
        line_h.setFixedWidth(220)
        plat_h = h("番線")
        plat_h.setAlignment(Qt.AlignCenter)
        plat_h.setFixedWidth(60)
        stat_h = h("状態")
        stat_h.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        stat_h.setFixedWidth(120)

        layout.addWidget(time_h, 0)
        layout.addWidget(dest_h, 5)
        layout.addWidget(line_h, 0)
        layout.addWidget(plat_h, 0)
        layout.addWidget(stat_h, 0)
        self.setLayout(layout)
        self.setObjectName("headerRow")


class DepartureBoard(QWidget):
    def __init__(self, parent: typing.Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.rows: list[DepartureRow] = []
        self._model: list[dict] = []  # visible rows: {"row": DepartureRow, "time": datetime, ...}
        self._all_items: list[dict] = []  # full schedule: {"raw": dict, "time": datetime, "shown": bool}

        self.clock_label = QLabel("")
        self.clock_label.setObjectName("clockLabel")
        self.clock_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(16, 16, 16, 8)
        top_bar.setSpacing(12)

        title = QLabel("出発案内")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # current station from config (if any)
        self.station_label = QLabel("")
        self.station_label.setObjectName("stationLabel")
        self.station_label.setAlignment(Qt.AlignCenter)

        top_bar.addWidget(title, 1)
        top_bar.addWidget(self.station_label, 0)
        top_bar.addItem(QSpacerItem(16, 16, QSizePolicy.Expanding, QSizePolicy.Minimum))
        top_bar.addWidget(self.clock_label, 0)

        header = HeaderRow()

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout()
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(1)
        self.list_container.setLayout(self.list_layout)
        self.list_container.setObjectName("listContainer")

        # Bottom banner (ticker / end-of-service): fixed height, centered, marquee-capable
        self.end_label = MarqueeLabel("")
        self.end_label.setObjectName("endOfService")
        self.end_label.setAlignment(Qt.AlignCenter)
        self.end_label.setFixedHeight(64)
        self.end_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.end_label.setStyleSheet(
            "background: #101725; color: #ffffff; padding: 10px 16px; border-radius: 12px; border: 2px solid #7aa2f7; font-weight: 800;"
        )
        self._end_blink = QTimer(self)
        self._end_blink.setInterval(700)
        self._end_blink_state = True
        def _toggle_end_style():
            self._end_blink_state = not self._end_blink_state
            if self._end_blink_state:
                self.end_label.setStyleSheet(
                    "background: #101725; color: #ffffff; padding: 10px 16px; border-radius: 12px; border: 2px solid #7aa2f7; font-weight: 800;"
                )
            else:
                self.end_label.setStyleSheet(
                    "background: #0e1420; color: #a8c6ff; padding: 10px 16px; border-radius: 12px; border: 2px solid #4f79bd; font-weight: 800;"
                )
        self._end_blink.timeout.connect(_toggle_end_style)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(top_bar)
        root.addWidget(header)
        # Pass-through notice banner (fixed area, below list)
        self.notice_label = OutlineLabel("")
        self.notice_label.setObjectName("noticeBanner")
        self.notice_label.setAlignment(Qt.AlignCenter)
        self.notice_label.setFixedHeight(48)
        self.notice_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.notice_label.setStyleSheet(
            "background: #1a2230; color: #ffd28a; padding: 6px 12px; border-top: 1px solid #273149; border-bottom: 1px solid #273149; font-weight: 800;"
        )
        root.addWidget(self.list_container)
        root.addWidget(self.notice_label)
        root.addWidget(self.end_label)
        self.setLayout(root)
        self.setObjectName("departureBoard")

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(500)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1_000)
        self._status_timer.timeout.connect(self._refresh_statuses)
        self._status_timer.start()

        # Notice blink
        self._notice_blink = QTimer(self)
        self._notice_blink.setInterval(600)
        self._notice_blink_state = True
        def _toggle_notice_style():
            self._notice_blink_state = not self._notice_blink_state
            if self._notice_blink_state:
                self.notice_label.setStyleSheet(
                    "background: #1a2230; color: #ffd28a; padding: 6px 12px; border-top: 1px solid #273149; border-bottom: 1px solid #273149; font-weight: 800;"
                )
            else:
                self.notice_label.setStyleSheet(
                    "background: #1a2230; color: #ffc166; padding: 6px 12px; border-top: 1px solid #273149; border-bottom: 1px solid #273149; font-weight: 800;"
                )
        self._notice_blink.timeout.connect(_toggle_notice_style)

    def _update_clock(self) -> None:
        now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        self.clock_label.setText(now)

    def set_departures(self, departures: list[dict]) -> None:
        # rebuild full schedule
        self._all_items.clear()
        now = datetime.now()
        for item in departures:
            dep_time = _parse_today_or_tomorrow_time(item.get("time", "00:00"))
            delay_secs = int(item.get("delay_secs", 0) or 0)
            adj_time = dep_time + timedelta(seconds=delay_secs)
            self._all_items.append({"raw": item, "time": adj_time, "shown": False})
        self._all_items.sort(key=lambda x: x["time"])

        # clear visible rows and model
        for r in self.rows:
            r.setParent(None)
        self.rows.clear()
        self._model.clear()

        # populate up to 6 upcoming
        self._fill_up_to_six()

    def _create_row_from_item(self, item: dict, adj_time: datetime, alt_index: int) -> DepartureRow:
        row = DepartureRow(
            item.get("time", "--:--"),
            item.get("destination", ""),
            item.get("line", ""),
            item.get("platform", "-"),
            "定刻",
        )
        row.setProperty("alt", bool(alt_index % 2))
        # type badge
        type_name = str(item.get("type", "")).strip()
        if type_name:
            row.type_badge.setText(type_name)
            color = self._type_color_hex(type_name)
            if color:
                row.type_badge.setStyleSheet(f"background: #{color}; color: #ffffff; padding: 2px 8px; border-radius: 6px; font-weight: 700;")
        else:
            row.type_badge.setVisible(False)
        # via
        via = str(item.get("via", "")).strip()
        if via:
            row.via_label.setText(f"経由: {via}")
            row.via_label.setVisible(True)
        else:
            row.via_label.setVisible(False)
        # stops (list or string)
        stops = item.get("stops")
        if isinstance(stops, list) and stops:
            row.stops_label.setText("停車駅: " + "・".join(stops))
            row.stops_label.setVisible(True)
        elif isinstance(stops, str) and stops.strip():
            row.stops_label.setText("停車駅: " + stops.strip())
            row.stops_label.setVisible(True)
        else:
            row.stops_label.setVisible(False)
        # hide stops for 回送
        if str(item.get("type", "")).strip() == "回送":
            row.stops_label.setVisible(False)
        # delay UI
        dep_time = _parse_today_or_tomorrow_time(item.get("time", "00:00"))
        delay_secs = int(item.get("delay_secs", 0) or 0)
        if delay_secs > 0:
            row.time_main.setText(adj_time.strftime("%H:%M"))
            row.time_sub.setText(f"(予定 {dep_time.strftime('%H:%M')})")
            delay_min = (delay_secs + 59) // 60
            row.delay_badge.setText(f"遅延 +{delay_min}分")
            row.delay_badge.setVisible(True)
            row.delay_badge.setStyleSheet("background: #ff6666; color: #ffffff; padding: 2px 8px; border-radius: 6px; font-weight: 700;")
        else:
            row.time_main.setText(dep_time.strftime("%H:%M"))
            row.time_sub.setText("")
            row.delay_badge.setVisible(False)

        # first/last flags (from JSON)
        if bool(item.get("first", False)):
            row.first_badge.setText("始発")
            row.first_badge.setVisible(True)
            row.first_badge.setStyleSheet("background: #2e8b57; color: #ffffff; padding: 2px 8px; border-radius: 6px; font-weight: 800;")
        else:
            row.first_badge.setVisible(False)
        if bool(item.get("last", False)):
            row.last_badge.setText("終電")
            row.last_badge.setVisible(True)
            row.last_badge.setStyleSheet("background: #8b2e2e; color: #ffffff; padding: 2px 8px; border-radius: 6px; font-weight: 800;")
        else:
            row.last_badge.setVisible(False)
        return row

    def _fill_up_to_six(self) -> None:
        now = datetime.now()
        while len(self.rows) < 6:
            next_item = None
            for it in self._all_items:
                if not it["shown"] and it["time"] >= now - timedelta(seconds=60):
                    next_item = it
                    break
            if not next_item:
                break
            idx = len(self.rows)
            row = self._create_row_from_item(next_item["raw"], next_item["time"], idx)
            self.rows.append(row)
            self.list_layout.addWidget(row)
            self._model.append({
                "row": row,
                "time": next_item["time"],
                "raw": next_item["raw"],
                "flags": {
                    "pass_through": bool(next_item["raw"].get("pass_through", False)),
                    # Treat JSON type "回送" as terminal-here (当駅止まり)
                    "terminal_here": str(next_item["raw"].get("type", "")).strip() == "回送",
                    "is_delayed": int(next_item["raw"].get("delay_secs", 0) or 0) > 0,
                },
                "dwell_until": None,
                "played": {"pre77": False, "arrival": False, "departed": False},
                "last_delta": None,
            })
            next_item["shown"] = True

        # mark next badge (first visible row)
        for i, entry in enumerate(self._model):
            row: DepartureRow = typing.cast(DepartureRow, entry["row"])
            if i == 0:
                row.next_badge.setText("次発")
                row.next_badge.setVisible(True)
                row.next_badge.setStyleSheet("background: #1a6fb3; color: #ffffff; padding: 2px 8px; border-radius: 6px; font-weight: 800;")
            else:
                row.next_badge.setVisible(False)

        # Auto-mark last train (終電) on last visible row if no more future items
        if self._model:
            now2 = datetime.now()
            any_future = any((not it["shown"]) and (it["time"] >= now2) for it in self._all_items)
            last_index = len(self._model) - 1
            for i, entry in enumerate(self._model):
                row: DepartureRow = typing.cast(DepartureRow, entry["row"])
                if (i == last_index) and (not any_future):
                    row.last_badge.setText("終電")
                    row.last_badge.setVisible(True)
                    row.last_badge.setStyleSheet("background: #8b2e2e; color: #ffffff; padding: 2px 8px; border-radius: 6px; font-weight: 800;")
                else:
                    if not bool(entry["raw"].get("last", False)):
                        row.last_badge.setVisible(False)

        self._toggle_end_of_service_message()

    def _toggle_end_of_service_message(self) -> None:
        # If no more items to show now or in future, show end-of-service message
        now = datetime.now()
        any_future = any((not it["shown"]) and (it["time"] >= now) for it in self._all_items)
        # Always show ticker text if provided via config; override with end-of-service text when ended
        ticker_text = getattr(self, "_ticker_message", "").strip() if hasattr(self, "_ticker_message") else ""
        if len(self.rows) == 0 and not any_future:
            self.end_label.setText("本日の営業は終了いたしました")
            if not self._end_blink.isActive():
                self._end_blink.start()
        else:
            if self._end_blink.isActive():
                self._end_blink.stop()
            self.end_label.setText(ticker_text)

    @staticmethod
    def _type_color_hex(type_name: str) -> str:
        mapping = {
            "普通": "000000",
            "区間快速": "669966",
            "快速": "1a4d1a",
            "急行": "cc6633",
            "特急": "b31a1a",
            "空港線": "4d8080",
            "通勤特急": "1a4d4d",
            "直通特急": "8066cc",
            "新快速": "1a3399",
        }
        return mapping.get(type_name, "")

    def _refresh_statuses(self) -> None:
        if not hasattr(self, "_thresholds"):
            return
        now = datetime.now()
        # Custom event times (seconds before departure)
        # Use thresholds if provided, else fall back to defaults
        pre77_sound_before = int(self._thresholds.get("approach_before_secs", 77))
        arrival_sound_before = int(self._thresholds.get("arrival_before_secs", 57))
        stop_before = int(self._thresholds.get("stop_before_secs", 40))
        remove_after = int(self._thresholds.get("remove_after_secs", 10))
        pass_before = int(self._thresholds.get("pass_before_secs", 20))
        pass_remove_after = int(self._thresholds.get("pass_remove_after_secs", 10))

        to_remove: list[int] = []
        for idx, entry in enumerate(self._model):
            dep_time = entry["time"]
            row: DepartureRow = typing.cast(DepartureRow, entry["row"])
            flags = entry.get("flags", {})
            is_terminal = bool(flags.get("terminal_here", False))
            is_pass = bool(flags.get("pass_through", False))
            is_deadhead = False
            is_delayed = bool(flags.get("is_delayed", False))

            if is_terminal:
                delta = (dep_time - now).total_seconds()
                if entry["dwell_until"] is None and delta <= 0:
                    entry["dwell_until"] = dep_time + timedelta(seconds=60)
            else:
                delta = (dep_time - now).total_seconds()
            last_delta = entry.get("last_delta")

            # Removal policy
            if is_terminal and entry["dwell_until"] is not None:
                # after dwell, show 発車 for remove_after seconds then remove
                if now >= entry["dwell_until"]:
                    # mark a post-depart phase start
                    if "post_depart_at" not in entry:
                        entry["post_depart_at"] = now
                    post_elapsed = (now - entry["post_depart_at"]).total_seconds()
                    if post_elapsed >= remove_after:
                        to_remove.append(idx)
                        continue
            elif (is_pass and delta <= -pass_remove_after) or (not is_pass and delta <= -remove_after):
                to_remove.append(idx)
                continue

            if 0 <= delta:
                if is_terminal:
                    if delta <= stop_before:
                        row.update_status("終着 停車中")
                        row.status_label.setStyleSheet("background: #ffd166; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                    elif delta <= arrival_sound_before:
                        row.update_status("終着 到着")
                        row.status_label.setStyleSheet("background: #9fdcff; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                    elif delta <= pre77_sound_before:
                        row.update_status("終着 接近")
                        row.status_label.setStyleSheet("background: #6699ff; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                    else:
                        row.update_status("定刻" if not is_delayed else "遅延")
                        if is_delayed:
                            row.status_label.setStyleSheet("background: #ffb84d; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        else:
                            row.status_label.setStyleSheet("background: #22e3a1; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                elif is_pass:
                    # Before time: behave like others (接近表示), and show centered notice during approach window
                    if delta <= pre77_sound_before:
                        row.update_status("接近")
                        row.status_label.setStyleSheet("background: #6699ff; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                        self.notice_label.setText(f"{row.platform_label.text()}番線に列車が通過します")
                        if not self._notice_blink.isActive():
                            self._notice_blink.start()
                    else:
                        row.update_status("定刻" if not is_delayed else "遅延")
                        if is_delayed:
                            row.status_label.setStyleSheet("background: #ffb84d; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        else:
                            row.status_label.setStyleSheet("background: #22e3a1; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                        if self._notice_blink.isActive():
                            self._notice_blink.stop()
                        self.notice_label.setText("")
                else:
                    if delta <= stop_before:
                        row.update_status("停車中")
                        row.status_label.setStyleSheet("background: #ffd166; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                    elif delta <= arrival_sound_before:
                        row.update_status("到着")
                        row.status_label.setStyleSheet("background: #9fdcff; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                    elif delta <= pre77_sound_before:
                        row.update_status("接近")
                        row.status_label.setStyleSheet("background: #6699ff; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                    else:
                        row.update_status("定刻" if not is_delayed else "遅延")
                        if is_delayed:
                            row.status_label.setStyleSheet("background: #ffb84d; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        else:
                            row.status_label.setStyleSheet("background: #22e3a1; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)

                # sounds
                if last_delta is not None:
                    if last_delta > arrival_sound_before >= delta and not entry["played"]["arrival"]:
                        entry["played"]["arrival"] = True
                        if hasattr(self, "on_event") and callable(self.on_event):
                            self.on_event("arrival")
                    if last_delta > pre77_sound_before >= delta and not entry["played"]["pre77"]:
                        entry["played"]["pre77"] = True
                        if hasattr(self, "on_event") and callable(self.on_event):
                            self.on_event("pre30")
                    # pass sound exactly at time 0
                    if is_pass and last_delta > 0 >= delta and not entry["played"].get("pass", False):
                        entry["played"]["pass"] = True
                        if hasattr(self, "on_event") and callable(self.on_event):
                            self.on_event("pass")
            else:
                if is_terminal:
                    # during dwell or post-depart phase
                    if entry.get("dwell_until") is not None and now >= entry["dwell_until"]:
                        row.update_status("発車")
                        row.status_label.setStyleSheet("background: #F2C201; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                    else:
                        row.update_status("終着 停車中")
                        row.status_label.setStyleSheet("background: #ffd166; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                        row.set_blinking(False)
                elif is_pass:
                    # At/after time: mark as 通過; keep notice for 10s then clear
                    row.update_status("通過")
                    row.status_label.setStyleSheet("background: #ff9900; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                    row.set_blinking(False)
                    if delta > -pass_remove_after:
                        self.notice_label.setText(f"{row.platform_label.text()}番線に列車が通過します")
                        if not self._notice_blink.isActive():
                            self._notice_blink.start()
                    else:
                        if self._notice_blink.isActive():
                            self._notice_blink.stop()
                        self.notice_label.setText("")
                else:
                    row.update_status("発車")
                    row.status_label.setStyleSheet("background: #F2C201; color: #0b111a; border-radius: 10px; padding: 4px 10px;")
                    row.set_blinking(False)
                    if not entry["played"]["departed"]:
                        entry["played"]["departed"] = True
                        if hasattr(self, "on_event") and callable(self.on_event):
                            self.on_event("depart")

            entry["last_delta"] = delta

        # remove rows from bottom indices to top to keep indices valid
        for i in reversed(to_remove):
            widget = self._model[i]["row"]
            widget.setParent(None)
            del self._model[i]
            del self.rows[i]

        # keep the list filled with up to six upcoming
        if to_remove:
            self._fill_up_to_six()
        else:
            # refresh next badge state
            self._fill_up_to_six()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("電車出発案内板")
        self.setMinimumSize(1024, 600)
        self._config = self._load_config()

        # Global palette tuning for dark theme
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(10, 12, 16))
        pal.setColor(QPalette.Base, QColor(10, 12, 16))
        pal.setColor(QPalette.Text, QColor(230, 235, 240))
        pal.setColor(QPalette.WindowText, QColor(230, 235, 240))
        self.setPalette(pal)

        self.board = DepartureBoard()
        self.board.on_event = self._handle_board_event
        self.setCentralWidget(self.board)

        self._install_qss()
        self._load_departures_from_json_or_sample()
        self._install_shortcuts()

        # thresholds to board
        thresholds = self._config.get("thresholds", {
            "approach_before_secs": 77,
            "arrival_before_secs": 57,
            "stop_before_secs": 40,
            "remove_after_secs": 10,
            "pass_before_secs": 20,
            "pass_remove_after_secs": 10,
        })
        self.board._thresholds = thresholds
        # ticker message from config
        self.board._ticker_message = str(self._config.get("ticker_message", "")).strip()

        # audio players
        self._players: dict[str, QMediaPlayer] = {}
        sound_cfg = self._config.get("sound", {})
        default_volume = int(sound_cfg.get("volume", 100))
        for key, fname in {
            "arrival": "arr.mp3",
            "pre30": "stop.mp3",
            "depart": "dep.mp3",
            "pass": "past.mp3",
        }.items():
            path = Path(__file__).with_name(fname)
            if path.exists():
                player = QMediaPlayer(self)
                player.setMedia(QMediaContent(QUrl.fromLocalFile(str(path))))
                try:
                    player.setVolume(default_volume)
                except Exception:
                    pass
                self._players[key] = player

        # watch departures.json for realtime updates
        custom_path = str(self._config.get("schedule_path", "")).strip()
        self._dep_path = Path(custom_path) if custom_path else Path(__file__).with_name("departures.json")
        self._dep_mtime = self._dep_path.stat().st_mtime if self._dep_path.exists() else 0
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(3_000)
        self._watch_timer.timeout.connect(self._maybe_reload_departures)
        self._watch_timer.start()

        # set station label if configured
        station_name = str(self._config.get("station_name", "")).strip()
        if station_name:
            self.board.station_label.setText(f"現在: {station_name}")
            self.board.station_label.setVisible(True)
        else:
            self.board.station_label.setVisible(False)

    def _install_qss(self) -> None:
        font_family = self._config.get("font_family", "BIZ UDPGothic")
        mono_family = self._config.get("mono_family", "Cascadia Mono")
        base_size = int(self._config.get("base_font_size", 13))
        app_font = QFont(font_family, base_size)
        QApplication.instance().setFont(app_font)

        qss = (
            """
        QWidget#departureBoard {
            background: #0a0c10;
        }
        QLabel#titleLabel {
            font-size: __TITLE_SIZE__px;
            font-weight: 700;
            letter-spacing: 1px;
            color: #cde6ff;
        }
        QLabel#stationLabel {
            font-size: __LINE_SIZE__px;
            color: #ffffff;
            background: #1a2230;
            padding: 4px 10px;
            border-radius: 8px;
        }
        QLabel#clockLabel {
            font-family: "__MONO__", monospace;
            font-size: __CLOCK_SIZE__px;
            color: #9fdcff;
            padding-right: 16px;
        }
        QWidget#headerRow {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                         stop:0 #0e1117, stop:1 #0b0d12);
            border-top: 1px solid #1a2230;
            border-bottom: 1px solid #1a2230;
        }
        QLabel#headerCell {
            color: #7aa2f7;
            font-weight: 600;
            text-transform: none;
        }
        QWidget#listContainer {
            background: #0a0c10;
        }
        QWidget#departureRow {
            background: #0d1016;
            border-bottom: 1px solid #121722;
        }
        QWidget#departureRow:hover {
            background: #101521;
        }
        QWidget#departureRow[alt="true"] {
            background: #0c0f15;
        }
        QLabel#timeLabel {
            font-family: "__MONO__", monospace;
            font-size: __TIME_SIZE__px;
            color: #ffdd66;
            min-width: 96px;
        }
        QLabel#destinationLabel {
            font-size: __DEST_SIZE__px;
            color: #e8ffe8;
        }
        QLabel#lineLabel {
            font-size: __LINE_SIZE__px;
            color: #a6c1ff;
        }
        QLabel#viaLabel {
            font-size: __STATUS_SIZE__px;
            color: #9ab3a5;
        }
        QLabel#stopsLabel {
            font-size: __STATUS_SIZE__px;
            color: #86a6ff;
        }
        QLabel#typeBadge {
            color: #ffffff;
            font-weight: 800;
            padding: 2px 8px;
            border-radius: 6px;
        }
        QLabel#platformLabel {
            font-family: "__MONO__", monospace;
            font-size: __PLAT_SIZE__px;
            color: #0b111a;
            min-width: 56px;
            padding: 4px 8px;
            background: #9fdcff;
            border-radius: 6px;
            qproperty-alignment: AlignCenter;
        }
        QLabel#statusLabel {
            font-size: __STATUS_SIZE__px;
            color: #0b111a;
            min-width: 112px;
            padding: 4px 10px;
            background: #22e3a1;
            border-radius: 10px;
            qproperty-alignment: AlignRight | AlignVCenter;
        }
            """
            .replace("__MONO__", mono_family)
            .replace("__TITLE_SIZE__", str(base_size + 8))
            .replace("__CLOCK_SIZE__", str(base_size + 4))
            .replace("__TIME_SIZE__", str(base_size + 6))
            .replace("__DEST_SIZE__", str(base_size + 6))
            .replace("__LINE_SIZE__", str(base_size + 2))
            .replace("__PLAT_SIZE__", str(base_size + 1))
            .replace("__STATUS_SIZE__", str(base_size))
        )
        self.setStyleSheet(qss)

    def _install_shortcuts(self) -> None:
        # Fullscreen toggle: F11
        full_btn = QPushButton(self)
        full_btn.setShortcut(Qt.Key_F11)
        full_btn.clicked.connect(self._toggle_fullscreen)
        full_btn.setVisible(False)

        # Exit fullscreen: Esc
        esc_btn = QPushButton(self)
        esc_btn.setShortcut(Qt.Key_Escape)
        esc_btn.clicked.connect(self._exit_fullscreen)
        esc_btn.setVisible(False)

        # Refresh data: R
        r_btn = QPushButton(self)
        r_btn.setShortcut(Qt.Key_R)
        r_btn.clicked.connect(self._load_departures_from_json_or_sample)
        r_btn.setVisible(False)

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def _load_sample_data(self) -> None:
        now = datetime.now().replace(second=0, microsecond=0)

        def t(minutes: int) -> str:
            return (now + timedelta(minutes=minutes)).strftime("%H:%M")

        data = [
            {
                "time": t(2),
                "destination": "快速 成田空港行 (エアポート快速) — 停車: 日暮里・空港第2ビル",
                "line": "JR 総武快速線",
                "platform": "3",
                "status": "定刻",
            },
            {
                "time": t(7),
                "destination": "各駅停車 秋葉原行",
                "line": "JR 中央・総武各駅停車",
                "platform": "1",
                "status": "定刻",
            },
            {
                "time": t(12),
                "destination": "特急 成田エクスプレス1号 横浜・大船行",
                "line": "JR 成田エクスプレス",
                "platform": "5",
                "status": "10分遅延",
            },
            {
                "time": t(18),
                "destination": "快速 逗子行 — グリーン車連結",
                "line": "JR 横須賀線",
                "platform": "4",
                "status": "定刻",
            },
            {
                "time": t(25),
                "destination": "快速 千葉行",
                "line": "JR 総武線快速",
                "platform": "3",
                "status": "まもなく",
            },
        ]

        self.board.set_departures(data)

    def _load_departures_from_json_or_sample(self) -> None:
        custom_path = str(self._config.get("schedule_path", "")).strip()
        dep_path = Path(custom_path) if custom_path else Path(__file__).with_name("departures.json")
        if dep_path.exists():
            try:
                with dep_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "departures" in data:
                    items = typing.cast(list, data["departures"])
                elif isinstance(data, list):
                    items = typing.cast(list, data)
                else:
                    items = []
                self.board.set_departures(items)
                return
            except Exception:
                pass
        self._load_sample_data()

    def _maybe_reload_departures(self) -> None:
        if not self._dep_path.exists():
            return
        try:
            mtime = self._dep_path.stat().st_mtime
        except Exception:
            return
        if mtime != self._dep_mtime:
            self._dep_mtime = mtime
            self._load_departures_from_json_or_sample()

    def _handle_board_event(self, event_key: str) -> None:
        player = self._players.get(event_key)
        if player is not None:
            # Restart playback from the beginning
            try:
                player.setVolume(100)
            except Exception:
                pass
            player.stop()
            # Some backends need a slight seek to ensure start
            try:
                player.setPosition(0)
            except Exception:
                pass
            player.play()

    def _load_config(self) -> dict:
        cfg_path = Path(__file__).with_name("config.json")
        if cfg_path.exists():
            try:
                with cfg_path.open("r", encoding="utf-8") as f:
                    return typing.cast(dict, json.load(f))
            except Exception:
                return {}
        return {}


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())


