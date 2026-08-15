#!/usr/bin/env python3
"""
Drive ChatGPT's web UI (already-logged-in Edge via CDP) to generate an image
and save it to disk.

usage: chatgpt_gen.py <prompt_file> <out_png> [tab_url_substring]

Assumes a ChatGPT tab is already open and logged in. Picks the tab whose URL
contains `tab_url_substring` (default: the bare https://chatgpt.com/ new-chat tab).
"""
import base64, sys, time

from playwright.sync_api import sync_playwright

CDP = "http://172.23.112.1:9223"
FETCH_B64 = """async (u) => {
  const r = await fetch(u, {credentials: 'include'});
  if (r.status !== 200) return {status: r.status};
  const buf = await r.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let bin = ''; const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH)
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  return {status: 200, type: r.headers.get('content-type'), b64: btoa(bin)};
}"""

# images already on the page before we send (avoids grabbing an old asset)
LIST_IMGS = """() => [...document.querySelectorAll(
    '[data-testid^="conversation-turn"] img')].map(i => i.src)
    .filter(s => s.startsWith('http'))"""


def main():
    prompt = open(sys.argv[1]).read().strip()
    out = sys.argv[2]
    match = sys.argv[3] if len(sys.argv) > 3 else "chatgpt.com/"

    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(CDP)
        pages = [x for c in b.contexts for x in c.pages if match in x.url]
        if not pages:
            sys.exit("no ChatGPT tab matching %r" % match)
        pg = pages[-1]
        print("tab:", pg.url)

        before = set(pg.evaluate(LIST_IMGS))

        # --- 1. type the prompt -------------------------------------------
        box = pg.wait_for_selector("#prompt-textarea", timeout=30000)
        box.click()
        # insert_text bypasses key interpretation, so newlines don't submit
        pg.keyboard.insert_text(prompt)
        time.sleep(1)

        # --- 2. send -------------------------------------------------------
        for sel in ('button[data-testid="send-button"]',
                    'button[aria-label*="Send"]',
                    '#composer-submit-button'):
            btn = pg.query_selector(sel)
            if btn and btn.is_enabled():
                btn.click()
                print("sent via", sel)
                break
        else:
            sys.exit("could not find an enabled send button")

        # --- 3. wait for a NEW image --------------------------------------
        deadline = time.time() + 600
        newsrc = None
        while time.time() < deadline:
            time.sleep(5)
            cur = pg.evaluate(LIST_IMGS)
            fresh = [s for s in cur if s not in before]
            if fresh:
                # image streams in progressively; wait for the stop-button to
                # disappear, i.e. the turn is finished, then re-read the src
                if not pg.query_selector('button[data-testid="stop-button"]'):
                    time.sleep(4)
                    cur = pg.evaluate(LIST_IMGS)
                    fresh = [s for s in cur if s not in before]
                    newsrc = fresh[-1]
                    break
            print("  waiting... (%d imgs)" % len(cur))
        if not newsrc:
            sys.exit("timed out waiting for image")
        print("image url:", newsrc[:110])

        # --- 4. download through the page so cookies apply -----------------
        res = pg.evaluate(FETCH_B64, newsrc)
        if res.get("status") != 200:
            sys.exit("fetch failed: %s" % res)
        data = base64.b64decode(res["b64"])
        open(out, "wb").write(data)
        print("wrote %s (%d bytes, %s)" % (out, len(data), res["type"]))
        print("conversation:", pg.url)


if __name__ == "__main__":
    main()
