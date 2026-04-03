from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8023'
OUT = Path('/workspace/ai-quant-platform/产品设计/复盘总结/assets/weekly-2026-04-03')
OUT.mkdir(parents=True, exist_ok=True)

PAGES = [
    ('home', '/', 'body'),
    ('workspace', '/workspace', 'body'),
    ('strategy', '/strategy', 'body'),
    ('backtests', '/backtests', 'body'),
    ('replay', '/replay', 'body'),
    ('mentor', '/mentor', 'body'),
    ('assistant', '/assistant', 'body'),
    ('admin', '/admin', 'body'),
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1200}, device_scale_factor=1)

    page = context.new_page()
    page.goto(f'{BASE}/', wait_until='networkidle')
    page.screenshot(path=str(OUT / 'home.png'), full_page=False)

    page.goto(f'{BASE}/login', wait_until='networkidle')
    page.fill('#username', 'admin')
    page.fill('#password', '618618')
    page.click('button[type="submit"]')
    page.wait_for_url('**/workspace', timeout=15000)
    page.wait_for_load_state('networkidle')
    page.screenshot(path=str(OUT / 'workspace.png'), full_page=False)

    for name, path, selector in PAGES[2:]:
        page.goto(f'{BASE}{path}', wait_until='networkidle')
        page.wait_for_selector(selector, timeout=15000)
        page.screenshot(path=str(OUT / f'{name}.png'), full_page=False)

    browser.close()
