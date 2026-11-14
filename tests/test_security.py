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
from unittest import mock

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

    def test_secrets_live_in_their_own_file(self):
        """密钥写进 secrets.json，偏好留在 config.json；旧版本留在 config.json 里的密钥启动时搬走"""
        s.save_json("secrets.json", {})  # 其他测试可能已经写过密钥
        st, _, _ = self.write({"eia_key": "EIA-SECRET-1"})
        self.assertEqual(st, 200)
        sec = json.load(open(os.path.join(s.DATA, "secrets.json"), encoding="utf-8"))
        self.assertEqual(sec["eia_key"], "EIA-SECRET-1")
        cfg = json.load(open(os.path.join(s.DATA, "config.json"), encoding="utf-8")) if os.path.exists(os.path.join(s.DATA, "config.json")) else {}
        self.assertFalse(any(k in cfg for k in s.KEY_FIELDS))
        self.assertEqual(s.config()["eia_key"], "EIA-SECRET-1")
        # 旧格式迁移
        s.save_json("config.json", {**cfg, "fred_key": "OLD-FRED", "alert_interval": 5})
        self.assertTrue(s.migrate_secrets())
        self.assertFalse(s.migrate_secrets())
        cfg2 = json.load(open(os.path.join(s.DATA, "config.json"), encoding="utf-8"))
        sec2 = json.load(open(os.path.join(s.DATA, "secrets.json"), encoding="utf-8"))
        self.assertNotIn("fred_key", cfg2)
        self.assertEqual(cfg2["alert_interval"], 5)
        self.assertEqual((sec2["fred_key"], sec2["eia_key"]), ("OLD-FRED", "EIA-SECRET-1"))
        if os.name != "nt":
            self.assertEqual(os.stat(os.path.join(s.DATA, "secrets.json")).st_mode & 0o777, 0o600)

    def test_export_has_no_secrets_and_import_validates(self):
        s.save_json("secrets.json", {"fred_key": "TOPSECRET"})
        st, _, data = self.req("GET", "/api/watchlist/export")
        self.assertEqual(st, 200)
        self.assertNotIn(b"TOPSECRET", data)
        body = json.loads(data)
        self.assertIn("watchlist", body)
        h = {"Content-Type": "application/json", "X-QS-Client": "1"}
        st, _, data = self.req("POST", "/api/watchlist/import", json.dumps({"watchlist": [{"sym": "../etc"}]}), h)
        self.assertEqual(st, 400)
        st, _, data = self.req("POST", "/api/watchlist/import", json.dumps({"watchlist": "nope"}), h)
        self.assertEqual(st, 400)
        st, _, data = self.req("POST", "/api/watchlist/import", json.dumps({"watchlist": [{"sym": "ADDED", "added": "2026-01-01"}]}), h)
        self.assertEqual(st, 200, data)  # 加入时间字段坏了不影响导入
        self.assertGreater(next(i for i in s.load_json("watchlist.json", []) if i["sym"] == "ADDED")["added"], 1_700_000_000)
        st, _, data = self.req("POST", "/api/watchlist/import", json.dumps({"watchlist": [{"sym": "msft", "move_pct": 999, "label": "x" * 100, "added": 1700000000}], "managers": [{"cik": "0001067983", "name": "Berkshire"}, {"cik": "abc"}]}), h)
        self.assertEqual(st, 200, data)
        r = json.loads(data)
        self.assertEqual(r["added"], 1)
        items = s.load_json("watchlist.json", [])
        m = next(i for i in items if i["sym"] == "MSFT")
        self.assertEqual((m["move_pct"], len(m["label"]), m["added"]), (100.0, 40, 1700000000))
        self.assertIn(1067983, [x["cik"] for x in s.load_json("managers.json", [])])
        # 再导一次同样的内容：合并模式不重复添加
        st, _, data = self.req("POST", "/api/watchlist/import", json.dumps({"watchlist": [{"sym": "MSFT"}]}), h)
        self.assertEqual(json.loads(data)["added"], 0)
        # 替换模式
        st, _, data = self.req("POST", "/api/watchlist/import", json.dumps({"watchlist": [{"sym": "TSLA"}], "replace": True}), h)
        self.assertEqual([i["sym"] for i in s.load_json("watchlist.json", [])], ["TSLA"])
        # 持仓也随备份导入；整份文件里没有一条格式正确的记录时拒绝
        st, _, data = self.req("POST", "/api/watchlist/import", json.dumps({"watchlist": [], "positions": [{"sym": "AAPL", "shares": 5, "cost": 100}]}), h)
        self.assertEqual((st, json.loads(data)["positions_added"]), (200, 1))
        self.assertEqual(s.load_json("positions.json", [])[0]["shares"], 5.0)
        st, _, data = self.req("POST", "/api/watchlist/import", json.dumps({"watchlist": [], "positions": [{"sym": "AAPL", "shares": 0}]}), h)
        self.assertEqual(st, 400)
        st, _, data = self.req("GET", "/api/watchlist/export")
        self.assertEqual(json.loads(data)["positions"][0]["sym"], "AAPL")
        # 持仓接口：写入要自定义头；删除
        st, _, _ = self.req("POST", "/api/portfolio", json.dumps({"sym": "MSFT", "shares": 1, "cost": 1}), {"Content-Type": "application/json"})
        self.assertEqual(st, 403)
        with mock.patch.object(s, "quote_summary", side_effect=s.ApiError("offline")):
            st, _, data = self.req("DELETE", "/api/portfolio?sym=AAPL", None, {"X-QS-Client": "1"})
        self.assertEqual(st, 200)
        self.assertEqual(s.load_json("positions.json", []), [])

    def test_long_cache_only_for_successful_static_files(self):
        st, h, _ = self.req("GET", "/fonts/fonts.css")
        self.assertEqual(st, 200)
        self.assertIn("immutable", h["Cache-Control"])
        st, h, _ = self.req("GET", "/fonts/missing.woff2")
        self.assertEqual(st, 404)
        self.assertEqual(h["Cache-Control"], "no-cache")  # 404 不能被浏览器缓存一年
        st, h, _ = self.req("GET", "/style.css")
        self.assertEqual(h["Cache-Control"], "no-cache")

    def test_unread_body_closes_the_connection(self):
        """被拒绝 / 过大的请求体没被读走时必须关连接，否则长连接上它会被当成下一个请求"""
        h = {"Content-Type": "application/json", "X-QS-Client": "1", "Content-Length": "2000000"}
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("POST", "/api/config", skip_host=True)
        for k, v in {"Host": f"127.0.0.1:{self.port}", **h}.items():
            c.putheader(k, v)
        c.endheaders()
        r = c.getresponse()
        self.assertEqual(r.status, 400)
        self.assertEqual(r.getheader("Connection"), "close")
        r.read()
        c.close()
        st, h2, _ = self.req("POST", "/api/config", '{"fred_key":"x"}', {"Content-Type": "application/json"})  # 403：没读 body
        self.assertEqual((st, h2.get("Connection")), (403, "close"))
        st, h3, _ = self.write({"finnhub_key": ""})  # 正常读完 body 的请求保持长连接
        self.assertEqual(st, 200)
        self.assertIsNone(h3.get("Connection"))

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

    def test_malformed_request_line_gets_an_error_response(self):
        """请求行不合法时 send_error 在解析出 path 之前就发响应头，这里不能抛异常，客户端要收到状态行"""
        import socket
        for raw, code in ((b"GET / HTTP/9.9\r\nHost: x\r\n\r\n", b"505"), (b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n", b"414"), (b"BLAH\r\n\r\n", b"400")):
            with self.subTest(code=code):
                c = socket.create_connection(("127.0.0.1", self.port), timeout=5)
                c.sendall(raw)
                head = b""
                while True:  # 读完整个响应再关，不然服务端写响应时会报 Broken pipe
                    chunk = c.recv(65536)
                    if not chunk:
                        break
                    head += chunk
                c.close()
                self.assertTrue(head.startswith(b"HTTP/1.1 " + code), head[:80])

    def test_rejected_body_is_not_run_as_next_request_on_keep_alive(self):
        """同一条长连接上：先发一个正常 POST（请求体已读），再发一个被拒绝的 POST，后者的请求体不能被当成下一个请求执行"""
        import socket
        import time
        host = f"Host: 127.0.0.1:{self.port}\r\n"
        b1 = b'{"enabled": false}'
        req1 = (f"POST /api/digest HTTP/1.1\r\n{host}X-QS-Client: 1\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(b1)}\r\n\r\n").encode() + b1
        hidden = f"GET /api/version HTTP/1.1\r\n{host}\r\n".encode()
        req2 = (f"POST /api/digest/run HTTP/1.1\r\n{host}Content-Type: application/json\r\n"
                f"Content-Length: {len(hidden)}\r\n\r\n").encode() + hidden
        c = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        c.sendall(req1)
        time.sleep(0.3)
        c.sendall(req2)
        out = b""
        while True:
            chunk = c.recv(65536)
            if not chunk:
                break
            out += chunk
        c.close()
        self.assertEqual(out.count(b"HTTP/1.1 "), 2, out[:300])  # 只有两个响应，藏在请求体里的 GET 没有执行
        self.assertNotIn(b'"version"', out)

    def test_xml_doctype_after_long_comment_rejected(self):
        """DOCTYPE 前面塞 30 KB 注释也要被识别出来，不能只检查开头一段"""
        pad = "<!--" + "x" * 30000 + "-->"
        evil = pad + '<!DOCTYPE r [<!ENTITY a "AAAA">]><rss><item><title>&a;</title></item></rss>'
        with self.assertRaises(s.ApiError):
            s.parse_xml(evil)
        with self.assertRaises(s.ApiError):
            s.parse_xml('<?xml version="1.0"?>\n<!-- c --><!DOCTYPE rss SYSTEM "http://evil/x.dtd"><rss/>')
        # 注释、处理指令、CDATA 里出现的 DOCTYPE 字样属于正文，不是声明
        ok = s.parse_xml(pad + '<?xml-stylesheet href="a"?><rss><item><title><![CDATA[<!DOCTYPE html> hi]]></title></item></rss>')
        self.assertEqual(ok.find("item/title").text, "<!DOCTYPE html> hi")

    def test_xml_entities_rejected(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss><item><title>&b;</title></item></rss>'
        with self.assertRaises(s.ApiError):
            s.parse_xml(bomb)
        self.assertEqual(s.parse_xml("<rss><item><title>ok</title></item></rss>").find("item/title").text, "ok")


class RemoteBody(unittest.TestCase):
    """远程响应的 gzip 解压和大小限制（不联网，用假的响应对象）"""

    class Resp:
        def __init__(self, body, enc=None):
            self.body, self.headers = body, {"Content-Encoding": enc} if enc else {}

        def read(self, n):
            return self.body[:n]

    def test_plain_and_gzip(self):
        import gzip
        self.assertEqual(s.read_body(self.Resp(b'{"a":1}')), b'{"a":1}')
        self.assertEqual(s.read_body(self.Resp(gzip.compress(b'{"a":1}'), "gzip")), b'{"a":1}')

    def test_size_limits(self):
        import gzip
        with self.assertRaises(s.ApiError):
            s.read_body(self.Resp(b"x" * 2001), limit=2000)
        bomb = gzip.compress(b"0" * 5_000_000)  # 压缩后只有几 KB，解压后远超限制
        self.assertLess(len(bomb), 2000 * 10)
        with self.assertRaises(s.ApiError):
            s.read_body(self.Resp(bomb, "gzip"), limit=100_000)

    def test_bad_encoding(self):
        with self.assertRaises(s.ApiError):
            s.read_body(self.Resp(b"not gzip", "gzip"))
        with self.assertRaises(s.ApiError):
            s.read_body(self.Resp(b"x", "br"))


if __name__ == "__main__":
    unittest.main()
