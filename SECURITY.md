# Security

Quant Stock God is a **local, single-user tool**. The server binds to `127.0.0.1` only and has no login, so anything that can reach that port on your machine is trusted. Do not expose it to a network (port forwarding, tunnels or reverse proxies) or run it on a shared server.

## What is protected

| Threat | Protection |
|---|---|
| A website you visit sends requests to `localhost:8767` (CSRF) | Every state-changing request must carry the custom header `X-QS-Client` and a JSON body; a cross-site page cannot add that header without a CORS preflight, which the server never approves. Requests whose `Origin` shows another site are also rejected with 403. |
| DNS rebinding (an attacker's domain resolves to 127.0.0.1) | Only `Host: 127.0.0.1:<port>` or `localhost:<port>` is accepted, for API calls and static files alike. |
| Malicious headlines or feed content containing HTML/JS | All rendered data is escaped, and links from feeds must be `http(s)`. A Content-Security-Policy allows only same-origin script files, so inline scripts and `on*=` handlers cannot run even if escaping were missed. |
| Clickjacking | `X-Frame-Options: DENY` and `frame-ancestors 'none'` |
| Hostile or hijacked data sources | Remote responses over 25 MB are rejected, before and after gzip decompression (so a small "compression bomb" cannot fill memory). XML with a DOCTYPE or entity declaration ("XML bombs") is refused before parsing; the whole prolog is scanned, so a long comment cannot push the DOCTYPE past the check. SEC accession numbers and document names must match their expected format before they are used in URLs, cache file names or page links. |
| Malformed input | Symbols, names and numbers are validated and length-limited; NaN and infinity are rejected. Request bodies over 1 MB are rejected. |

These checks are covered by `tests/test_security.py`, which starts a real server on a random port.

## Where your data lives

- **API keys and the SEC contact email** are stored in `data/config.json`. The page only ever shows "configured / not configured", and keys are kept out of error messages, logs and cache keys. The file is written with owner-only permissions where the file system supports it (external drives formatted as exFAT do not).
- **Runtime data.** `data/` also holds the watchlist, alert history and cache. It is never committed (see `.gitignore`).
- **Outbound requests.** The tool only contacts the public HTTPS data sources listed in the README. The symbols you look up are therefore visible to those providers. Your SEC contact email is sent only to sec.gov, as SEC requires.

## Reporting a vulnerability

Please report security issues privately through GitHub's **"Report a vulnerability"** (security advisory) on the repository instead of opening a public issue. Include steps to reproduce and the affected version or commit. If that isn't available, send a DM on X to [@FuturEvoLab](https://x.com/FuturEvoLab) and don't post the details publicly.
