from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from confluence_sync import cli as confluence_cli
from confluence_sync.client import ConfluenceClient, ConfluenceError
from confluence_sync.sync import SyncReport, sync_root
from local_docs_rag.config import Settings
from local_docs_rag.cli import main as local_docs_main
from local_docs_rag.indexing import Indexer
from local_docs_rag.store import IndexStore


SITE_URL = "https://acme.atlassian.net"
ROOT_ID = "100"
PROJECT = "team-docs"


class MockConfluence:
    def __init__(self) -> None:
        self.pages = {
            "100": self._page("100", "Operations", "RootSignal original root body."),
            "200": self._page("200", "Recovery", "OldVersionSignal rollback details."),
            "300": self._page("300", "Escalation", "DeleteMeSignal escalation contacts."),
        }
        self.descendants = [
            {"id": "200", "type": "page", "title": "Recovery", "parentId": "100"},
            {"id": "900", "type": "database", "title": "Runbook table", "parentId": "100"},
            {"id": "300", "type": "page", "title": "Escalation", "parentId": "200"},
        ]
        self.fail_next_page = False
        self.requests: list[httpx.Request] = []

    @staticmethod
    def _page(page_id: str, title: str, body: str) -> dict[str, object]:
        body_markup = f"<p>{body}</p>"
        if page_id == "200":
            body_markup = f"<h2>Rollback</h2>{body_markup}"
        return {
            "id": page_id,
            "title": title,
            "parentId": None if page_id == ROOT_ID else "100",
            "body": {"storage": {"value": body_markup}},
            "_links": {
                "base": SITE_URL + "/wiki",
                "webui": f"/spaces/OPS/pages/{page_id}/{title}",
            },
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != "Basic dXNlcjp0b2tlbg==":
            return httpx.Response(401)

        path = request.url.path
        if path == f"/wiki/api/v2/pages/{ROOT_ID}/descendants":
            cursor = request.url.params.get("cursor")
            if cursor == "next" and self.fail_next_page:
                return httpx.Response(503)
            page_ids = [page["id"] for page in self.descendants if page["type"] == "page"]
            if cursor == "next":
                results = [page for page in self.descendants if page["id"] == page_ids[1]]
                links: dict[str, str] = {}
            else:
                results = [page for page in self.descendants if page["id"] == page_ids[0]]
                links = {"next": "/wiki/api/v2/pages/100/descendants?cursor=next"} if len(page_ids) > 1 else {}
            return httpx.Response(200, json={"results": results, "_links": links})

        prefix = "/wiki/api/v2/pages/"
        if path.startswith(prefix):
            page_id = path.removeprefix(prefix)
            if self.fail_next_page and page_id == "200":
                return httpx.Response(503)
            page = self.pages.get(page_id)
            return httpx.Response(404) if page is None else httpx.Response(200, json=page)

        return httpx.Response(404)


def make_client(api: MockConfluence) -> ConfluenceClient:
    transport = httpx.MockTransport(api)
    return ConfluenceClient(
        SITE_URL,
        "user",
        "token",
        http_client=httpx.Client(transport=transport),
    )


def make_settings(tmp_path: Path) -> Settings:
    source_dir = tmp_path / "documents"
    source_dir.mkdir()
    return Settings(
        source_dir=source_dir,
        database_path=tmp_path / "index.sqlite3",
        base_url=None,
        embedding_model=None,
        embedding_dimensions=None,
        answer_model=None,
        projects={PROJECT: [], "personal": []},
    )


def test_sync_indexes_root_descendants_urls_edits_and_deletions(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = make_settings(tmp_path)
    unrelated = settings.source_dir / "personal.md"
    unrelated.write_text("# Local note\n\nKeep this unrelated document.\n", encoding="utf-8")
    store = IndexStore(settings.database_path)
    assert Indexer(settings.source_dir, store, project="personal").run().added == 1
    api = MockConfluence()
    client = make_client(api)

    first = sync_root(ROOT_ID, settings, client, PROJECT)

    assert first.added == 3
    assert first.removed == 0
    assert len([request for request in api.requests if request.url.path.endswith("/descendants")]) == 2
    assert not any(request.url.path.endswith("/pages/900") for request in api.requests)
    for query, expected_url in (
        ("RootSignal", "https://acme.atlassian.net/wiki/spaces/OPS/pages/100/Operations"),
        ("OldVersionSignal", "https://acme.atlassian.net/wiki/spaces/OPS/pages/200/Recovery"),
        ("DeleteMeSignal", "https://acme.atlassian.net/wiki/spaces/OPS/pages/300/Escalation"),
    ):
        result = store.search_keyword(query, limit=5, project=PROJECT)[0].chunk
        assert expected_url in result.locator
    assert " > Rollback" in store.search_keyword(
        "OldVersionSignal", limit=5, project=PROJECT
    )[0].chunk.locator

    api.pages["200"] = api._page("200", "Recovery", "NewVersionSignal updated rollback details.")
    api.descendants = [api.descendants[0]]

    second = sync_root(ROOT_ID, settings, client, PROJECT)

    assert second.updated == 1
    assert second.removed == 1
    assert store.search_keyword("OldVersionSignal", limit=5, project=PROJECT) == []
    updated = store.search_keyword("NewVersionSignal", limit=5, project=PROJECT)[0].chunk
    assert "https://acme.atlassian.net/wiki/spaces/OPS/pages/200/Recovery" in updated.locator
    assert " > Rollback" in updated.locator
    assert store.search_keyword("DeleteMeSignal", limit=5, project=PROJECT) == []
    assert store.search_keyword("unrelated document", limit=5, project="personal")
    assert store.search_keyword("unrelated document", limit=5, project=PROJECT) == []
    assert unrelated.is_file()
    assert (
        settings.source_dir
        / "confluence-sync"
        / PROJECT
        / "acme.atlassian.net"
        / ROOT_ID
        / f"{ROOT_ID}.md"
    ).is_file()

    citation = store.get_chunks([updated.id], project=PROJECT)[0]
    assert "https://acme.atlassian.net/wiki/spaces/OPS/pages/200/Recovery" in citation.locator
    config_path = tmp_path / "local-docs-rag.json"
    settings.save(config_path)
    assert local_docs_main(
        ["search", PROJECT, "NewVersionSignal", "--config-path", str(config_path)]
    ) == 0
    assert "https://acme.atlassian.net/wiki/spaces/OPS/pages/200/Recovery" in capsys.readouterr().out


def test_incomplete_snapshot_does_not_change_mirror_or_index(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = IndexStore(settings.database_path)
    api = MockConfluence()
    client = make_client(api)
    sync_root(ROOT_ID, settings, client, PROJECT)
    before_hashes = store.document_hashes(project=PROJECT)
    before_files = {
        path.relative_to(settings.source_dir): path.read_bytes()
        for path in settings.source_dir.rglob("*.md")
    }
    api.fail_next_page = True

    with pytest.raises(ConfluenceError):
        sync_root(ROOT_ID, settings, client, PROJECT)

    after_files = {
        path.relative_to(settings.source_dir): path.read_bytes()
        for path in settings.source_dir.rglob("*.md")
    }
    assert store.document_hashes(project=PROJECT) == before_hashes
    assert after_files == before_files
    assert store.search_keyword("DeleteMeSignal", limit=5, project=PROJECT)


def test_cli_registers_mirror_directory_for_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    config_path = tmp_path / "local-docs-rag.json"
    settings.save(config_path)

    class MockClient:
        def __init__(self, site_url: str, email: str, api_token: str) -> None:
            self.site_url = site_url

        def close(self) -> None:
            pass

    monkeypatch.setattr(confluence_cli, "load_credentials", lambda: ("user", "token"))
    monkeypatch.setattr(confluence_cli, "ConfluenceClient", MockClient)
    monkeypatch.setattr(
        confluence_cli,
        "sync_root",
        lambda root_page_id, settings, client, project, provider: SyncReport(1, 0, 0, 0, 0),
    )

    assert confluence_cli._sync(SITE_URL, ROOT_ID, PROJECT, config_path) == 0

    updated = Settings.load(config_path=config_path)
    expected_dir = (
        settings.source_dir
        / "confluence-sync"
        / PROJECT
        / "acme.atlassian.net"
        / ROOT_ID
    ).resolve()
    assert expected_dir in updated.projects[PROJECT]