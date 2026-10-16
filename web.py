import json
import requests
from config import get_config
from logger import log_event

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

def search_web(query: str, max_results: int = 5) -> dict:
    """
    Executes a web search via Tavily API with max 5 results.
    Logs full request and result/failure to console and harness.log.
    """
    api_key = get_config("TAVILY_API_KEY")
    if not api_key:
        msg = "Tavily search skipped: TAVILY_API_KEY is not configured."
        log_event(msg, level="warning")
        return {"error": msg, "results": []}

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": min(max_results, 5),
        "search_depth": "basic",
        "include_answer": False,
    }

    log_event(f"Tavily search initiated for query: '{query}' (max_results: {payload['max_results']})")
    
    try:
        response = requests.post(
            TAVILY_SEARCH_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        
        if response.status_code != 200:
            err_text = f"Tavily API HTTP {response.status_code}: {response.text}"
            log_event(f"Tavily search failed: {err_text}", level="error")
            return {"error": err_text, "results": []}

        data = response.json()
        raw_results = data.get("results", [])
        
        formatted_results = []
        for r in raw_results[:5]:
            formatted_results.append({
                "title": r.get("title", "No Title"),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            })

        log_event(f"Tavily search succeeded. Retrieved {len(formatted_results)} results for '{query}'.")
        return {"query": query, "results": formatted_results}

    except Exception as exc:
        err_msg = f"Tavily request exception: {str(exc)}"
        log_event(err_msg, level="error")
        return {"error": err_msg, "results": []}

def format_search_results(search_data: dict) -> str:
    """Formats Tavily search results into readable context for LLM grounding."""
    if search_data.get("error"):
        return f"[Web search failed: {search_data['error']}]"
    
    results = search_data.get("results", [])
    if not results:
        return "[Web search returned no results for this query.]"

    formatted = [f"Web Search Results for '{search_data.get('query', '')}':\n"]
    for idx, item in enumerate(results, start=1):
        formatted.append(f"{idx}. {item['title']}\nURL: {item['url']}\nSnippet: {item['content']}\n")
    
    return "\n".join(formatted)
