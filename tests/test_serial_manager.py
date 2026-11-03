"""Tests for app/acquisition/serial_manager.py, with a pretend serial port.

No Arduino needed: the pretend port hands over prepared lines exactly as
pyserial's readline() would, including b"" when nothing arrives in time.
"""

from app.acquisition.serial_manager import ADC_MAX, SerialManager


class PretendPort:
    def __init__(self, lines):
        self._lines = list(lines)
        self.is_open = True

    def readline(self):
        return self._lines.pop(0) if self._lines else b""

    def reset_input_buffer(self):
        self._lines.clear()


def manager_with(lines):
    manager = SerialManager(port="pretend")
    manager._serial = PretendPort(lines)
    return manager


def read_all(manager, count):
    return [manager.read_sample() for _ in range(count)]


def test_good_lines_are_read_as_numbers():
    manager = manager_with([b"8000\r\n", b"0\r\n", f"{ADC_MAX}\r\n".encode()])
    assert read_all(manager, 3) == [8000, 0, 16383]
    assert manager.samples_read == 3
    assert manager.bad_lines == 0


def test_impossible_value_is_replaced_and_reported():
    """The real case from 23 Oct: 507693 between 7650 and 7745."""
    manager = manager_with([b"7650\r\n", b"507693\r\n", b"7745\r\n"])
    assert read_all(manager, 3) == [7650, 7650, 7745]
    assert manager.bad_lines == 1
    assert manager.bad_at == [1]              # the second sample
    assert manager.samples_read == 3          # the slot is kept, so timing stays right


def test_garbled_and_negative_lines_are_replaced():
    manager = manager_with([b"8000\r\n", b"80\xff0\r\n", b"-5\r\n", b"\r\n", b"8100\r\n"])
    assert read_all(manager, 5) == [8000, 8000, 8000, 8000, 8100]
    assert manager.bad_lines == 3
    assert manager.bad_at == [1, 2, 3]


def test_first_fragment_is_skipped_not_invented():
    manager = manager_with([b"0\xff\r\n", b"8000\r\n"])
    assert read_all(manager, 2) == [None, 8000]
    assert manager.bad_lines == 1
    assert manager.bad_at == []                # it never became a sample
    assert manager.samples_read == 1


def test_nothing_arriving_is_a_gap_not_a_sample():
    manager = manager_with([b"8000\r\n"])
    assert read_all(manager, 3) == [8000, None, None]
    assert manager.bad_lines == 0
    assert manager.samples_read == 1


def test_flush_forgets_the_last_sample():
    """After a pause, a bad first line must not be filled with a value from before it."""
    manager = manager_with([b"8000\r\n"])
    manager.read_sample()
    manager.flush()
    manager._serial = PretendPort([b"99999\r\n", b"8200\r\n"])
    assert read_all(manager, 2) == [None, 8200]