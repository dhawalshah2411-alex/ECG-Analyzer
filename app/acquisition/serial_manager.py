"""Serial acquisition from the Arduino ECG firmware.

Finds the board by USB vendor ID and reads one integer sample per line.

The Arduino sends exactly one line every 2 ms, so every line is one
sample slot. A line that arrives but can't be a real sample still stands
for one slot, and dropping it would make every later sample, and every
later beat, 2 ms early. So a bad line is replaced by the last good sample
and counted, and its position is kept so it can be reported. A real
recording (S002, 23 Oct) had one such line: 507693, which a 14-bit
reading can never be (the most is 16383). It sat between 7650 and 7745
and was accepted as a sample, which made a false beat and hid a real one.
"""

import serial
from serial.tools import list_ports

ARDUINO_VID = 0x2341
BAUD_RATE = 115200
SAMPLE_RATE = 500
ADC_MAX = 2 ** 14 - 1        # the firmware reads 14 bits: every real sample is 0..16383
MAX_POSITIONS = 1000         # remember where the first 1000 bad lines were (all are counted)


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
        self._last = None          # the last good sample, to stand in for a bad line
        self.samples_read = 0      # every sample handed on, repaired ones included
        self.bad_lines = 0         # lines that arrived but were not a real sample
        self.bad_at = []           # their positions, as sample numbers (0 = first sample)

    def connect(self):
        """Open the serial port. Raises IOError if no board is found."""
        if self.port is None:
            self.port = find_arduino_port()
        if self.port is None:
            raise IOError("No Arduino found. Is it plugged in?")

        self._serial = serial.Serial(self.port, self.baud, timeout=1)
        return self.port

    def flush(self):
        """Discard any data waiting in the port's input buffer.

        The Arduino keeps sending while acquisition is paused, and the
        operating system stores those samples. Without flushing, they
        would all arrive at once when acquisition restarts — old signal
        presented as live, and possibly saved into a new recording. The
        last good sample is forgotten too, so a bad first line after the
        pause can't be filled in with a value from before it.
        """
        if self._serial is not None and self._serial.is_open:
            self._serial.reset_input_buffer()
        self._last = None

    def read_sample(self):
        """Return the next sample as an int, or None if there is no sample.

        - A good line (a whole number from 0 to 16383): that number.
        - A bad line (garbled, or out of range): the last good sample
          instead, counted in bad_lines and its position kept in bad_at.
          The first line after connecting or flushing is often a fragment;
          with no good sample yet to repeat, it is counted and skipped.
        - Nothing for 1 s (the cable was pulled, the board stopped): None.
          That is a gap in the signal, not a sample, so it is never filled in.
        """
        raw = self._serial.readline()
        if not raw:
            return None
        try:
            value = int(raw.decode("ascii").strip())
        except (ValueError, UnicodeDecodeError):
            value = None
        if value is None or not 0 <= value <= ADC_MAX:
            self.bad_lines += 1
            if self._last is None:
                return None
            if len(self.bad_at) < MAX_POSITIONS:
                self.bad_at.append(self.samples_read)
            value = self._last
        else:
            self._last = value
        self.samples_read += 1
        return value

    def disconnect(self):
        """Close the port if it is open."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        self._serial = None