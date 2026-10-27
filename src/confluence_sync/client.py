from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


class ConfluenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfluencePage:
    id: str
    title: str
    canonical_url: str
    storage_body: str


class ConfluenceClient:
    def __init__(
        self,
        site_url: str,
        email: str,
        api_token: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        parsed = urlsplit(site_url.strip().rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("site URL must be an HTTPS Confluence Cloud site URL")
        site_path = parsed.path.rstrip("/")
        if site_path and site_path != "/wiki":
            raise ValueError("site URL must be the site origin, optionally ending in /wiki")
        self._site_base = urlunsplit(("https", parsed.netloc, site_path or "/wiki", "", ""))
        self.site_url = self._site_base
        self._api_base = self._site_base.rstrip("/") + "/api/v2/"
        self._email = email
        self._api_token = api_token
        self._http = http_client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def fetch_tree(self, root_page_id: str) -> list[ConfluencePage]:
        if not root_page_id.isdigit():
            raise ValueError("root page ID must contain only digits")

        root = self._get_page(root_page_id)
        descendants = self._get_descendants(root_page_id)
        page_ids: dict[str, None] = {}
        for item in descendants:
            if not isinstance(item.get("type"), str) or item["type"].lower() != "page":
                continue
            page_id = item.get("id")
            if not isinstance(page_id, (str, int)) or not str(page_id).isdigit():
                raise ConfluenceError("Confluence returned a page descendant without a valid ID")
            if str(page_id) != root_page_id:
                page_ids[str(page_id)] = None
        return [root, *(self._get_page(page_id) for page_id in page_ids)]

    def _get_descendants(self, root_page_id: str) -> list[dict[str, object]]:
        next_url = f"{self._api_base}pages/{root_page_id}/descendants?limit=100"
        descendants: list[dict[str, object]] = []
        visited: set[str] = set()
        while next_url:
            if next_url in visited:
                raise ConfluenceError("Confluence returned a repeated descendants cursor")
            visited.add(next_url)
            payload = self._get_json(next_url)
            results = payload.get("results")
            if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
                raise ConfluenceError("Confluence returned an invalid descendants response")
            descendants.extend(results)
            links = payload.get("_links", {})
            next_link = links.get("next") if isinstance(links, dict) else None
            if next_link is None:
                next_url = ""
            elif isinstance(next_link, str) and next_link:
                resolved = urljoin(next_url, next_link)
                parsed = urlsplit(resolved)
                expected = urlsplit(self._site_base)
                if parsed.scheme != "https" or parsed.netloc != expected.netloc:
                    raise ConfluenceError("Confluence pagination link left the configured site")
                next_url = resolved
            else:
                raise ConfluenceError("Confluence returned an invalid pagination link")
        return descendants

    def _get_page(self, page_id: str) -> ConfluencePage:
        payload = self._get_json(f"{self._api_base}pages/{page_id}?body-format=storage")
        page_body = payload.get("body")
        storage = page_body.get("storage") if isinstance(page_body, dict) else None
        body_value = storage.get("value") if isinstance(storage, dict) else None
        links = payload.get("_links")
        webui = links.get("webui") if isinstance(links, dict) else None
        link_base = links.get("base") if isinstance(links, dict) else None
        title = payload.get("title")
        returned_id = payload.get("id")
        if (
            not isinstance(title, str)
            or not title.strip()
            or str(returned_id) != page_id
            or not isinstance(body_value, str)
            or not isinstance(webui, str)
            or not webui
        ):
            raise ConfluenceError(f"Confluence returned incomplete page data for page {page_id}")
        canonical_url = self._canonical_url(webui, link_base)
        return ConfluencePage(page_id, title.strip(), canonical_url, body_value)

    def _canonical_url(self, webui: str, link_base: object) -> str:
        parsed_webui = urlsplit(webui)
        if parsed_webui.scheme:
            resolved = webui
        else:
            base = link_base if isinstance(link_base, str) and link_base else self._site_base
            parsed_base = urlsplit(base)
            if parsed_base.scheme != "https" or parsed_base.netloc != urlsplit(self._site_base).netloc:
                raise ConfluenceError("Confluence returned an invalid page link base")
            if webui.startswith("/"):
                base_path = parsed_base.path.rstrip("/")
                page_path = webui if webui.startswith(base_path + "/") else base_path + webui
                resolved = urlunsplit(("https", parsed_base.netloc, page_path, parsed_webui.query, ""))
            else:
                resolved = urljoin(base.rstrip("/") + "/", webui)
        parsed = urlsplit(resolved)
        if parsed.scheme != "https" or parsed.netloc != urlsplit(self._site_base).netloc:
            raise ConfluenceError("Confluence returned a page link outside the configured site")
        return resolved

    def _get_json(self, url: str) -> dict[str, object]:
        try:
            response = self._http.get(
                url,
                auth=(self._email, self._api_token),
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError as error:
            raise ConfluenceError("Confluence request could not be completed") from error
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            suffix = f"; retry after {retry_after} seconds" if retry_after else ""
            raise ConfluenceError(f"Confluence rate limited the sync{suffix}")
        if response.is_error:
            raise ConfluenceError(f"Confluence request failed with HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise ConfluenceError("Confluence returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise ConfluenceError("Confluence returned an invalid response")
        return payload