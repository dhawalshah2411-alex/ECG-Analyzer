"""Tests for app/acquisition/acquisition_thread.py, with a pretend reader and clock.

No Arduino needed. The pretend reader hands over prepared results: a
sample, None (nothing arrived), or an error to raise. When it runs out
it raises, as pyserial does when the USB cable is pulled. The pretend
clock gives the time of each read, so a silence can be tested without
waiting for it.
"""

from app.acquisition.acquisition_thread import SILENCE_S, AcquisitionThread
from app.acquisition.data_buffer import DataBuffer


class PretendReader:
    def __init__(self, results):
        self._results = list(results)

    def flush(self):
        pass

    def read_sample(self):
        item = self._results.pop(0) if self._results else OSError("pretend: cable pulled")
        if isinstance(item, Exception):
            raise item
        return item


def run(results, times, thread=None):
    """Run the thread until the pretend reader runs out, and return it.

    times: the clock at the start, then at each read that didn't raise.
    """
    clock = iter(times)
    if thread is None:
        thread = AcquisitionThread(None, DataBuffer(sample_rate=500, window_seconds=10))
    thread.serial = PretendReader(results)
    thread._clock = lambda: next(clock)
    thread.start()
    thread._thread.join(timeout=2.0)
    return thread


def test_samples_go_into_the_buffer():
    thread = run([8000, 8001, 8002], [0.0, 0.002, 0.004, 0.006])
    assert list(thread.buffer.get_values()) == [8000, 8001, 8002]
    assert thread.gaps_at == []


def test_a_failed_link_is_kept_not_hidden():
    thread = run([8000], [0.0, 0.002])
    assert thread.failed
    assert isinstance(thread.error, OSError)
    assert not thread.is_running
    assert thread.buffer.total_added == 1


def test_a_silence_is_recorded_once_where_it_happened():
    # Two samples, then nothing for two seconds, then the signal returns.
    thread = run([8000, 8001, None, None, 8002, 8003],
                 [0.0, 0.002, 0.004, 0.004 + SILENCE_S, 2.004, 2.006, 2.008])
    assert thread.gaps_at == [2]          # after the second sample
    assert thread.buffer.total_added == 4


def test_a_quick_skipped_line_is_not_a_gap():
    """The first line after connecting is often a fragment: skipped at once, no silence."""
    thread = run([None, 8000], [0.0, 0.001, 0.003])
    assert thread.gaps_at == []
    assert thread.buffer.total_added == 1


def test_any_unexpected_error_is_kept_too():
    thread = run([8000, ValueError("a bug")], [0.0, 0.002])
    assert isinstance(thread.error, ValueError)


def test_it_can_start_again_after_a_failure():
    thread = run([8000], [0.0, 0.002])
    assert thread.failed
    run([8001, 8002], [0.0, 0.002, 0.004], thread=thread)
    assert thread.buffer.total_added == 3    # it really ran again