# What Hunter TTS Lab downloads, and whose it is

This repository holds only the app: the page, the small local server and the
installer logic. It is MIT licensed (see `LICENSE`).

The parts that actually make a voice are not in this repository. The app
downloads them from their authors' own pages when you press Install, checks
each file against a pinned SHA-256 checksum (`app/catalog.py`), and keeps
them in the `data` folder on your PC. Their licences apply to them, not ours.

| What | Made by | Licence | Downloaded from |
|---|---|---|---|
| audio.cpp v0.9.1, the engine that runs the models | ShugoAI LLC | Apache 2.0 | github.com/0xShug0/audio.cpp (releases) |
| Chatterbox, voice model | Resemble AI | MIT | huggingface.co/audio-cpp/audio.cpp-gguf |
| VoxCPM2, voice model | OpenBMB | Apache 2.0 | huggingface.co/audio-cpp/audio.cpp-gguf |
| NVIDIA CUDA runtime libraries (only on NVIDIA cards, and one of them for the CPU engine) | NVIDIA | NVIDIA CUDA Toolkit EULA | shipped with the audio.cpp release |
| Python 3.13 (embeddable), runs the app's local server | Python Software Foundation | PSF Licence | python.org |

`web/sample-voice.wav` was generated with VoxCPM2 with no reference voice. It
is a computer-made voice, not a recording of a person.

Script polishing is optional and uses Google's Gemini API with your own key,
under Google's terms.
