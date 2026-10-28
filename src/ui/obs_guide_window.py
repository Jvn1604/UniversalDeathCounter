"""
OBS Setup (sidebar): step-by-step guide for showing the death
counter on stream, filled in with the player's own details (overlay
hotkey, the window name OBS lists, the deaths.txt path), plus buttons that
do the app-side half of each method.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from html import escape
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.overlay.overlay_window import OVERLAY_WINDOW_TITLE


def _process_name() -> str:
    """The executable name OBS shows in brackets in its window list."""
    return Path(sys.executable).name


def _page(html: str) -> QTextBrowser:
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setHtml(
        "<style>li { margin-bottom: 6px; } b.ui { color: #ff6b6b; } "
        "code { color: #b56cff; } .tip { color: #999999; }</style>" + html
    )
    return browser


class ObsGuideWindow(QDialog):
    """Tabs for the two OBS methods, each with buttons that prepare the app side."""

    def __init__(
        self,
        overlay_hotkey: str,
        deaths_txt_path: Path,
        show_overlay_green: Callable[[], None],
        enable_deaths_txt: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Up the Death Counter in OBS")
        self.resize(640, 600)
        self._deaths_txt_path = deaths_txt_path

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        window_name = f"[{_process_name()}]: {OVERLAY_WINDOW_TITLE}"
        hotkey = escape(overlay_hotkey or "Overlay in the sidebar")
        overlay_tab = QWidget()
        overlay_layout = QVBoxLayout(overlay_tab)
        overlay_layout.addWidget(_page(f"""
            <h3>Method 1: Overlay window (recommended)</h3>
            <p>Shows the styled counter card (game, boss, big number) on stream.</p>
            <ol>
              <li>Click <b class="ui">Show Overlay in Green-Screen Mode</b> below. This
                  turns on the overlay (shortcut <code>{hotkey}</code>) with a solid
                  green background that OBS can make transparent. Drag it to move it,
                  and drag its bottom-right corner to resize.</li>
              <li>In OBS, under <b class="ui">Sources</b>, click <b class="ui">+</b> →
                  <b class="ui">Window Capture</b>, name it "Death Counter", and click
                  OK.</li>
              <li>Set <b class="ui">Window</b> to <code>{escape(window_name)}</code>.</li>
              <li>Set <b class="ui">Capture Method</b> to
                  <b class="ui">Windows 10 (1903 and up)</b> and untick
                  <b class="ui">Capture Cursor</b>. Click OK.</li>
              <li>Right-click the source → <b class="ui">Filters</b> → under
                  <b class="ui">Effect Filters</b> click <b class="ui">+</b> →
                  <b class="ui">Chroma Key</b>. Set <b class="ui">Key Color Type</b> to
                  <b class="ui">Green</b>. The green disappears and only the counter is
                  left.</li>
              <li>Position and scale the source in your OBS scene.</li>
            </ol>
            <p class="tip">Tips:</p>
            <ul class="tip">
              <li>Keep the overlay open (it can sit behind your game). Minimizing or
                  closing it blanks the capture.</li>
              <li>With two monitors, right-click the overlay → <b>Move Overlay to Display</b>
                  to keep it off your game screen.</li>
              <li>Green fringe around the text? Raise <b>Similarity</b> in the Chroma
                  Key filter a little.</li>
              <li>Prefer a dark card instead? Set <b>Settings → Overlay → Background</b>
                  to "dark" and skip the Chroma Key filter.</li>
            </ul>
        """))
        overlay_button = QPushButton("Show Overlay in Green-Screen Mode")
        overlay_button.setObjectName("AccentButton")
        overlay_button.clicked.connect(show_overlay_green)
        overlay_layout.addWidget(overlay_button)
        tabs.addTab(overlay_tab, "Overlay Window")

        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        text_layout.addWidget(_page(f"""
            <h3>Method 2: Text source (lightest)</h3>
            <p>OBS reads the count from a small text file that the app rewrites on every
               death. No overlay window is needed, and you style the text in OBS.</p>
            <ol>
              <li>Click <b class="ui">Enable deaths.txt &amp; Copy Path</b> below. The
                  file is:<br><code>{escape(str(self._deaths_txt_path))}</code></li>
              <li>In OBS, under <b class="ui">Sources</b>, click <b class="ui">+</b> →
                  <b class="ui">Text (GDI+)</b>, name it "Deaths", and click OK.</li>
              <li>Tick <b class="ui">Read from file</b>, click <b class="ui">Browse</b>,
                  and paste the path (Ctrl+V) into the file name box.</li>
              <li>Choose a font, size and color, then click OK.</li>
            </ol>
            <p class="tip">Change what the text says under <b>Settings → Streaming</b>
               with a template such as <code>{{game}} - {{boss}}: {{deaths}}</code>
               (placeholders: {{game}} {{boss}} {{deaths}} {{session}} {{boss_deaths}}
               {{total}}).</p>
        """))
        text_buttons = QHBoxLayout()
        enable_button = QPushButton("Enable deaths.txt && Copy Path")
        enable_button.setObjectName("AccentButton")
        enable_button.clicked.connect(lambda: self._enable_text(enable_deaths_txt, enable_button))
        text_buttons.addWidget(enable_button)
        text_layout.addLayout(text_buttons)
        tabs.addTab(text_tab, "Text Source")

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    def _enable_text(self, enable: Callable[[], None], button: QPushButton) -> None:
        enable()
        QApplication.clipboard().setText(str(self._deaths_txt_path))
        button.setText("✓ Enabled, path copied")
