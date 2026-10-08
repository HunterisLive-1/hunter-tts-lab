"""The name and the credit line. Every screen, banner and page takes them from here."""

NAME = "Hunter TTS Lab"
VERSION = "1.0.0"
CREDIT = "Built & customized by The Hunter AI"
CHANNEL_NAME = "The Hunter AI"
CHANNEL_URL = "https://www.youtube.com/@TheHunter-AI"
REPO_URL = "https://github.com/HunterisLive-1/hunter-tts-lab"


def banner() -> str:
    line = "=" * 62
    return f"{line}\n  {NAME}  v{VERSION}\n  {CREDIT}\n  {CHANNEL_URL}\n{line}"
