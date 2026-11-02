"""安全回归测试：在随机端口起一个真实服务（临时数据目录），检查跨站请求、DNS 重绑定、点击劫持防护等。
不联网、不发通知。python3 -m unittest discover tests"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server as s  # noqa: E402


class Security(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.old_data = s.DATA
        s.DATA = cls.tmp
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        s.DATA = cls.old_data
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, dict(r.getheaders()), data

    def write(self, body, extra=None):
        h = {"Content-Type": "application/json", "X-QS-Client": "1", **(extra or {})}
        return self.req("POST", "/api/config", json.dumps(body), h)

    def test_write_needs_custom_header(self):
        st, _, _ = self.req("POST", "/api/config", json.dumps({"fred_key": "x"}), {"Content-Type": "application/json"})
        self.assertEqual(st, 403)

    def test_text_plain_rejected(self):
        st, _, _ = self.req("POST", "/api/config", '{"fred_key":"x"}', {"Content-Type": "text/plain", "X-QS-Client": "1"})
        self.assertEqual(st, 403)

    def test_foreign_origin_rejected(self):
        st, _, _ = self.write({"fred_key": "x"}, {"Origin": "https://evil.example"})
        self.assertEqual(st, 403)

    def test_dns_rebinding_rejected(self):
        for path in ("/api/watchlist", "/"):
            st, _, _ = self.req("GET", path, headers={"Host": f"evil.example:{self.port}"})
            self.assertEqual(st, 403, path)

    def test_restart_needs_custom_header(self):
        st, _, _ = self.req("POST", "/api/restart")
        self.assertEqual(st, 403)  # 千万不能真的重启测试进程

    def test_config_never_echoed(self):
        st, _, data = self.write({"fred_key": "SECRET-KEY-123", "sec_email": "me@example.com"})
        self.assertEqual(st, 200)
        self.assertNotIn(b"SECRET", data)
        self.assertNotIn(b"example.com", data)
        self.assertEqual(json.loads(data)["fred_key"], True)

    def test_security_headers(self):
        st, h, _ = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn("frame-ancestors 'none'", h.get("Content-Security-Policy", ""))
        self.assertIn("script-src 'self'", h.get("Content-Security-Policy", ""))
        self.assertEqual(h.get("X-Frame-Options"), "DENY")
        self.assertEqual(h.get("X-Content-Type-Options"), "nosniff")

    def test_no_directory_listing(self):
        st, _, data = self.req("GET", "/fonts/")
        self.assertEqual(st, 404)
        self.assertNotIn(b"woff2", data)

    def test_path_traversal(self):
        st, _, data = self.req("GET", "/../server.py")
        self.assertNotEqual(st, 200)
        self.assertNotIn(b"def route", data)

    def test_bad_symbol_rejected_before_saving(self):
        st, _, _ = self.req("POST", "/api/watchlist", json.dumps({"sym": "<script>"}),
                            {"Content-Type": "application/json", "X-QS-Client": "1"})
        self.assertEqual(st, 400)
        self.assertNotIn("<SCRIPT>", json.dumps(s.load_json("watchlist.json", [])))

    def test_xml_entities_rejected(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss><item><title>&b;</title></item></rss>'
        with self.assertRaises(s.ApiError):
            s.parse_xml(bomb)
        self.assertEqual(s.parse_xml("<rss><item><title>ok</title></item></rss>").find("item/title").text, "ok")


if __name__ == "__main__":
    unittest.main()
