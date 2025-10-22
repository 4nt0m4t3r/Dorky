#!/usr/bin/env python3
"""
dorky_playwright_reuse.py

Playwright Google scraper — reuses a single context + page (no new tab per query),
adds light humanization and reliable manual-captcha detection/waiting.

Features:
 - skip google-owned results (google, googleusercontent, youtube)
 - normalize URLs to dedupe variants that only differ by query *values*
 - detect "did not match any documents" and stop paging for the query
 - ignore results that do NOT include any query parameters (user request)
"""

import argparse
import logging
import os
import random
import sys
import time
import urllib.parse
from urllib.parse import unquote
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError
except Exception:
    print("playwright missing or browsers not installed. Install: pip install playwright beautifulsoup4")
    print("Then run: playwright install")
    raise

# Config
DEBUG_DIR = "debug_failed_pages"
DEFAULT_PAGES = 2
DEFAULT_TRIES = 4
DEFAULT_TIMEOUT = 25
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36")

# Logging
logger = logging.getLogger("dorky")
h = logging.StreamHandler(sys.stdout)
h.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
logger.addHandler(h)
logger.setLevel(logging.INFO)

# Utils
def ensure_debug_dir():
    os.makedirs(DEBUG_DIR, exist_ok=True)

def sanitize_filename(s: str):
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in s)[:200]

def save_debug_artifacts(page, base):
    ensure_debug_dir()
    html_path = os.path.join(DEBUG_DIR, base + ".html")
    png_path = os.path.join(DEBUG_DIR, base + ".png")
    try:
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(page.content())
        try:
            page.screenshot(path=png_path, full_page=True)
        except Exception:
            pass
        logger.debug("Saved debug: %s, %s", html_path, png_path)
    except Exception as e:
        logger.debug("Failed saving debug: %s", e)

# --- Filtering and normalization helpers ---
TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "icid", "mc_eid")

def is_google_host(host):
    if not host:
        return False
    h = host.lower()
    return ("google." in h) or ("googleusercontent.com" in h) or ("youtube.com" in h)

def normalize_url_for_dedupe(u: str):
    """
    Normalize a URL to a dedupe key:
      - strip fragments
      - remove values of query params (keep param names)
      - drop common tracking params (utm_*, gclid, fbclid, etc.)
      - lowercase scheme+host, keep path as-is
      - return scheme://host/path?sorted_param_names
    """
    try:
        p = urllib.parse.urlparse(u)
    except Exception:
        return u
    scheme = (p.scheme or "http").lower()
    host = (p.netloc or "").lower()
    path = p.path or "/"
    qitems = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    keys = []
    for k, v in qitems:
        lowk = k.lower()
        if any(lowk.startswith(pref) for pref in TRACKING_PREFIXES):
            continue
        keys.append(lowk)
    seen_k = []
    for k in keys:
        if k not in seen_k:
            seen_k.append(k)
    if seen_k:
        qpart = "&".join(f"{k}=" for k in sorted(seen_k))
        return f"{scheme}://{host}{path}?{qpart}"
    else:
        return f"{scheme}://{host}{path}"

# Extract URLs from SERP HTML
def extract_serp_urls(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/url?q="):
            real = href.split("/url?q=")[1].split("&")[0]
            results.append(unquote(real))
    if not results:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http://") or href.startswith("https://"):
                results.append(href)
    out = []
    seen = set()
    for u in results:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def build_proxy(proxy_str):
    if not proxy_str:
        return None
    if "@" in proxy_str:
        up, host = proxy_str.split("@", 1)
        if ":" in up:
            user, pwd = up.split(":", 1)
        else:
            user, pwd = up, ""
        return {"server": f"http://{host}", "username": user, "password": pwd}
    return {"server": f"http://{proxy_str}"}

# small stealth tweaks
STEALTH_JS = r"""
Object.defineProperty(navigator, 'webdriver', {get: () => false});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
"""

# captcha detection & manual wait
def looks_like_captcha(page):
    try:
        u = (page.url or "").lower()
        if "/sorry/" in u or "accounts.google.com" in u:
            return True
        html = page.content().lower()
        if "our systems have detected unusual traffic" in html:
            return True
        if "why did this happen" in html:
            return True
        if "i'm not a robot" in html or "are you a robot" in html:
            return True
        if page.query_selector('iframe[src*="recaptcha"]') or page.query_selector('iframe[src*="gstatic.com/recaptcha"]'):
            return True
    except Exception:
        return True
    return False

def wait_for_serp_after_manual_solve(page, max_wait=300, poll_interval=2, debug_base=None):
    start = time.time()
    logger.info("Waiting up to %ds for manual solve and SERP to appear...", max_wait)
    serp_selectors = ['a[href^="/url?q="]', 'div#search', 'div#rso', 'div.g', 'div.yuRUbf a']
    while True:
        if time.time() - start > max_wait:
            logger.warning("Timeout waiting for SERP after manual solve")
            if debug_base:
                save_debug_artifacts(page, debug_base + "_timeout")
            return False
        try:
            try:
                page.reload(wait_until="domcontentloaded", timeout=10*1000)
            except PWTimeout:
                logger.debug("Reload timed out; continuing checks")
            cur = (page.url or "").lower()
            if "/sorry/" in cur or "accounts.google.com" in cur:
                logger.debug("Still interstitial by URL: %s", cur)
                time.sleep(poll_interval)
                continue
            html_low = page.content().lower()
            if "our systems have detected unusual traffic" in html_low or "why did this happen" in html_low:
                logger.debug("Blocked text still present")
                time.sleep(poll_interval)
                continue
            for sel in serp_selectors:
                try:
                    if page.query_selector(sel):
                        logger.info("Detected SERP selector: %s", sel)
                        return True
                except Exception:
                    pass
            if "/url?q=" in html_low:
                logger.info("Found /url?q= in HTML; SERP present")
                return True
            time.sleep(poll_interval)
        except Exception as e:
            logger.debug("Exception while waiting for SERP: %s", e)
            time.sleep(poll_interval)

# Humanize small interactions (mouse move, scroll)
def humanize_page(page):
    try:
        viewport = page.viewport_size or {"width": 1200, "height": 800}
        w = viewport.get("width", 1200)
        h = viewport.get("height", 800)
        # small random mouse moves
        for _ in range(random.randint(1,3)):
            x = random.randint(int(w*0.1), int(w*0.9))
            y = random.randint(int(h*0.1), int(h*0.9))
            try:
                page.mouse.move(x, y, steps=random.randint(5, 12))
            except Exception:
                pass
            time.sleep(0.05 + random.random()*0.15)
        # small scroll
        try:
            page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight*0.2));")
        except Exception:
            pass
    except Exception:
        pass

# single-page fetch (uses already-created page)
def fetch_single_page(page, query, page_num, timeout_s, tries, headful):
    q_enc = urllib.parse.quote_plus(query)
    start = page_num * 10
    url = f"https://www.google.com/search?q={q_enc}&hl=en&gl=US&start={start}"
    last_err = None
    for attempt in range(1, tries+1):
        logger.info("page=%s attempt=%s -> %s", page_num, attempt, url)
        try:
            page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_s*1000)
            time.sleep(0.2)
            if looks_like_captcha(page):
                base = sanitize_filename(f"cap_{query}_p{page_num}_a{attempt}")
                save_debug_artifacts(page, base)
                if headful:
                    logger.warning("Captcha/interstitial detected (manual solve required).")
                    try:
                        input("Solved? press ENTER to continue (Ctrl-C to abort)... ")
                    except KeyboardInterrupt:
                        logger.info("User abort during manual solve.")
                        return [], "user-abort"
                    ok = wait_for_serp_after_manual_solve(page, max_wait=300, poll_interval=2, debug_base=base)
                    if not ok:
                        last_err = "captcha-still"
                        logger.warning("Still blocked after manual solve; retrying (attempt=%s)", attempt)
                        time.sleep(1 + random.random()*2)
                        continue
                else:
                    last_err = "captcha-headless"
                    logger.warning("Blocked in headless; retrying after delay.")
                    time.sleep(1 + random.random()*2)
                    continue
            # humanize before reading DOM
            humanize_page(page)
            html = page.content()

            # if the query returned no results, stop further pagination
            if "did not match any documents" in html.lower():
                logger.info("No results found for query: %s", query)
                return [], "no-results"

            urls = extract_serp_urls(html)
            if urls:
                logger.info("[OK] page %s -> %d urls", page_num, len(urls))
                return urls, None
            else:
                base = sanitize_filename(f"debug_{query}_p{page_num}_a{attempt}")
                save_debug_artifacts(page, base)
                last_err = "no-urls"
        except PWTimeout as t:
            last_err = f"timeout:{t}"
            logger.warning("Timeout: %s", t)
        except PWError as pe:
            last_err = f"playwright:{pe}"
            logger.warning("Playwright error: %s", pe)
        except Exception as e:
            last_err = f"error:{type(e).__name__}:{e}"
            logger.exception("Unhandled error")
        time.sleep(1 + random.random()*2)
    return [], last_err

# CLI parse
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("-qF", "--queries-file", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    p.add_argument("-p", "--proxy", default=None, help="user:pass@host:port or host:port")
    p.add_argument("--profile", default=None, help="persistent profile directory (recommended)")
    p.add_argument("--tries", type=int, default=DEFAULT_TRIES)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--headful", action="store_true")
    p.add_argument("--delay-min", type=float, default=1.0)
    p.add_argument("--delay-max", type=float, default=3.0)
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    logger.info("queries=%s pages=%s proxy=%s profile=%s headful=%s tries=%s",
                args.queries_file if False else "file", args.pages, bool(args.proxy), args.profile, args.headful, args.tries)

    if not os.path.exists(args.queries_file):
        logger.error("Queries file not found")
        sys.exit(1)
    with open(args.queries_file, "r", encoding="utf-8") as fh:
        queries = [ln.strip() for ln in fh if ln.strip() and not ln.strip().startswith("#")]

    proxy_obj = build_proxy(args.proxy) if args.proxy else None
    ensure_debug_dir()
    open(args.output, "a").close()

    with sync_playwright() as pw:
        chromium = pw.chromium
        launch_kwargs = {"headless": (not args.headful), "args": ["--no-sandbox"], "timeout": args.timeout*1000}
        if proxy_obj:
            launch_kwargs["proxy"] = proxy_obj

        # Use persistent context if profile provided, otherwise a single context
        context = None
        browser = None
        if args.profile:
            logger.info("Launching persistent context (profile=%s)", args.profile)
            context = chromium.launch_persistent_context(user_data_dir=args.profile, **launch_kwargs)
        else:
            logger.info("Launching browser + single context")
            browser = chromium.launch(**{k:v for k,v in launch_kwargs.items() if k!="timeout"})
            context = browser.new_context(user_agent=USER_AGENT, viewport={"width":1280,"height":800})

        try:
            # init stealth script
            try:
                context.add_init_script(STEALTH_JS)
            except Exception:
                pass

            page = context.new_page()
            # set UA via page if possible
            try:
                page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
            except Exception:
                pass

            # iterate queries and pages reusing *same* page
            with open(args.output, "a", encoding="utf-8") as outfh:
                seen_normalized = set()
                for qi, q in enumerate(queries, start=1):
                    logger.info("[Q %s/%s] %s", qi, len(queries), q)
                    saved = 0
                    for pnum in range(args.pages):
                        urls, err = fetch_single_page(page, q, pnum, timeout_s=args.timeout, tries=args.tries, headful=args.headful)

                        # if Google says "did not match any documents.", skip remaining pages for this query
                        if err == "no-results":
                            logger.info("Skipping remaining pages for query: %s", q)
                            break

                        if urls:
                            for u in urls:
                                # skip obvious google-owned results
                                try:
                                    parsed = urllib.parse.urlparse(u)
                                    netloc = (parsed.netloc or "").lower()
                                    if is_google_host(netloc):
                                        logger.debug("Skipping google host URL: %s", u)
                                        continue
                                except Exception:
                                    logger.debug("Failed to parse URL for host check: %s", u)
                                    # fall through to normalization/fallback

                                # skip URLs that do NOT include any query parameters (user requested)
                                try:
                                    parsed = urllib.parse.urlparse(u)
                                    #if not parsed.query:
                                        #logger.debug("Skipping URL without query params: %s", u)
                                        #continue
                                except Exception:
                                    # if parsing fails, keep going (we'll normalize/fallback)
                                    pass

                                # normalize for dedupe (keep first-seen variant)
                                try:
                                    key = normalize_url_for_dedupe(u)
                                except Exception:
                                    # Defensive fallback: simple canonicalization
                                    try:
                                        p = urllib.parse.urlparse(u)
                                        key = f"{(p.scheme or 'http').lower()}://{(p.netloc or '').lower()}{p.path}"
                                    except Exception:
                                        key = u

                                if key in seen_normalized:
                                    logger.debug("Duplicate (norm) skipped: %s -> %s", u, key)
                                    continue

                                seen_normalized.add(key)
                                outfh.write(u + "\n")
                                saved += 1

                            outfh.flush()
                            logger.info("Wrote %d urls for page=%s", saved, pnum)
                        else:
                            logger.info("No results for page=%s (err=%s)", pnum, err)

                        # delay between pages/queries (human-like)
                        d = random.uniform(args.delay_min, args.delay_max)
                        logger.debug("Sleeping %.2fs between requests", d)
                        time.sleep(d)

                    logger.info("Query done — saved %d urls", saved)
        finally:
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception:
                pass

    logger.info("All done — results appended to %s", args.output)

if __name__ == "__main__":
    main()

