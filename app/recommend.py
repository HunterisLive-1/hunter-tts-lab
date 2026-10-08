"""Which model suits this PC, and how it should be run.

Plain rules over what hardware.detect() found, kept free of anything that
touches the system so they can be tested with made-up PCs (see tests/).
"""

from __future__ import annotations

import re

from catalog import MODELS, NEEDS, SPEED, TEST_PC

# Windows and the browser already hold some graphics memory, and the PC needs
# RAM for itself. A model "fits well" with this much to spare and "just fits"
# with less.
VRAM_SPARE_GOOD, VRAM_SPARE_TIGHT = 2.0, 0.5
RAM_SPARE_GOOD, RAM_SPARE_TIGHT = 4.0, 2.0
MIN_GPU_GB = 3.5

DEVICE_LABEL = {"cuda": "NVIDIA graphics card", "vulkan": "graphics card (Vulkan)", "cpu": "processor (CPU)"}


def choose_device(hw: dict, prefer: str = "auto") -> dict:
    gpus = hw.get("gpus") or []
    nvidia = [g for g in gpus if g["vendor"] == "nvidia" and g["vram_gb"] >= MIN_GPU_GB]
    other = [g for g in gpus if g["vendor"] in ("amd", "intel") and not g["integrated"] and g["vram_gb"] >= MIN_GPU_GB]
    if prefer == "cpu":
        return {"device": "cpu", "gpu": None, "why": "You chose to run on the processor."}
    if nvidia and prefer in ("auto", "cuda"):
        return {"device": "cuda", "gpu": nvidia[0], "why": f"{nvidia[0]['name']} with {nvidia[0]['vram_gb']:g} GB of graphics memory."}
    if (other or nvidia) and prefer in ("auto", "vulkan"):
        g = (other or nvidia)[0]
        return {"device": "vulkan", "gpu": g, "why": f"{g['name']} with {g['vram_gb']:g} GB of graphics memory, through Vulkan."}
    if not gpus:
        why = "No graphics card was found."
    elif all(g["integrated"] for g in gpus):
        why = f"{gpus[0]['name']} is built into the processor and shares the PC's RAM, so the processor does the work."
    else:
        why = f"{gpus[0]['name']} has {gpus[0]['vram_gb']:g} GB of graphics memory, too little for these models."
    return {"device": "cpu", "gpu": None, "why": why}


def _old_nvidia(name: str) -> bool:
    """Cards the newest NVIDIA libraries no longer drive (GTX 900 and 1000 series and their relatives)."""
    n = name.lower()
    return bool(re.search(r"gtx\s*(9\d\d|10\d\d)|gt\s*10\d\d|titan\s*(x|xp|v)\b|quadro\s*[mp]\d|mx\s?[1-3]\d\d", n))


def runtime_order(hw: dict, device: str, gpu: dict | None) -> list[str]:
    """Runtimes to try, best first. Install tests each and keeps the first that speaks."""
    if device == "cpu":
        return ["cpu"]
    if device == "vulkan":
        return ["vulkan", "cpu"]
    name = (gpu or {}).get("name", "")
    try:
        driver = float(str((gpu or {}).get("driver", "0")).split(".")[0])
    except ValueError:
        driver = 0.0
    if _old_nvidia(name) or 0 < driver < 580:
        return ["cuda12", "vulkan", "cpu"]
    if re.search(r"rtx\s*50\d\d", name.lower()):  # the 50 series needs the newest libraries
        return ["cuda13", "vulkan", "cpu"]
    return ["cuda13", "cuda12", "vulkan", "cpu"]


def fit(model_id: str, device: str, hw: dict, gpu: dict | None) -> dict:
    need = NEEDS[model_id][device]
    if device == "cpu":
        have, want, unit = hw.get("ram_gb", 0.0), need["ram"], "RAM"
        good, tight = RAM_SPARE_GOOD, RAM_SPARE_TIGHT
    else:
        have, want, unit = (gpu or {}).get("vram_gb", 0.0), need["vram"], "graphics memory"
        good, tight = VRAM_SPARE_GOOD, VRAM_SPARE_TIGHT
    if have >= want + good:
        level, why = "good", f"Needs about {want:g} GB of {unit}; this PC has {have:g} GB."
    elif have >= want + tight:
        level, why = "tight", f"Needs about {want:g} GB of {unit} and this PC has {have:g} GB. It should run; close other heavy apps first."
    else:
        level, why = "no", f"Needs about {want:g} GB of {unit}; this PC has {have:g} GB."
    return {"level": level, "why": why, "need_gb": want, "have_gb": have, "unit": unit}


def speed_words(seconds_per_10s: float) -> str:
    if seconds_per_10s < 60:
        return f"about {seconds_per_10s:.0f} seconds for 10 seconds of voice"
    return f"about {seconds_per_10s / 60:.0f} minute{'s' if seconds_per_10s >= 90 else ''} for 10 seconds of voice"


def plan(hw: dict, prefer: str = "auto") -> dict:
    chosen = choose_device(hw, prefer)
    device, gpu = chosen["device"], chosen["gpu"]
    notes: list[str] = []

    def rate(dev: str, g: dict | None) -> dict:
        return {m: fit(m, dev, hw, g) for m in MODELS}

    fits = rate(device, gpu)
    if device != "cpu" and all(f["level"] == "no" for f in fits.values()):
        # A card that is found but too small for every model: use the processor.
        notes.append(f"{gpu['name']} has too little graphics memory for these models, so the processor is used.")
        device, gpu = "cpu", None
        fits = rate(device, gpu)

    # VoxCPM2 where it fits well, Chatterbox everywhere else: it is the lighter one.
    if device != "cpu" and fits["voxcpm2"]["level"] == "good":
        pick = "voxcpm2"
    elif fits["chatterbox"]["level"] != "no":
        pick = "chatterbox"
    elif fits["voxcpm2"]["level"] != "no":
        pick = "voxcpm2"
    else:
        pick = None

    models = []
    for m in MODELS:
        guess = SPEED[m][device]
        models.append({
            "id": m,
            **fits[m],
            "recommended": m == pick,
            "speed_guess": f"{speed_words(guess).capitalize()} on our test PC ({TEST_PC})." if device != "cpu"
            else f"{speed_words(guess).capitalize()} on our test PC's processor ({TEST_PC.split(',')[0]}).",
        })  # fmt: skip

    if device == "cuda":
        headline = f"This PC makes voices on its {gpu['name']}."
    elif device == "vulkan":
        headline = f"This PC makes voices on its {gpu['name']}, through Vulkan."
        notes.append("Vulkan was tested by us on an NVIDIA card only. On AMD and Intel cards it should work; the test after install will tell.")
    else:
        headline = "This PC makes voices on its processor. It works, slowly: about a minute for 10 seconds of voice."
        if not hw.get("cpu", {}).get("avx2", True):
            notes.append("This processor is an older kind (no AVX2), so it will be slower still.")
    if pick is None:
        notes.append("This PC has too little memory for either model. Closing other apps may help; 8 GB of RAM is the least that works.")
    if hw.get("disk_free_gb", 99) < 6:
        notes.append(f"Only {hw['disk_free_gb']:g} GB is free on this drive. A model needs 3 to 4 GB.")

    return {
        "device": device,
        "device_label": DEVICE_LABEL[device],
        "gpu": gpu,
        "why": chosen["why"],
        "headline": headline,
        "notes": notes,
        "pick": pick,
        "models": models,
        "runtimes": runtime_order(hw, device, gpu),
    }
