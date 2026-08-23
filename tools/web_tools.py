"""Web tools for lama_ole — fetch URLs and search the web."""

__tool_readonly__ = True

import re
import urllib.request
import urllib.error
from html.parser import HTMLParser

from tool_base import tool

import requests 


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


# @tool(description="Search the web using a search engine")
# def web_search_yacy(query: str, timeout: int = 15) -> str:
#     import urllib.parse
# 
#     encoded = urllib.parse.quote(query)
#     url = f"http://localhost:8090/yacysearch.json?query={encoded}"
# 
#     return web_fetch(url, timeout=timeout)


cached_startRecord = 0 # + 10
cached_query = ""

@tool(description="Search the web using the yacy search engine, provides first 10 results via tool yacy_get_result_page() ")
def web_search_yacy(query):
    global cached_startRecord
    global cached_query
    # API abrufen
    cached_startRecord = 0
    cached_query = f"{query}"

    # response = requests.get(f"http://localhost:8090/yacysearch.json?query={query}").json()
    # cached_results = response["channels"][0]["items"] # all items
    
    return yacy_get_result_page()

@tool(description=" Provides the next results from the previous web_search_yacy call ( can be continued ) ")
def yacy_get_result_page():
    global cached_startRecord
    global cached_query

    request = f"http://localhost:8090/yacysearch.json?query={cached_query}&startRecord={cached_startRecord}"

    response = requests.get(request).json()
    results = response["channels"][0]["items"] # all items


    if 0 == len( results) :
        return {"status": "error", "message": f"no more data"}

    start = cached_startRecord
    cached_startRecord += len( results)

    return { "status":"success", "data" : {
        "results": results,
        "current_window": f"{start} to {cached_startRecord}"
           } }


@tool(description="Search the web using another search engine")
def web_search_duckduckgo(query: str, timeout: int = 15) -> str:
    import urllib.parse

    encoded = urllib.parse.quote(query)
    url = f"https://lite.duckduckgo.com/lite/?q={encoded}"
    html = web_fetch(url, timeout=timeout)
    if html.startswith("Error") or html.startswith("HTTP"):
        return html

    results = []
    for match in re.finditer(
        r"<a[^>]+class='result-link'[^>]*>(.*?)</a>",
        html,
        re.DOTALL,
    ):
        link_tag = match.group(0)
        href_m = re.search(r'href="([^"]+)"', link_tag)
        link = href_m.group(1) if href_m else ""
        title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        uddg = re.search(r"[?&]uddg=([^&]+)", link)
        if uddg:
            link = urllib.parse.unquote(uddg.group(1))
        results.append(f"{title}\n  {link}")

    if not results:
        return "(no results found)"

    return "\n\n".join(results[:10])
