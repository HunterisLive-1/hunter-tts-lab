"""Cutting a script into pieces, and joining clips.

    python -m unittest discover tests
"""

import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
os.environ["HUNTER_TTS_LAB_DATA"] = tempfile.mkdtemp(prefix="htl-test-")

import speech  # noqa: E402
import store  # noqa: E402
import voices  # noqa: E402
from jobs import UserError  # noqa: E402

DANDA = chr(0x0964)


def tone(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(int(rate * seconds) * 2))
    return buf.getvalue()


class SplitScript(unittest.TestCase):
    def test_short_text_is_one_piece(self):
        self.assertEqual(speech.split_script("Hello doston. Kaise ho?"), ["Hello doston. Kaise ho?"])

    def test_pieces_stay_under_the_limit_and_keep_every_word(self):
        text = " ".join(f"Yeh sentence number {n} hai." for n in range(60))
        pieces = speech.split_script(text, 250)
        self.assertTrue(all(len(p) <= 250 for p in pieces))
        self.assertEqual(" ".join(pieces).split(), text.split())
        self.assertTrue(all(p.endswith(".") for p in pieces))  # cut at sentence ends only

    def test_hindi_danda_ends_a_sentence(self):
        text = ("namaste" + DANDA + " ") * 40
        pieces = speech.split_script(text, 100)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(p.endswith(DANDA) for p in pieces))

    def test_one_endless_sentence_is_cut_at_commas_then_spaces(self):
        text = "ek, do, teen, " * 40 + "bas"
        pieces = speech.split_script(text, 120)
        self.assertTrue(all(len(p) <= 120 for p in pieces))
        self.assertEqual("".join(pieces).replace(" ", ""), text.replace(" ", ""))
        no_commas = "shabd " * 100
        self.assertTrue(all(len(p) <= 80 for p in speech.split_script(no_commas, 80)))

    def test_new_lines_and_blank_lines(self):
        self.assertEqual(speech.split_script("Line one\n\n\nLine two\r\nLine three"), ["Line one Line two Line three"])

    def test_nothing_sayable_gives_nothing(self):
        self.assertEqual(speech.split_script("   \n ... !!! \n"), [])

    def test_a_word_longer_than_the_limit_does_not_hang(self):
        pieces = speech.split_script("a" * 1000, 100)
        self.assertEqual("".join(pieces), "a" * 1000)


class DownloadName(unittest.TestCase):
    def test_hindi_words_keep_their_vowel_signs(self):
        namaste = "".join(chr(c) for c in (0x0928, 0x092E, 0x0938, 0x094D, 0x0924, 0x0947))  # na-ma-s-virama-ta-e
        name = speech.download_name({"id": "20261009-010203-abcdef", "text": namaste + ", doston! 123"})
        self.assertEqual(name, namaste + "-doston-123-abcdef.wav")

    def test_nothing_usable_still_gives_a_name(self):
        self.assertEqual(speech.download_name({"id": "20261009-010203-abcdef", "text": "?!... //"}), "voice-abcdef.wav")


class JoinWavs(unittest.TestCase):
    def test_joined_length_is_the_parts_plus_the_pauses(self):
        folder = Path(tempfile.mkdtemp())
        parts = []
        for n, secs in enumerate((1.0, 0.5, 2.0)):
            p = folder / f"{n}.wav"
            p.write_bytes(tone(secs))
            parts.append(p)
        out = folder / "out.wav"
        length = speech.join_wavs(parts, out, gap=0.25)
        self.assertAlmostEqual(length, 4.0, places=2)
        with wave.open(str(out), "rb") as w:
            self.assertAlmostEqual(w.getnframes() / w.getframerate(), 4.0, places=2)

    def test_mixed_formats_are_refused(self):
        folder = Path(tempfile.mkdtemp())
        a, b = folder / "a.wav", folder / "b.wav"
        a.write_bytes(tone(1.0, 24000))
        b.write_bytes(tone(1.0, 48000))
        with self.assertRaises(UserError):
            speech.join_wavs([a, b], folder / "out.wav")


class Voices(unittest.TestCase):
    def test_add_list_rename_delete(self):
        v = voices.add("  Hunter <b>  ", tone(6.0))
        self.assertEqual(v["name"], "Hunter b")
        self.assertEqual(v["seconds"], 6.0)
        self.assertTrue(voices.path_of(v["id"]).exists())
        voices.rename(v["id"], "Mera awaaz")
        self.assertEqual(voices.name_of(v["id"]), "Mera awaaz")
        voices.delete(v["id"])
        self.assertIsNone(voices.path_of(v["id"]))

    def test_too_short_too_long_and_not_audio(self):
        for bad in (tone(1.0), tone(45.0), b"not audio at all"):
            with self.assertRaises(UserError):
                voices.add("x", bad)

    def test_ids_cannot_reach_other_files(self):
        for bad in ("../config", "..\\..\\x", "sample/../x", "", "zzzzzzzzzzzz"):
            self.assertIsNone(voices.path_of(bad))
        for bad in ("../../etc", "a/b", ""):
            self.assertIsNone(speech.clip_path(bad))


class Store(unittest.TestCase):
    def test_a_damaged_file_falls_back_to_the_previous_copy(self):
        f = Path(tempfile.mkdtemp()) / "x.json"
        store.write(f, {"n": 1})
        store.write(f, {"n": 2})
        f.write_bytes(bytes(40))  # what a power cut leaves behind: the right length, all zeros
        self.assertEqual(store.read(f, {}), {"n": 1})
        self.assertTrue(f.with_suffix(".json.corrupt").exists())

    def test_something_removed_on_purpose_does_not_linger_in_the_backup(self):
        f = Path(tempfile.mkdtemp()) / "config.json"
        store.write(f, {"gemini_key": "secret-key"})
        store.write(f, {"gemini_key": ""})
        self.assertIn("secret-key", f.with_suffix(".json.bak").read_text())  # the ordinary backup still has it
        store.forget_previous(f)
        self.assertNotIn("secret-key", f.with_suffix(".json.bak").read_text())

    def test_missing_file_gives_the_default(self):
        self.assertEqual(store.read(Path(tempfile.mkdtemp()) / "none.json", [1]), [1])


if __name__ == "__main__":
    unittest.main()
