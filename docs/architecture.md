# Architecture

Module structure, data flow, and the design decisions behind them.

**Last updated:** 12 August 2026

---

## 1. Design Principles

### 1.1 Layered separation

The system is organised as a sequence of layers, each depending only
on the layer below it:

Hardware
→ Acquisition
→ Signal processing
→ Analysis
→ Visualization
→ Storage

No layer reaches upward. Acquisition does not know that a GUI exists;
signal processing does not know where its samples came from.

### 1.2 Source independence

The processing and analysis layers accept a stream of samples and a
sampling rate. They do not know whether those samples arrived from a
serial port or were read from a file.

This is what makes replay mode possible: the same pipeline runs on
live and recorded data without modification. It also makes algorithm
development possible without a subject attached, which is both more
practical and more rigorous — a recorded dataset can be replayed
identically to test whether a change actually improved anything.

### 1.3 Raw data is never destroyed

Filtering produces a new array. The raw signal remains available for
display, comparison and storage throughout. The interface supports
raw, filtered and overlay views.

### 1.4 No GUI framework below the visualization layer

`app/acquisition/`, `app/signal_processing/` and `app/analysis/`
contain no Qt imports. Consequences:

- These layers can be tested with `pytest` without launching a GUI.
- Replay mode can reuse them directly.
- A different interface could be built on the same core.

---

## 2. Module Structure

app/
├── acquisition/
│ ├── serial_manager.py port discovery, reading, error counting
│ ├── data_buffer.py fixed-size rolling window
│ └── acquisition_thread.py background reading loop
├── signal_processing/
│ ├── filters.py band-pass, notch
│ ├── preprocessing.py baseline correction
│ └── signal_quality.py noise and contact assessment
├── analysis/
│ ├── r_peaks.py R-peak detection
│ ├── heart_rate.py rate from RR intervals
│ └── intervals.py PR, QRS, QT estimation
├── visualization/
│ ├── ecg_plot.py waveform widget
│ └── dashboard.py metric displays
├── database/
│ ├── models.py schema
│ └── database.py session persistence
└── ui/
├── main_window.py window, navigation, timers
└── components/ reusable widgets

---

## 3. Data Flow

### 3.1 Live acquisition

Arduino → SerialManager.read_sample()
↓
AcquisitionThread (background thread)
↓
DataBuffer.add()
↓
───────────────────────────── thread boundary
↓
QTimer, ~30 Hz (GUI thread)
↓
DataBuffer.get_values()
↓
filters → analysis → plot

### 3.2 Threading model

Two threads share one buffer.

| Thread      | Responsibility                                                 |
| ----------- | -------------------------------------------------------------- |
| Acquisition | Blocking serial reads, appending to the buffer. No GUI access. |
| GUI         | Timer-driven redraw, reading from the buffer. All Qt objects.  |

**Constraint.** Qt objects may only be accessed from the GUI thread.
Violating this produces intermittent crashes that are difficult to
reproduce and diagnose.

**Why a background thread is required.** A serial read blocks until
data arrives. A GUI blocked inside a read cannot redraw or respond to
input, producing an application that appears frozen and cannot be
closed cleanly.

**Synchronisation.** The buffer is not locked. The GUI reads the
sample array first and derives its time axis from that snapshot, so
the two always match even if the buffer grows in between. A lock was
considered and rejected: it would add overhead at 500 Hz and
introduce deadlock risk, in exchange for correctness that a display
refresh does not require.

### 3.3 Replay

Recorded file → sample array
↓
filters → analysis → plot

Identical from the processing layer onward.

---

## 4. Key Decisions

### 4.1 Processing in software, not firmware

The firmware samples and transmits. It performs no filtering or
detection.

**Rationale.** Firmware is harder to test, harder to change, and
cannot be applied to recorded data. Keeping the microcontroller
minimal means the same processing runs identically on live and
recorded signals, and can be developed without hardware attached.

### 4.2 Fixed-size rolling buffer

**Problem.** At 500 Hz the system produces 1.8 million samples per
hour. Unbounded storage grows until the application fails — typically
after tens of minutes, which is precisely when a demonstration
would be running.

**Solution.** `collections.deque` with `maxlen`. Appending to a full
deque discards from the opposite end automatically. Memory use is
constant regardless of session length.

**Scope.** This is the display and analysis window only. Persistent
recording is a separate concern; nothing is permanently discarded by
this mechanism.

### 4.3 Board discovery by USB vendor ID

**Problem.** Windows assigns COM port numbers per USB socket. A
hard-coded port number breaks whenever the board is plugged into a
different socket.

**Solution.** `SerialManager` enumerates ports and matches on USB
vendor ID `0x2341`.

### 4.4 Redraw at 30 Hz, sample at 500 Hz

Display refresh is decoupled from acquisition rate. The eye cannot
resolve faster than approximately 30 fps, so redrawing at the sample
rate would consume CPU for no visible benefit. No data is lost —
only the drawing is throttled.

The plot curve is created once and its data replaced each frame.
Creating a new curve per frame would accumulate objects and degrade
within minutes.

### 4.5 Parse failures are counted, not ignored

`SerialManager` counts lines it cannot parse rather than discarding
them silently.

**Rationale.** Dropped samples are a genuine signal-quality
indicator — a failing USB connection would appear here first. Silent
failure would mean debugging the filters while the fault lay in the
cable.

### 4.6 CSV before SQLite

Early recording uses CSV. SQLite is introduced only once session
management requires it.

**Rationale.** A database adds schema, migration and query concerns
before there is anything to query. CSV is inspectable in any text
editor, which is valuable while the recording format is still
changing.

---

## 5. Known Limitations

| Item                                                                     | Status                                                                      |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `AcquisitionThread` catches all exceptions to exit cleanly on disconnect | Should become a specific exception type with the error surfaced to the user |
| `app/` is not yet a proper Python package                                | Test scripts use a temporary `sys.path` insertion                           |
| No error reporting path to the interface                                 | Required before recording is implemented                                    |
| Long-duration stability                                                  | Partially tested                                                            |

---

## 6. Scope Limitation

Automated feature detection is research and educational analysis, not
clinical diagnosis. Detected features are reported as candidates and
estimates. The system makes no diagnostic claims.
