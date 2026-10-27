from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from local_docs_rag.config import DEFAULT_CONFIG_PATH, Settings
from local_docs_rag.providers import EmbeddingProvider

from confluence_sync.client import ConfluenceClient, ConfluenceError
from confluence_sync.credentials import load_credentials, prompt_and_store_credentials
from confluence_sync.sync import mirror_directory, sync_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="confluence-sync")
    commands = parser.add_subparsers(dest="command", required=True)

    credentials = commands.add_parser("credentials", help="manage Confluence credentials")
    credential_commands = credentials.add_subparsers(dest="credential_command", required=True)
    set_credentials = credential_commands.add_parser("set", help="save API token in the OS credential store")
    set_credentials.set_defaults(handler=lambda args: _set_credentials())

    sync = commands.add_parser("sync", help="explicitly sync a root page and its descendants")
    sync.add_argument("--site-url", required=True, help="HTTPS Confluence Cloud site URL")
    sync.add_argument("--root-page-id", required=True, help="numeric root page ID")
    sync.add_argument("--project", required=True, help="registered local-docs-rag project")
    sync.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    sync.set_defaults(
        handler=lambda args: _sync(
            args.site_url,
            args.root_page_id,
            args.project,
            args.config_path,
        )
    )
    return parser


def _set_credentials() -> int:
    prompt_and_store_credentials()
    print("Confluence credentials saved to the OS credential store.")
    return 0


def _sync(site_url: str, root_page_id: str, project: str, config_path: Path) -> int:
    settings = Settings.load(config_path=config_path)
    if project not in settings.projects:
        raise ValueError(
            f"unknown project {project!r}; register it with "
            f"'local-docs-rag project add {project} --config-path {config_path}'"
        )
    email, api_token = load_credentials()
    provider = None
    if settings.embedding_model is not None or settings.embedding_dimensions is not None:
        provider = EmbeddingProvider.create(settings)
    client = ConfluenceClient(site_url, email, api_token)
    try:
        report = sync_root(root_page_id, settings, client, project, provider)
    finally:
        client.close()
    root_dir = mirror_directory(settings, project, site_url, root_page_id).resolve()
    projects = dict(settings.projects)
    project_dirs = list(projects[project])
    if root_dir not in {directory.resolve() for directory in project_dirs}:
        project_dirs.append(root_dir)
        projects[project] = project_dirs
        replace(settings, projects=projects).save(config_path)
    print(
        f"Sync complete: added={report.added} updated={report.updated} "
        f"unchanged={report.unchanged} removed={report.removed} failed={report.failed}"
    )
    if provider is not None:
        print("Page text was sent to the configured embedding provider.")
    return 0 if report.failed == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ConfluenceError, FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())