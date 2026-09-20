#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""neon-dash 模组签名支持（预留扩展点）。

本应用当前不开放 .neon-dash 模组系统（浏览器屏的主题就是 URL，无需扩展模组）。
但保留该文件作为后续接入的基座——直接复制 fnos-dashboard 的实现即可：

  cp ../fnos-dashboard/app/bin/neon_crypto.py ./

协议不变：ed25519 (RFC 8032) + 规范化摘要 (按名排序 + name+\0+SHA256(content))，
与 .neon-dash ZIP 包结构兼容。后续在 dash_http.py 与 dash_pages.py 基础上
扩展 install/payload 接口即可启用。

本占位文件仅声明模块位置，避免 dash_config 之类外部引用路径变化。
"""

# 当真正启用模组系统时，这里应替换为完整实现（参见 fnos-dashboard 源码）。
# 当前实现仅暴露一个 VERSION 常量供诊断。
NEON_CRYPTO_VERSION = "stub-0.1.0"