# ECG Analyzer

A low-cost single-lead ECG system built from scratch: a BioAmp EXG Pill
amplifier, an Arduino UNO R4 Minima sampling at 500 Hz with 14-bit
resolution, and a Python desktop application that filters the signal,
finds every heartbeat, rates how far each reading can be trusted, and
measures heart-rate recovery after exercise.

> **Not a medical device.** This is an engineering and educational
> instrument. It is not certified for clinical use, it does not screen
> for or diagnose any condition, and its output must not be used to make
> decisions about anyone's health.

---

## Signal chain

```
Body surface (about 1 mV)
  -> 3 gel electrodes
  -> BioAmp EXG Pill (amplification and band-pass filtering)
  -> Arduino UNO R4 Minima (14-bit ADC, 500 samples per second)
  -> USB serial, 115200 baud
  -> Desktop application (filtering, beat detection, analysis, display)
```

The Arduino only acquires samples. All processing happens in the
application, so recorded data runs through exactly the same pipeline as
a live signal.

---

## What it does

| Part                | What it shows or measures                                                                                                                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Live screen         | ECG on a paper-style grid (raw, filtered or both), beat markers, heart rate, RR interval, variability (SDNN), heart-rate trend, and a signal-quality rating with its reason                                   |
| Recording           | A details form with a required consent tick-box, timed sessions (resting or exercise test), and a settling period before recording starts                                                                     |
| Report              | Clean and noisy parts of the recording, heart rate and its range, early beats and long gaps, SDNN and RMSSD, and the average beat with PR, QRS and QT/QTc beside typical adult ranges and their sources       |
| Exercise test       | Rest, rounds of exercise and rest, then recovery, with on-screen phases and beeps; heart rate through the whole test, each round's rise and fall, and peak heart rate as a share of the age-predicted maximum |
| Heart-rate recovery | Fall at 10, 60 and 120 s after stopping, share of the exercise rise recovered, T30, and time to return within 10% of resting                                                                                  |
| Whole-ECG viewer    | Every second of a recording as strips of ECG paper                                                                                                                                                            |

**Data handling:**

- The raw signal is saved untouched, as WFDB, CSV and JSON.
- Corrupted serial samples and signal gaps are counted and their times saved with the recording.
- Recordings are stored under subject IDs only. Names stay in a separate private file.
- Recordings and that file are excluded from this repository.

---

## Validation

All figures below were measured on public reference data or on this
hardware. Methods are named so each one can be checked.

| Test                                                                                                                                                                                    | Result                                                                                                                               |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Beat detection, all 48 records of the MIT-BIH Arrhythmia Database (91,285 cardiologist-annotated beats; ANSI/AAMI EC57 matching within 150 ms, first 5 minutes of each record excluded) | Sensitivity 99.36% (95% CI 99.31–99.41), positive predictivity 99.26% (95% CI 99.21–99.32)                                           |
| Beat detection under electrode-motion noise, MIT-BIH Noise Stress Test Database (12 records)                                                                                            | Signal-to-noise 24 and 18 dB: sensitivity 100%, positive predictivity 99.9%. At 12 dB: 100% and 91.7%. At 6 dB and below, unreliable |
| Sampling rate                                                                                                                                                                           | 500.0 Hz measured (5,001 samples in 10.00 s, none dropped)                                                                           |
| Repeatability                                                                                                                                                                           | One volunteer recorded three times at rest: 80, 81 and 82 bpm                                                                        |
| Automated tests                                                                                                                                                                         | 45 tests, including synthetic exercise tests with a known answer                                                                     |

---

## Known limitations

- **One lead only.** It cannot rule out a heart attack, and it gives limited information about wave shape.
- **Uncalibrated amplitudes.** They are in raw ADC counts, not millivolts.
- **Clipped R waves.** At the board's current gain, tall R waves are clipped at the top of the range. Heart rate is unaffected; R-wave height is not reliable.
- **Unvalidated intervals.** PR and QT have not been checked against a reference, and QT is not trusted on this board.
- **Heavy movement noise can fool the live heart rate.** In the noise stress test, at 6 dB or worse the live screen often showed a wrong heart rate while rating it good or fair. Recovery is measured while the person is still, and the finished analysis leaves noisy stretches out. The live number during vigorous movement should not be relied on.
- **No reference-device comparison yet.** The planned reference is a Polar H10 chest strap, compared using Bland–Altman analysis.
- **Small informal volunteer set, no ethics approval.** No dataset will be published until ethics approval is in place.

---

## Requirements

- Windows, Python 3.13 or later
- Arduino IDE 2.x with the Arduino UNO R4 board package
- BioAmp EXG Pill, Arduino UNO R4 Minima, 3 gel electrodes

## Setup

```powershell
git clone https://github.com/dhawalshah2411-alex/ECG-Analyzer.git
cd ECG-Analyzer
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

Upload `firmware/arduino/ecg_acquisition/ecg_acquisition.ino` to the
board first. The application finds the board by its USB vendor ID.

## Running

| Task                        | Command                                                           |
| --------------------------- | ----------------------------------------------------------------- |
| Live, from the Arduino      | `py -m app.main`                                                  |
| Replay a reference record   | `py -m app.main --replay data/sample/100`                         |
| Replay your own recording   | `py -m app.main --replay recordings/S001/<session> --channel ECG` |
| Reopen a recording's report | `py -m app.ui.report_window recordings/S001/<session>`            |
| Reopen an exercise test     | `py -m app.ui.exercise_window recordings/S001/<session>`          |
| Run the tests               | `py -m pytest tests`                                              |

**Electrical safety:**

- While electrodes are on a person, run the laptop on battery with the charger unplugged.
- Power the BioAmp only from the Arduino's 5 V pin.

See [docs/hardware.md](docs/hardware.md) for wiring and safety notes.

---

## Methods and sources

- **Filtering:** 0.5–40 Hz band-pass and a 50 Hz notch, zero-phase for analysis.
- **Beat detection:** Pan J, Tompkins WJ. A real-time QRS detection algorithm. _IEEE Trans Biomed Eng_ 1985;32(3):230–236.
- **Signal quality (bSQI, agreement of two detectors):** Li Q, Mark RG, Clifford GD. _Physiol Meas_ 2008;29(1):15–32.
- **Heart-rate variability:** Task Force of the ESC and NASPE. _Circulation_ 1996;93(5):1043–1065.
- **Age-predicted maximum heart rate (208 − 0.7 × age):** Tanaka H, Monahan KD, Seals DR. _J Am Coll Cardiol_ 2001;37(1):153–156.
- **Heart-rate recovery:**
  - The 1-minute fall: Cole CR et al. _N Engl J Med_ 1999;341(18):1351–1357.
  - T30: Imai K et al. _J Am Coll Cardiol_ 1994;24:1529–1535.
- **Reference data:**
  - MIT-BIH Arrhythmia Database: Moody GB, Mark RG. _IEEE Eng Med Biol Mag_ 2001;20(3):45–50.
  - MIT-BIH Noise Stress Test Database: Moody GB, Muldrow WE, Mark RG. _Computers in Cardiology_ 1984;11:381–384.
  - Both are from [PhysioNet](https://physionet.org).

---

## Repository layout

```
firmware/            Arduino acquisition firmware
app/
  acquisition/       serial reading, buffering, background thread, replay
  signal_processing/ filters and signal quality
  analysis/          beat detection, heart rate, intervals, reports,
                     exercise test and recovery
  visualization/     ECG plot
  database/          session storage
  ui/                windows: live screen, report, exercise test, ECG viewer
tests/               automated tests (pytest)
docs/                hardware and architecture documentation
data/sample/         MIT-BIH records 100, 105, 108 and 203
```

## Documentation

- [Hardware reference](docs/hardware.md): pinout, wiring, configuration, acquisition settings and safety
- [Architecture](docs/architecture.md): module structure, data flow and design decisions

## License

MIT. See [LICENSE](LICENSE).
