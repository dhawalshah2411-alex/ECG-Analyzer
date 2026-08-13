# Hardware Reference

Hardware configuration for the ECG Analyzer acquisition system.
All values in this document were verified against the physical
hardware or measured directly. Figures taken from manufacturer
documentation are marked as such.

**Last verified:** 12 August 2026

---

## 1. Overview

### 1.1 Signal chain

Body surface potential (~1 mV)
→ Gel electrodes
→ BioAmp Cable v3
→ BioAmp EXG Pill (amplification + analog filtering)
→ Arduino UNO R4 Minima (14-bit ADC, 500 Hz sampling)
→ USB serial (115200 baud)
→ Desktop application

### 1.2 Division of responsibility

| Stage                 | Responsibility                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------- |
| BioAmp EXG Pill       | Analog front end. Amplifies the microvolt-level body signal to a range the ADC can resolve. |
| Arduino UNO R4 Minima | Data acquisition only. Samples at a fixed rate and streams values. No analysis.             |
| Desktop application   | All filtering, analysis, visualization and storage.                                         |

The Arduino is deliberately kept lightweight. Moving processing
into firmware would make it harder to test, harder to change, and
would prevent the same processing pipeline being reused for replay
of recorded data.

---

## 2. Component Inventory

| Item                   | Model / Detail                             | Quantity |
| ---------------------- | ------------------------------------------ | -------- |
| Biopotential amplifier | BioAmp EXG Pill v1.0 (MAR 2023), assembled | 1        |
| Electrode cable        | BioAmp Cable v3                            | 1        |
| Gel electrodes         | Disposable, pre-gelled                     | 12       |
| Microcontroller        | Arduino UNO R4 Minima                      | 1        |
| Jumper wires           | Male-to-female                             | 3        |
| Breadboard             | Standard half-size                         | 1        |

### 2.1 Consumable note

Gel electrodes are single-use. The conductive gel dries and adhesion
degrades after removal, so they cannot be reliably reapplied. Three
electrodes are required per recording session.

---

## 3. BioAmp EXG Pill

### 3.1 Board identification

| Property       | Value                                     |
| -------------- | ----------------------------------------- |
| Manufacturer   | Upside Down Labs                          |
| Product        | BioAmp EXG Pill                           |
| Board revision | v1.0                                      |
| Date marking   | MAR 2023                                  |
| Main IC        | Texas Instruments OPA4323PW (quad op-amp) |
| Supply         | 5 V                                       |

### 3.2 MCU-side header (3-pin)

Silkscreen labels, reading along the board edge:

| Pin   | Function                                            |
| ----- | --------------------------------------------------- |
| `OUT` | Amplified analog output → microcontroller ADC input |
| `GND` | Ground / common reference                           |
| `VCC` | Supply input, 5 V                                   |

### 3.3 Electrode connector (3-pin JST)

| Pin   | Function                             |
| ----- | ------------------------------------ |
| `REF` | Reference electrode (body reference) |
| `IN+` | Non-inverting input                  |
| `IN-` | Inverting input                      |

### 3.4 Configuration pads

Four solder-pad groups are present on the reverse of the board.
**All four are currently unbridged**, confirmed by visual inspection
under magnification on 11 August 2026.

| Pad group    | Silkscreen options | Current state                |
| ------------ | ------------------ | ---------------------------- |
| `GAIN`       | —                  | Unbridged (default)          |
| `ELECTRODES` | `3E` / `2E`        | Unbridged — 3-electrode mode |
| `FILTER`     | —                  | Unbridged (default)          |
| `BANDPASS`   | `EMG/ECG`          | Unbridged — EEG/EOG default  |

---

## 4. Configuration Decisions

### 4.1 BANDPASS jumper — deliberately left unbridged

**Status:** Not soldered.

**Background.** Per manufacturer documentation, the board ships
configured for EEG and EOG acquisition. Bridging the `BANDPASS`
pads reconfigures the analog filtering for EMG and ECG.

**Manufacturer position.** The documentation states that ECG can be
recorded without the solder bridge, and that the bridge improves
accuracy rather than enabling the capability. It also notes that
signal clipping can occur when recording ECG with electrodes placed
very close to the heart, which the jumper helps address.

**Decision rationale.**

1. The modification is permanent and cannot easily be reversed.
2. Modifying hardware before any signal has been observed removes
   the ability to attribute a later fault to a specific cause.
   With the jumper unsoldered, a poor signal can only be wiring,
   firmware, software or electrode contact.
3. Recording the same subject before and after the modification
   provides a directly comparable measurement of its effect,
   which is of documentary value to this project.

**Revisit condition.** Reassess once a clean ECG has been recorded
in the current configuration and its amplitude and clipping
behaviour have been characterised.

### 4.2 ELECTRODES jumper — permanently excluded

**Status:** Not soldered. Not to be soldered.

**Rationale.** Bridging these pads selects 2-electrode mode.
Manufacturer documentation restricts this configuration to
battery-operated setups and warns of high interference noise
resulting from the absence of a proper body reference. This system
is powered from a mains-connected laptop over USB, making
3-electrode operation with a dedicated reference the correct choice.

---

## 5. Wiring

### 5.1 Connection table

| BioAmp pin | Arduino pin          | Wire colour (this build) |
| ---------- | -------------------- | ------------------------ |
| `GND`      | `GND` (POWER header) | Black                    |
| `VCC`      | `5V`                 | Yellow                   |
| `OUT`      | `A0`                 | Red                      |

### 5.2 Notes on pin selection

- **`5V`, not `VIN` or `3.3V`.** The BioAmp is a 5 V board.
  `VIN` is an unregulated external supply input.
- **`GND` in the POWER header**, adjacent to `5V`. All ground pins
  on the Arduino are electrically common; the power-header pin is
  used so that supply and return form a visually adjacent pair.
- **`A0`.** Manufacturer example code uses `A0`. If changed, the
  `ECG_PIN` constant in the firmware must be updated to match.

### 5.3 Assembly procedure

1. Disconnect USB before making or altering any connection.
2. Connect `GND` first. Ground is the reference against which all
   other potentials are measured.
3. Connect `VCC`, then `OUT`.
4. Verify every connection at both ends before reapplying power.
   Each jumper is a single continuous conductor; a wire displaced
   at the far end can route ground into an analog input or supply
   voltage to an unintended pin.

---

## 6. Acquisition Configuration

### 6.1 ADC

| Parameter              | Value               |
| ---------------------- | ------------------- |
| Resolution             | 14 bits             |
| Output range           | 0 – 16383           |
| Reference              | 5 V (board default) |
| Approximate resolution | ~0.3 mV per count   |

The UNO R4's ADC defaults to 10-bit for backward compatibility.
The firmware calls `analogReadResolution(14)` explicitly. The
manufacturer specifically recommends the UNO R4 for biopotential
acquisition on the basis of this 14-bit converter.

### 6.2 Sampling rate

| Parameter     | Value    |
| ------------- | -------- |
| Target rate   | 500 Hz   |
| Sample period | 2000 µs  |
| Measured rate | 500.0 Hz |

**Selection rationale.** The Nyquist criterion sets a hard floor of
roughly 80 Hz, since QRS complex content extends to approximately
40 Hz. However, satisfying Nyquist alone preserves only the presence
of the complex, not its shape; QRS duration measurement requires
adequate shape fidelity. 500 Hz yields approximately 12 samples
across a typical QRS complex and aligns with both clinical
(500–1000 Hz) and research (250–500 Hz) practice.

**Verification.** Measured by counting received samples over a
fixed 10-second window: 5001 samples in 10.00 s = 500.0 Hz.
This was verified empirically rather than assumed, because a rate
error propagates directly into every heart-rate and interval
calculation without producing any visibly incorrect waveform.

### 6.3 Serial link

| Parameter   | Value                                           |
| ----------- | ----------------------------------------------- |
| Baud rate   | 115200                                          |
| Format      | One decimal integer per line, `\r\n` terminated |
| USB VID:PID | `2341:0069`                                     |

At 115200 baud a maximum-width sample (`16383\r\n`, 7 characters)
occupies approximately 610 µs of the 2000 µs sample period,
leaving adequate margin.

Port assignment is not fixed — Windows allocates COM numbers per
USB socket. The application locates the board by USB vendor ID
(`0x2341`) rather than by port name.

---

## 7. Baseline Characteristics

Measured with no electrodes connected (floating input):

| Property             | Value                    |
| -------------------- | ------------------------ |
| Resting level        | ~8200 – 8400 counts      |
| Theoretical mid-rail | 8192 counts              |
| Observed variation   | ~200 counts peak-to-peak |

The amplifier centres its output near mid-supply so that the signal
can swing in both directions. A floating high-impedance input
couples ambient electromagnetic interference, producing the observed
variation. This is expected behaviour and serves as a useful
reference: a reading pinned at 0 or 16383 would indicate a fault.

Contact with the electrode connector produces a large deflection
followed by a slow settling period, as the body couples mains-frequency
interference into the input and residual charge dissipates.

---

## 8. Safety

### 8.1 Operating constraints

- The system operates at 5 V, supplied via USB from a laptop.
- Electrodes must only be connected in the manufacturer's
  documented 3-electrode configuration.
- No voltage source other than the BioAmp output is to be
  connected to the electrode leads.
- Do not operate while the host laptop is connected to a mains
  charger if avoidable; battery operation reduces leakage-current
  paths to earth.

### 8.2 Handling

The BioAmp is a sensitive analog front end and its input stage is
susceptible to electrostatic discharge.

- Store in antistatic packaging, not plastic bags or foam.
- Touch an earthed metal object before handling.
- Do not allow exposed header pins to contact conductive surfaces.

### 8.3 Scope limitation

This is an engineering and educational instrument. It is not a
medical device, is not certified for clinical use, and its output
must not be used for diagnosis.

---

## 9. Open Items

| Item                                      | Status                                            |
| ----------------------------------------- | ------------------------------------------------- |
| BANDPASS jumper evaluation                | Pending first clean ECG recording                 |
| Electrode placement configuration         | Not yet established                               |
| Amplifier gain figure                     | Not yet confirmed from manufacturer documentation |
| Analog bandwidth in current configuration | Not yet confirmed                                 |
| Long-duration acquisition stability       | Partially tested                                  |
