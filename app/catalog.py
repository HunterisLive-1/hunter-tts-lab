"""Everything the app can download, pinned to an exact file and checksum.

Nothing here is made by this project. The engine is audio.cpp (ShugoAI,
Apache 2.0); the voice models are Chatterbox (Resemble AI, MIT) and VoxCPM2
(OpenBMB, Apache 2.0), in the GGUF packages published for audio.cpp. They are
fetched from their own official pages at install time and checked against the
hashes below, so a broken or swapped download is refused instead of run.

OmniVoice (k2-fsa) is the optional third model. There is no good audio.cpp
build of it, so it runs the way its authors ship it: in Python, on PyTorch.
The app sets that up in a folder of its own (see omni_engine.py); nothing is
installed into Windows and a Python the user already has is never touched.

The numbers in NEEDS and SPEED were measured on one PC (Ryzen 5 5600, RTX 5060
Ti 16 GB, 32 GB RAM) on 2026-10-08, with text fed in pieces of 250 characters
the way this app feeds it. They are a guide for the recommendation, and the
app replaces them with what it measures on the user's own PC after install.
"""

from __future__ import annotations

AUDIOCPP_VERSION = "v0.9.1"
_REL = f"https://github.com/0xShug0/audio.cpp/releases/download/{AUDIOCPP_VERSION}"
_GGUF = "https://huggingface.co/audio-cpp/audio.cpp-gguf/resolve/9c78726d0d2cf7ee8511e68ef003490c1251062f"
_TORCH = "https://download.pytorch.org/whl"
_OMNI = "https://huggingface.co/k2-fsa/OmniVoice/resolve/c5fdb5ccb189668d56333f77ba2629f4cd7535f4"
_WHISPER = "https://huggingface.co/openai/whisper-large-v3-turbo/resolve/41f01f3fe87f28c78e2fbf8b568835947dd65ed9"

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
    # OmniVoice's own Python (python-build-standalone 3.11.15, the version it
    # was tested on) and PyTorch 2.8.0 in three builds.
    "python311": {
        "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20260310/cpython-3.11.15%2B20260310-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
        "size": 26071247,
        "sha256": "9302cfe055216e60309bb99961d8a093189183af8dd27a3bd7c40d5e6252090b",
    },
    "torch-cu128": {
        "url": f"{_TORCH}/cu128/torch-2.8.0%2Bcu128-cp311-cp311-win_amd64.whl",
        "unpacked": int(6.88 * 1024**3),  # on disk, before the parts nobody needs are taken out again
        "size": 3461420395,
        "sha256": "34c55443aafd31046a7963b63d30bc3b628ee4a704f826796c865fdfd05bb596",
    },
    "torchaudio-cu128": {
        "url": f"{_TORCH}/cu128/torchaudio-2.8.0%2Bcu128-cp311-cp311-win_amd64.whl",
        "size": 4678509,
        "sha256": "7a1eb6154e05b8056b34c7a41495e09d57f79eb0180eb4e7f3bb2a61845ca8ea",
    },
    "torch-cu126": {
        "url": f"{_TORCH}/cu126/torch-2.8.0%2Bcu126-cp311-cp311-win_amd64.whl",
        "unpacked": int(6.14 * 1024**3),  # on disk, before the parts nobody needs are taken out again
        "size": 2915474854,
        "sha256": "cfb2c640a8955fbd8686c056802f53a512b610c098960d6dad5800cbc16c02b6",
    },
    "torchaudio-cu126": {
        "url": f"{_TORCH}/cu126/torchaudio-2.8.0%2Bcu126-cp311-cp311-win_amd64.whl",
        "size": 4242362,
        "sha256": "48e19338f6fd24588cd5608b21087d00b80e30ddf054d9ce83f792a4b0025d7f",
    },
    "torch-cpu": {
        "url": f"{_TORCH}/cpu/torch-2.8.0%2Bcpu-cp311-cp311-win_amd64.whl",
        "unpacked": int(2.93 * 1024**3),  # on disk, before the parts nobody needs are taken out again
        "size": 619392861,
        "sha256": "7631ef49fbd38d382909525b83696dc12a55d68492ade4ace3883c62b9fc140f",
    },
    "torchaudio-cpu": {
        "url": f"{_TORCH}/cpu/torchaudio-2.8.0%2Bcpu-cp311-cp311-win_amd64.whl",
        "size": 2501032,
        "sha256": "db37df7eee906f8fe0a639fdc673f3541cb2e173169b16d4133447eb922d1938",
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
    # OmniVoice's Python with PyTorch. PyTorch has to match the card: the
    # newest NVIDIA build drives the 50 series but not the GTX 900 and 1000
    # series, and the build before it is the other way round. There is no
    # PyTorch for AMD or Intel cards on Windows, so those PCs use the processor.
    "torch-cu128": {"kind": "torch", "label": "NVIDIA graphics card (PyTorch)", "on": "the NVIDIA graphics card", "backend": "cuda",
                    "torch": "torch-cu128", "torchaudio": "torchaudio-cu128"},
    "torch-cu126": {"kind": "torch", "label": "NVIDIA graphics card, older kind (PyTorch)", "on": "the NVIDIA graphics card", "backend": "cuda",
                    "torch": "torch-cu126", "torchaudio": "torchaudio-cu126"},
    "torch-cpu": {"kind": "torch", "label": "Processor only (PyTorch)", "on": "the processor", "backend": "cpu",
                  "torch": "torch-cpu", "torchaudio": "torchaudio-cpu"},
}  # fmt: skip

# The other Python packages OmniVoice needs are listed, each with its
# checksums, in omni-requirements.txt next to this file. About this much is
# downloaded for them.
TORCH_PACKAGES_BYTES = 200 * 1024**2


def _omni(path: str, size: int, sha256: str) -> dict:
    return {"path": path, "url": f"{_OMNI}/{path}", "size": size, "sha256": sha256}


def _whisper(path: str, size: int, sha256: str) -> dict:
    return {"path": f"whisper/{path}", "url": f"{_WHISPER}/{path}", "size": size, "sha256": sha256}


# OmniVoice copies a voice from the recording plus the words spoken in it.
# Whisper (OpenAI, MIT) writes those words down, once per saved voice, so the
# user is never asked to type them.
_OMNI_FILES = [
    _omni("model.safetensors", 2450344112, "730839316de585f4c8298ec0e1712efc10fb19c6fa4e36eb741cb8d51ebcf6aa"),
    _omni("audio_tokenizer/model.safetensors", 805665628, "fe7c5e8785e0a05833e1bfc3e002ec7f55af21e306b2e7154a448c1f54ccfb0d"),
    _omni("tokenizer.json", 11423986, "408f669b7e2b045fdf54201d815bd364e6667dbd845115da81239c40bc6dcfd1"),
    _omni("config.json", 2238, "5e359117e13b420c5e0c925d4aba650d624767131f1d1746928f8b850d5dc372"),
    _omni("tokenizer_config.json", 533, "49f78845596a82bf15c83673794bdf9f76f812b11f60ab6a2239d9be65b00676"),
    _omni("chat_template.jinja", 4168, "a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8"),
    _omni("audio_tokenizer/config.json", 2531, "eefb20806f7104e77c9a5277c9df0f9bb8826b08eb1d4e8ab2b9829b6ef9fac1"),
    _omni("audio_tokenizer/preprocessor_config.json", 206, "ae61eea88558608ee2fa86d2aec9fce8d99a5ff75d09cb7651ccce21ae1d9084"),
    _whisper("model.safetensors", 1617824864, "542566a422ae4f3fd23f1ba11add198fca01bbf82e66e6a2857b3f608b1eb9d1"),
    _whisper("tokenizer.json", 2710337, "297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd"),
    _whisper("vocab.json", 1036558, "e2aa043ef015641d363d8288e7c241c85e36a5c761fb303598e0710233344387"),
    _whisper("merges.txt", 493869, "2df2990a395e35e8dfbc7511e08c12d56018d8d04691e0133e5d63b21e154dc6"),
    _whisper("tokenizer_config.json", 282843, "844b642c73a91359722f47b35705f7174686df33d252695d8572cf9ac03a6389"),
    _whisper("normalizer.json", 52666, "bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd"),
    _whisper("added_tokens.json", 34648, "3c51f66c4c21f9e126970078f11ae77a78c74aee8df606ee9daba86e467108e0"),
    _whisper("generation_config.json", 3772, "cce11bfe3aaa6ae9e072ea2637caaec8795e68d9b67e655a5af16ee509681a4c"),
    _whisper("special_tokens_map.json", 2186, "baea4ea09372eb4fca86b4e4346139fd73cb807d5087e9de0948e971739c3e74"),
    _whisper("config.json", 1256, "c5b526b3e3cd64cd8940dabb45e8ba726629e22d8ed389c29b552f9140daf04a"),
    _whisper("preprocessor_config.json", 340, "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711"),
]

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
    "omnivoice": {
        "name": "OmniVoice",
        "by": "k2-fsa",
        "license": "CC-BY-NC (non-commercial)",
        "home": "https://github.com/k2-fsa/OmniVoice",
        "engine": "omnivoice",
        "optional": True,
        "folder": "OmniVoice",
        "files": _OMNI_FILES,
        "size": sum(f["size"] for f in _OMNI_FILES),
        "needs_voice": True,
        "summary": "The fastest on an NVIDIA card, and the lightest on graphics memory.",
        "detail": "A bigger setup than the other two: it brings its own Python and PyTorch, which the app installs into its own folder. "
                  "On a processor it is the slowest of the three.",
    },
}  # fmt: skip

# Memory each model needs for one piece of text, in GB. vram = graphics
# memory, ram = PC memory.
NEEDS: dict[str, dict] = {
    "chatterbox": {"cuda": {"vram": 3.5, "ram": 1.4}, "vulkan": {"vram": 3.5, "ram": 1.6}, "cpu": {"ram": 3.2}},
    "voxcpm2": {"cuda": {"vram": 5.0, "ram": 4.1}, "vulkan": {"vram": 6.5, "ram": 6.8}, "cpu": {"ram": 9.1}},
    # No "vulkan": on an AMD or Intel card OmniVoice runs on the processor.
    # Measured through this app: 2.3 to 2.6 GB of graphics memory while
    # speaking, and on a processor 5.8 GB of RAM at its fullest (Whisper and
    # the model one after the other, never both at once).
    "omnivoice": {"cuda": {"vram": 3.0, "ram": 4.2}, "cpu": {"ram": 5.8}},
}

# Seconds of work for 10 seconds of voice on the test PC.
SPEED: dict[str, dict] = {
    "chatterbox": {"cuda": 4.9, "vulkan": 6.4, "cpu": 55},
    "voxcpm2": {"cuda": 4.8, "vulkan": 8.6, "cpu": 59},
    "omnivoice": {"cuda": 2.6, "cpu": 91},
}
# OmniVoice builds a clip in steps. 32 is its own default; 16 is twice as
# fast and loses a few words on longer text (English 88% of words right
# against 99% in our test), which is a fair trade on a processor only.
OMNI_STEPS = {"cuda": 32, "cpu": 16}
TEST_PC = "Ryzen 5 5600, RTX 5060 Ti 16 GB"

# A script is cut into pieces of at most this many characters and the engine
# is started once per piece. Graphics memory grows with the length of what
# the engine is given in one go: VoxCPM2 took 4.7 GB for one line and 10 GB
# for a 967-character page. The engine's own chunking option was tried and
# is not used: it kept VoxCPM2 to 6.2 GB but raised Chatterbox from 4.4 GB
# to 6.1 GB. One start per piece keeps both at their one-line figure, and
# lets the app show progress and stop between pieces.
PIECE_CHARS = 250
