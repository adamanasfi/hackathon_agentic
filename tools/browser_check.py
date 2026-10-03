"""Dev-only: open a generated page in Chrome, operate its controls, report JS errors and save screenshots.
Usage: python tools/browser_check.py runs/x/index.html"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

page_path = Path(sys.argv[1]).resolve()
shots = page_path.parent
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.on("console", lambda m: m.type == "error" and errs.append(f"console: {m.text}"))
    pg.goto(page_path.as_uri())
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(shots / "shot_full.png"), full_page=True)
    banner = pg.inner_text("#errors")
    tests = pg.inner_text("#tests")
    live = pg.inner_text("#live") if pg.query_selector("#live") else ""
    # operate every range slider
    for i, r in enumerate(pg.query_selector_all("#play input[type=range]")):
        mx = r.get_attribute("max") or "100"
        r.evaluate("(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); }", mx)
        pg.wait_for_timeout(150)
    for c in pg.query_selector_all("#play input[type=checkbox]"):
        c.click()
        pg.wait_for_timeout(150)
    pg.wait_for_timeout(500)
    pg.query_selector("#play").screenshot(path=str(shots / "shot_play_max.png"))
    for i, btn in enumerate(pg.query_selector_all("[data-preset]")):
        btn.click()
        pg.wait_for_timeout(700)
        pg.query_selector("#play").screenshot(path=str(shots / f"shot_preset{i}.png"))
    if pg.query_selector("#tnext"):
        for i in range(8):
            if pg.query_selector("#tnext").is_disabled():
                break
            pg.click("#tnext")
            pg.wait_for_timeout(600)
            if i == 1:
                pg.query_selector("#play").screenshot(path=str(shots / "shot_tour.png"))
        pg.click("#texit")
    if pg.query_selector("#lrun"):
        pg.click("#lrun")
        pg.wait_for_timeout(2500)
        pg.query_selector("#play").screenshot(path=str(shots / "shot_learn.png"))
    banner2 = pg.inner_text("#errors")
    b.close()
print("ERROR BANNER (initial):", banner or "-")
print("ERROR BANNER (after interaction):", banner2 or "-")
print("JS errors:", errs or "-")
print("SELF-TESTS:\n" + tests)
print("LIVE CHECKS:\n" + live)
