"""ECG Analyzer — application entry point."""

import sys

from PySide6.QtWidgets import QApplication

from app.acquisition.data_buffer import DataBuffer
from app.acquisition.record_loader import RecordLoader
from app.acquisition.replay_source import ReplaySource
from app.ui import theme
from app.ui.main_window import MainWindow

ANALYSIS_SECONDS = 60.0              # how much signal the analysis sees
REPLAY_RECORD = "data/sample/100"    # path relative to the project folder


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())

    window = MainWindow()

    loader = RecordLoader(REPLAY_RECORD)
    signal, fs = loader.load()
    buffer = DataBuffer(sample_rate=fs, window_seconds=ANALYSIS_SECONDS)
    source = ReplaySource(signal, fs, buffer, loop=True)
    window.attach_source(source, buffer, fs, f"Replay · MIT-BIH 100 · {fs:.0f} Hz")

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())