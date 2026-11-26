"""Synthetic, display-independent reader editing and transfer snapshot coverage."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bundle.editing import EditSession, SourceText
from bundle.model import Card
from bundle.transfer_window import TransferWindow


class EditSessionTests(unittest.TestCase):
    def setUp(self):
        self.original = "  별, (달:1.2)\r\n🌙\t  "
        # Two source images can have identical fields, even identical Card objects.
        self.card = Card("ok", "원문\n", "characters", self.original, "",
                         ((self.original, None), (None, "")))
        self.session = EditSession([self.card, self.card])

    def test_image_and_field_identity_is_independent_of_matching_text(self):
        self.assertFalse(self.session.dirty)
        self.session.set_value(0, "Base Positive", "")
        self.session.set_value(1, "Character 1 Positive", "두 번째 이미지")
        self.assertTrue(self.session.dirty)
        self.assertEqual(self.session.value(0, "Base Positive"), "")
        self.assertEqual(self.session.value(1, "Base Positive"), self.original)
        self.assertEqual(self.session.value(0, "Character 1 Positive"), self.original)
        self.assertEqual(self.session.value(1, "Character 1 Positive"), "두 번째 이미지")
        self.assertEqual(self.card.base, self.original)
        self.assertEqual(self.card.characters, ((self.original, None), (None, "")))
        self.assertEqual(self.card.readable, "원문\n")

    def test_restoring_each_edit_to_exact_original_clears_dirty_state(self):
        self.session.set_value(1, "Base Positive", "임시")
        self.session.set_value(1, "Base Undesired", "다른 칸")
        self.session.restore(1, "Base Positive")
        self.assertEqual(self.session.value(1, "Base Positive"), self.original)
        self.assertTrue(self.session.dirty)
        self.session.set_value(1, "Base Undesired", "")
        self.assertFalse(self.session.dirty)

    def test_selection_and_whole_values_are_immutable_snapshots(self):
        chosen = "  (바람:0.8)🌬\r\n  "
        field = "Character 1 Positive"
        self.session.set_value(1, field, chosen + "뒤")
        selected = self.session.capture(1, field, chosen)
        whole = self.session.capture(1, field, self.session.value(1, field))
        self.session.set_value(1, field, "새 편집")
        self.session.restore(1, field)
        self.assertEqual((selected.image, selected.field, selected.text), (1, field, chosen))
        self.assertEqual(whole.text, chosen + "뒤")
        with self.assertRaises(AttributeError):
            selected.text = "재할당"

    def test_present_empty_field_stays_addressable_and_missing_field_is_rejected(self):
        self.assertEqual(self.session.capture(0, "Character 2 Undesired", "").text, "")
        with self.assertRaises((LookupError, ValueError)):
            self.session.set_value(0, "Character 2 Positive", "")
        self.assertFalse(self.session.dirty)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.queue = TransferWindow(None, lambda: None)
        self.queue.status = Mock()
        self.queue.add_source(SourceText(0, "Base Positive", " 첫째 "))
        self.queue.add_source(SourceText(1, "Character 1 Positive", "둘째\n"))
        self.first, self.second = self.queue.items

    def test_cross_field_mapping_is_bound_to_the_selected_instance_and_revision(self):
        target = "Character 3 Undesired"
        self.queue.endpoint = SimpleNamespace(instance_id="instance-a")
        self.queue.revision = "revision-a"
        self.queue.targets = {target: ("slot-three", "undesired")}
        self.queue.target_positions = {("slot-three", "undesired"): ("character", 3)}
        self.queue.dest = Mock()
        self.queue.dest.get.return_value = target
        self.queue.mode = Mock()
        self.queue.mode.get.return_value = "replace"
        with patch.object(self.queue, "selected", return_value=self.first):
            self.queue.assign()
        self.assertEqual(self.first.source.field, "Base Positive")
        self.assertEqual((self.first.slot, self.first.field, self.first.mode),
                         ("slot-three", "undesired", "replace"))
        self.assertEqual(self.second.mode, "append")
        self.assertFalse(self.second.slot)
        self.assertTrue(self.queue.is_current(self.first))
        self.queue.revision = "revision-b"
        self.assertFalse(self.queue.is_current(self.first))
        self.queue.revision = "revision-a"
        self.queue.endpoint = SimpleNamespace(instance_id="instance-b")
        self.assertFalse(self.queue.is_current(self.first))

    def test_reordering_and_removing_an_item_preserve_the_order_of_remaining_excerpts(self):
        self.queue.add_source(SourceText(0, "Base Positive", " 첫째 "))
        duplicate = self.queue.items[-1]
        with patch.object(self.queue, "selected", return_value=duplicate):
            self.queue.move(-1)
            self.assertEqual(self.queue.items, [self.first, duplicate, self.second])
            self.queue.move(-1)
            self.queue.move(-1)
            self.assertEqual(self.queue.items, [duplicate, self.first, self.second])
            self.queue.remove()
        self.assertEqual(self.queue.items, [self.first, self.second])
        self.assertEqual([item.source.text for item in self.queue.items], [" 첫째 ", "둘째\n"])


if __name__ == "__main__":
    unittest.main()
