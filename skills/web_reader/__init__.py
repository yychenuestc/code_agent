# -*- coding: utf-8 -*-
"""
Web Reader Skill - 网页内容读取技能

提供 read_webpage 工具，抓取网页并提取正文内容。
支持静态网页和部分动态网页（通过 requests + HTML 解析）。
"""
import re
import requests

# ============ Skill 配置 ============

REQUEST_TIMEOUT = 15
MAX_CONTENT_LENGTH = 10000


def configure(config: dict):
    """由 skill_loader 调用，注入配置"""
    global REQUEST_TIMEOUT, MAX_CONTENT_LENGTH
    REQUEST_TIMEOUT = config.get("REQUEST_TIMEOUT", REQUEST_TIMEOUT)
    MAX_CONTENT_LENGTH = config.get("MAX_CONTENT_LENGTH", MAX_CONTENT_LENGTH)


# ============ 网页抓取核心 ============

def _fetch_webpage(url: str, timeout: int = REQUEST_TIMEOUT) -> dict:
    """
    抓取网页内容

    Returns:
        dict with keys: success, title, content, error
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or 'utf-8'

        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        html = resp.text
        if not html:
            return {"success": False, "error": "页面内容为空"}

        # 提取标题
        title = ""
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()

        # 提取正文内容
        content = _extract_content(html)

        return {
            "success": True,
            "title": title,
            "url": resp.url,  # 可能和输入不同（重定向后）
            "content_length": len(content),
            "content": content[:MAX_CONTENT_LENGTH],
        }

    except requests.Timeout:
        return {"success": False, "error": f"请求超时（{timeout}秒）"}
    except requests.ConnectionError:
        return {"success": False, "error": "连接失败，请检查URL或网络"}
    except Exception as e:
        return {"success": False, "error": f"请求异常: {str(e)}"}


def _extract_content(html: str) -> str:
    """
    从HTML中提取正文内容

    策略: 移除标签 → 清理空白 → 按段落分割
    对于SPA页面，尝试从内嵌JSON数据中提取文本
    """
    # 先尝试从内嵌的 JSON 数据中提取（适用于部分 SPA）
    json_texts = re.findall(r'"title"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', html)
    json_texts2 = re.findall(r'"name"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', html)
    json_texts3 = re.findall(r'"description"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', html)

    # 移除 script 和 style 标签
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.IGNORECASE | re.DOTALL)

    # 将块级标签替换为换行
    text = re.sub(r'<(br|p|div|h[1-6]|li|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)
    # 移除所有HTML标签
    text = re.sub(r'<[^>]+>', '', text)
    # 解码HTML实体
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
    # 清理多余空白
    text = re.sub(r'[ \t]+', ' ', text)
    # 按行分割，去除空行
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        if line and len(line) > 2:  # 过滤太短的行
            lines.append(line)

    main_content = '\n'.join(lines)

    # 如果正文内容太少，可能是 SPA，拼接 JSON 提取的文本
    if len(main_content) < 200 and (json_texts or json_texts2 or json_texts3):
        extra_parts = []
        seen = set()
        for t in json_texts + json_texts2 + json_texts3:
            t = t.strip()
            # 解码转义
            t = t.replace('\\n', ' ').replace('\\"', '"')
            if t and len(t) > 5 and t not in seen:
                seen.add(t)
                extra_parts.append(t)
        if extra_parts:
            main_content += "\n\n--- 从页面数据中提取的内容 ---\n" + '\n'.join(extra_parts[:50])

    # SPA 检测：正文内容极少且无明显正文标记
    if len(main_content) < 100:
        main_content += (
            "\n\n[提示] 该网站可能是SPA（单页应用），内容由JavaScript动态渲染，"
            "requests无法获取动态内容。建议：1) 使用浏览器手动访问；2) 寻找该网站的API接口；"
            "3) 使用headless浏览器（如Playwright）渲染后再提取。"
        )

    return main_content


def tool_read_webpage(args: dict) -> str:
    """读取网页内容的工具函数"""
    url = args.get("url", "")
    if not url:
        return "请提供URL"

    # 简单的URL校验
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = _fetch_webpage(url)

    if not result["success"]:
        return f"读取网页失败: {result['error']}"

    output = f"标题: {result.get('title', '无')}\n"
    output += f"URL: {result.get('url', url)}\n"
    output += f"内容长度: {result.get('content_length', 0)} 字符\n\n"
    output += result.get("content", "")

    if len(output) > MAX_CONTENT_LENGTH:
        output = output[:MAX_CONTENT_LENGTH] + "\n\n... (内容过长，已截断)"

    return output


# ============ LangChain Tool 定义 ============

_langchain_tool = None


def get_langchain_tool():
    """获取 LangChain Tool 实例（延迟加载）"""
    global _langchain_tool
    if _langchain_tool is None:
        from langchain_core.tools import tool as lc_tool
        _real_read_webpage = tool_read_webpage

        @lc_tool
        def read_webpage(url: str) -> str:
            """读取网页内容。输入URL，返回网页标题和正文文本。支持静态网页，部分SPA可能只能获取有限内容。"""
            return _real_read_webpage({"url": url})

        _langchain_tool = read_webpage
    return _langchain_tool


# ============ Skill 接口 ============

def get_tools():
    """返回此 skill 提供的 LangChain Tool 列表"""
    return [get_langchain_tool()]


def get_hooks():
    """返回此 skill 提供的 Hook 函数"""
    return {}


def get_skill_prompt():
    """返回此 skill 的技能提示"""
    return (
        "### 网页读取工作流\n"
        "当用户要求读取网页、获取网站信息时，按以下步骤执行：\n"
        "1. **读取网页**: 使用 read_webpage 工具获取网页正文内容\n"
        "2. **提取信息**: 根据用户需求从返回的内容中提取关键信息\n"
        "3. **总结输出**: 将提取的信息整理后向用户报告\n"
        "注意: 部分网站（如SPA单页应用）可能无法获取动态内容，此时应告知用户限制"
    )
