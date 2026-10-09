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

## Only if you install OmniVoice

OmniVoice is the optional third model. It has no audio.cpp build that reads
Hindi typed in English letters properly, so it runs the way its authors ship
it: in Python, on PyTorch. The app sets that up inside its own `data` folder.
Nothing is installed into Windows, and a Python you already have is not used
or changed.

| What | Made by | Licence | Downloaded from |
|---|---|---|---|
| OmniVoice, the code | k2-fsa (Han Zhu and others) | Apache 2.0 | pypi.org (`omnivoice` 0.2.1) |
| OmniVoice, the voice model | k2-fsa | **CC-BY-NC: free for non-commercial use** | huggingface.co/k2-fsa/OmniVoice |
| Higgs Audio v2 tokenizer, shipped inside the OmniVoice model | Boson AI | Boson Higgs Audio 2 Community Licence | huggingface.co/k2-fsa/OmniVoice |
| Whisper large-v3-turbo, writes down what a voice recording says | OpenAI | MIT | huggingface.co/openai/whisper-large-v3-turbo |
| PyTorch 2.8.0 and torchaudio | The PyTorch Foundation | BSD-3-Clause | download.pytorch.org |
| NVIDIA CUDA libraries inside PyTorch (NVIDIA builds only) | NVIDIA | NVIDIA software licences | shipped inside the PyTorch download |
| Python 3.11 (python-build-standalone), runs OmniVoice | Python Software Foundation, packaged by Astral | PSF Licence | github.com/astral-sh/python-build-standalone |
| About 85 other Python packages (transformers, numpy, librosa and what they need) | their authors | their own open-source licences | pypi.org |

The Python packages are listed one by one, each with its checksums, in
`app/omni-requirements.txt`. pip refuses any file that does not match.

The OmniVoice model's licence is about the model files, and it is its
authors' to explain: read it on the model's page before using OmniVoice
clips in paid work. Chatterbox and VoxCPM2 have no such limit.

`web/sample-voice.wav` was generated with VoxCPM2 with no reference voice. It
is a computer-made voice, not a recording of a person.

Script polishing is optional and uses Google's Gemini API with your own key,
under Google's terms.
