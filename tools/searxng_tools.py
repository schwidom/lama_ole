import requests
from tool_base import tool

class SearXNGIterator:
    """
    An iterator that manages pagination for a SearXNG search session.
    It fetches results page by page and caches them to allow seamless 
    retrieval of batches.
    """
    def __init__(self, query: str):
        self.query = query
        self.base_url = "http://localhost:8888/search"
        self.all_results = []
        self.current_page = 1
        self.current_index = 0
        self.finished = False

    def _fetch_next_page(self) -> bool:
        """
        Fetches the next page of results from SearXNG.
        Returns True if new results were added, False if no more data is available.
        """
        if self.finished:
            return False

        params = {
            'q': self.query,
            'format': 'json',
            'category_general': 1,
            'pageno': self.current_page
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                new_results = data.get('results', [])
                
                if not new_results:
                    self.finished = True
                    return False
                
                self.all_results.extend(new_results)
                self.current_page += 1
                return True
            else:
                # If we get a non-200 status, we treat it as the end of valid data for this session
                self.finished = True
                return False
        except Exception:
            self.finished = True
            return False

    def get_batch(self, count: int) -> list:
        """
        Retrieves up to 'count' results. If the current cache is smaller than 
        'count', it attempts to fetch more pages until the requirement is met 
        or no more data exists.
        """
        # While we have fewer results in our buffer than requested, and there's more to fetch
        while (len(self.all_results) - self.current_index < count) and not self.finished:
            if not self._fetch_next_page():
                break

        start = self.current_index
        end = start + count
        batch = self.all_results[start:end]
        self.current_index = end
        return batch

# Global state to maintain the search session
cached_searxng_iterator = None

@tool(description="Search SearXNG locally at http://localhost:8888/. Returns up to 10 results.")
def web_search_searxng(query: str, maxcount=10) -> dict:
    """
    Initiates a new search in the local SearXNG engine.
    Clamps maxcount between 1 and 10.
    """
    global cached_searxng_iterator

    # Validate and clamp maxcount
    try:
        maxcount = int(maxcount)
    except (ValueError, TypeError):
        maxcount = 10

    if maxcount > 10:
        maxcount = 10
    if maxcount < 1:
        maxcount = 1

    try:
        # Reinitialize the iterator for every new search
        cached_searxng_iterator = SearXNGIterator(query)
        
        # Trigger initial fetch to populate first page
        cached_searxng_iterator._fetch_next_page()
        
        results = cached_searxng_iterator.get_batch(maxcount)

        if not results:
            return {"status": "success", "data": {"results": [], "total_found": 0}}

        return {
            "status": "success",
            "data": {
                "results": results,
                "current_index": cached_searxng_iterator.current_index,
                "has_more": not cached_searxng_iterator.finished
            }
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

@tool(description="Provides the next batch of results from the previous web_search_searxng call.")
def searxng_next_results(maxcount=10) -> dict:
    """
    Retrieves up to 10 subsequent results. If the cache is exhausted, 
    it automatically fetches the next page from SearXNG.
    """
    global cached_searxng_iterator

    # Validate and clamp maxcount
    try:
        maxcount = int(maxcount)
    except (ValueError, TypeError):
        maxcount = 10

    if maxcount > 10:
        maxcount = 10
    if maxcount < 1:
        maxcount = 1

    if cached_searxng_iterator is None:
        return {"status": "error", "message": "No active search. Please run web_search_searxng first."}

    try:
        results = cached_searxng_iterator.get_batch(maxcount)

        if not results:
            return {"status": "error", "message": "No more data available."}

        return {
            "status": "success",
            "data": {
                "results": results,
                "current_index": cached_searxng_iterator.current_index,
                "has_more": not cached_searxng_iterator.finished
            }
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

