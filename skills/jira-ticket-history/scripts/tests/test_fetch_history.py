import base64
import json
import os
import sys
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fetch_history as fh  # noqa: E402

SITE = "https://example.atlassian.net"
API = SITE + "/rest/api/2/issue/DEMO-42"


class FakeJira(object):
    """Routes by path, pages by startAt/maxResults, records every URL."""

    def __init__(self, changelog=5, comments=3, worklog_status=200, changelog_status=200, dc=False):
        self.seen = []
        mk = lambda n, p: [{"id": "%s%d" % (p, i + 1), "created": "2026-03-02T10:00:00.000+0200"} for i in range(n)]
        self.all = {"changelog": mk(changelog, "h"), "comments": mk(comments, "c"), "worklogs": mk(1, "w")}
        self.worklog_status, self.changelog_status, self.dc = worklog_status, changelog_status, dc

    def get(self, url, headers=None):
        self.seen.append(url)
        u = urlparse(url)
        q = parse_qs(u.query)
        start = int(q.get("startAt", ["0"])[0])
        size = int(q.get("maxResults", ["50"])[0])
        cut = lambda xs: xs[start:start + size]
        if u.path.endswith("/serverInfo"):
            return {"deploymentType": "Server" if self.dc else "Cloud"}
        if u.path.endswith("/changelog"):
            if self.changelog_status != 200:
                raise fh.HttpError(self.changelog_status, "nope")
            values = cut(self.all["changelog"])
            return {"startAt": start, "total": len(self.all["changelog"]),
                    "isLast": start + len(values) >= len(self.all["changelog"]), "values": values}
        if u.path.endswith("/comment"):
            return {"startAt": start, "total": len(self.all["comments"]), "comments": cut(self.all["comments"])}
        if u.path.endswith("/worklog"):
            if self.worklog_status != 200:
                raise fh.HttpError(self.worklog_status, "no permission")
            return {"startAt": 0, "maxResults": 5000, "total": 1, "worklogs": self.all["worklogs"]}
        if q.get("expand") == ["changelog"]:
            h = self.all["changelog"]
            return {"changelog": {"startAt": 0, "total": len(h), "histories": h}}
        return {"id": "10042", "key": "DEMO-42", "fields": {"summary": "x"}, "names": {}, "schema": {}}


class Parsing(unittest.TestCase):
    def test_keys_and_urls(self):
        self.assertEqual(fh.parse_ticket("demo-42", "https://x.test/"), {"site": "https://x.test", "key": "DEMO-42"})
        self.assertEqual(fh.parse_ticket("https://acme.atlassian.net/browse/OPS-7?atlOrigin=abc"),
                         {"site": "https://acme.atlassian.net", "key": "OPS-7"})
        self.assertIsNone(fh.parse_ticket("not a ticket"))

    def test_auth(self):
        self.assertEqual(fh.auth_header("cloud", "a@b.c", "t"), "Basic " + base64.b64encode(b"a@b.c:t").decode())
        self.assertEqual(fh.auth_header("datacenter", None, "pat"), "Bearer pat")

    def test_args(self):
        with self.assertRaises(ValueError):
            fh.parse_args([])
        with self.assertRaises(ValueError):
            fh.parse_args(["--key", "A-1", "--page-size", "0"])
        self.assertEqual(fh.parse_args(["--key", "A-1", "--page-size", "25"])["page_size"], 25)


class Paging(unittest.TestCase):
    def test_follows_is_last(self):
        j = FakeJira(changelog=5)
        items, info, capped = fh.page_all(API + "/changelog", "values", j.get, 2, 50)
        self.assertEqual(info, {"got": 5, "total": 5, "pages": 3, "complete": True})
        self.assertFalse(capped)

    def test_stops_on_total(self):
        j = FakeJira(comments=3)
        _, info, _ = fh.page_all(API + "/comment?orderBy=created", "comments", j.get, 2, 50)
        self.assertEqual(info, {"got": 3, "total": 3, "pages": 2, "complete": True})

    def test_empty_page_is_incomplete(self):
        _, info, _ = fh.page_all(API + "/changelog", "values", lambda u: {"total": 10, "values": [], "isLast": False}, 2, 50)
        self.assertEqual(info, {"got": 0, "total": 10, "pages": 1, "complete": False})

    def test_cap_is_reported(self):
        j = FakeJira(changelog=9)
        _, info, capped = fh.page_all(API + "/changelog", "values", j.get, 2, 2)
        self.assertTrue(capped)
        self.assertFalse(info["complete"])


class Fetch(unittest.TestCase):
    def test_everything_to_the_end(self):
        j = FakeJira()
        b = fh.fetch_history(SITE + "/", "DEMO-42", "auto", "a@b.c", "t", 2, 50, get_impl=j.get,
                             now=datetime(2026, 3, 4, tzinfo=timezone.utc))
        self.assertEqual(b["deployment"], "cloud")
        self.assertEqual((len(b["changelog"]), len(b["comments"]), len(b["worklogs"])), (5, 3, 1))
        self.assertEqual(b["completeness"]["changelog"], {"got": 5, "total": 5, "pages": 3, "complete": True})
        self.assertEqual(b["errors"], [])
        self.assertEqual(b["fetched_at"], "2026-03-04T00:00:00.000Z")
        self.assertFalse(any("expand=changelog" in u for u in j.seen))

    def test_failing_source_is_recorded(self):
        j = FakeJira(worklog_status=403)
        b = fh.fetch_history(SITE, "DEMO-42", "cloud", "a", "t", 2, 50, get_impl=j.get)
        self.assertEqual(b["errors"], [{"source": "worklogs", "message": "no permission"}])
        self.assertFalse(b["completeness"]["worklogs"]["complete"])

    def test_datacenter_fallback(self):
        j = FakeJira(changelog_status=404, dc=True, changelog=4)
        b = fh.fetch_history(SITE, "DEMO-42", "auto", None, "pat", 2, 50, get_impl=j.get)
        self.assertEqual(b["deployment"], "datacenter")
        self.assertEqual(b["completeness"]["changelog"], {"got": 4, "total": 4, "pages": 1, "complete": True})


class Http(unittest.TestCase):
    def serve(self, handler):
        server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d/x" % server.server_address[1]

    def test_retries_429_after_retry_after(self):
        calls = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                calls.append(1)
                if len(calls) == 1:
                    self.send_response(429)
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"auth": self.headers.get("Authorization")}).encode())

        waits = []
        body = fh.get_json(self.serve(H), {"Authorization": "Bearer t"}, sleep=waits.append)
        self.assertEqual(body, {"auth": "Bearer t"})
        self.assertEqual(waits, [0.0])

    def test_errors_carry_reason(self):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"errorMessages": ["Issue does not exist"]}).encode())

        with self.assertRaises(fh.HttpError) as ctx:
            fh.get_json(self.serve(H), {})
        self.assertEqual(ctx.exception.status, 404)
        self.assertIn("Issue does not exist", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
