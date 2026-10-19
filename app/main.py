"""ECG Analyzer — application entry point."""

import sys

from PySide6.QtWidgets import QApplication

from app.ui import theme
from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())