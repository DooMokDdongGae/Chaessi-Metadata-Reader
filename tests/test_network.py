import html
import io
import json
import socket
import ssl
import time
import unittest
from unittest.mock import MagicMock, patch

import reader_network as net


WORK = "https://aitag.win/i/42"


def picture(number):
    return f'<img src="https://{net.IMAGE_HOST}/fixture-{number}.png">'


def block(value):
    return "<pre><code>" + html.escape(json.dumps(value, ensure_ascii=False)) + "</code></pre>"


class PublicReaderTests(unittest.TestCase):
    def fails(self, code, function, *args):
        with self.assertRaises(net.ReaderNetworkError) as caught:
            function(*args)
        self.assertEqual(code, caught.exception.code)

    def test_gallery_order_entities_empty_slot_and_duplicate_cover(self):
        first = {"Description": "  <b>종이</b> &amp; (ink:1.2)\n", "Comment": {"uc": ""}}
        third = {"parameters": "blue sky\nNegative prompt: grain\nSteps: 2"}
        page = (picture(1) + "<h1>제목</h1>" + picture(1) + block(first)
                + picture(2) + picture(3) + block(third))
        with patch.object(net, "_get", return_value=(200, "", "text/html", page.encode())) as get:
            self.assertEqual([first, {}, third], net.fetch_work(WORK))
            self.assertEqual(1, get.call_count)
            self.assertEqual("/i/42", get.call_args.args[0])

    def test_json_single_and_bundle(self):
        a = {"prompt": "  apricot  "}
        for body, expected in ((a, [a]), ({"images": [None, a]}, [{}, a])):
            with self.subTest(body=body), patch.object(net, "_get", return_value=(
                    200, "", "application/json", json.dumps(body).encode())):
                self.assertEqual(expected, net.fetch_work(WORK))

    def test_unrelated_html_and_script_are_never_metadata(self):
        before = "<pre>{\"prompt\":\"outside\"}</pre>"
        script = '<script type="application/json">{"prompt":"embedded code"}</script>'
        page = (before + picture(1) + script).encode()
        with patch.object(net, "_get", return_value=(200, "", "text/html", page)):
            self.fails("layout", net.fetch_work, WORK)
        self.fails("layout", net._images, "text/html", before.encode())
        explicit_empty = (picture(1) + block({})).encode()
        with patch.object(net, "_get", return_value=(200, "", "text/html", explicit_empty)):
            self.fails("no_metadata", net.fetch_work, WORK)

    def test_duplicate_and_unfinished_json_fail_entire_work(self):
        prefix = picture(0) + block({"prompt": "earlier"}) + picture(1)
        for suffix, code in ((block({"a": 1}) + block({"b": 2}), "layout"),
                             ("<pre>{", "layout"), ("<code>{bad}</code>", "malformed")):
            with self.subTest(code=code):
                self.fails(code, net._images, "text/html", (prefix + suffix).encode())

    def test_official_dynamic_view_stops_before_work_data(self):
        shell = b'<script src="/app.js?v=1"></script><script src="/ai_metadata_view.js"></script>'
        preview = (picture(1) + block({"prompt": "preview only"})).encode()
        for document in (shell, shell + preview):
            with patch.object(net, "_get", return_value=(200, "", "text/html", document)) as get:
                self.fails("site_view_required", net.fetch_work, WORK)
                self.assertEqual(1, get.call_count)
        self.fails("site_view_required", net._images, "application/json", b'{"work":{},"images":[]}')

    def test_urls_checked_before_any_io(self):
        invalid = ["http://aitag.win/i/1", "https://aitag.win:444/i/1",
                   "https://aitag.win@127.0.0.1/i/1", "https://aitag.win.evil.test/i/1",
                   "https://aitag.win/i/1?next=https://example.com", "https://aitag.win/i/1#2",
                   "https://aitag.win/i/1/../../other", "file:///tmp/test", "https://[::1]/i/1",
                   "https://aitag.win/i/１", "https://aitag.win/i/1\r\nOther: foo"]
        with patch.object(net, "_get") as get:
            for link in invalid:
                with self.subTest(link=link):
                    self.fails("url", net.fetch_work, link)
            get.assert_not_called()

    def test_redirect_target_and_work_checked_before_second_get(self):
        for link in ("https://example.com/i/42", "/i/43", "//127.0.0.1/i/42", "/login", ""):
            with self.subTest(link=link), patch.object(net, "_get", return_value=(
                    302, link, "text/html", b"")) as get:
                self.fails("redirect", net.fetch_work, WORK)
                self.assertEqual(1, get.call_count)
        with patch.object(net, "_get", side_effect=[
                (301, "/i/42/", "", b""), (200, "", "application/json", b'{"prompt":"sky"}')]):
            self.assertEqual([{"prompt": "sky"}], net.fetch_work(WORK))
        with patch.object(net, "_get", return_value=(307, WORK, "", b"")) as get:
            self.fails("redirect", net.fetch_work, WORK)
            self.assertEqual(3, get.call_count)

    def test_http_restrictions_and_transport_failures(self):
        for status, code in ((403, "restricted"), (429, "restricted"), (404, "http"), (500, "http")):
            with self.subTest(status=status), patch.object(net, "_get", return_value=(
                    status, "", "text/html", b"forbidden")) as get:
                self.fails(code, net.fetch_work, WORK)
                self.assertEqual(get.call_count, 1)
        for error, code in ((TimeoutError(), "timeout"), (ssl.SSLError(), "tls"),
                            (ConnectionResetError(), "connection")):
            with self.subTest(code=code), patch.object(net, "_get", side_effect=error):
                self.fails(code, net.fetch_work, WORK)

    def test_private_dns_mixed_answers_and_special_ranges_are_blocked(self):
        for address in ("127.0.0.1", "10.1.1.1", "169.254.169.254", "100.64.0.1",
                        "224.0.0.1", "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1",
                        "64:ff9b::7f00:1", "2002:7f00:0001::", "ff05::1"):
            with self.subTest(address=address):
                self.assertFalse(net._public_address(address))
        entries = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
                   for ip in ("1.1.1.1", "127.0.0.1")]
        with patch.object(net.socket, "getaddrinfo", return_value=entries), patch.object(
                net.socket, "socket") as connect:
            self.fails("address", net.fetch_work, WORK)
            connect.assert_not_called()
        with patch.object(net.socket, "getaddrinfo", side_effect=socket.gaierror()):
            self.fails("dns", net.fetch_work, WORK)

    def test_tls_uses_pinned_address_and_certificate_host(self):
        target = ("1.1.1.1", 443)
        entry = (socket.AF_INET, socket.SOCK_STREAM, 6, "", target)
        with patch.object(net.socket, "getaddrinfo", return_value=[entry]) as lookup, patch.object(
                net.socket, "socket") as factory, patch.object(net.ssl, "create_default_context") as tls:
            net._connect(time.monotonic() + 5)
            raw = factory.return_value.__enter__.return_value
            raw.connect.assert_called_once_with(target)
            tls.return_value.wrap_socket.assert_called_once_with(raw, server_hostname="aitag.win")
            lookup.assert_called_once_with("aitag.win", 443, type=socket.SOCK_STREAM)

    def test_http_read_is_anonymous_bounded_get(self):
        with patch.object(net, "_connect"), patch.object(net.http.client, "HTTPConnection") as factory:
            response = factory.return_value.getresponse.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"prompt":"rain"}'
            response.getheader.side_effect = {"Content-Type": "application/json"}.get
            status, _, _, data = net._get("/i/42", time.monotonic() + 5)
            self.assertEqual((200, b'{"prompt":"rain"}'), (status, data))
            request = factory.return_value.request.call_args
            self.assertEqual(("GET", "/i/42"), request.args)
            self.assertEqual({"User-Agent", "Accept", "Accept-Encoding", "Connection"},
                             set(request.kwargs["headers"].keys()))
            response.read.assert_called_once_with(net.MAX_BYTES + 1)

    def test_declared_size_stream_size_and_truncation(self):
        with patch.object(net, "MAX_BYTES", 8):
            for length, content, error in (("9", b"", "size"), (None, b"123456789", "size"),
                                           ("6", b"12", "http"), ("-1", b"", "http")):
                with self.subTest(error=error, length=length):
                    reply = MagicMock()
                    reply.getheader.side_effect = {"Content-Length": length}.get
                    reply.read = io.BytesIO(content).read
                    self.fails(error, net._read_body, reply)

    def test_unrecognized_media_or_malformed_json(self):
        self.fails("format", net._images, "image/png", b"data")
        self.fails("format", net._images, "text/html", b"\xfe")
        self.fails("format", net._images, "application/json", b'"wrong"')
        self.fails("format", net._images, "application/json", b'{"images":{}}')
        self.fails("malformed", net._images, "application/json", b'{')


if __name__ == "__main__":
    unittest.main()
