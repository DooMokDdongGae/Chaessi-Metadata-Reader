import unittest

from bundle.model import FORMAT, Card, decode_bundle, decode_input


class PresenceTests(unittest.TestCase):
    def test_present_fields_keep_value_and_original_slot_number(self):
        raw = "형식: nai\n\n프롬프트:\n  {종이}:1.1\r\n지도  "
        first, second = decode_bundle({
            "format": FORMAT, "version": 1, "count": 2,
            "cards": [
                {"index": 1, "status": "ok", "readable": raw, "structure": "characters",
                 "base": "  {종이}:1.1\r\n지도  ", "negative": None,
                 "characters": [{"positive": None, "negative": None},
                                {"positive": "", "negative": "  "},
                                {"positive": "문\t🌿", "negative": None}]},
                {"index": 0, "status": "missing"},
            ]
        })
        self.assertEqual(first.fields(), [])
        self.assertEqual(second.fields(), [
            ("Base Positive", "  {종이}:1.1\r\n지도  "),
            ("Character 2 Positive", ""),
            ("Character 2 Undesired", "  "),
            ("Character 3 Positive", "문\t🌿"),
        ])
        self.assertEqual(second.readable, raw)
        self.assertEqual(second.model_family, "NAI")

    def test_base_negative_can_be_the_only_present_field(self):
        card = Card("ok", "Format: sd", negative="")
        self.assertEqual(card.fields(), [("Base Undesired", "")])
        self.assertEqual(card.model_family, "SD")

    def test_explicit_family_is_independent_of_slot_structure(self):
        for line, family in [
            ("형식: nai\r\n", "NAI"), ("Format: NovelAI\n", "NAI"), ("格式: SD\n", "SD"),
            ("形式: Stable Diffusion\r", "SD"), ("Format: nai", "NAI"),
        ]:
            for structure in ("single", "characters", "unknown"):
                with self.subTest(line=line, structure=structure):
                    card = Card("ok", line, structure)
                    self.assertEqual((card.source_format, card.model_family), (family, family))

    def test_interface_format_does_not_identify_a_model_family(self):
        for raw, expected in [
            ("형식: a1111\n\n프롬프트:\nNovelAI", "A1111"),
            ("Format: ComfyUI\r\n\r\nPrompt:\nStable Diffusion", "ComfyUI"),
            ("형식: a1111-plugin\n\n프롬프트:\na1111", "unknown"),
            ("메모\nFormat: ComfyUI", "unknown"),
        ]:
            with self.subTest(raw=raw):
                card = Card("ok", raw, "single", base="nai")
                self.assertEqual(card.source_format, expected)
                self.assertEqual(card.model_family, "unknown")
                self.assertEqual(card.readable, raw)

    def test_unknown_format_is_never_guessed_from_prompt_or_later_lines(self):
        for raw in [
            None, "", "메모\n형식: nai", "Format: ComfyUI\n\nPrompt:\nNovelAI",
            "Format: novelai-like", "Format: SD or NAI", "Format:\nNAI", "Prompt: Stable Diffusion",
            "형식: 기타\n\n프롬프트:\n형식: nai", "Format: unknown\nFormat: sd",
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(Card("ok", raw, "characters", characters=(("nai", "sd"),)).model_family,
                                 "unknown")
        local, = decode_input({"Software": "NovelAI", "Description": "Format: nai"})
        self.assertEqual(local.source_format, "unknown")
        self.assertEqual(local.model_family, "unknown")
        self.assertEqual(local.fields(), [("Base Positive", "Format: nai")])


if __name__ == "__main__":
    unittest.main()
