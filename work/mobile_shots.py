"""Chụp ảnh mobile 390px mặc định của từng trang: work/shots/mobile_page_<id>.png (cho critic chấm bản điện thoại)."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

html = Path(sys.argv[1]).resolve(); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    pg.goto(f"file://{html}"); pg.wait_for_function("window.DashRuntime !== undefined")
    ids = pg.evaluate("APP.pages.map(p => p.id)")
    for pid in ids:
        pg.evaluate("s => DashRuntime.applyState(s)", {"page": pid, "filters": {}, "params": {}})
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out / f"mobile_page_{pid}.png"), full_page=True)
        if pid != "recommendation":
            pg.evaluate("s => DashRuntime.applyState(s)", {"page": pid, "filters": {"unit": ["HEAD"]}, "params": {}})
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(out / f"mobile_page_{pid}__filtered.png"), full_page=True)
    sw = pg.evaluate("document.documentElement.scrollWidth")
    b.close()
print({"pages": ids, "scrollWidth_last": sw})
