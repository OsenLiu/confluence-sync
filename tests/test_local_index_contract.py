from pathlib import Path

from local_docs_rag.indexing import Indexer
from local_docs_rag.models import DocumentChunk
from local_docs_rag.store import IndexStore


def test_markdown_heading_preserves_canonical_url_in_search_locator(tmp_path: Path) -> None:
    source_dir = tmp_path / "documents"
    page_url = "https://acme.atlassian.net/wiki/spaces/TEAM/pages/123456/Runbook"
    page = source_dir / "confluence" / "acme.atlassian.net" / "123456" / "123456.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        f"# Runbook <{page_url}>\n\nUse the rollback procedure for recovery.\n",
        encoding="utf-8",
    )
    store = IndexStore(tmp_path / "index.sqlite3")

    report = Indexer(source_dir, store, project="team-docs").run()
    results = store.search_keyword("rollback procedure", limit=5, project="team-docs")

    assert report.added == 1
    assert len(results) == 1
    assert results[0].chunk.source == str(page.resolve())
    assert results[0].chunk.locator == f"Runbook <{page_url}>"


def test_index_run_preserves_sources_outside_its_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "documents"
    source_dir.mkdir()
    store = IndexStore(tmp_path / "index.sqlite3")
    page_url = "https://acme.atlassian.net/wiki/spaces/TEAM/pages/123456/Runbook"
    chunk = DocumentChunk("remote", page_url, "Runbook", "remote page content", "remote-hash")
    store.upsert_document(page_url, "remote-hash", [chunk])

    Indexer(source_dir, store).run()

    assert store.document_hashes()[page_url] == "remote-hash"