from recoll import recoll
from tool_base import tool

# Global state to maintain search context for pagination
cached_recoll_query = ""
cached_recoll_total = 0
cached_recoll_current_index = 0

@tool(description="Search the local Recoll database. Returns the first 10 results.")
def recoll_search(query: str) -> dict:
    """
    Executes a search in the Recoll database and returns the first 10 matches.
    Sets up pagination state for subsequent calls to recoll_get_next_page.
    """
    global cached_recoll_query, cached_recoll_total, cached_recoll_current_index

    try:
        db = recoll.connect()
        q = db.query()
        count = q.execute(query)

        # Update global state for pagination
        cached_recoll_query = query
        cached_recoll_total = count
        cached_recoll_current_index = 0

        if count == 0:
            return {"status": "success", "data": {"results": [], "total_found": 0}}

        results = []
        # Fetch up to the first 10 results
        for _ in range(min(10, count)):
            doc = q.next()
            if doc:
                results.append({
                    "title": doc.get('title'),
                    "filename": doc.get('filename'),
                    "url": doc.get('url'),
                    "abstract": doc.get('abstract')
                })

        return {
            "status": "success",
            "data": {
                "results": results,
                "total_found": count,
                "current_range": f"0 to {len(results)}"
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@tool(description="Provides the next 10 results from the previous recoll_search call.")
def recoll_get_next_page() -> dict:
    """
    Retrieves the next batch of up to 10 results based on the last recoll_search.
    Returns an error if no search is active or no more results are available.
    """
    global cached_recoll_query, cached_recoll_total, cached_recoll_current_index

    if not cached_recoll_query:
        return {"status": "error", "message": "No active search. Please run recoll_search first."}

    try:
        db = recoll.connect()
        q = db.query()
        q.execute(cached_recoll_query)

        # Advance the iterator to the current position in the result set
        for _ in range(cached_recoll_current_index):
            if not q.next():
                break

        results = []
        # Calculate how many items are left to fetch
        remaining = cached_recoll_total - cached_recoll_current_index
        items_to_fetch = min(10, remaining)

        for _ in range(items_to_fetch):
            doc = q.next()
            if doc:
                results.append({
                    "title": doc.get('title'),
                    "filename": doc.get('filename'),
                    "url": doc.get('url'),
                    "abstract": doc.get('abstract')
                })
                cached_recoll_current_index += 1
            else:
                break

        if not results:
            return {"status": "error", "message": "no more data"}

        return {
            "status": "success",
            "data": {
                "results": results,
                "total_found": cached_recoll_total,
                "current_range": f"{cached_recoll_current_index - len(results)} to {cached_recoll_current_index}"
            }
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

