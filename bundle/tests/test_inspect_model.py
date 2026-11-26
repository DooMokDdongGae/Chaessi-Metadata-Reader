import unittest

from bundle.model import Card, FORMAT, decode_bundle


def read_card(**changes):
    item = dict(index=0, status="ok", structure="single", readable="합성 원문",
                base="종이배", negative=None, characters=[])
    item.update(changes)
    card, = decode_bundle(dict(format=FORMAT, version=1, count=1, cards=[item]))
    return card


class InspectModelTests(unittest.TestCase):
    def test_simplified_copy_and_three_empty_character_negatives_are_preserved(self):
        original = "  (가을:1.2)\r\n연필\t🍂\n\n  "
        card = read_card(origin="novelai_inspect", readable=original, structure="characters",
                         base="  (가을:1.2)\r\n연필", negative=" 점 ",
                         characters=[{"positive": value, "negative": ""}
                                     for value in ("종이", "  판지  ", "선\n둘")])
        self.assertEqual(card.origin, "novelai_inspect")
        self.assertEqual((card.source_format, card.model_family), ("NAI", "NAI"))
        self.assertEqual(card.readable, original)
        self.assertEqual(card.fields(), [
            ("Base Positive", "  (가을:1.2)\r\n연필"), ("Base Undesired", " 점 "),
            ("Character 1 Positive", "종이"), ("Character 1 Undesired", ""),
            ("Character 2 Positive", "  판지  "), ("Character 2 Undesired", ""),
            ("Character 3 Positive", "선\n둘"), ("Character 3 Undesired", ""),
        ])

    def test_missing_fields_leave_slot_numbers_intact(self):
        card = read_card(origin="novelai_inspect", base=None, negative="", structure="characters",
                         characters=[{"positive": None, "negative": None},
                                     {"positive": "", "negative": "  "}])
        self.assertEqual(card.fields(), [
            ("Base Undesired", ""), ("Character 2 Positive", ""), ("Character 2 Undesired", "  "),
        ])

    def test_old_and_explicit_aitag_inputs_keep_the_format_header_rule(self):
        for attributes in ({}, {"origin": "aitag"}):
            for raw, source, family in [
                ("형식: nai\n\n프롬프트:\n종이", "NAI", "NAI"),
                ("Format: a1111\r\n\nPrompt:\nleaf", "A1111", "unknown"),
                ("Format: ComfyUI", "ComfyUI", "unknown"), ("Format: sd", "SD", "SD"),
                ("종이\nFormat: nai", "unknown", "unknown"),
            ]:
                with self.subTest(attributes=attributes, source=source):
                    card = read_card(readable=raw, **attributes)
                    self.assertEqual((card.origin, card.source_format, card.model_family),
                                     ("aitag", source, family))
                    self.assertEqual(card.readable, raw)

    def test_unknown_origin_preserves_readable_only(self):
        original = "형식: nai\n\n원문"
        for origin in (None, False, "", "novelai", "NOVELAI_INSPECT", [], {}):
            with self.subTest(origin=origin):
                card = read_card(origin=origin, readable=original)
                self.assertIsNone(card.origin)
                self.assertEqual((card.source_format, card.model_family), ("unknown", "unknown"))
                self.assertEqual(card.structure, "unknown")
                self.assertEqual(card.fields(), [])
                self.assertEqual(card.readable, original)

    def test_valid_source_survives_unreadable_field_mapping(self):
        card = read_card(origin="novelai_inspect", readable="  나뭇잎\n", characters="오류")
        self.assertEqual((card.origin, card.source_format), ("novelai_inspect", "NAI"))
        self.assertEqual(card.readable, "  나뭇잎\n")
        self.assertEqual(card.fields(), [])
        self.assertEqual(card.structure, "unknown")

    def test_missing_or_failed_inspect_cards_do_not_claim_a_model(self):
        for status in ("missing", "failed"):
            card = read_card(origin="novelai_inspect", status=status)
            self.assertEqual((card.origin, card.source_format), ("novelai_inspect", "unknown"))
            self.assertIsNone(card.readable)
            self.assertEqual(card.fields(), [])

    def test_old_positional_local_flag_remains_in_place(self):
        card = Card("ok", "Format: nai", "single", "paper", None, (), True)
        self.assertTrue(card.local)
        self.assertEqual(card.source_format, "unknown")
        self.assertEqual(card.fields(), [("Base Positive", "paper")])


if __name__ == "__main__":
    unittest.main()
