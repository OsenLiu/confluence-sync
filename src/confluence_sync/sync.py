from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from local_docs_rag.config import Settings, validate_project_name
from local_docs_rag.indexing import Indexer
from local_docs_rag.providers import EmbeddingProvider
from local_docs_rag.store import IndexStore

from confluence_sync.client import ConfluenceClient
from confluence_sync.convert import render_page


@dataclass(frozen=True)
class SyncReport:
    added: int
    updated: int
    unchanged: int
    removed: int
    failed: int


def _safe_site_name(site_url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(site_url).hostname or "unknown-site"


def mirror_directory(settings: Settings, project: str, site_url: str, root_page_id: str) -> Path:
    return settings.source_dir / "confluence-sync" / project / _safe_site_name(site_url) / root_page_id


@contextmanager
def _root_lock(root_dir: Path) -> Iterator[None]:
    root_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = root_dir / ".sync.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_page(path: Path, contents: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def sync_root(
    root_page_id: str,
    settings: Settings,
    client: ConfluenceClient,
    project: str,
    embedding_provider: EmbeddingProvider | None = None,
) -> SyncReport:
    if not root_page_id.isdigit():
        raise ValueError("root page ID must contain only digits")
    validate_project_name(project)
    if project not in settings.projects:
        raise ValueError(
            f"unknown project {project!r}; register it with 'local-docs-rag project add'"
        )

    root_dir = mirror_directory(settings, project, client.site_url, root_page_id)
    with _root_lock(root_dir):
        pages = client.fetch_tree(root_page_id)
        rendered = {
            f"{page.id}.md": render_page(page.title, page.canonical_url, page.storage_body)
            for page in pages
        }

        existing = {
            path.name: path.read_bytes()
            for path in root_dir.glob("[0-9]*.md")
            if path.stem.isdigit()
        }
        to_write = {name: content for name, content in rendered.items() if existing.get(name) != content}
        to_delete = existing.keys() - rendered.keys()

        for filename, contents in to_write.items():
            _write_page(root_dir / filename, contents)
        for filename in to_delete:
            (root_dir / filename).unlink()

        store = IndexStore(settings.database_path, settings.embedding_dimensions)
        index_report = Indexer(root_dir, store, embedding_provider, project=project).run()
        return SyncReport(
            added=len(rendered.keys() - existing.keys()),
            updated=len(to_write.keys() & existing.keys()),
            unchanged=len(rendered) - len(to_write),
            removed=len(to_delete),
            failed=index_report.failed,
        )