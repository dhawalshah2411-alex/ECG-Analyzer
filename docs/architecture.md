# Architecture

Module structure, data flow, the methods behind every number, and the
design decisions that shaped them.

**Last updated:** 3 November 2026

---

## 1. Design principles

### 1.1 Layered separation

Each layer depends only on the layers below it:

```
Hardware -> Acquisition -> Signal processing -> Analysis -> Storage / Interface
```

No layer reaches upward. Acquisition does not know that a window
exists; signal processing does not know where its samples came from.

### 1.2 Source independence

The processing and analysis layers take an array of samples and a
sampling rate. They do not know whether the samples came from the
serial port or from a file. As a result:

- live and replayed data run through exactly the same code;
- every algorithm can be developed and scored on public reference
  data (MIT-BIH, at 360 Hz) before it touches a person, and the same
  code then runs on this hardware at 500 Hz.

### 1.3 Raw data is never altered

- Filtering always produces a new array; the raw signal is kept.
- Recordings are saved raw. Filtering is reapplied whenever a
  recording is opened.
- The live screen offers raw, filtered and overlay views.
- Nothing in the application deletes a recording.

### 1.4 No Qt below the interface

`app/acquisition/`, `app/signal_processing/`, `app/analysis/` and
`app/database/` contain no Qt imports. As a result:

- these layers are tested with `pytest` without opening a window;
- replay and the offline reports reuse them directly;
- a different interface could be built on the same core.

### 1.5 Every number is traceable

- Each measurement comes from a named, published method, cited in the
  code and on the screen that shows it.
- Every threshold is a named constant with a comment saying why it has
  that value. Many comments record the real recording or test that set
  the value.
- Analysis uses only the parts of a recording judged clean. Every
  screen says how much of the recording that was.

### 1.6 A missing number is better than a wrong one

When the signal cannot support a measurement, the interface shows a
dash and the reason, not a guess. Examples:

- **Live screen:** heart rate is hidden while the quality rating is "poor".
- **Recovery:** T30 is shown only when its fit is good.
- **Average beat:** intervals need at least 20 alike beats.

### 1.7 Privacy by structure

- Session files carry a subject ID only.
- Names and other identifying details live in one private file,
  `recordings/subjects_private.csv`.
- The whole `recordings/` folder is excluded from Git, so no
  physiological data can reach the public repository by accident.

---

## 2. Module structure

```
app/
├── main.py                    entry point: live or --replay
├── acquisition/
│   ├── serial_manager.py      finds the board by USB vendor ID; reads and checks samples
│   ├── acquisition_thread.py  background reading loop; records silences and errors
│   ├── data_buffer.py         rolling window for display, plus capture for recording
│   ├── record_loader.py       reads WFDB records (MIT-BIH and saved sessions)
│   └── replay_source.py       plays a recording back at its original rate
├── signal_processing/
│   ├── filters.py             band-pass and notch: zero-phase for analysis,
│   │                          streaming for the live display
│   └── signal_quality.py      bSQI and the quality rating
├── analysis/
│   ├── pipeline.py            one pass of the live analysis: beats, rate, quality
│   ├── r_peaks.py             Pan-Tompkins detector and a second, simpler detector
│   ├── heart_rate.py          rolling-median heart rate with plausibility limits
│   ├── intervals.py           average beat; P, QRS and T boundaries; PR, QRS, QT, QTc
│   ├── references.py          typical adult ranges and their sources
│   ├── report.py              resting report: clean parts, beat timing, variability
│   ├── exercise_test.py       exercise test: phases, rounds, peak, unusual beats
│   └── recovery.py            heart-rate recovery measures
├── database/
│   └── session_store.py       saves sessions (WFDB, CSV, JSON); private subject list
├── visualization/
│   └── ecg_plot.py            ECG on a paper-style grid
└── ui/
    ├── main_window.py         live dashboard and the session flow
    ├── recording_dialog.py    two-step form: the person, then the test
    ├── report_window.py       resting report
    ├── exercise_window.py     exercise test report
    ├── ecg_viewer.py          whole recording as ECG strips; saves pages as images
    ├── widgets.py             metric, quality and recording cards; phase banner
    └── theme.py               colours and fonts

firmware/arduino/ecg_acquisition/   14-bit sampling at 500 Hz, one value per line
tests/                              pytest suite (45 tests)
data/sample/                        MIT-BIH records 100, 105, 108, 203
```

---

## 3. Data flow

### 3.1 Live acquisition

```
Arduino (500 samples/s, one number per line over USB)
  -> SerialManager.read_sample()       checks each value is 0-16383
  -> AcquisitionThread                 background thread; notes silences
  -> DataBuffer                        last 60 s, plus everything since recording began
  ---------------------------------------------------------- thread boundary
  -> GUI timer every 33 ms             streaming filter -> ECG view, beat markers
  -> GUI timer every 500 ms            AnalysisPipeline -> heart rate, RR, SDNN, quality
```

The live analysis runs on the most recent 60 s each time:

1. zero-phase filter;
2. Pan-Tompkins beats;
3. second detector;
4. heart rate;
5. quality rating.

### 3.2 Threading model

| Thread      | Responsibility                                                                                             |
| ----------- | ---------------------------------------------------------------------------------------------------------- |
| Acquisition | Blocking serial reads; appends to the buffer; keeps any error and the times of silences. Never touches Qt. |
| GUI         | Timers, drawing, analysis, dialogs. Owns every Qt object.                                                  |

**Why a background thread.** A serial read blocks until data arrives.
A window blocked inside a read cannot redraw or respond, and cannot be
closed cleanly.

**Only the GUI thread touches Qt objects.** Breaking this rule causes
crashes that appear at random, minutes later.

**No lock on the buffer.**

- The GUI reads the sample array first and builds its time axis from
  that snapshot, so the two always match.
- A lock was rejected: it adds overhead to every sample at 500 Hz and
  risks deadlock.
- A one-sample-stale snapshot is invisible at 30 frames a second.

### 3.3 Recording session

```
idle -> details form -> settling (15 s) -> recording -> saved -> report opens
```

1. **Details form** (two steps):
   - first the person: name, age, gender, profession, city, and a
     required consent tick-box;
   - then the test: a resting recording, or an exercise test with its
     timetable of phases.
2. **Settling, 15 s.** The signal is shown but not saved while the
   electrodes settle. At the end, the number of samples received is
   checked against the computer's clock. If they arrived more than 5%
   off 500 per second, nothing is recorded and the person is told why.
   This check exists because an old sketch once sent about 6,400
   samples a second, which made every time and heart rate wrong with
   nothing on screen to show it.
3. **Recording.** The buffer captures every sample. Windows is kept
   awake so it cannot sleep mid-recording. During an exercise test a
   banner shows the phase, and the app beeps 5 s before and at every
   change.
4. **Saving.** The session is saved, and the report or exercise-test
   window opens.

### 3.4 Replay

```
WFDB record -> RecordLoader -> ReplaySource (at the record's own rate) -> DataBuffer -> same as live
```

### 3.5 Offline analysis

The report and exercise-test windows analyse the whole saved recording
at once with the same filters and detector. They can be reopened at any
time from PowerShell (see the README).

---

## 4. Signal processing and analysis

### 4.1 Filters

| Use          | Filter                                                                                                       | Why                                                                                                                                                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Analysis     | 2nd-order Butterworth band-pass 0.5–40 Hz, then a 50 Hz notch (Q 30), both zero-phase (forward and backward) | Zero-phase keeps peak timing exact                                                                                                                                    |
| Live display | The same filters, applied forward only, chunk by chunk, keeping their state                                  | Can show each new sample at once. Filtering only the last 4 s with the zero-phase filter on every frame distorted the newest edge of the trace by thousands of counts |

**The filter band is deliberately not narrower.** On the MIT-BIH Noise
Stress Test Database:

- narrowing the band changed nothing at light noise, because detection
  was already essentially perfect there;
- at heavy noise it reduced false beats only slightly (at 6 dB,
  positive predictivity rose from 66% to 76% at best).

Electrode-motion noise shares the heartbeat's own frequencies, so it is
reduced at the source instead: skin preparation, cable strain relief,
and steady movement.

### 4.2 Beat detection: Pan-Tompkins

Pan and Tompkins (1985):

1. band-pass at 5–15 Hz;
2. differentiate;
3. square;
4. integrate over 150 ms;
5. apply adaptive thresholds with searchback for missed beats.

Three additions, each made after a failure on real data:

- **T-wave rule (from the original paper).** A candidate within 360 ms
  of the previous beat, with less than half its steepest slope, is a T
  wave, not a beat. Without it, a real recording with unusually shaped
  beats had nearly every one of them counted twice.
- **Re-learning after silence.** If no beat has been accepted for 3 s,
  the thresholds are re-learned from the last 2 s. Otherwise loud noise
  can raise them so far that the detector stays deaf for the rest of
  the recording.
- **Peak refinement.** Each detection is moved to the true peak of the
  original signal.

**Result on all 48 MIT-BIH records** (91,285 beats; EC57 matching
within 150 ms, first 5 minutes of each record excluded):

- sensitivity 99.36%;
- positive predictivity 99.26%.

### 4.3 Signal quality

A second detector finds beats by height alone. Agreement between the
two is bSQI (Li, Mark & Clifford 2008): the beats both found, divided
by all the beats either found, over the last 10 s, matched within
150 ms.

| Rating | Rule                                                                                                                                          |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Good   | bSQI at least 9/11                                                                                                                            |
| Fair   | bSQI at least 2/3                                                                                                                             |
| Poor   | bSQI below 2/3; no beats found; an implausible heart rate; a flat signal; or the signal stuck at its limit for more than 10% of the last 10 s |

The rating answers one question: can this heart rate be trusted?
Problems that don't change the heart rate are added as notes, not as a
worse rating:

- R-wave tips cut off at the top of the range;
- a brief jolt to the limit.

**Known weakness.** Under heavy movement noise (6 dB or worse in the
noise stress test), both detectors are fooled by the same noise and
agree, so a wrong heart rate can be rated good or fair. Four further
checks were tested and rejected, because each either hid real heart
rates or failed to catch the wrong ones:

- regularity of beat gaps;
- kurtosis;
- spectral share;
- heart-rate continuity.

### 4.4 Heart rate

- The median of the last 8 gaps between beats. One missed or extra
  beat changes a single gap, which the median ignores.
- Values outside 30–300 bpm are not shown.

### 4.5 Clean and noisy parts (offline reports)

The recording is judged in 5-second blocks. A block is noisy if any of
these is true:

- the signal is stuck at its limit for 50 ms or more;
- it is more than 3 times noisier than the typical block;
- it swings 1.5 times higher than a typical R wave;
- the two detectors agree on less than 9/11 of beats.

For resting recordings, two further rules apply:

- a block is also rejected if two "beats" come closer than half the
  usual gap;
- the blocks either side of a noisy block are rejected too.

### 4.6 Early beats and long gaps

- **Early beat:** its gap is at least 20% shorter than **both** the gap
  just before it **and** the usual gap (the median of the 10 clean gaps
  around it).
- **Long gap:** at least 20% longer than both.

Requiring both is what separates early beats from breathing. Breathing
changes the gaps gradually, a few percent a beat, so each gap stays
close to the one before it. The first version, which compared with the
usual gap only, flagged ordinary breathing as long gaps.

Checked against cardiologists' marks on four MIT-BIH records:

- found 58 of the 66 premature beats;
- 10 false flags, against 20 for the first version.

### 4.7 Average beat and intervals

- Clean beats with normal timing and a shape similar to the first-pass
  average (correlation at least 0.90) are lined up on their R peaks.
  Their median is the average beat. At least 20 such beats are needed.
- P, QRS and T boundaries are found on that average with slope and
  tangent rules.
- PR, QRS, QT, and QTc by both Bazett and Fridericia are shown beside
  typical adult ranges, with their sources.
- These rules have not yet been checked against annotated data (the
  PhysioNet QT Database), and QT is not trusted on this board.

### 4.8 Exercise test

The test is one continuous recording that follows a timetable:

```
rest before -> exercise 1 -> rest 1 -> ... -> exercise N -> recovery
```

**Changes from the resting rules, each made after a real test:**

- **No "too close" or neighbour rules.** On the first real test they
  threw away two-thirds of a readable rest. Odd gaps are removed beat
  by beat instead.
- **The second detector looks only above 5 Hz.** Walking sways the
  trace about twice a second, lifting T waves over its height
  threshold.
- **Beats within 2 s of a noisy block are left out.** Noise spills
  over the block edge. In one test, beats there made a false peak of
  143 bpm where the ECG shows 110–120.

**What it measures:**

- **Heart-rate curve:** one point a second, the median of the beats
  within 2.5 s. Gaps stay gaps; they are never joined across noise.
- **Each round:** heart rate at its start and end, its rise, its peak,
  and the fall in the 60 s after it ends.
- **Peak heart rate,** as a share of the age-predicted maximum,
  208 − 0.7 × age (Tanaka et al. 2001).
- **Resting variability** from the rest before: SDNN and RMSSD (Task
  Force 1996).
- **Unusual beats in the still phases:** each beat's QRS (100 ms before
  R to 120 ms after) is compared with the usual resting beat.
  - A similarity under 0.6 marks it.
  - Beats with noise as steep as a QRS beside them are not judged.
  - Exercise phases are never judged.

### 4.9 Heart-rate recovery

- **Resting heart rate:** the last 60 s before exercise.
- **Heart rate at the stop:** the beats in the last 5 s before
  stopping, if at least 3 are clean. Otherwise the beats from 3 s
  before to 5 s after are used, and flagged; they read slightly low.
- **At 10, 60 and 120 s after the stop:** heart rate (median within
  ±2.5 s), the fall since the stop, and the share of the exercise rise
  recovered. The share is shown only if the heart rose at least 5 bpm.
- **T30** (Imai et al. 1994): a time constant from a straight-line fit
  to log(heart rate) over the first 30 s. Shown only if the fit
  explains at least 70% of the variation and the fall is at least 3
  times the beat-to-beat scatter.
- **Back to rest:** the first time the heart rate, having been above
  the band, is within 10% of resting and stays there for 10 s.

---

## 5. Storage and privacy

Each session is saved three ways:

| File                   | Contents                                                                                                                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.dat` + `.hea` (WFDB) | The raw samples, in the PhysioNet research format, so recordings replay through the same loader as MIT-BIH                                                                         |
| `.csv`                 | The same samples with times, readable in any spreadsheet                                                                                                                           |
| `.json`                | Subject ID, age, gender, notes, test type and phases, settings, measured sample rate, any bad samples replaced and signal gaps with their times, and why a recording stopped early |

**Where things live:**

- **File names:** `recordings/<ID>/<ID>_<date>_<time>`, for example
  `recordings/S005/S005_20261024_164633`.
- **Identifying details:** in `recordings/subjects_private.csv`, which
  links each ID to a name.
- **If that file is open in Excel:** Windows blocks writing to it, so
  the app says so and offers Retry instead of crashing.

There is no database yet. Files are easy to inspect and to share as a
dataset; SQLite can come once session management needs queries.

---

## 6. Robustness

| Failure                                                              | What the application does                                                                                                |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Board plugged into a different USB socket                            | Found by USB vendor ID (0x2341), not by COM port number                                                                  |
| A garbled or out-of-range line from the serial port                  | Replaced by the last good sample so timing stays correct; counted, and its position kept and saved                       |
| No data for 1 s while the port stays open (the port's wait runs out) | Recorded as a signal gap with its time; shown in the header                                                              |
| Board unplugged mid-recording                                        | Recording stopped and what was captured saved; the reason is shown; the port is found again when the next session starts |
| Wrong sample rate from old firmware                                  | Detected while settling; nothing recorded                                                                                |
| Windows going to sleep on battery                                    | Prevented while a recording runs                                                                                         |
| Detector deafened by loud noise                                      | Thresholds re-learned after 3 s without a beat                                                                           |

---

## 7. Key decisions

### 7.1 Processing in software, not firmware

The firmware samples and sends; it does no filtering or detection.
Firmware is harder to test and change, and cannot be applied to
recorded data. Keeping it minimal means the same processing runs on
live and recorded signals.

### 7.2 Fixed-size rolling buffer, separate capture

- **The display window** is a `deque` with a maximum length: memory
  stays constant however long the screen runs.
- **Recording** is separate. Once it starts, every sample is captured,
  so nothing recorded is ever discarded by the window.

### 7.3 Redraw at 30 Hz, analyse at 2 Hz, sample at 500 Hz

- Drawing faster than about 30 frames a second uses processor time for
  no visible gain.
- Analysis twice a second keeps the numbers current.
- No sample is lost: only drawing and analysis are throttled.

### 7.4 Bad samples are counted, not hidden

A failing USB connection shows up as replaced samples and silences, and
these are saved with the recording. Without this, a cable fault could
be mistaken for a filtering problem.

### 7.5 The quality rating is about the heart rate

Replaying two real exercise tests through the first rating rule showed
the problem with judging the signal's looks:

- the heart rate was hidden for 15–18% of the exercise;
- yet, where it could be checked, it was within about 1 bpm of the
  finished analysis.

The rule now judges only whether the heart rate can be trusted. A
recording where an electrode really came off is still rated poor.

### 7.6 Validate on public data before people

Every detector change is scored against cardiologist-annotated
PhysioNet records before it is used on a person, and the scores are
reported with confidence intervals.

---

## 8. Testing

**Run:** `py -m pytest tests` (45 tests). No hardware is needed.

| Test file                    | What it checks                                                                                                                                    |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_detector.py`           | Detection against MIT-BIH annotations                                                                                                             |
| `test_serial_manager.py`     | Bad, out-of-range and missing serial values, using a pretend port                                                                                 |
| `test_acquisition_thread.py` | Silences, errors and restarts in the reading thread                                                                                               |
| `test_signal_quality.py`     | Each quality rule on its own                                                                                                                      |
| `test_beat_timing.py`        | Early beats and long gaps against made-up gap series with known answers                                                                           |
| `test_recovery.py`           | Recovery measures on synthetic recordings with a known answer                                                                                     |
| `test_exercise_test.py`      | A synthetic 17-minute exercise test with walking noise and a burst of heavy noise: rounds, peak, recovery and variability against the true values |
| `test_unusual_beats.py`      | The unusual-beat check, including two cases the first version got wrong                                                                           |

---

## 9. Known limitations

| Item                                          | Status                                                                                                        |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Single lead                                   | Limited information on wave shape; cannot rule out a heart attack                                             |
| Amplitudes in ADC counts                      | Not calibrated to millivolts                                                                                  |
| R-wave tips clipped at the current board gain | Heart rate unaffected; heights not reliable                                                                   |
| Live heart rate under heavy movement noise    | Can be wrong while rated good or fair (section 4.3)                                                           |
| PR, QRS, QT boundaries                        | Not yet checked against annotated data; QT not trusted on this board                                          |
| Signal gaps                                   | Recorded with their times, but not yet used by the analysis                                                   |
| QRS direction                                 | The second detector assumes the QRS points up; a recording with a mainly downward QRS is rated poor too often |
| Reference-device comparison                   | Not done yet (planned: Polar H10, Bland–Altman)                                                               |
| Long sessions                                 | Recordings of up to about 17 minutes so far; no longer endurance test yet                                     |

---

## 10. Scope

This is research and educational analysis, not clinical diagnosis.
Measurements are estimates from one lead. The system makes no
diagnostic claims and does not screen for any condition.
