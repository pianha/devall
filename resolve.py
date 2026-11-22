#!/usr/bin/env python3
"""Resolve every stream URL in a source m3u to its final real address.

The source list (pianha/IPTV-Unicom IPTV.m3u) contains only redirector
URLs like http://45.192.97.170:8880/play/<id>.m3u8 . Each of them answers
with a 302 chain; a browser/player follows it and ends up on the real
upstream m3u8 (often carrying a timestamp/token). This script follows the
same chain for every entry and writes a new m3u where each redirector URL
is replaced by the final effective URL. Entries that fail to resolve keep
their original URL, so the output never loses a channel.

Stdlib only. Usage:
    python3 resolve.py [source_url_or_file] [output_file]
Defaults: the IPTV-Unicom raw URL -> IPTV-real.m3u
Env:
    RESOLVE_LIMIT   if set to N, only resolve the first N stream URLs
                    (for quick tests); other lines pass through unchanged.
    RESOLVE_WORKERS thread count (default 32)
    RESOLVE_TIMEOUT per-request timeout seconds (default 15)
"""
import concurrent.futures
import os
import sys
import urllib.error
import urllib.request

DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/pianha/IPTV-Unicom/"
    "refs/heads/main/IPTV.m3u"
)
DEFAULT_OUTPUT = "IPTV-real.m3u"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)
WORKERS = int(os.environ.get("RESOLVE_WORKERS", "32"))
TIMEOUT = float(os.environ.get("RESOLVE_TIMEOUT", "15"))
LIMIT = int(os.environ.get("RESOLVE_LIMIT", "0"))


def fetch_source(source):
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    with open(source, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def resolve_one(url):
    """Follow redirects like a browser; return (final_url, ok)."""
    for _attempt in range(2):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                final = resp.geturl()
                status = resp.status
            if status == 200 and final:
                return final, final != url
            return url, False
        except Exception:
            continue
    return url, False


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    output = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT

    text = fetch_source(source)
    lines = text.splitlines()

    stream_idx = [
        i for i, ln in enumerate(lines)
        if ln.strip().startswith(("http://", "https://"))
    ]
    targets = stream_idx if LIMIT <= 0 else stream_idx[:LIMIT]
    print(f"total streams: {len(stream_idx)}, resolving: {len(targets)}",
          flush=True)

    resolved = {}
    ok = changed = 0
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=WORKERS
    ) as pool:
        futures = {
            pool.submit(resolve_one, lines[i].strip()): i
            for i in targets
        }
        for fut in concurrent.futures.as_completed(futures):
            i = futures[fut]
            final, is_changed = fut.result()
            resolved[i] = final
            ok += 1
            changed += 1 if is_changed else 0
            if ok % 500 == 0:
                print(f"  {ok}/{len(targets)} done, "
                      f"{changed} redirected", flush=True)

    failed = len(targets) - changed
    for i, final in resolved.items():
        lines[i] = final

    with open(output, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"done: {len(targets)} checked, {changed} replaced with real "
          f"address, {failed} kept original (failed or no redirect)")
    print(f"output: {output}")


if __name__ == "__main__":
    main()
