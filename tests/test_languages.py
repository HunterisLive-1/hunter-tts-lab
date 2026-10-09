"""Which model speaks which language, and how text in other scripts is cut.

    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import languages  # noqa: E402
import speech  # noqa: E402
from catalog import MODELS  # noqa: E402


def text(*codes: int) -> str:
    """A string from code points, so this file stays plain ASCII."""
    return "".join(chr(c) for c in codes)


class Lists(unittest.TestCase):
    def test_every_model_has_a_list_with_hindi_and_english_in_it(self):
        for model in MODELS:
            self.assertTrue(languages.speaks(model, "hi") and languages.speaks(model, "en"), model)
        page = languages.for_page()
        self.assertEqual({m: len(v) for m, v in page["models"].items()}, {"chatterbox": 19, "voxcpm2": 30, "omnivoice": 646})

    def test_chatterbox_lists_only_what_this_engine_can_do(self):
        # Its makers list 23; the engine refuses these four ("unsupported Chatterbox language"), found by trying each.
        for code in ("zh", "he", "ja", "ru"):
            self.assertFalse(languages.speaks("chatterbox", code), code)
            self.assertTrue(languages.speaks("voxcpm2", code) and languages.speaks("omnivoice", code), code)

    def test_only_omnivoice_speaks_the_other_indian_languages(self):
        for code in languages.INDIA:
            self.assertTrue(languages.speaks("omnivoice", code), code)
            self.assertFalse(languages.speaks("chatterbox", code) or languages.speaks("voxcpm2", code), code)
        self.assertEqual(languages.name("ta"), "Tamil")
        self.assertEqual(languages.name("pa"), "Punjabi")  # the model's table spells it Panjabi

    def test_one_code_per_language_whatever_the_model_calls_it(self):
        # Arabic is "ar" for two models and "Standard Arabic", arb, in OmniVoice's table.
        for model in MODELS:
            self.assertTrue(languages.speaks(model, "ar"), model)
        self.assertEqual(languages.given("omnivoice", "ar"), "arb")
        self.assertEqual(languages.given("chatterbox", "ar"), "ar")
        self.assertFalse(languages.speaks("omnivoice", "arb"))  # not offered twice
        self.assertEqual(languages.given("omnivoice", "tl"), "fil")
        self.assertEqual(languages.given("voxcpm2", "tl"), "tl")

    def test_lists_are_by_name_and_have_no_language_twice(self):
        for model, pairs in languages.for_page()["models"].items():
            names = [n for _c, n in pairs]
            self.assertEqual(names, sorted(names), model)
            self.assertEqual(len({c for c, _n in pairs}), len(pairs), model)
            self.assertEqual(len(set(names)), len(names), model)

    def test_unknown_codes_are_not_known(self):
        for junk in ("", "other", "xx-nope", None, 7, "HI"):
            self.assertFalse(languages.known(junk), junk)
        self.assertTrue(languages.known("bn"))
        self.assertFalse(languages.speaks("chatterbox", "bn"))


class OtherScripts(unittest.TestCase):
    def test_japanese_is_cut_at_its_own_full_stops_into_short_pieces(self):
        # twelve sentences of ten kana each, ended by the ideographic full stop
        sentence = text(*([0x3042] * 10), 0x3002)
        pieces = speech.split_script(sentence * 12, speech.piece_chars("ja"))
        self.assertTrue(all(len(p.replace(" ", "")) <= 70 for p in pieces), [len(p) for p in pieces])
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(p.endswith(chr(0x3002)) for p in pieces))
        self.assertEqual("".join(p.replace(" ", "") for p in pieces), sentence * 12)  # nothing lost

    def test_text_without_any_punctuation_or_spaces_is_still_cut(self):
        pieces = speech.split_script(text(*([0x4E2D] * 200)), speech.piece_chars("zh"))
        self.assertEqual([len(p) for p in pieces], [70, 70, 60])

    def test_urdu_and_arabic_marks_end_a_sentence(self):
        one = text(0x06CC, 0x06C1, 0x0020, 0x0627, 0x06CC, 0x06A9, 0x06D4)  # ends in the Urdu full stop
        two = text(0x06A9, 0x06CC, 0x0627, 0x061F)  # ends in the Arabic question mark
        pieces = speech.split_script(one + " " + two, limit=8)
        self.assertEqual(pieces, [one, two])

    def test_languages_written_with_spaces_keep_the_usual_piece_size(self):
        for code in ("hi", "en", "ta", "bn", "fr", "ar", "ur"):
            self.assertEqual(speech.piece_chars(code), 250, code)
        for code in ("zh", "ja", "ko", "th"):
            self.assertEqual(speech.piece_chars(code), 70, code)


class Polishing(unittest.TestCase):
    """Script polishing is told the language, so that it does not turn a Tamil script into Hindi."""

    def rules_sent(self, script, language):
        import gemini
        from unittest import mock

        sent = {}

        def fake_call(key, path, body=None):
            sent.update(body)
            return {"candidates": [{"content": {"parts": [{"text": "polished"}]}}]}

        with mock.patch.object(gemini, "_call", fake_call):
            self.assertEqual(gemini.polish("key", "some-model", "a script", script, language), "polished")
        return sent["systemInstruction"]["parts"][0]["text"]

    def test_another_language_is_kept_and_not_translated(self):
        rules = self.rules_sent("devanagari", "Tamil")
        self.assertIn("The script is in Tamil. Keep it in Tamil", rules)
        self.assertIn("Do not translate", rules)
        self.assertNotIn("Devanagari", rules)  # the Hindi choice does not apply to it

    def test_hindi_and_english_keep_their_own_choices(self):
        self.assertIn("Devanagari", self.rules_sent("devanagari", None))
        self.assertIn("stays in English letters", self.rules_sent("keep", None))


if __name__ == "__main__":
    unittest.main()
