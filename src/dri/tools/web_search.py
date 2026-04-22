"""
Web search tool — uses Tavily API (primary) with Brave API fallback.
If neither API key is configured, returns a clear error rather than silently failing.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from dri.config.settings import settings
from dri.tools.base import BaseTool, ToolOutput, ToolRegistry


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for information. Returns a list of relevant results with "
        "titles, URLs, and content snippets. Use for fact-checking, research, and "
        "finding up-to-date information."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific and targeted.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-10).",
                "default": 5,
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        query: str = raw_input.get("query", "").strip()
        max_results: int = min(int(raw_input.get("max_results", 5)), 10)

        if not query:
            return ToolOutput.fail("Query cannot be empty.")

        if not settings.has_web_search:
            return ToolOutput.fail(
                "No web search API key configured. "
                "Set TAVILY_API_KEY or BRAVE_API_KEY in .env to enable web search."
            )

        if settings.tavily_api_key:
            return await self._tavily_search(query, max_results)
        return await self._brave_search(query, max_results)

    async def _tavily_search(self, query: str, max_results: int) -> ToolOutput:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": settings.tavily_api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "basic",
                        "include_answer": True,
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = []
                if data.get("answer"):
                    results.append({"type": "answer", "content": data["answer"]})

                for r in data.get("results", []):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "content": r.get("content", "")[:800],
                        }
                    )

                return ToolOutput.ok(results)
            except httpx.HTTPStatusError as e:
                return ToolOutput.fail(f"Tavily API error {e.response.status_code}: {e.response.text[:200]}")
            except Exception as e:
                return ToolOutput.fail(f"Web search failed: {e}")

    async def _brave_search(self, query: str, max_results: int) -> ToolOutput:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": settings.brave_api_key,
                    },
                    params={"q": query, "count": max_results},
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for r in data.get("web", {}).get("results", []):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "content": r.get("description", "")[:800],
                        }
                    )

                return ToolOutput.ok(results)
            except httpx.HTTPStatusError as e:
                return ToolOutput.fail(f"Brave API error {e.response.status_code}: {e.response.text[:200]}")
            except Exception as e:
                return ToolOutput.fail(f"Web search failed: {e}")


ToolRegistry.register(WebSearchTool())
