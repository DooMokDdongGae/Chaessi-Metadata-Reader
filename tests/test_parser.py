import json
from pathlib import Path
import struct
import unittest
import zlib

from reader_parser import (
    MAX_CHARACTERS, MAX_IMAGES, MAX_TEXT_BYTES, PNG_SIGNATURE,
    ParserError, load_png, parse_work,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(*text_chunks):
    header = struct.pack(">2I5B", 1, 1, 8, 2, 0, 0, 0)
    return b"".join([
        PNG_SIGNATURE, chunk(b"IHDR", header), *text_chunks,
        chunk(b"IDAT", zlib.compress(b"\0\0\0\0")), chunk(b"IEND", b""),
    ])


class ParserTests(unittest.TestCase):
    def test_images_keep_their_own_prompts_and_character_slots(self):
        raw = json.loads((FIXTURES / "synthetic-work.json").read_text("utf-8"))
        first, second = parse_work(raw)
        self.assertEqual((first.status, second.status), ("ok", "ok"))
        self.assertEqual((first.base, first.negative, first.characters), ("종이배 한 척", "비", []))
        self.assertEqual(second.base, "  종이 정원, (구름:1.2)\nblue sky  ")
        self.assertEqual(second.negative, "")
        self.assertEqual([(char.positive, char.negative) for char in second.characters],
                         [("노란 우산", "stripes"), ("  연필 & 지도  ", None)])
        self.assertIs(second.raw, raw["images"][1])
        self.assertEqual(second.characters[1].centers, [{"x": .75, "y": .5}])

    def test_modern_caption_precedence_even_when_empty(self):
        data = {"prompt": "legacy", "uc": "legacy negative", "v4_prompt": {"caption": {"base_caption": ""}}}
        record, = parse_work({"Comment": json.dumps(data), "Description": "preview", "Software": "NovelAI"})
        self.assertEqual((record.base, record.negative), ("", "legacy negative"))

    def test_negative_only_slots_keep_order_and_holes(self):
        record, = parse_work({"v4_negative_prompt": {"caption": {"char_captions": [
            None, {"char_caption": ""}, {"char_caption": "  "},
        ]}}})
        self.assertEqual(record.status, "ok")
        self.assertEqual([(char.positive, char.negative) for char in record.characters],
                         [(None, None), (None, ""), (None, "  ")])
        self.assertIsNone(record.base)

    def test_json_wrapper_and_source_stay_intact(self):
        prompt = " \r\n🎈, {{종이}}, <script>window.bad()</script>, nsfw, &amp;\t "
        raw = {"metadata": json.dumps({"Comment": json.dumps({"prompt": prompt})})}
        record, = parse_work(raw)
        self.assertIs(record.raw, raw)
        self.assertEqual(record.status, "ok")
        self.assertEqual(record.base, prompt)
        self.assertIsNone(record.negative)

    def test_descriptions_are_only_used_as_novelai_prompts(self):
        record, unrelated = parse_work([
            {"Software": "NovelAI", "Description": "blue"},
            {"Software": "Camera", "Description": "image alt text"},
        ])
        self.assertEqual(record.base, "blue")
        self.assertEqual(unrelated.status, "unsupported")
        self.assertIsNone(unrelated.base)

    def test_an_invalid_image_does_not_shift_its_neighbors(self):
        raw = [{"prompt": "first"}, None, {"Comment": "{"}, {"workflow": {}},
               {"metadata": ""}, {"prompt": "last"}]
        records = parse_work(raw)
        self.assertEqual([r.status for r in records],
                         ["ok", "no_metadata", "malformed", "unsupported", "no_metadata", "ok"])
        self.assertEqual([r.base for r in records], ["first", None, None, None, None, "last"])
        for i, record in enumerate(records):
            self.assertIs(record.raw, raw[i])

    def test_malformed_field_never_yields_partial_success(self):
        for obj in [
            {"prompt": 123}, {"prompt": "x", "uc": False}, {"Comment": []},
            {"v4_prompt": {"caption": {"char_captions": "bad"}}},
            {"v4_prompt": {"caption": {"char_captions": [{"char_caption": []}]}}},
            {"prompt": "\x00"}, {"prompt": "\ud800"},
        ]:
            with self.subTest(obj=obj):
                r, = parse_work(obj)
                self.assertEqual(r.status, "malformed")
                self.assertIsNone(r.base)

    def test_limits_and_top_level_errors(self):
        for raw, code in [([], "no_metadata"), (42, "malformed"),
                          ({"images": {}}, "malformed"), ([{}] * (MAX_IMAGES + 1), "unsupported")]:
            with self.assertRaises(ParserError) as caught:
                parse_work(raw)
            self.assertEqual(caught.exception.code, code)
        record, = parse_work({"v4_prompt": {"caption": {"char_captions": [None] * (MAX_CHARACTERS + 1)}}})
        self.assertEqual(record.status, "unsupported")

    def test_simple_sd_json_and_parameters(self):
        simple, infotext = parse_work([
            {"prompt": "cloud", "negative_prompt": ""},
            {"parameters": "  cloud \r\n2\r\n\r\nNegative prompt:  fog  \r\nleaves\r\n"
                           "Steps: 12, Sampler: Euler, Seed: 4"},
        ])
        self.assertEqual((simple.base, simple.negative), ("cloud", ""))
        self.assertEqual((infotext.base, infotext.negative), ("  cloud \r\n2\r\n", " fog  \r\nleaves"))
        empty, = parse_work({"parameters": "x\nNegative prompt:\nSteps: 10, Sampler: Euler"})
        self.assertEqual(empty.negative, "")

    def test_sd_embedded_steps_text_is_not_an_option_line(self):
        text = "a\nSteps: 12, Sampler: part of a story\nend\nNegative prompt: b"
        record, = parse_work({"parameters": text})
        self.assertEqual(record.base, "a\nSteps: 12, Sampler: part of a story\nend")

    def test_png_graph_string_is_not_a_prompt(self):
        graph = {"1": {"class_type": "Example", "inputs": {"text": "paper"}}}
        for representation in (graph, json.dumps(graph)):
            record, = parse_work({"prompt": representation})
            self.assertEqual(record.status, "unsupported")
        other, = parse_work({"parameters": "paper\nSteps: 10, Sampler: Euler", "Comment": "photo note"})
        self.assertEqual(other.base, "paper")

    def test_png_metadata_kinds(self):
        raw_comment = json.dumps({"prompt": "  책 \n🎈  ", "uc": ""}, ensure_ascii=False).encode("utf-8")
        for flag in (0, 1):
            data = zlib.compress(raw_comment) if flag else raw_comment
            sample = png(
                chunk(b"tEXt", b"Software\0NovelAI"),
                chunk(b"zTXt", b"Title\0\0" + zlib.compress(b"practice")),
                chunk(b"iTXt", b"Comment\0" + bytes([flag, 0]) + b"ko\0\0" + data),
            )
            raw = load_png(sample)
            record, = parse_work(raw)
            self.assertEqual(raw["Title"], "practice")
            self.assertEqual(record.base, "  책 \n🎈  ")
            self.assertEqual(record.negative, "")

    def test_unmarked_png_and_duplicate_comment(self):
        record, = parse_work(load_png(png()))
        self.assertEqual(record.status, "no_metadata")
        c = chunk(b"tEXt", b'Comment\0{"prompt":"a"}')
        record, = parse_work(load_png(png(c, c)))
        self.assertEqual(record.status, "malformed")

    def test_png_rejects_bad_headers_crc_zip_and_bomb(self):
        over = zlib.compress(b"x" * (MAX_TEXT_BYTES + 1))
        for bad, code in [
            (b"other", "unsupported"), (png()[:-1], "malformed"),
            (png().replace(b"IDAT", b"IDAN"), "malformed"),
            (png(chunk(b"iTXt", b"Comment\0\x02\x00\0\0foo")), "malformed"),
            (png(chunk(b"zTXt", b"Comment\0\0" + zlib.compress(b"small")[:-1])), "malformed"),
            (png(chunk(b"zTXt", b"Comment\0\0" + over)), "too_large"),
        ]:
            with self.assertRaises(ParserError) as caught:
                load_png(bad)
            self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
