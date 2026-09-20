#!/bin/sh
# fnOS CGI 入口：把 /cgi/ThirdParty/com.fnos.kiosk/index.cgi/ 下的请求
# 反向代理到本机 kiosk 服务（fnOS 校验 NAS 登录态后才执行本脚本）。
#
# 端口解析优先级：
#   1. TRIM_SERVICE_PORT 环境变量（fnOS 在启动 cmd/* 时注入）
#   2. ${TRIM_PKGVAR:-/var/apps/com.fnos.kiosk/var}/port.txt（cmd/main 写入）
#   3. ${TRIM_SERVICE_PORT:-8280}（兜底，与 manifest service_port=8280 对齐）
#
# 历史上曾只用兜底 8200，结果在某些 NAS 上 8200 被 MiniDLNA 占用，
# 导致 CGI 把请求代理到 MiniDLNA，用户打开「浏览器屏」看到 DLNA 状态页。
# 现已修复：默认改 8280 + 优先读 cmd/main 写入的实际端口。
TARGET_HOST=127.0.0.1
PKGVAR_DIR=${TRIM_PKGVAR:-/var/apps/com.fnos.kiosk/var}
if [ -f "$PKGVAR_DIR/port.txt" ]; then
    TARGET_PORT=$(cat "$PKGVAR_DIR/port.txt" 2>/dev/null | tr -d '[:space:]')
fi
if [ -z "$TARGET_PORT" ] || [ "$TARGET_PORT" = "8200" ]; then
    # 没文件 + 不是显式设 8200 → 走 TRIM_SERVICE_PORT → 兜底 8280
    TARGET_PORT=${TRIM_SERVICE_PORT:-8280}
fi

REQ_URI=${REQUEST_URI:-"/"}
URI_NO_QUERY=${REQ_URI%%\?*}
QUERY_STRING=${QUERY_STRING:-}

# 无尾斜杠的入口 302 到带斜杠形式，保证页面内相对路径可用
case "$URI_NO_QUERY" in
    */index.cgi)
        printf "Status: 302 Found\r\n"
        printf "Location: %s/%s\r\n" "$URI_NO_QUERY" "${QUERY_STRING:+?$QUERY_STRING}"
        printf "Content-Type: text/plain; charset=utf-8\r\n"
        printf "Cache-Control: no-store\r\n\r\n"
        exit 0
        ;;
esac

# 取 index.cgi 之后的子路径：/cgi/.../index.cgi/settings -> /settings
case "$URI_NO_QUERY" in
    *index.cgi*) REL_PATH="${URI_NO_QUERY#*index.cgi}" ;;
    *) REL_PATH="$URI_NO_QUERY" ;;
esac
[ -n "$REL_PATH" ] || REL_PATH="/"
case "$REL_PATH" in
    *..*)
        printf "Status: 400 Bad Request\r\n"
        printf "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        printf "Bad Request\n"
        exit 0
        ;;
esac

TARGET_URL="http://${TARGET_HOST}:${TARGET_PORT}${REL_PATH}"
[ -n "$QUERY_STRING" ] && TARGET_URL="${TARGET_URL}?${QUERY_STRING}"

METHOD=${REQUEST_METHOD:-GET}
# --max-time：后端卡住时快速失败，避免 CGI 进程堆积
set -- -s --max-time 30 --connect-timeout 5 -X "$METHOD"
[ -n "$HTTP_ACCEPT" ]          && set -- "$@" -H "accept: $HTTP_ACCEPT"
[ -n "$HTTP_ACCEPT_LANGUAGE" ] && set -- "$@" -H "accept-language: $HTTP_ACCEPT_LANGUAGE"
[ -n "$HTTP_USER_AGENT" ]      && set -- "$@" -H "user-agent: $HTTP_USER_AGENT"
[ -n "$HTTP_ORIGIN" ]          && set -- "$@" -H "origin: $HTTP_ORIGIN"
[ -n "$HTTP_REFERER" ]         && set -- "$@" -H "referer: $HTTP_REFERER"
case "$METHOD" in
    POST|PUT|PATCH|DELETE)
        set -- "$@" -H "Content-Type: ${CONTENT_TYPE:-application/json}"
        set -- "$@" --data-binary @-
        ;;
esac

HEADER_FILE=$(mktemp) || exit 1
BODY_FILE=$(mktemp) || { rm -f "$HEADER_FILE"; exit 1; }
trap 'rm -f "$HEADER_FILE" "$BODY_FILE"' EXIT

curl "$@" -D "$HEADER_FILE" -o "$BODY_FILE" "$TARGET_URL" || {
    printf "Status: 502 Bad Gateway\r\n"
    printf "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    printf "后端服务未响应，请在应用中心重启该应用。\n"
    exit 0
}

CODE=$(head -1 "$HEADER_FILE" | awk '{print $2}')
[ -n "$CODE" ] && [ "$CODE" != "200" ] && printf "Status: %s\r\n" "$CODE"
grep -i "^Content-Type:" "$HEADER_FILE" | tail -1 | tr -d '\r'
printf "Cache-Control: no-store\r\n"
printf "\r\n"
cat "$BODY_FILE"