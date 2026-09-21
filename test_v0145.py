#!/usr/bin/env python3
"""v0.1.45 viewport 计算测试"""
def compute_viewport(bw_cfg, W, H):
    if isinstance(bw_cfg, str):
        bw_lower = bw_cfg.lower()
        if bw_lower in ('match_fb', 'fb', 'auto'):
            return (W, H)
        elif bw_lower in ('match_fb_wide', 'wide', '1.25x'):
            return (int(W * 1.25), int(H * 1.25))
        elif bw_lower in ('match_dashboard', '16:9', 'wide16'):
            if W >= H:
                win_h = H
                win_w = int(win_h * 16 / 9)
            else:
                win_w = W
                win_h = int(win_w * 16 / 9)
            return (win_w, win_h)
    return (int(bw_cfg[0]), int(bw_cfg[1]))

cases = [
    ('fb 1024x768 (4:3 横向)', 1024, 768, [
        ('match_dashboard', 'match_dashboard', (1365, 768)),
        ('match_fb_wide',   'match_fb_wide',   (1280, 960)),
        ('match_fb',        'match_fb',        (1024, 768)),
        ('explicit',        [1280, 720],       (1280, 720)),
        ('alias 16:9',      '16:9',            (1365, 768)),
        ('alias wide16',    'wide16',          (1365, 768)),
    ]),
    ('fb 1920x1080 (16:9)', 1920, 1080, [
        ('match_dashboard', 'match_dashboard', (1920, 1080)),
        ('match_fb_wide',   'match_fb_wide',   (2400, 1350)),
        ('match_fb',        'match_fb',        (1920, 1080)),
    ]),
    ('fb 1280x720 (16:9)', 1280, 720, [
        ('match_dashboard', 'match_dashboard', (1280, 720)),
        ('match_fb_wide',   'match_fb_wide',   (1600,  900)),
        ('match_fb',        'match_fb',        (1280,  720)),
    ]),
    ('fb 768x1024 (纵向)',  768, 1024, [
        ('match_dashboard', 'match_dashboard', ( 768, 1365)),
        ('match_fb',        'match_fb',        ( 768, 1024)),
    ]),
]
all_pass = True
for case_name, W, H, presets in cases:
    print(f'\n=== {case_name} ===')
    for label, cfg, expected in presets:
        actual = compute_viewport(cfg, W, H)
        ok = 'OK' if actual == expected else 'FAIL'
        if actual != expected:
            all_pass = False
        print(f'  {ok} {label}: {actual} (expect {expected})')
print()
print('ALL PASS' if all_pass else 'SOME FAILED')