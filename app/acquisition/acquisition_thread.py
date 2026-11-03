"""Background thread that reads samples into a buffer.

Runs independently of the GUI so that blocking serial reads never
freeze the interface.

Two things can interrupt the signal. Both are recorded, not hidden, so
the window can say what happened and a recording can be marked:

- The link fails (the USB cable is pulled, the board resets). Reading
  raises an error; the thread stops and keeps the error in .error.
  Before, it stopped silently: the trace froze and a recording's timer
  stood still, with nothing on screen to say why.
- Nothing arrives while the link stays open (the board stopped
  sending), so the port gives up waiting after 1 s. Each silence is kept
  in .gaps_at, as the number of samples that had arrived before it. The
  samples on either side of a gap are not continuous, so beat-to-beat
  times across it would be wrong.
"""

import threading
import time

SILENCE_S = 0.5     # a read that came back empty after this long is the port's 1 s wait
                    # running out, not a skipped fragment (those return at once). Not
                    # 1.0: a wait timed at 0.9999 s must still count.


class AcquisitionThread:
    """Reads from a SerialManager into a DataBuffer on a background thread."""

    def __init__(self, serial_manager, data_buffer, clock=time.monotonic):
        self.serial = serial_manager
        self.buffer = data_buffer
        self._clock = clock
        self._thread = None
        self._running = threading.Event()
        self.error = None           # why reading stopped by itself, if it did
        self.gaps_at = []           # buffer.total_added at the start of each silence

    def start(self):
        """Begin acquiring in the background, discarding stale data first."""
        if self._thread is not None and self._thread.is_alive():
            return
        self.serial.flush()
        self.error = None
        self.gaps_at = []
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        """Loop until stopped. Runs on the background thread."""
        last = self._clock()
        silent = False
        while self._running.is_set():
            try:
                sample = self.serial.read_sample()
            except Exception as error:      # any failure: keep it, so the window can say so
                self.error = error
                break
            now = self._clock()
            if sample is None:
                if not silent and now - last >= SILENCE_S:
                    silent = True
                    self.gaps_at.append(self.buffer.total_added)
                continue
            silent = False
            last = now
            self.buffer.add(sample)
        self._running.clear()

    def stop(self):
        """Stop acquiring and wait for the thread to finish."""
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def failed(self):
        """True if reading stopped by itself because of an error (see .error)."""
        return self.error is not None