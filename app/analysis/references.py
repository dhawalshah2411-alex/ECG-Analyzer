"""Typical adult reference ranges, and where each one comes from.

Shown beside measurements for context only. A value inside or outside
a range on a one-lead, uncalibrated device is not a diagnosis.
Every range was checked against its source before being added here;
anything without a checked source is left without a range.
"""

from dataclasses import dataclass

SOURCES = {
    "mayo_hr": "Mayo Clinic. Heart rate: What's normal? "
               "(60 to 100 beats per minute for adults at rest)",
    "statpearls_ecg": "Sattar Y, Chhabra L. Electrocardiogram. StatPearls, "
                      "NCBI Bookshelf NBK549803",
    "aha_2009_qt": "Rautaharju PM, Surawicz B, Gettes LS, et al. AHA/ACCF/HRS "
                   "recommendations for the standardization and interpretation "
                   "of the electrocardiogram, Part IV: the ST segment, T and U "
                   "waves, and the QT interval. Circulation, 2009",
}


@dataclass(frozen=True)
class Reference:
    text: str           # how the range is shown, e.g. "120–200 ms"
    source: str         # key into SOURCES


_RANGES = {
    "heart_rate": Reference("60–100 bpm at rest", "mayo_hr"),
    "p_duration": Reference("up to about 120 ms", "statpearls_ecg"),
    "pr_interval": Reference("120–200 ms", "statpearls_ecg"),
    "qrs": Reference("under 120 ms (usually 60–100)", "statpearls_ecg"),
}

_QTC = {
    "male": Reference("under 450 ms (men)", "aha_2009_qt"),
    "female": Reference("under 460 ms (women)", "aha_2009_qt"),
    None: Reference("under 450 ms (men) · 460 ms (women)", "aha_2009_qt"),
}


def reference(name, sex=None):
    """The reference for a measurement, or None if there isn't a checked one.

    sex: the form's gender answer; only QTc limits differ by sex.
    """
    if name == "qtc":
        key = sex.lower() if isinstance(sex, str) and sex.lower() in ("male", "female") else None
        return _QTC[key]
    return _RANGES.get(name)