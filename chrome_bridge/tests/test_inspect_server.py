import copy
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from chrome_bridge.server import Bridge, INSPECT_URL
from bundle.model import decode_bundle


class InspectTransportTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Bridge(port=0, token="b" * 64)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(self.bridge.close)
        self.addCleanup(self.pool.shutdown)

    def start(self):
        future = self.pool.submit(self.bridge.request_inspect, timeout=2)
        deadline = time.monotonic() + 1
        while self.bridge.job is None and time.monotonic() < deadline:
            time.sleep(.005)
        job = self.bridge.claim()["job"]
        self.assertEqual(job["kind"], "inspect")
        self.assertEqual(job["url"], INSPECT_URL)
        return future, job["id"]

    def result(self, job_id, text):
        return {"id": job_id, "event": "result", "url": INSPECT_URL, "bundle": {
            "format": "chaessi.readable-bundle", "version": 1, "source": INSPECT_URL, "count": 1,
            "cards": [{"index": 0, "origin": "novelai_inspect", "status": "ok", "structure": "characters",
                       "readable": "Prompt: " + text, "base": text, "negative": "",
                       "characters": [{"positive": " paper bird ", "negative": None}]}]}}

    def test_inspect_is_one_card_and_source_bound(self):
        future, job_id = self.start()
        self.assertFalse(self.bridge.accept({"id": job_id, "event": "count", "count": 2}))
        self.assertTrue(self.bridge.accept({"id": job_id, "event": "count", "count": 1}))
        result = self.result(job_id, "  {garden}:1.2\r\n🌿  ")
        for where in ("url", "source", "origin"):
            altered = copy.deepcopy(result)
            if where == "url": altered["url"] = "https://novelai.net/"
            elif where == "source": altered["bundle"]["source"] = "https://novelai.net/inspect?other=1"
            else: altered["bundle"]["cards"][0]["origin"] = "aitag"
            self.assertFalse(self.bridge.accept(altered))
        self.assertTrue(self.bridge.accept(result))
        card, = decode_bundle(future.result(timeout=1))
        self.assertEqual(card.origin, "novelai_inspect")
        self.assertEqual(card.readable, result["bundle"]["cards"][0]["readable"])
        self.assertEqual(card.fields()[1], ("Base Undesired", ""))

    def test_new_inspect_request_never_reuses_previous_result(self):
        first, old_id = self.start()
        self.bridge.accept({"id": old_id, "event": "count", "count": 1})
        old = self.result(old_id, "first paper bird")
        self.assertTrue(self.bridge.accept(old))
        self.assertEqual(first.result(timeout=1)["cards"][0]["base"], "first paper bird")
        second, new_id = self.start()
        self.assertNotEqual(old_id, new_id)
        self.assertFalse(self.bridge.accept(old))
        self.bridge.accept({"id": new_id, "event": "count", "count": 1})
        self.assertTrue(self.bridge.accept(self.result(new_id, "two paper birds")))
        self.assertEqual(second.result(timeout=1)["cards"][0]["base"], "two paper birds")

    def test_aitag_route_does_not_accept_inspect_url(self):
        with self.assertRaises(ValueError):
            self.bridge.request(INSPECT_URL, timeout=.01)


if __name__ == "__main__":
    unittest.main()
