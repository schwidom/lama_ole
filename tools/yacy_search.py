"""Web tools for lama_ole — fetch URLs and search the web."""

__tool_readonly__ = True

import re
import urllib.request
import urllib.error
from html.parser import HTMLParser

from tool_base import tool

import requests 

cached_startRecord = 0 # + 10
cached_query = ""

@tool(description="Search the web using the yacy search engine, provides first 10 results via tool yacy_next_results() ")
def web_search_yacy(query):
    global cached_startRecord
    global cached_query
    # API abrufen
    cached_startRecord = 0
    cached_query = f"{query}"

    # response = requests.get(f"http://localhost:8090/yacysearch.json?query={query}").json()
    # cached_results = response["channels"][0]["items"] # all items
    
    return yacy_next_results()

@tool(description=" Provides the next results from the previous web_search_yacy call ( can be continued ) ")
def yacy_next_results():
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


