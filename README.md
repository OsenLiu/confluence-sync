# Confluence Sync

An explicitly invoked, local companion CLI that mirrors Confluence Cloud pages into a registered local-docs-rag project. It uses the existing project-scoped index, search, and MCP citation flow. It does not write to Confluence or run on a schedule.

## Install

Requires Python 3.11 or newer. The package pins the public local-docs-rag Git commit whose `IndexStore`/`Indexer` contracts it uses.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Configure local-docs-rag first so it points to the document directory and SQLite database this sync should use. Register a project with the same config file before syncing:

```bash
"$HOME/Projects/local-docs-rag/.venv/bin/local-docs-rag" project add team-docs \
  --config-path "$HOME/Library/Application Support/local-docs-rag/config.json"
```

Confluence page files are written under `<document-directory>/confluence-sync/<project>/<site-host>/<root-page-id>/`. The sync registers each root mirror directory in the project's source-directory list.

## Credentials

For this personal/local CLI, Atlassian account email and API token are stored in the OS credential store under the `confluence-sync` service. This is separate from local-docs-rag's model-provider key.

```bash
.venv/bin/confluence-sync credentials set
```

This API-token flow is for a local script, not a distributable integration. A distributed app should use a registered OAuth 2.0 3LO integration with least-privilege read scopes. Credentials are never printed or written to the project config. Pages remain local unless semantic indexing is configured, in which case local-docs-rag sends page text to its configured embedding provider.

## Sync

Use the numeric Confluence page ID and HTTPS site URL. A root page URL is not parsed in v1.

```bash
.venv/bin/confluence-sync sync \
  --site-url https://acme.atlassian.net \
  --root-page-id 123456 \
  --project team-docs \
  --config-path "$HOME/Library/Application Support/local-docs-rag/config.json"
```

The command fetches the root, all page descendants, and their storage bodies. It follows every descendants cursor, ignores non-page descendants, and writes the API-provided `webui` URL into each Markdown title. Existing search results and citations show that URL in the heading locator. Page IDs name mirror files, so title changes do not change file identity.

The mirror and index are scoped to the selected project; indexing does not scan or change other project directories. The mirror is changed only after the root, descendants, bodies, and conversions are all fetched successfully. On a later complete sync, pages no longer visible under the root are removed from that root's mirror only; the indexer then removes their chunks from the selected project. API, permission, pagination, or conversion failures leave the mirror and index unchanged. A failure during local indexing is reported; rerun the same explicit sync to reconcile the mirror and index.

Search with the selected project using the existing `local-docs-rag search` command or MCP server. For example, `local-docs-rag search team-docs "rollback procedure"`. Each MCP tool call must also specify `team-docs` as its project. The canonical URL is included in both search locators and citations; the source remains the local Markdown path because that is the source field expected by the file indexer.

## Tests

```bash
.venv/bin/python -m pytest -q
```

The end-to-end tests use a mocked HTTP API and a real temporary local-docs-rag SQLite index. They cover root and descendant pages, cursor pagination, canonical URL locators, edits, deletions, project isolation, and failure-safe snapshots. No real Confluence tenant is used.