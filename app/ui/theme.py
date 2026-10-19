"""Visual theme for the ECG Analyzer interface.

All colours, fonts and shared styling live here, so the look of the
whole application can be adjusted from one file.
"""

FONT_FAMILY = "Segoe UI"        # Windows system font, always installed

# Surfaces
WINDOW_BG = "#F4F3EF"           # behind everything
PANEL_BG = "#FFFFFF"            # header and control bar
CARD_BG = "#F8F7F4"             # metric cards
BORDER = "#E2E0D9"

# Text
TEXT_PRIMARY = "#1F1E1C"
TEXT_SECONDARY = "#5F5E5A"
TEXT_MUTED = "#8A8984"

# The single accent colour — used sparingly
ACCENT = "#A32D2D"

# Selected-button colours (view toggle)
SELECTED_BG = "#E6F1FB"
SELECTED_TEXT = "#0C447C"
SELECTED_BORDER = "#B5D4F4"

# Signal quality states: (background, text)
QUALITY_COLOURS = {
    "good": ("#EAF3DE", "#27500A"),
    "fair": ("#FAEEDA", "#633806"),
    "poor": ("#FCEBEB", "#791F1F"),
    "unknown": ("#F1EFE8", "#444441"),
}


def stylesheet():
    """Application-wide Qt stylesheet."""
    return f"""
    QWidget {{
        font-family: "{FONT_FAMILY}";
        color: {TEXT_PRIMARY};
    }}
    QMainWindow, QWidget#central {{
        background: {WINDOW_BG};
    }}
    QFrame#panel {{
        background: {PANEL_BG};
        border: none;
    }}
    QFrame#card {{
        background: {CARD_BG};
        border-radius: 8px;
    }}
    QLabel#cardLabel {{
        color: {TEXT_SECONDARY};
        font-size: 12px;
    }}
    QLabel#muted {{
        color: {TEXT_MUTED};
        font-size: 12px;
    }}
    QPushButton#segment {{
        background: transparent;
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 5px 14px;
        color: {TEXT_SECONDARY};
        font-size: 13px;
    }}
    QPushButton#segment:checked {{
        background: {SELECTED_BG};
        color: {SELECTED_TEXT};
        border-color: {SELECTED_BORDER};
    }}
    """