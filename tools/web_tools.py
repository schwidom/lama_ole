"""Web tools for lama_ole — fetch URLs and search the web."""

import re
import urllib.request
import urllib.error
from html.parser import HTMLParser

from tool_base import tool


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._text.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data.strip())

    def get_text(self) -> str:
        raw = " ".join(self._text)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n", "\n\n", raw)
        return raw.strip()


@tool(description="Fetch a URL and return its content")
def web_fetch(url: str, timeout: int = 15) -> str:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "lama_ole/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return f"HTTP error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"URL error: {e.reason}"
    except Exception as e:
        return f"Error: {e}"


@tool(description="Fetch a URL and extract readable text (strip HTML)")
def web_fetch_text(url: str, timeout: int = 15) -> str:
    html = web_fetch(url, timeout=timeout)
    if html.startswith("Error") or html.startswith("HTTP"):
        return html
    extractor = _TextExtractor()
    extractor.feed(html)
    text = extractor.get_text()
    if len(text) > 10000:
        text = text[:10000] + "\n\n[...truncated at 10000 characters]"
    return text


@tool(description="Search the web using a search engine")
def web_search(query: str, timeout: int = 15) -> str:
    import urllib.parse

    encoded = urllib.parse.quote(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    html = web_fetch(url, timeout=timeout)
    if html.startswith("Error") or html.startswith("HTTP"):
        return html

    results = []
    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    ):
        link = match.group(1)
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        results.append(f"{title}\n  {link}")

    if not results:
        return "(no results found)"

    return "\n\n".join(results[:10])
