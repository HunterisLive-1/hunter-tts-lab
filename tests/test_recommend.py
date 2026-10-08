"""Made-up PCs through the recommendation rules.

    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import recommend  # noqa: E402


def pc(ram=16.0, gpus=(), avx2=True, disk=200.0):
    return {"cpu": {"name": "Test CPU", "threads": 8, "avx2": avx2, "avx512": False}, "ram_gb": ram, "gpus": list(gpus), "disk_free_gb": disk}


def gpu(name, vram, vendor="nvidia", driver="616.92", integrated=False):
    return {"name": name, "vendor": vendor, "vram_gb": vram, "driver": driver, "integrated": integrated}


def levels(plan):
    return {m["id"]: m["level"] for m in plan["models"]}


class Recommend(unittest.TestCase):
    def test_big_nvidia_card_gets_voxcpm2(self):
        p = recommend.plan(pc(32, [gpu("NVIDIA GeForce RTX 5060 Ti", 15.9)]))
        self.assertEqual(p["device"], "cuda")
        self.assertEqual(p["pick"], "voxcpm2")
        self.assertEqual(levels(p), {"chatterbox": "good", "voxcpm2": "good"})
        self.assertEqual(p["runtimes"], ["cuda13", "vulkan", "cpu"])

    def test_8gb_card_gets_voxcpm2(self):
        p = recommend.plan(pc(16, [gpu("NVIDIA GeForce RTX 3060 Ti", 8.0)]))
        self.assertEqual(levels(p), {"chatterbox": "good", "voxcpm2": "good"})
        self.assertEqual(p["pick"], "voxcpm2")
        self.assertEqual(p["runtimes"][0], "cuda13")

    def test_6gb_card_picks_chatterbox_and_allows_voxcpm2(self):
        p = recommend.plan(pc(16, [gpu("NVIDIA GeForce RTX 2060", 6.0)]))
        self.assertEqual(levels(p), {"chatterbox": "good", "voxcpm2": "tight"})
        self.assertEqual(p["pick"], "chatterbox")

    def test_4gb_card_just_fits_chatterbox(self):
        p = recommend.plan(pc(16, [gpu("NVIDIA GeForce GTX 1650", 4.0, driver="552.22")]))
        self.assertEqual(p["device"], "cuda")
        self.assertEqual(levels(p)["chatterbox"], "tight")
        self.assertEqual(p["runtimes"][0], "cuda12")  # old driver: the newest libraries would not start

    def test_old_card_uses_older_libraries_even_with_a_new_driver(self):
        p = recommend.plan(pc(16, [gpu("NVIDIA GeForce GTX 1070", 8.0, driver="581.10")]))
        self.assertEqual(p["runtimes"][0], "cuda12")

    def test_2gb_card_falls_back_to_the_processor(self):
        p = recommend.plan(pc(16, [gpu("NVIDIA GeForce GT 1030", 2.0)]))
        self.assertEqual(p["device"], "cpu")
        self.assertEqual(p["pick"], "chatterbox")

    def test_amd_card_goes_through_vulkan(self):
        p = recommend.plan(pc(16, [gpu("AMD Radeon RX 6600", 8.0, vendor="amd", driver="31.0")]))
        self.assertEqual(p["device"], "vulkan")
        self.assertEqual(p["runtimes"], ["vulkan", "cpu"])
        self.assertEqual(levels(p), {"chatterbox": "good", "voxcpm2": "tight"})
        self.assertTrue(any("Vulkan" in n for n in p["notes"]))

    def test_laptop_with_built_in_graphics_uses_the_processor(self):
        p = recommend.plan(pc(8, [gpu("Intel(R) UHD Graphics 620", 1.0, vendor="intel", integrated=True)]))
        self.assertEqual(p["device"], "cpu")
        self.assertEqual(levels(p), {"chatterbox": "good", "voxcpm2": "no"})
        self.assertEqual(p["pick"], "chatterbox")
        self.assertIn("built into the processor", p["why"])

    def test_16gb_ram_can_also_run_voxcpm2_on_the_processor(self):
        p = recommend.plan(pc(16, []))
        self.assertEqual(levels(p), {"chatterbox": "good", "voxcpm2": "good"})
        self.assertEqual(p["pick"], "chatterbox")  # the lighter one stays the pick on a processor

    def test_4gb_ram_gets_an_honest_no(self):
        p = recommend.plan(pc(4, []))
        self.assertIsNone(p["pick"])
        self.assertTrue(any("too little memory" in n for n in p["notes"]))

    def test_user_can_force_the_processor(self):
        p = recommend.plan(pc(32, [gpu("NVIDIA GeForce RTX 4090", 24.0)]), prefer="cpu")
        self.assertEqual(p["device"], "cpu")
        self.assertEqual(p["runtimes"], ["cpu"])

    def test_low_disk_is_mentioned(self):
        p = recommend.plan(pc(16, [], disk=3.0))
        self.assertTrue(any("free on this drive" in n for n in p["notes"]))


if __name__ == "__main__":
    unittest.main()
