"""Exercise the reader's transfer controller without a display, sockets, or clipboard."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bundle import transfer_client as client
from bundle.editing import EditSession
from bundle.model import Card
from bundle.i18n import Language
from bundle.transfer_window import TransferWindow


class Choice:
    """The small part of a read-only Tk combobox used by the controller."""

    def __init__(self, values=()):
        self.values = list(values)
        self.value = ""

    def configure(self, *, values):
        self.values = list(values)

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def current(self, index=None):
        if index is not None:
            self.value = self.values[index]
        return self.values.index(self.value) if self.value in self.values else -1


def synchronous(work, success, error=None):
    """Only replace scheduling. The controller still constructs and handles each call."""
    try:
        result = work()
    except client.TransferError as exc:
        if error is None:
            raise
        error(exc)
    else:
        success(result)


class TransferWindowTests(unittest.TestCase):
    def setUp(self):
        prevent_tk = patch("tkinter.Tk.__init__", side_effect=AssertionError("headless test"))
        prevent_tk.start()
        self.addCleanup(prevent_tk.stop)
        dialogs = patch("bundle.transfer_window.confirm", return_value=False)
        self.confirm = dialogs.start()
        self.addCleanup(dialogs.stop)
        settings = tempfile.TemporaryDirectory()
        self.addCleanup(settings.cleanup)
        self.ui = Language(Path(settings.name) / "language.json")
        self.session = Mock()
        self.form = TransferWindow(Mock(), lambda: None, self.ui, session=self.session)
        self.form.run = synchronous
        self.form.status = Mock()
        self.form.dest = Choice()
        self.form.mode = Choice(["append", "replace"])
        self.form.selected = Mock(return_value=None)
        self.end_a = SimpleNamespace(instance_id="synthetic-a", pid=101, liveness_check=None)
        self.end_b = SimpleNamespace(instance_id="synthetic-b", pid=102, liveness_check=None)
        self.state = {
            "revision": "draft-1", "limit": 3, "canCreate": 2,
            "targets": [{"slot": "base", "number": 0, "fields": ["positive", "undesired"]},
                        {"slot": "slot-b", "number": 1, "fields": ["positive", "undesired"]}],
        }
        # Authentication, sockets and receiver decisions have their own tests.
        self.record = SimpleNamespace(name="Synthetic Preset", path=Path("example.exe"), digest="test")
        self.session.refresh.side_effect = lambda endpoint: (endpoint, self.state, self.record)
        self.session.connect.side_effect = lambda **_: (self.end_a, self.state, self.record)
        self.preview = self.stub("preview", return_value="pending")
        self.status = self.stub("status", return_value="pending")
        self.form.install_targets(self.end_a, self.state)
        self.raw = "작가, (달:1.25)\n\t별"
        card = Card("ok", "합성 원문", "characters", self.raw, "",
                    (("첫째", "둘째"), ("끝", "끝 제외")))
        self.edits = EditSession([card, card])
        self.edits.set_value(0, "Base Positive", self.raw + "  수정됨")
        self.excerpt = "(달:1.25)\n\t별"

    def stub(self, name, **options):
        replacement = patch.object(client, name, **options)
        self.addCleanup(replacement.stop)
        return replacement.start()

    def add(self, image, field, text, destination, mode=0):
        self.form.add_source(self.edits.capture(image, field, text))
        item = self.form.items[-1]
        self.form.selected.return_value = item
        self.form.shown = item
        self.form.dest.set(destination)
        self.form.mode.current(mode)
        self.form.assign()
        return item

    def assert_edit_preserved(self):
        self.assertTrue(self.edits.dirty)
        self.assertEqual(self.edits.value(0, "Base Positive"), self.raw + "  수정됨")
        self.assertEqual(self.edits.original(0, "Base Positive"), self.raw)

    def test_source_to_wire_uses_order_and_exact_excerpts_then_polls_applied(self):
        self.add(1, "Character 2 Undesired", "  끝 제외 ", "캐릭터 1 · 긍정 프롬프트", 1)
        self.add(0, "Base Positive", self.excerpt, "캐릭터 1 · 긍정 프롬프트")
        self.form.send()
        self.preview.assert_called_once()
        endpoint, body = self.preview.call_args.args
        data = json.loads(body)
        self.assertIs(endpoint, self.end_a)
        self.assertEqual(set(data), {"revision", "requestId", "items"})
        self.assertTrue(client.canonical_id(data["requestId"]))
        self.assertEqual(data["revision"], "draft-1")
        self.assertEqual(data["items"], [
            {"source": {"image": 2, "number": 2, "field": "undesired"},
             "slot": "slot-b", "field": "positive", "mode": "replace", "text": "  끝 제외 "},
            {"source": {"image": 1, "number": 0, "field": "positive"},
             "slot": "slot-b", "field": "positive", "mode": "append", "text": self.excerpt},
        ])
        self.assertEqual(len(self.form.items), 2)
        # The operator can collect another excerpt while the receiver shows its preview.
        self.form.add_source(self.edits.capture(0, "Base Undesired", ""))
        later = self.form.items[-1]
        self.status.return_value = "applied"
        delay, poll = self.form.root.after.call_args.args
        self.assertEqual(delay, 800)
        poll()
        self.status.assert_called_once_with(endpoint, data["requestId"])
        self.assertIsNone(self.form.pending)
        self.assertEqual(self.form.items, [later])
        self.assertIs(self.form.endpoint, self.end_a)
        self.assert_edit_preserved()
        poll()
        self.assertEqual(self.status.call_count, 1)

    def test_unconfirmed_rows_survive_then_only_applied_batch_is_removed(self):
        untouched = self.add(0, "Base Positive", self.excerpt, "캐릭터 1 · 제외 프롬프트")
        chosen = self.add(1, "Character 1 Positive", "첫째", "베이스 · 긍정 프롬프트")
        for terminal in ("cancelled", "expired", "failed"):
            with self.subTest(terminal=terminal):
                self.preview.return_value = terminal
                self.form.send()
                items = json.loads(self.preview.call_args.args[1])["items"]
                self.assertEqual([i["text"] for i in items], [self.excerpt, "첫째"])
                self.assertEqual(self.form.items, [untouched, chosen])
                self.assertIsNone(self.form.pending)
        self.preview.return_value = "applied"
        self.form.send()
        self.assertEqual(self.form.items, [])
        self.assert_edit_preserved()

    def test_unknown_receipt_and_not_found_only_resubmit_identical_bytes_after_confirmation(self):
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 긍정 프롬프트")
        self.preview.side_effect = [client.TransferError("시험 응답 유실"), "cancelled"]
        self.form.send()
        pending = self.form.pending
        self.assertIsNotNone(pending)
        endpoint, original = self.preview.call_args.args
        self.assertIn("결과 확인", self.form.status.configure.call_args.kwargs["text"])
        self.form.send()
        self.preview.assert_called_once()
        self.status.side_effect = client.TransferError("시험 조회 결과 없음", code="NOT_FOUND")
        self.confirm.side_effect = [False, False, True]
        self.form.check_result()
        self.assertIs(self.form.pending, pending)
        self.assertEqual(self.form.items, [row])
        self.preview.assert_called_once()
        self.form.check_result()
        self.assertEqual(self.confirm.call_count, 3)
        retried_endpoint, retried = self.preview.call_args.args
        self.assertIs(retried_endpoint, endpoint)
        self.assertEqual(retried, original)
        request_id = json.loads(original)["requestId"]
        for lookup in self.status.call_args_list:
            self.assertEqual(lookup.args, (endpoint, request_id))
        self.assertEqual(self.preview.call_count, 2)
        self.assertIsNone(self.form.pending)
        self.assertEqual(self.form.items, [row])
        self.assert_edit_preserved()

    def test_authentication_failures_cannot_produce_applied_or_a_new_preview(self):
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 제외 프롬프트")
        self.preview.side_effect = client.TransferError("시험 인증 실패", code="UNAUTHORIZED")
        self.form.send()
        self.assertIsNone(self.form.pending)
        self.assertEqual(self.form.items, [row])
        self.status.assert_not_called()
        self.preview.side_effect = None
        self.form.send()
        pending = self.form.pending
        calls = self.preview.call_count
        self.status.side_effect = client.TransferError("서명 확인 실패")
        self.form.root.after.call_args.args[1]()
        self.confirm.assert_not_called()
        self.assertIs(self.form.pending, pending)
        self.assertEqual(self.form.items, [row])
        self.assertEqual(self.preview.call_count, calls)
        self.assert_edit_preserved()

    def test_manual_stop_tracking_after_disconnect_preserves_queue_and_requires_new_assignment(self):
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 제외 프롬프트")
        self.preview.side_effect = client.TransferError("시험 형식 오류", code="INVALID", delivery_possible=False)
        self.form.send()
        self.assertIsNone(self.form.pending)
        self.assertEqual(self.form.items, [row])
        self.preview.side_effect = client.TransferError("응답 유실", delivery_possible=True)
        self.form.send()
        self.status.side_effect = client.TransferError("대상 종료")
        self.confirm.return_value = True
        self.form.check_result()
        self.confirm.assert_called_once()
        self.assertIsNone(self.form.pending)
        self.assertIs(self.form.endpoint, self.end_a)
        self.assertEqual(self.form.items, [row])
        self.assertFalse(row.slot)
        self.assertEqual(row.source.text, self.excerpt)
        self.form.send()
        self.assertEqual(self.preview.call_count, 2)
        self.assert_edit_preserved()

    def test_send_reconnects_with_no_picker_but_new_instance_requires_destination_selection(self):
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 긍정 프롬프트")
        self.session.refresh.side_effect = client.TransferError("offline", delivery_possible=False)
        self.session.connect.side_effect = None
        self.session.connect.return_value = (self.end_b, self.state, self.record)
        self.form.send()
        self.session.connect.assert_called_once_with(allow_launch=True)
        self.preview.assert_not_called()
        self.assertEqual(self.form.items, [row])
        self.assertIs(self.form.endpoint, self.end_b)
        self.assertTrue(row.needs_selection)
        self.session.refresh.side_effect = lambda endpoint: (endpoint, self.state, self.record)
        self.form.assign()
        self.form.send()
        self.preview.assert_called_once()
        self.assertIs(self.preview.call_args.args[0], self.end_b)

    def test_stale_preview_invalidates_old_slot_id_before_current_number_can_be_reassigned(self):
        row = self.add(0, "Base Positive", self.excerpt, "캐릭터 1 · 긍정 프롬프트")
        def edit_during_preview(*_):
            self.state["revision"] = "draft-2"
            self.state["targets"][1]["slot"] = "different-object"
            raise client.TransferError("초안 변경", code="STALE")

        self.preview.side_effect = edit_during_preview
        self.form.send()
        self.assertIs(self.form.endpoint, self.end_a)
        self.assertEqual(self.form.message[0], "send.stale")
        self.assertTrue(row.needs_selection)
        self.assertEqual(self.form.items, [row])
        self.form.send()
        self.assertEqual(self.preview.call_count, 1)
        self.assertEqual(row.slot, "slot-b")
        self.form.assign()
        self.preview.side_effect = None
        self.preview.return_value = "stale"
        self.form.send()
        payload = json.loads(self.preview.call_args.args[1])
        self.assertEqual(payload["revision"], "draft-2")
        self.assertEqual(payload["items"][0]["slot"], "different-object")
        self.assertIs(self.form.endpoint, self.end_a)
        self.assertEqual(self.form.items, [row])
        self.assert_edit_preserved()

    def test_explicit_executable_change_cannot_revive_a_previous_assignment(self):
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 긍정 프롬프트")
        self.form.invalidate_catalogue(reselect=True)
        self.form.install_targets(self.end_a, self.state)
        self.assertTrue(row.needs_selection)
        self.form.send()
        self.preview.assert_not_called()
        self.assertEqual(row.source.text, self.excerpt)

    def test_sparse_new_slot_alone_keeps_exact_absolute_destination(self):
        self.state.update(limit=6, canCreate=5)
        self.form.install_targets(self.end_a, self.state)
        row = self.add(0, "Base Positive", self.excerpt, "캐릭터 4 (새로 만들기) · 긍정 프롬프트")
        self.form.send()
        self.preview.assert_called_once()
        item, = json.loads(self.preview.call_args.args[1])["items"]
        self.assertEqual(item["slot"], "new:3")
        self.assertEqual(item["text"], self.excerpt)
        self.assertEqual(self.form.items, [row])
        self.assertEqual(self.form.message[0], "send.pending")
        self.assert_edit_preserved()

    def test_sparse_reverse_order_and_duplicate_destinations_keep_wire_order(self):
        self.state.update(limit=6, canCreate=5)
        self.form.install_targets(self.end_a, self.state)
        self.add(0, "Base Positive", self.excerpt, "캐릭터 5 (새로 만들기) · 긍정 프롬프트")
        self.add(1, "Character 2 Undesired", " ", "캐릭터 3 (새로 만들기) · 제외 프롬프트")
        self.add(0, "Base Undesired", "", "캐릭터 5 (새로 만들기) · 제외 프롬프트", 1)
        self.form.move(-1)
        self.form.send()
        items = json.loads(self.preview.call_args.args[1])["items"]
        self.assertEqual([i["slot"] for i in items], ["new:4", "new:4", "new:2"])
        self.assertEqual(items[1]["text"], "")
        self.assertEqual(items[1]["mode"], "replace")
        self.assertEqual(items[2]["text"], " ")
        self.assertNotIn("캐릭터 7 (새로 만들기) · 긍정 프롬프트", self.form.dest.values)
        self.assert_edit_preserved()

    def test_new_numbers_include_existing_characters_omitted_from_catalogue(self):
        self.state.update(limit=6, canCreate=3)
        self.state["targets"] = [self.state["targets"][0]]
        self.form.install_targets(self.end_a, self.state)
        self.assertEqual(self.form.targets["캐릭터 4 (새로 만들기) · 긍정 프롬프트"],
                         ("new:1", "positive"))
        self.assertNotIn("캐릭터 1 (새로 만들기) · 긍정 프롬프트", self.form.targets)
        self.add(0, "Base Positive", self.excerpt, "캐릭터 6 (새로 만들기) · 긍정 프롬프트")
        self.form.send()
        self.assertEqual(json.loads(self.preview.call_args.args[1])["items"][0]["slot"], "new:3")

    def test_incomplete_send_explains_missing_input_and_preserves_text(self):
        self.form.send()
        self.assertEqual(self.form.message, ("send.add_first", {}))
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 긍정 프롬프트")
        self.form.endpoint = None
        self.form.invalidate_catalogue(reselect=True)
        self.form.send()
        self.session.connect.assert_called_once_with(allow_launch=True)
        self.assertEqual(self.form.message, ("send.choose_target", {"n": 1}))
        self.assertEqual(row.source.text, self.excerpt)
        self.preview.assert_not_called()

    def test_old_receiver_rejecting_sparse_slots_is_visible_and_keeps_the_queue(self):
        self.state.update(limit=6, canCreate=5)
        self.form.install_targets(self.end_a, self.state)
        row = self.add(0, "Base Positive", self.excerpt, "캐릭터 4 (새로 만들기) · 긍정 프롬프트")
        self.preview.side_effect = client.TransferError(client.ERRORS["INVALID"], code="INVALID")
        self.form.send()
        self.preview.assert_called_once()
        self.assertEqual(self.form.message, ("diagnostic", {"error": client.ERRORS["INVALID"]}))
        self.assertEqual(self.form.items, [row])
        self.assertIsNone(self.form.pending)
        self.assertEqual(row.source.text, self.excerpt)
        self.status.assert_not_called()
        self.assert_edit_preserved()

    def test_unavailable_fields_and_immediate_changes_only_touch_selected_row(self):
        self.state["targets"][1]["fields"] = ["positive"]
        self.form.connect()
        self.assertNotIn("캐릭터 1 · 제외 프롬프트", self.form.dest.values)
        self.assertNotIn("캐릭터 2 (새로 만들기) · 제외 프롬프트", self.form.dest.values)
        other = self.add(0, "Base Positive", self.excerpt, "베이스 · 제외 프롬프트")
        row = self.add(0, "Base Positive", self.excerpt, "캐릭터 1 · 긍정 프롬프트")
        self.form.mode.set("replace")
        self.form.assign_mode()
        self.assertEqual(row.mode, "replace")
        self.assertEqual(other.mode, "append")
        self.form.dest.set("베이스 · 긍정 프롬프트")
        self.form.assign()
        self.form.send()
        items = json.loads(self.preview.call_args.args[1])["items"]
        self.assertEqual([(i["slot"], i["field"], i["mode"]) for i in items],
                         [("base", "undesired", "append"), ("base", "positive", "replace")])

    def test_text_edit_refreshes_revision_without_rebinding_same_destination(self):
        row = self.add(0, "Base Positive", self.excerpt, "캐릭터 1 · 긍정 프롬프트")
        self.state["revision"] = "draft-2"
        self.form.send()
        self.session.connect.assert_not_called()
        self.preview.assert_called_once()
        self.assertFalse(row.needs_selection)
        payload = json.loads(self.preview.call_args.args[1])
        self.assertEqual(payload["revision"], "draft-2")
        self.assertEqual(payload["items"][0]["slot"], "slot-b")

    def test_new_choice_is_invalidated_when_its_absolute_number_moves(self):
        row = self.add(0, "Base Positive", self.excerpt, "캐릭터 2 (새로 만들기) · 긍정 프롬프트")
        self.state.update(revision="draft-2", canCreate=1)
        self.form.send()
        self.assertTrue(row.needs_selection)
        self.preview.assert_not_called()
        self.state.update(revision="draft-3", canCreate=2)
        self.form.send()
        self.assertTrue(row.needs_selection)
        self.preview.assert_not_called()

    def test_definite_pre_submit_failure_recovers_once_without_using_ambiguous_delivery(self):
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 긍정 프롬프트")
        self.preview.side_effect = [client.TransferError("probe stopped", delivery_possible=False), "cancelled"]
        self.form.send()
        self.session.connect.assert_called_once_with(allow_launch=True)
        self.assertEqual(self.preview.call_count, 2)
        self.assertIsNone(self.form.pending)
        self.assertEqual(self.form.items, [row])

    def test_periodic_reconnect_never_requests_launch_or_interrupts_pending(self):
        self.form.window = Mock()
        self.form.window.state.return_value = "normal"
        self.form.watch_connection = True
        self.form._connect = Mock()
        self.form.watch()
        self.form._connect.assert_called_once_with()
        self.form.pending = (self.end_a, "synthetic", b"{}", ())
        self.form.watch()
        self.form._connect.assert_called_once_with()
        self.form.pending = None
        self.form.window.state.return_value = "withdrawn"
        self.form.watch()
        self.form._connect.assert_called_once_with()

    def test_signed_periodic_liveness_does_not_make_ui_busy_or_mutate_targets(self):
        row = self.add(0, "Base Positive", self.excerpt, "캐릭터 1 · 긍정 프롬프트")
        before = (dict(vars(row)), self.form.revision, list(self.form.catalogue),
                  dict(self.form.targets), self.form.dest.get(), self.form.message)
        self.form.window = Mock()
        self.form.window.state.return_value = "normal"
        self.form.watch_connection = True
        self.end_a.liveness_check = Mock()
        self.form._connect = Mock()
        self.form.run = Mock()
        self.form.refresh_list = Mock()
        self.form.watch()
        self.end_a.liveness_check.assert_called_once_with()
        self.form._connect.assert_not_called()
        self.form.run.assert_not_called()
        self.session.refresh.assert_not_called()
        self.session.connect.assert_not_called()
        self.form.refresh_list.assert_not_called()
        self.assertFalse(self.form.busy)
        self.assertIs(self.form.endpoint, self.end_a)
        self.assertEqual(before, (dict(vars(row)), self.form.revision, list(self.form.catalogue),
                                  dict(self.form.targets), self.form.dest.get(), self.form.message))
        self.preview.assert_not_called()
        self.status.assert_not_called()

    def test_signed_periodic_dead_or_changed_process_requests_full_reconnect(self):
        self.form.window = Mock()
        self.form.window.state.return_value = "normal"
        self.form.watch_connection = True
        self.form._connect = Mock()
        for code in ("preset.not_running", "preset.changed", "preset.unverified"):
            with self.subTest(code=code):
                self.end_a.liveness_check = Mock(side_effect=client.TransferError("synthetic", code=code))
                self.form._connect.reset_mock()
                self.form.watch()
                self.end_a.liveness_check.assert_called_once_with()
                self.form._connect.assert_called_once_with()

    def test_signed_periodic_watch_skips_pending_busy_choosing_and_hidden_windows(self):
        self.form.window = Mock()
        self.form.window.state.return_value = "normal"
        self.form.watch_connection = True
        self.end_a.liveness_check = Mock()
        self.form._connect = Mock()
        pending = (self.end_a, "synthetic", b"{}", ())
        for blocked in ("pending", "busy", "choosing", "withdrawn", "disabled"):
            with self.subTest(blocked=blocked):
                self.form.pending = pending if blocked == "pending" else None
                self.form.busy = blocked == "busy"
                self.form.choosing = blocked == "choosing"
                self.form.window.state.return_value = "withdrawn" if blocked == "withdrawn" else "normal"
                self.form.watch_connection = blocked != "disabled"
                self.form.watch()
                if blocked == "pending":
                    self.assertIs(self.form.pending, pending)
        self.end_a.liveness_check.assert_not_called()
        self.form._connect.assert_not_called()

    def test_queue_addition_after_send_click_stays_out_of_inflight_batch(self):
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 긍정 프롬프트")

        def collect_during_refresh(endpoint):
            self.form.add_source(self.edits.capture(0, "Base Undesired", "later"))
            return endpoint, self.state, self.record

        self.session.refresh.side_effect = collect_during_refresh
        self.form.send()
        self.assertEqual(self.form.pending[3], (row,))
        self.assertEqual(len(self.form.items), 2)
        payload = json.loads(self.preview.call_args.args[1])
        self.assertEqual([item["text"] for item in payload["items"]], [self.excerpt])

    def test_language_is_display_only_and_preview_bytes_stay_frozen(self):
        chosen = self.add(0, "Base Positive", self.excerpt, "베이스 · 제외 프롬프트")
        self.form.send()
        original = self.form.pending
        body = original[2]
        for code, target in (("en", "Base · Undesired"), ("ja", "ベース · 除外プロンプト"),
                             ("ko", "베이스 · 제외 프롬프트")):
            self.ui.set(code)
            self.form._format_targets()
            self.assertEqual(self.form._name_for_item(chosen), target)
            self.assertIs(self.form.pending, original)
            self.assertIs(self.form.pending[2], body)
            self.assertEqual(chosen.source.text, self.excerpt)
            self.assertEqual((chosen.field, chosen.mode), ("undesired", "append"))
        self.preview.assert_called_once()

    def test_single_send_never_silently_skips_an_unassigned_row(self):
        selected = self.add(0, "Base Positive", self.excerpt, "베이스 · 긍정 프롬프트")
        self.form.add_source(self.edits.capture(0, "Base Positive", self.excerpt))
        self.form.selected.return_value = selected
        self.form.send()
        self.preview.assert_not_called()
        self.assertEqual(self.form.message, ("send.choose_target", {"n": 2}))
        self.assertEqual(len(self.form.items), 2)
        self.form.items.pop()
        self.form.send()
        self.preview.assert_called_once()
        self.assertEqual(len(json.loads(self.preview.call_args.args[1])["items"]), 1)

    def test_all_languages_use_approved_short_mode_labels(self):
        for lang, modes in (("ko", ("추가", "덮어 쓰기")), ("en", ("Append", "Replace")),
                            ("ja", ("末尾に追加", "上書き"))):
            self.ui.set(lang)
            self.assertEqual(tuple(self.ui.t(key) for key in ("send.append", "send.replace")), modes)
            self.form._error(client.TransferError("send.connection_error"))
            self.assertNotIn("private", self.form.status.configure.call_args.kwargs["text"].lower())

    def test_signed_release_failures_display_localized_recovery_without_internal_keys(self):
        row = self.add(0, "Base Positive", self.excerpt, "베이스 · 긍정 프롬프트")
        before = dict(vars(row))
        keys = ("preset.signature_invalid", "preset.signature_expired", "preset.signature_revoked",
                "preset.signature_rollback", "preset.runtime_mismatch")
        for locale in ("ko", "en", "ja"):
            self.ui.set(locale)
            for key in keys:
                with self.subTest(locale=locale, key=key):
                    expected = self.ui.t(key)
                    self.assertTrue(expected.strip())
                    self.assertNotIn("preset.", expected)
                    self.form._error(client.TransferError(key, code=key, delivery_possible=False))
                    self.assertEqual(self.form.message, (key, {}))
                    self.assertEqual(self.form.status.configure.call_args.kwargs["text"], expected)
                    self.assertEqual(self.form.items, [row])
                    self.assertEqual(vars(row), before)
        self.confirm.assert_not_called()
        self.preview.assert_not_called()
        self.status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
