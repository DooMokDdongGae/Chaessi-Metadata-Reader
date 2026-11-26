"""Exercise a temporary bridge over loopback HTTP. All input is synthetic."""
import http.client
import json
import secrets
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from bundle.model import decode_bundle
from chrome_bridge.server import Bridge


SYNTHETIC_URL = "https://aitag.win/i/42"  # Job data only; no site request.
ORIGIN = "chrome-extension://" + "a" * 32


def synthetic_bundle():
    base = "  종이 정원\r\n  (cloud:1.2)\n🌱\r  "
    positive = "  우산\nleaf\r\n  "
    negative = "\tstripes  "
    readable = "기본\r\n" + base + "\n\n인물\n" + positive + "\r\n" + negative
    return {
        "format": "chaessi.readable-bundle", "version": 1, "source": SYNTHETIC_URL, "count": 2, "cards": [
            {"index": 0, "status": "ok", "structure": "characters",
             "readable": readable, "base": base, "negative": "",
             "characters": [{"positive": positive, "negative": negative},
                            {"positive": "blue", "negative": None}]},
            {"index": 1, "status": "missing", "readable": None, "base": None, "negative": None,
             "characters": [], "structure": "unknown"}
        ]
    }


class BridgeHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Supplying the token keeps test execution independent of any installed bridge key.
        cls.bridge = Bridge(port=0, token=secrets.token_hex(32))
        cls.port = cls.bridge.http.server_port
        cls.addClassCleanup(cls.bridge.close)

    def setUp(self):
        self.pool = ThreadPoolExecutor(max_workers=6)
        self.addCleanup(self.pool.shutdown)

    def http(self, method, path, data=None, headers=None):
        request_headers = {
            "Origin": ORIGIN, "Authorization": "Bearer " + self.bridge.token,
            "Content-Type": "application/json"
        }
        for key, value in (headers or {}).items():
            if value is None:
                request_headers.pop(key, None)
            else:
                request_headers[key] = value
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, data, request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read()), response.headers
        finally:
            connection.close()

    def next_job(self):
        status, response, _ = self.http("GET", "/next")
        self.assertEqual(status, 200)
        return response["job"]

    def new_request(self, progress=lambda _: None, timeout=3):
        future = self.pool.submit(self.bridge.request, SYNTHETIC_URL, progress, timeout)
        deadline = time.monotonic() + 1
        # Synchronize only test startup; all job claiming and delivery below use real HTTP.
        while time.monotonic() < deadline:
            with self.bridge.lock:
                if self.bridge.job is not None:
                    return future
            time.sleep(0.005)
        self.fail("The synthetic request was not queued.")

    def event(self, job_id, kind, **data):
        if kind == "result":
            data.setdefault("url", SYNTHETIC_URL)
        event = {"event": kind, "id": job_id, **data}
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        return self.http("POST", "/event", payload)[0]

    def test_origin_authorization_host_and_preflight(self):
        for overrides in [
            {"Authorization": None}, {"Authorization": "Bearer wrong-test-key"},
            {"Origin": "https://fixture.invalid"},
            {"Host": f"localhost:{self.port}"}
        ]:
            with self.subTest(header=next(iter(overrides))):
                self.assertEqual(self.http("GET", "/next", headers=overrides)[0], 403)
                self.assertEqual(self.http("POST", "/event", b"", overrides)[0], 403)
        status, _, response = self.http("OPTIONS", "/event", headers={"Authorization": None})
        self.assertEqual(status, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], ORIGIN)
        self.assertIn("Authorization", response["Access-Control-Allow-Headers"])
        status, _, response = self.http("OPTIONS", "/event", headers={"Origin": "https://fixture.invalid"})
        self.assertEqual(status, 403)
        self.assertIsNone(response.get("Access-Control-Allow-Origin"))
        self.assertEqual(self.http("GET", "/unused")[0], 404)

    def test_chromium_privileged_origins_still_require_secret_and_host(self):
        destination = f"http://127.0.0.1:{self.port}"
        self.assertEqual(self.http("GET", "/next", headers={"Origin": None})[0], 200)
        self.assertEqual(self.http("GET", "/next", headers={"Origin": destination})[0], 200)
        for origin in (None, destination):
            self.assertEqual(self.http("GET", "/next", headers={"Origin": origin, "Authorization": None})[0], 403)
            self.assertEqual(self.http("GET", "/next", headers={"Origin": origin, "Host": f"localhost:{self.port}"})[0], 403)
        for origin in (None, "null", "https://fixture.invalid", "http://127.0.0.1:1"):
            self.assertEqual(self.http("POST", "/event", b"", {"Origin": origin})[0], 403)
        self.assertEqual(self.http("OPTIONS", "/event", headers={"Origin": None})[0], 403)
        future = self.new_request()
        job = self.http("GET", "/next", headers={"Origin": None})[1]["job"]
        event = json.dumps({"id": job["id"], "event": "error", "message": "synthetic origin check"})
        self.assertEqual(self.http("POST", "/event", event, {"Origin": destination})[0], 200)
        with self.assertRaisesRegex(ValueError, "synthetic origin check"):
            future.result(timeout=1)
        counts = self.bridge.snapshot()["requests"]
        self.assertGreater(counts["missing_origin"], 0)
        self.assertGreater(counts["destination_origin"], 0)

    def test_concurrent_clients_claim_only_once(self):
        future = self.new_request()
        with self.assertRaises(ValueError):
            self.bridge.request(SYNTHETIC_URL, timeout=0.1)
        requests = [self.pool.submit(self.next_job) for _ in range(4)]
        claims = [result for item in requests if (result := item.result(timeout=2))]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["url"], SYNTHETIC_URL)
        self.assertEqual(self.event(claims[0]["id"], "error", message="synthetic interruption"), 200)
        with self.assertRaisesRegex(ValueError, "synthetic interruption"):
            future.result(timeout=1)
        self.assertIsNone(self.next_job())

    def test_count_progress_and_exact_utf8_result(self):
        counts = []
        first_count = threading.Event()

        def progress(count):
            counts.append(count)
            first_count.set()

        future = self.new_request(progress)
        job_id = self.next_job()["id"]
        expected = synthetic_bundle()
        self.assertEqual(self.event(job_id, "count", count=2), 200)
        self.assertTrue(first_count.wait(1), "Image count must be reported before completion.")
        self.assertFalse(future.done())
        self.assertEqual(self.event(job_id, "result", bundle=expected), 200)
        actual = future.result(timeout=1)
        self.assertEqual(counts, [2])
        self.assertTrue(actual == expected, "Transport changed a synthetic value.")
        card, missing = decode_bundle(actual)
        first = expected["cards"][0]
        self.assertTrue(card.readable.encode("utf-8") == first["readable"].encode("utf-8"), "Raw bytes changed.")
        self.assertTrue(card.base == first["base"] and card.negative == "")
        self.assertTrue(card.characters == tuple((c["positive"], c["negative"]) for c in first["characters"]))
        self.assertEqual(missing.status, "missing")
        self.assertEqual(self.event(job_id, "result", bundle=expected), 409)

    def test_rejected_events_leave_active_job_recoverable(self):
        future = self.new_request()
        job_id = self.next_job()["id"]
        self.assertEqual(self.http("POST", "/event", b"{")[0], 400)
        self.assertEqual(self.event(job_id, "result", bundle=synthetic_bundle()), 409)
        self.assertEqual(self.event(job_id, "count", count=True), 409)
        self.assertEqual(self.event(job_id, "count", count=0), 409)
        self.assertEqual(self.event(job_id, "count", count=2), 200)
        self.assertEqual(self.event(job_id, "count", count=2), 409)
        other_url = "https://aitag.win/i/43"
        self.assertEqual(self.event(job_id, "result", url=other_url, bundle=synthetic_bundle()), 409)
        other_work = synthetic_bundle()
        other_work["source"] = other_url
        self.assertEqual(self.event(job_id, "result", bundle=other_work), 409)
        for problem in ["mismatched-count", "missing-card", "wrong-order", "duplicate-index", "invalid-version"]:
            with self.subTest(problem=problem):
                data = synthetic_bundle()
                if problem == "mismatched-count":
                    data["count"] = 1
                    data["cards"].pop()
                elif problem == "missing-card":
                    data["cards"].pop()
                elif problem == "wrong-order":
                    data["cards"].reverse()
                elif problem == "duplicate-index":
                    data["cards"][1]["index"] = 0
                else:
                    data["version"] = 100
                self.assertIn(self.event(job_id, "result", bundle=data), (400, 409))
        self.assertFalse(future.done())
        self.assertEqual(self.event(job_id, "result", bundle=synthetic_bundle()), 200)
        self.assertTrue(future.result(timeout=1) == synthetic_bundle(), "Valid result after retry changed.")

    def test_timeout_and_late_reply_do_not_reach_next_job(self):
        expired = self.new_request(timeout=0.35)
        old_id = self.next_job()["id"]
        with self.assertRaisesRegex(ValueError, "시간"):
            expired.result(timeout=2)
        self.assertEqual(self.event(old_id, "count", count=2), 409)
        new = self.new_request()
        new_id = self.next_job()["id"]
        self.assertNotEqual(new_id, old_id)
        self.assertEqual(self.event(old_id, "error", message="late from previous job"), 409)
        self.assertEqual(self.event(new_id, "count", count=2), 200)
        self.assertEqual(self.event(new_id, "result", bundle=synthetic_bundle()), 200)
        self.assertTrue(new.result(timeout=1) == synthetic_bundle())


if __name__ == "__main__":
    unittest.main()
