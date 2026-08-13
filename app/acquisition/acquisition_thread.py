"""Background thread that reads samples into a buffer.

Runs independently of the GUI so that blocking serial reads never
freeze the interface.
"""

import threading


class AcquisitionThread:
    """Reads from a SerialManager into a DataBuffer on a background thread."""

    def __init__(self, serial_manager, data_buffer):
        self.serial = serial_manager
        self.buffer = data_buffer
        self._thread = None
        self._running = threading.Event()

    def start(self):
        """Begin acquiring in the background."""
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        """Loop until stopped. Runs on the background thread."""
        while self._running.is_set():
            try:
                sample = self.serial.read_sample()
            except Exception:
                break
            if sample is not None:
                self.buffer.add(sample)

    def stop(self):
        """Stop acquiring and wait for the thread to finish."""
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()