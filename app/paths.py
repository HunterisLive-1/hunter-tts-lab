"""Where everything lives.

The app folder holds the program. The data folder holds everything the app
creates or downloads: voices, clips, engines, models, settings. Deleting the
data folder puts the app back to a fresh install.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
# Set HUNTER_TTS_LAB_DATA to keep the data somewhere else, for instance on a
# bigger drive: the models take 2 to 3 GB each.
DATA = Path(os.environ.get("HUNTER_TTS_LAB_DATA") or ROOT / "data")

RUNTIMES = DATA / "runtimes"  # the audio.cpp program, one folder per device kind
MODELS = DATA / "models"  # one folder per voice model
VOICES = DATA / "voices"  # saved reference voices
OUTPUTS = DATA / "outputs"  # generated clips
DOWNLOADS = DATA / "downloads"  # files in flight; safe to delete
LOGS = DATA / "logs"

CONFIG = DATA / "config.json"
HISTORY = DATA / "history.json"
VOICE_INDEX = DATA / "voices.json"
INSTALLED = DATA / "installed.json"


def ensure() -> None:
    for d in (DATA, RUNTIMES, MODELS, VOICES, OUTPUTS, DOWNLOADS, LOGS):
        d.mkdir(parents=True, exist_ok=True)
