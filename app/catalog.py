"""Everything the app can download, pinned to an exact file and checksum.

Nothing here is made by this project. The engine is audio.cpp (ShugoAI,
Apache 2.0); the voice models are Chatterbox (Resemble AI, MIT) and VoxCPM2
(OpenBMB, Apache 2.0), in the GGUF packages published for audio.cpp. They are
fetched from their own official pages at install time and checked against the
hashes below, so a broken or swapped download is refused instead of run.

The numbers in NEEDS and SPEED were measured on one PC (Ryzen 5 5600, RTX 5060
Ti 16 GB, 32 GB RAM) on 2026-10-08, with text fed in pieces of 250 characters
the way this app feeds it. They are a guide for the recommendation, and the
app replaces them with what it measures on the user's own PC after install.
"""

from __future__ import annotations

AUDIOCPP_VERSION = "v0.9.1"
_REL = f"https://github.com/0xShug0/audio.cpp/releases/download/{AUDIOCPP_VERSION}"
_GGUF = "https://huggingface.co/audio-cpp/audio.cpp-gguf/resolve/9c78726d0d2cf7ee8511e68ef003490c1251062f"

FILES: dict[str, dict] = {
    "cuda13-bin": {
        "url": f"{_REL}/audio-{AUDIOCPP_VERSION}-bin-windows-x64-cuda13.3.zip",
        "size": 273940483,
        "sha256": "dd04894fae8bb0d1365b4f62407fb51550558a6478f1ef719cad7aefc00720de",
    },
    "cuda13-libs": {
        "url": f"{_REL}/audio-{AUDIOCPP_VERSION}-cudart-windows-x64-cuda13.3.zip",
        "size": 575457454,
        "sha256": "fa0fb817540c578bad085c7befb9d25b5a7634548e47955bff7b732b04b8a84b",
    },
    "cuda12-bin": {
        "url": f"{_REL}/audio-{AUDIOCPP_VERSION}-bin-windows-x64-cuda12.4.zip",
        "size": 462376707,
        "sha256": "f32a40f8fb14ac4772c9c25525f97715db228979178e51654da73aa65005c0ef",
    },
    "cuda12-libs": {
        "url": f"{_REL}/audio-{AUDIOCPP_VERSION}-cudart-windows-x64-cuda12.4.zip",
        "size": 607273675,
        "sha256": "8bfdce7cb00b5a51560b5ab0d444344d86a2f0d7e2727bb7f18c15ef4734451b",
    },
    "vulkan-bin": {
        "url": f"{_REL}/audio-{AUDIOCPP_VERSION}-bin-windows-x64-vulkan.zip",
        "size": 61526433,
        "sha256": "3425c4e60f36c16d50b5418e37b8a5f2811741237a8575ae645c119fbceeadd4",
    },
}

# One runtime per way of running the engine. "libs" are the NVIDIA libraries
# that have to sit next to the program.
RUNTIMES: dict[str, dict] = {
    "cuda13": {"label": "NVIDIA graphics card", "on": "the NVIDIA graphics card", "backend": "cuda", "bin": "cuda13-bin", "libs": "cuda13-libs"},
    "cuda12": {"label": "NVIDIA graphics card (older driver or card)", "on": "the NVIDIA graphics card", "backend": "cuda", "bin": "cuda12-bin", "libs": "cuda12-libs"},
    "vulkan": {"label": "Graphics card through Vulkan", "on": "the graphics card, through Vulkan", "backend": "vulkan", "bin": "vulkan-bin", "libs": None},
    # The engine's own "cpu" download stops with an illegal-instruction error
    # on processors without AVX-512 (it did on a Ryzen 5 5600), and its
    # "cpu-portable" download took 421 s for a 2.4 s sentence. The fast CPU
    # code ships inside the NVIDIA package, so the CPU runtime is that package
    # without the NVIDIA parts. One library has to stay or the program will
    # not start; only that one file is taken out of the 575 MB archive.
    "cpu": {
        "label": "Processor only (no graphics card)",
        "on": "the processor",
        "backend": "cpu",
        "bin": "cuda13-bin",
        "libs": "cuda13-libs",
        "leave_out": ("ggml-cuda", "cublas", "cudart"),
        "only_libs": ("cufft64_12.dll",),
    },
}

MODELS: dict[str, dict] = {
    "chatterbox": {
        "name": "Chatterbox",
        "by": "Resemble AI",
        "license": "MIT",
        "home": "https://github.com/resemble-ai/chatterbox",
        "family": "chatterbox",
        "task": "clon",
        "folder": "Chatterbox-GGUF",
        "file": "chatterbox-q8_0.gguf",
        "url": f"{_GGUF}/Chatterbox-GGUF/chatterbox-q8_0.gguf",
        "size": 2088393668,
        "sha256": "d586dd1aa59613cab8046176fb7ca5ba191c02a9b10ffa5b0d892ed22b470656",
        "needs_voice": True,
        "summary": "Light on memory. Clear in Hindi script.",
        "detail": "Reads Hindi written in Devanagari best. For Hindi typed in English letters, polish the script first.",
    },
    "voxcpm2": {
        "name": "VoxCPM2",
        "by": "OpenBMB",
        "license": "Apache 2.0",
        "home": "https://github.com/OpenBMB/VoxCPM",
        "family": "voxcpm2",
        "task": "tts",
        "folder": "VoxCPM2-GGUF",
        "file": "voxcpm2-q8_0.gguf",
        "url": f"{_GGUF}/VoxCPM2-GGUF/voxcpm2-q8_0.gguf",
        "size": 2955000480,
        "sha256": "c8e01ab4416011e12a28f24ede298a1aa5ce64b43f8e8aaad53b1e2fe7c96432",
        "needs_voice": False,
        "summary": "Best at Hinglish. Studio-quality sound, needs more memory.",
        "detail": "Reads Hindi typed in English letters almost as well as Hindi script. 48 kHz output.",
    },
}

# Memory each model needs for one piece of text, in GB. vram = graphics
# memory, ram = PC memory.
NEEDS: dict[str, dict] = {
    "chatterbox": {"cuda": {"vram": 3.5, "ram": 1.4}, "vulkan": {"vram": 3.5, "ram": 1.6}, "cpu": {"ram": 3.2}},
    "voxcpm2": {"cuda": {"vram": 5.0, "ram": 4.1}, "vulkan": {"vram": 6.5, "ram": 6.8}, "cpu": {"ram": 9.1}},
}

# Seconds of work for 10 seconds of voice on the test PC.
SPEED: dict[str, dict] = {
    "chatterbox": {"cuda": 4.9, "vulkan": 6.4, "cpu": 55},
    "voxcpm2": {"cuda": 4.8, "vulkan": 8.6, "cpu": 59},
}
TEST_PC = "Ryzen 5 5600, RTX 5060 Ti 16 GB"

# A script is cut into pieces of at most this many characters and the engine
# is started once per piece. Graphics memory grows with the length of what
# the engine is given in one go: VoxCPM2 took 4.7 GB for one line and 10 GB
# for a 967-character page. The engine's own chunking option was tried and
# is not used: it kept VoxCPM2 to 6.2 GB but raised Chatterbox from 4.4 GB
# to 6.1 GB. One start per piece keeps both at their one-line figure, and
# lets the app show progress and stop between pieces.
PIECE_CHARS = 250
