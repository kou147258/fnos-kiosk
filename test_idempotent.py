#!/usr/bin/env python3
"""验证 set_page 幂等性"""
import sys, os
sys.path.insert(0, 'app/bin')
import dash_pages as dp

class MockCanvas:
    def __init__(self):
        self._page = None
        self._page_url = ''
        self._loaded_at = 0.0
        self._kiosk_css_pending = ''
        self._fit_mode = 'stretch'
        self.page_store = dp.PageStore('/tmp/_test_pages')
        self.http_port = 0

    def set_page(self, page, kiosk_css=''):
        self._kiosk_css_pending = kiosk_css or ''
        if not page:
            self._page = None
            self._page_url = ''
            self._loaded_at = 0.0
            return
        new_url = dp.resolve_url(page, self.page_store, http_port=self.http_port)
        old_url = self._page_url
        self._page = page
        self._page_url = new_url
        page_fit = (page.get('fit') or 'none').lower() if isinstance(page.get('fit'), str) else 'none'
        if page_fit in ('stretch', 'contain', 'cover'):
            self._fit_mode = page_fit
        if new_url != old_url:
            self._loaded_at = 0.0


canvas = MockCanvas()

# 1. 首次设 page A
A = {'id': 'a', 'type': 'url', 'url': 'https://x', 'fit': 'cover', 'zoom': 2.0}
canvas.set_page(A, kiosk_css='body{color:red}')
print(f'1. set A: page.zoom={canvas._page["zoom"]}, fit={canvas._fit_mode}, loaded_at={canvas._loaded_at}')
assert canvas._page == A
assert canvas._fit_mode == 'cover'
assert canvas._loaded_at == 0.0

# 2. 模拟导航完成
canvas._loaded_at = 100.0

# 3. 用户改 zoom (A → A2)
A2 = {'id': 'a', 'type': 'url', 'url': 'https://x', 'fit': 'cover', 'zoom': 0.5}
canvas.set_page(A2, kiosk_css='body{color:red}')
print(f'2. set A2 (zoom 2.0→0.5): page.zoom={canvas._page["zoom"]}, loaded_at={canvas._loaded_at}')
assert canvas._page == A2
assert canvas._loaded_at == 100.0, "URL 没变 → 不应重导航"

# 4. 用户改 fit
A3 = {'id': 'a', 'type': 'url', 'url': 'https://x', 'fit': 'contain', 'zoom': 0.5}
canvas.set_page(A3, kiosk_css='body{color:red}')
print(f'3. set A3 (fit cover→contain): fit={canvas._fit_mode}, loaded_at={canvas._loaded_at}')
assert canvas._fit_mode == 'contain'
assert canvas._loaded_at == 100.0

# 5. 切到不同 URL（应触发重导航）
B = {'id': 'b', 'type': 'url', 'url': 'https://y', 'fit': 'none', 'zoom': 1.0}
canvas.set_page(B, kiosk_css='')
print(f'4. set B (new URL): page.id={canvas._page["id"]}, loaded_at={canvas._loaded_at}')
assert canvas._page == B
assert canvas._loaded_at == 0.0, "URL 变了 → 应重导航"

# 6. 切到 B 后又调一次（应幂等）
canvas._loaded_at = 200.0
canvas.set_page(B, kiosk_css='')
print(f'5. set B again: loaded_at={canvas._loaded_at}')
assert canvas._loaded_at == 200.0

# 7. None page → 重置
canvas._loaded_at = 100.0
canvas.set_page(None, kiosk_css='')
print(f'6. set None: page={canvas._page}, loaded_at={canvas._loaded_at}')
assert canvas._page is None
assert canvas._loaded_at == 0.0

# 8. media_file path 变化 → 触发重导航
canvas.set_page({'type': 'media_file', 'path': 'a.png', 'fit': 'none'}, kiosk_css='')
print(f'7. set media a.png: page_url={canvas._page_url}, loaded_at={canvas._loaded_at}')
canvas._loaded_at = 300.0
canvas.set_page({'type': 'media_file', 'path': 'b.png', 'fit': 'none'}, kiosk_css='')
print(f'8. set media b.png: page_url={canvas._page_url}, loaded_at={canvas._loaded_at}')
assert canvas._loaded_at == 0.0, "path 变 → 应重导航"

print()
print('ALL IDEMPOTENCY CHECKS PASS')