"""ECG Analyzer — application entry point.

    py -m app.main                            live, from the Arduino
    py -m app.main --replay data/sample/100   replay a recorded file
"""

import argparse
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.acquisition.acquisition_thread import AcquisitionThread
from app.acquisition.data_buffer import DataBuffer
from app.acquisition.serial_manager import SAMPLE_RATE, SerialManager
from app.ui import theme
from app.ui.main_window import MainWindow

ANALYSIS_SECONDS = 60.0       # how much signal the analysis sees

DEVICE_HELP = (
    "Check that the Arduino is plugged in, and that Arduino IDE's "
    "Serial Monitor is closed — only one program can use the port.\n\n"
    "To run on recorded data instead:\n"
    "py -m app.main --replay data/sample/100"
)


def parse_args():
    parser = argparse.ArgumentParser(description="ECG Analyzer")
    parser.add_argument("--replay", metavar="RECORD",
                        help="replay a recorded file (path without extension)")
    parser.add_argument("--channel", default="MLII",
                        help="channel to replay: MLII for MIT-BIH, ECG for your own recordings")
    return parser.parse_args()


def attach_replay(window, path, channel):
    """Play back a recorded file through the same pipeline as live data."""
    from app.acquisition.record_loader import RecordLoader
    from app.acquisition.replay_source import ReplaySource

    loader = RecordLoader(path, channel_name=channel)
    signal, fs = loader.load()
    buffer = DataBuffer(sample_rate=fs, window_seconds=ANALYSIS_SECONDS)
    source = ReplaySource(signal, fs, buffer, loop=True)
    window.attach_source(source, buffer, fs,
                         f"Replay · {path} · {fs:.0f} Hz", units=loader.units)


def attach_live(window):
    """Connect to the Arduino. Raises OSError if it is missing or busy."""
    serial_mgr = SerialManager()
    port = serial_mgr.connect()
    buffer = DataBuffer(sample_rate=SAMPLE_RATE, window_seconds=ANALYSIS_SECONDS)
    source = AcquisitionThread(serial_mgr, buffer)
    window.attach_source(source, buffer, SAMPLE_RATE,
                         f"Live · Arduino on {port} · {SAMPLE_RATE} Hz", units="adu")
    return serial_mgr


def main():
    args = parse_args()
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())
    window = MainWindow()

    serial_mgr = None
    if args.replay:
        attach_replay(window, args.replay, args.channel)
    else:
        try:
            serial_mgr = attach_live(window)
        except OSError as error:
            QMessageBox.critical(None, "ECG device not available",
                                 f"{error}\n\n{DEVICE_HELP}")
            return 1

    window.show()
    exit_code = app.exec()

    if serial_mgr is not None:
        serial_mgr.disconnect()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())