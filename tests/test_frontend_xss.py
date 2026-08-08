"""前端渲染安全回归测试：静态扫描 app.js，防止 XSS 注入向量回归。

背景：全应用用模板字符串 + innerHTML 渲染，动态数据统一经 escapeHtml() 转义，
flash() 走 textContent，confirm/alert/prompt 走 JS 字符串上下文（非 HTML）。
这两个测试把该约定固化为 CI 检查：
  1. 事件处理器 onxxx="..." 内的插值不得引用用户数据字段（曾发生 adminRevokeCode 注入模式）
  2. innerHTML 模板内用户数据字段插值必须经 escapeHtml() 或处于显式安全上下文
"""
import re
from pathlib import Path

APP_JS = Path(__file__).parent.parent / "app" / "static" / "app.js"

# 用户可控/动态数据字段（来自 API 响应或用户输入）
USER_FIELDS = [
    "name", "external_id", "url", "title", "content", "code", "username",
    "category_name", "kol_name", "error", "detail", "note", "latest",
    "requester", "user_name", "screen_name", "avatar_url",
    "platform", "status",  # 动态来源字段（曾有多处 PLATFORM_LABELS[x] || x 裸插值）
]

# 安全上下文白名单：插值处于这些表达式/调用中时不要求 escapeHtml
SAFE_CONTEXTS = [
    # 数字/主键/布尔字段（服务端生成，无注入面）
    r"\.(id|kol_id|user_id|count|kol_count|subscriber_count|favorite|priority|enabled|is_admin|used_by|has_update)\b",
    # 硬编码标签/图标表索引
    r"PLATFORM_LABELS\[|PLATFORM_ICONS\[|CHANNEL_ICONS\[|statusPill\(|PLATFORM_TABS",
    # 安全渲染辅助函数（内部已转义或为纯数字）
    r"avatarHtml\(|avatarText\(|emptyState\(|format_published_at\(|fmtDbTime\(|fmtTs\(|rateBar\(",
    # URL 编码 / 数值转换
    r"encodeURIComponent\(|Number\(|parseInt\(",
    # 内部筛选状态（来自硬编码 PLATFORM_TABS，非用户数据）
    r"state\.platform",
    # 三元比较链：字段仅用于 === 字符串比较，输出为硬编码字面量（如 status === "approved" ? "status-ok" : ...）
    r"=== \"",
    # JS 字符串上下文（非 HTML 渲染）：弹窗/提示/toast（flash 用 textContent）
    r"confirm\(|alert\(|prompt\(|flash\(|textContent",
    # 批量导入失败的错误行拼接（进 alert 的 JS 字符串）
    r"f\.line|f\.error|r\.error|r\.ok|r\.detail",
    # adminTestPush 的 prompt 文案（JS 字符串上下文）
    r"user\s*\?\s*user\.username",
    # 编辑模态框的 innerHTML 输入 value（escapeHtml 已在同表达式）
    r"ek-name",
]


def _interpolations(line: str) -> list[str]:
    return re.findall(r"\$\{([^}]*)\}", line)


def test_event_handlers_do_not_interpolate_user_data():
    """onclick/onchange 等内联处理器中不得插入用户数据（字符串注入面）。"""
    bad = []
    for i, line in enumerate(APP_JS.read_text().splitlines(), 1):
        if not re.search(r'on(?:click|change|keydown|input)="[^"]*\$', line):
            continue
        for expr in _interpolations(line):
            for field in USER_FIELDS:
                # 数字字段安全；字符串数据字段在任何 handler 插值中都危险
                if re.search(r"\.\s*" + field + r"\b", expr) and not re.search(
                    r"\.(id|kol_id|user_id|count|has_update)\b", expr
                ):
                    bad.append(f"L{i}: {line.strip()[:110]}")
                    break
    assert not bad, "事件处理器插入了用户数据字段（XSS 注入面）：\n" + "\n".join(bad)


def test_innerhtml_templates_escape_user_fields():
    """innerHTML 模板中用户数据字段必须被 escapeHtml 包裹或处于白名单上下文。"""
    bad = []
    for i, line in enumerate(APP_JS.read_text().splitlines(), 1):
        if "${" not in line:
            continue
        # JS 字符串上下文（非 HTML 渲染）：flash 用 textContent，confirm/alert/prompt 直接弹文本
        if re.search(r"confirm\(|alert\(|prompt\(|flash\(|textContent\s*=", line):
            continue
        # emptyState 内部自行 escapeHtml，传入的参数无需再转义
        if re.search(r"emptyState\(", line):
            continue
        for expr in _interpolations(line):
            if "escapeHtml" in expr:
                continue
            for field in USER_FIELDS:
                if not re.search(r"\.\s*" + field + r"\b", expr):
                    continue
                if any(re.search(ctx, expr) for ctx in SAFE_CONTEXTS):
                    continue
                bad.append(f"L{i}: ${{{expr.strip()[:80]}}}")
                break
    assert not bad, "innerHTML 模板中未转义的用户数据字段：\n" + "\n".join(bad)
