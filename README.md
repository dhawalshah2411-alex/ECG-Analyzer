# ECG Analyzer

A desktop application for acquiring, visualizing and analyzing
electrocardiogram signals, built around a BioAmp EXG Pill analog
front end and an Arduino UNO R4 Minima.

> **Not a medical device.** This is an engineering and educational
> instrument. It is not certified for clinical use and its output
> must not be used for diagnosis.

---

## Signal chain

Body surface potential (~1 mV)
→ Gel electrodes
→ BioAmp EXG Pill analog amplification
→ Arduino UNO R4 Minima 14-bit ADC, 500 Hz
→ USB serial 115200 baud
→ Desktop application filtering, analysis, display

The microcontroller performs acquisition only. All signal processing
and analysis happen in the desktop application, which keeps the
firmware simple and allows the same processing pipeline to run on
recorded data as on a live signal.

---

## Status

Acquisition and live display are working. Signal processing and
analysis are in progress.

| Capability                       | State                          |
| -------------------------------- | ------------------------------ |
| Fixed-rate acquisition firmware  | Working — measured at 500.0 Hz |
| Serial acquisition and buffering | Working                        |
| Real-time waveform display       | Working                        |
| Filtering                        | Not started                    |
| R-peak detection and heart rate  | Not started                    |
| Recording and replay             | Not started                    |

---

## Requirements

- Python 3.13 or later
- Arduino IDE 2.x with the Arduino UNO R4 board package
- BioAmp EXG Pill, Arduino UNO R4 Minima, 3 gel electrodes

## Setup

```bash
git clone https://github.com/dhawalshah2411-alex/ECG-Analyzer.git
cd ECG-Analyzer
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

Upload `firmware/arduino/ecg_acquisition/ecg_acquisition.ino` to the
board before running the application. The application locates the
board automatically by USB vendor ID.

---

## Repository layout

firmware/ Arduino acquisition firmware
app/ Desktop application
acquisition/ serial reading, buffering, threading
signal_processing/ filtering and signal quality
analysis/ R-peak detection, heart rate, intervals
visualization/ plotting
database/ session storage
ui/ windows and components
tests/ Automated tests
docs/ Documentation
data/ Sample datasets

---

## Documentation

- [Hardware reference](docs/hardware.md) — pinout, wiring,
  configuration decisions, acquisition settings and safety notes
- [Architecture](docs/architecture.md) — module structure and
  data flow

---

## License

See [LICENSE](LICENSE).
