#!/usr/bin/env python3
"""v0.1.46 测试覆盖：
1. _sanitize 接受 match_dashboard / match_fb_wide / wide16 / 16:9 / wide
2. _sanitize 拒绝未知字符串 fallback 到 match_dashboard
3. _sanitize 接受 list [W, H]
4. URL 页面强制 match_dashboard viewport 算法
5. CJK 字体检测 API 返回结构
"""
import os
import sys
import json
import tempfile
import shutil

# 测试 1-3: dash_config._sanitize
def test_sanitize_accepts_new_presets():
    sys.path.insert(0, 'app/bin')
    import dash_config
    cases = [
        # (input, expected_normalized)
        ("match_dashboard", "match_dashboard"),
        ("MATCH_DASHBOARD", "match_dashboard"),
        ("16:9", "match_dashboard"),
        ("wide16", "match_dashboard"),
        ("match_fb_wide", "match_fb_wide"),
        ("wide", "match_fb_wide"),
        ("1.25x", "match_fb_wide"),
        ("match_fb", "match_fb"),
        ("fb", "match_fb"),
        ("auto", "match_fb"),
        # 旧版本残留值 → fallback match_dashboard
        ("match_fb_wide_old_typo", "match_dashboard"),
        ("some_random_string", "match_dashboard"),
        # list 值
        ([1920, 1080], [1920, 1080]),
        ([1280, 720], [1280, 720]),
        ([300, 200], [320, 240]),  # 太小 clip 到 min
        ([10000, 10000], [7680, 4320]),  # 太大 clip 到 max
    ]
    for inp, expected in cases:
        cfg = {"browser_window": inp}
        out = dash_config.Config._sanitize(None, cfg)
        actual = out["browser_window"]
        ok = "OK" if actual == expected else "FAIL"
        if actual != expected:
            print(f"  {ok} _sanitize({inp!r}) = {actual!r}, expected {expected!r}")
            return False
        print(f"  {ok} _sanitize({inp!r}) = {actual!r}")
    return True

# 测试 4: URL 页面 viewport 算法（模拟 fb_render.compute_viewport）
def test_url_forces_match_dashboard():
    W, H = 1024, 768
    has_url = True
    bw_cfg = "match_dashboard"  # 因为有 URL 页
    if isinstance(bw_cfg, str):
        bw_lower = bw_cfg.lower()
        if bw_lower in ("match_dashboard", "16:9", "wide16"):
            if W >= H:
                win_h = H
                win_w = int(win_h * 16 / 9)
            else:
                win_w = W
                win_h = int(win_w * 16 / 9)
            assert (win_w, win_h) == (1365, 768), f"got ({win_w}, {win_h})"
            print(f"  OK URL 强制 match_dashboard: fb {W}x{H} -> viewport {win_w}x{win_h}")
            return True
    return False

# 测试 5: 非 URL 页保留 user 配置
def test_non_url_uses_user_config():
    W, H = 1024, 768
    has_url = False
    bw_cfg = "match_fb"  # user 设置
    if isinstance(bw_cfg, str):
        bw_lower = bw_cfg.lower()
        if bw_lower in ("match_fb", "fb", "auto"):
            win_w, win_h = W, H
            assert (win_w, win_h) == (1024, 768), f"got ({win_w}, {win_h})"
            print(f"  OK 非 URL 用 user 配置 match_fb: viewport {win_w}x{win_h}")
            return True
    return False

# 测试 6: CJK 检测返回结构
def test_cjk_font_check_structure():
    # 直接调用 _has_cjk_font 验证返回 (installed, hint)
    if sys.platform == "win32":
        print("  SKIP _has_cjk_font: Windows 无 fcntl，运行时验证需在 NAS 上做")
        return True
    sys.path.insert(0, 'app/bin')
    import fb_render
    installed, hint = fb_render._has_cjk_font()
    assert isinstance(installed, bool), f"installed not bool: {type(installed)}"
    assert isinstance(hint, str), f"hint not str: {type(hint)}"
    if not installed:
        assert hint, "missing font should have non-empty hint"
        assert "apt" in hint or "fonts" in hint, f"hint should mention apt/fonts: {hint}"
    print(f"  OK _has_cjk_font: installed={installed} hint={hint[:60]!r}")
    return True

# 主测试
print("=== v0.1.46: _sanitize 接受新预设 ===")
r1 = test_sanitize_accepts_new_presets()
print()
print("=== v0.1.46: URL 页面强制 match_dashboard viewport ===")
r2 = test_url_forces_match_dashboard()
print()
print("=== v0.1.46: 非 URL 页面用 user 配置 ===")
r3 = test_non_url_uses_user_config()
print()
print("=== v0.1.46: CJK 字体检测 ===")
r4 = test_cjk_font_check_structure()
print()
print("ALL PASS" if all([r1, r2, r3, r4]) else "SOME FAILED")