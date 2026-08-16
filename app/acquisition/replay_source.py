"""Replays a recorded signal at its original rate.

Feeds a DataBuffer exactly as AcquisitionThread does, so the same
display and processing pipeline runs on recorded and live data.
"""

import threading
import time


class ReplaySource:
    """Streams a recorded signal into a buffer in real time."""

    def __init__(self, signal, sample_rate, data_buffer, loop=False):
        self.signal = signal
        self.sample_rate = sample_rate
        self.buffer = data_buffer
        self.loop = loop
        self.position = 0
        self._thread = None
        self._running = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        period = 1.0 / self.sample_rate
        next_due = time.perf_counter()

        while self._running.is_set():
            if self.position >= len(self.signal):
                if not self.loop:
                    break
                self.position = 0

            self.buffer.add(self.signal[self.position])
            self.position += 1

            next_due += period
            delay = next_due - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_due = time.perf_counter()

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()