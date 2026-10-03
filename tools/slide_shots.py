"""Dev-only: screenshot a slide-style page, pressing ArrowRight between shots; report JS errors."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
p_ = Path(sys.argv[1]).resolve(); n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    pg.goto(p_.as_uri()); pg.wait_for_timeout(800)
    for i in range(n):
        pg.screenshot(path=str(p_.parent / f"slide{i:02d}.png"))
        pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(700)
    # poke every slider/input to max
    for r in pg.query_selector_all("input[type=range]"):
        try: r.evaluate("e => { e.value = e.max; e.dispatchEvent(new Event('input', {bubbles:true})); }")
        except Exception as e: errs.append(str(e))
    pg.wait_for_timeout(500)
    b.close()
print("JS errors:", errs or "-")
