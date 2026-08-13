"""Serial acquisition from the Arduino ECG firmware.

Finds the board by USB vendor ID, reads one integer sample per line,
and reports how many lines could not be parsed.
"""

import serial
from serial.tools import list_ports

ARDUINO_VID = 0x2341
BAUD_RATE = 115200
SAMPLE_RATE = 500


def find_arduino_port():
    """Return the port name of the first Arduino found, or None."""
    for port in list_ports.comports():
        if port.vid == ARDUINO_VID:
            return port.device
    return None


class SerialManager:
    """Reads ECG samples from the Arduino over USB serial."""

    def __init__(self, port=None, baud=BAUD_RATE):
        self.port = port
        self.baud = baud
        self._serial = None
        self.samples_read = 0
        self.bad_lines = 0

    def connect(self):
        """Open the serial port. Raises IOError if no board is found."""
        if self.port is None:
            self.port = find_arduino_port()
        if self.port is None:
            raise IOError("No Arduino found. Is it plugged in?")

        self._serial = serial.Serial(self.port, self.baud, timeout=1)
        return self.port

    def read_sample(self):
        """Return the next sample as an int, or None if the line was unusable."""
        raw = self._serial.readline()
        try:
            return int(raw.decode("ascii").strip())
        except (ValueError, UnicodeDecodeError):
            self.bad_lines += 1
            return None

    def disconnect(self):
        """Close the port if it is open."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        self._serial = None
        