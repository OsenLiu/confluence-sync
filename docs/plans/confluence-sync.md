# Confluence Sync Plan

**Evidence boundary:** The `confluence-sync` workspace was empty at planning time and contains no application code or tests to inspect. Repository facts below were verified against the adjacent `local-docs-rag` checkout and its tests; confirm that checkout's version and dependency policy before implementation. Recommendations and unresolved questions are labeled explicitly.

## 1. Purpose and user problem

Users have useful Confluence Cloud knowledge that is absent from their local-docs-rag search and citation workflow. This standalone companion should let a user explicitly sync a chosen root page and its descendant pages into the same local SQLite index, so existing search and answer tools can retrieve the content and cite its canonical Confluence URL.

## 2. Goals and non-goals

**Goals**
- Target Confluence Cloud and sync the selected root page plus descendant pages.
- Index page content into the existing local-docs-rag search experience and preserve canonical URLs in results/citations.
- Reflect edits and removals on a later user-invoked sync; make no remote content changes.
- Keep the first version explicitly invoked and user-controlled.

**Non-goals**
- Scheduled/background sync, webhook handling, or unattended polling.
- Confluence Data Center, writing to Confluence, and indexing non-page content such as comments or attachments.
- Replacing or forking local-docs-rag's search, CLI, or MCP server.
- Connecting to a real Confluence instance for development or tests.

## 3. User workflow

**Recommendation:** Provide a companion CLI command that accepts a Confluence site and a root page identifier or URL, resolves and confirms the page title/site, then performs one complete sync and reports added, updated, unchanged, removed, and failed pages. A dry-run could be a later enhancement; the initial command should never delete local index entries after an incomplete fetch.

Expected flow: configure credentials and the shared local-docs-rag index; explicitly run sync for a root; review its summary; use the existing `local-docs-rag search` / `ask` or MCP tools. No remote edits or scheduled execution occur.

**Open question:** Should v1 accept a page ID, a page URL, or both? URL parsing and tenant validation must be based on documented/observed Cloud URL forms, not guessed formats.

## 4. Architecture options and recommendation

**Verified local-docs-rag contracts** (adjacent checkout):
- `DocumentChunk` in `src/local_docs_rag/models.py` contains `id`, `source`, `locator`, `text`, and `document_hash` only.
- `IndexStore` in `src/local_docs_rag/store.py` keys documents by `source`; `upsert_document` replaces a document's FTS/vector chunks and `remove_document` removes them. The store does not require `source` to be a filesystem path.
- `chunk_sections` in `src/local_docs_rag/chunking.py` accepts `(locator, content)` sections and creates stable chunk IDs from source, locator, section, and text.
- The current file `Indexer` only reads PDF/Markdown and deletes indexed sources missing from its scanned directory. The CLI's `index` command uses it.
- `SearchService` searches that store; the CLI and MCP search return `source` and `locator`. MCP answer citations resolve chunk IDs back to those same fields. Current search/answer citation contracts therefore have no separate URL metadata field.
- Existing configuration supplies a SQLite path and optional embedding provider. Without an embedding provider, the index still supports FTS5 keyword search.

**Option A: write canonical URLs directly through `IndexStore`.** This makes URL the existing citation `source`, but `local-docs-rag index` removes any indexed source that is not a PDF/Markdown file under its configured source directory. URL sources would disappear on a normal index run, so this is not suitable for the shared database without changing local-docs-rag.

**Option B: mirror pages as Markdown under the configured document directory, then invoke the existing file indexer. Recommended.** Store files by numeric page ID under a reserved site/root directory. Put the API-returned canonical `webui` URL in the Markdown title heading; the existing parser carries it in `locator`, which search, CLI, MCP, and answer citations already return. Keep the local Markdown path as `source`, so a normal full-directory index preserves the pages. Fetch and convert the entire snapshot before changing files; write changed pages first, remove stale numeric page files only inside that root's directory, then run the existing `Indexer`. This avoids private schema access and companion ownership tables, at the cost of URLs appearing in `locator` rather than `source`.

The companion pins the verified public local-docs-rag commit in its package metadata because that repository has no published release at planning time. Recheck the pinned dependency before upgrading.

## 5. Page identity, hierarchy, content conversion, URL citations, and change behavior

**Verified Atlassian API facts:** Confluence REST API v2 provides `GET /pages/{id}` for a page, including its ID, `parentId`, version, body, and `_links.webui`; `body-format` is a query parameter. `GET /pages/{id}/descendants` returns descendant records in top-to-bottom order with IDs, type, parent ID, and depth; results are cursor-paginated and minimal, so fetch page details separately. Descendant records can represent page and non-page content. `GET /pages/{id}/children` is documented as deprecated; the direct-children endpoint is available if traversal is chosen instead. The v2 API uses cursor pagination via the next URL/cursor. See official links in section 10.

**Implementation choice:** Accept a numeric root page ID plus an HTTPS site URL in v1. This avoids guessing URL path formats. Fetch the root separately, then retrieve all descendants (filtering to `type=page`) and fetch each page's body and URL. Handle every cursor. Use page-ID-named files for stable identity; use page title, canonical URL, and heading ancestry in locators. Compare rendered Markdown bytes to skip unchanged files. If a page URL changes, its file remains stable by page ID and the content is reindexed because the heading changed.

Use the API-returned `webui` page link in the Markdown title, resolving a relative link against the API's configured site base. Do not construct a URL from title or page ID when the API supplies the web link. Search citations preserve the complete canonical URL in `locator`; `source` remains the local mirror path under the existing index contract.

**Content conversion recommendation:** Request a documented page body representation, convert it into plain-text/Markdown-like sections, then use the existing chunker. Preserve headings and code blocks where possible; include the page title in locator/context. Do not index raw storage markup as readable prose. Start with page text only; treat macros, embedded content, tables, images, and attachments as conversion boundaries requiring explicit policy and tests.

**Deletion/update recommendation:** Fetch and convert the root, every descendant page, all pagination, and every page body before changing the mirror. On authentication, permission, pagination, network, or conversion failure, retain the previous mirror and index. On a complete snapshot, update pages and remove only stale numeric Markdown files inside the selected root's dedicated mirror directory; unrelated files remain untouched. A page moved outside the chosen root is removed from that root's local scope.

**Implementation choice:** A page missing from a complete visible-page snapshot is removed from that root's local scope, whether deleted remotely, no longer visible, or moved outside the root. This is not represented as proof of remote deletion. If the root itself or any required page cannot be fetched, abort without pruning.

## 6. Authentication, credential handling, permissions, privacy, and failure handling

**Verified facts:** Page reads require the user's Confluence view permissions. The documented OAuth 2.0 granular scopes include `read:page:confluence` for page content and `read:hierarchical-content:confluence` for descendants. REST v2 describes direct REST authentication with Basic auth as supported, and Atlassian's Basic auth guidance uses account email plus API token but recommends it for scripts/manual calls; its guidance says distributed integrations should use a single 3LO app rather than collect API tokens or direct customers to create individual apps.

**Implementation choice:** This release is a personal/local CLI, so use direct Basic authentication with the user's Atlassian account email and API token, stored in the OS credential store under a distinct `confluence-sync` namespace. Atlassian documents this for scripts/manual API calls and recommends one registered OAuth 2.0 3LO app for distributable integrations. Do not reuse local-docs-rag's model-provider credential. A future distributed version must use 3LO and its registered client flow.

Content and index remain on the user's machine unless local-docs-rag semantic embeddings or answer generation are configured; its README states chunks/questions/evidence are sent to the configured provider for those features. Disclose this in setup/output and provide keyword-only operation. Handle invalid credentials, insufficient permissions, deleted/moved pages, unsupported representations, pagination interruption, and transient service errors with actionable summaries and no destructive partial reconciliation. Retry/backoff policy and handling of Atlassian rate-limit responses must follow the current official guidance.

**Open questions:** Which auth model and distribution target apply? Which OS credential-store implementations are supported? Should sync warn or require confirmation when configured embeddings will send Confluence text to an external provider? What are the current rate-limit retry requirements?

## 7. Acceptance criteria

- User can explicitly sync a chosen Confluence Cloud root and its descendant pages; no scheduler or automatic remote polling exists.
- The root and every visible descendant page are indexed; non-page descendants are not treated as pages.
- Search results and MCP/answer citations contain the API-provided canonical Confluence URL in the locator and a useful page/heading context; the `source` remains the local mirror file path.
- Repeating an unchanged sync reports no page-content updates; editing a page replaces old searchable text with new text.
- A removed or out-of-scope page is removed from the companion's local index only after a complete successful reconciliation; unrelated documents remain indexed.
- Failed or partial sync does not prune the previous index snapshot and clearly reports failures.
- Sync never writes to Confluence, and credentials/content are not logged.

## 8. Testing strategy

Center the main end-to-end test on a mocked Confluence HTTP API and a real temporary local-docs-rag `IndexStore`/SQLite database. Do not connect to a real Confluence tenant. Use fixtures for a root, nested descendants, multiple cursor pages, page body representations, and API-returned web links.

The end-to-end flow should sync the root and descendants, query the real index through `SearchService` or its keyword store search, and assert each page's canonical URL and locator. Mutate a fixture page and sync again; assert new terms are searchable and old terms are gone. Remove a descendant from the mock snapshot and sync; assert its chunks disappear while unrelated local documents remain. Also assert the root is included, cursor traversal is complete, unchanged content is skipped, and failed/incomplete fetches do not trigger deletion. Add focused tests for URL resolution, conversion/locators, identity/URL changes, credential redaction, and auth/API error handling.

## 9. Phased implementation plan with dependencies

1. **Lock contracts and fixtures:** Confirm the pinned local-docs-rag dependency, shared source directory/database settings, canonical web-link shape, page body representation, and numeric root ID input. Build mock fixtures first. Depends on decisions in sections 4-6.
2. **Read-only Confluence client:** Implement auth transport, root lookup, cursor-aware descendants retrieval, page fetching, and typed failures. Validate against mocks only. Depends on the auth decision.
3. **Conversion and mirror:** Convert page bodies into Markdown headings/text and embed canonical URLs in the title heading. Use numeric page-ID filenames under a site/root-owned directory and safe atomic writes. Depends on API fixtures.
4. **Shared-index sync command:** Load the same document/index settings, run the existing file Indexer after a complete mirror update, and remove stale files only under the selected root directory. Depends on phases 2-3.
5. **End-to-end validation and docs:** Run the mocked-API/real-index scenarios, failure-safety tests, and manual CLI usability review; document credentials, privacy, and recovery. Depends on phase 4.

## 10. Risks and open questions

- **Citation location:** The existing indexer uses a local path as `source`; the canonical Confluence URL is included in the Markdown title so the parsed `locator` carries it into CLI, MCP, and answer citations.
- **Permission loss vs deletion:** descendant results include only what the user may view. A complete snapshot cannot by itself prove a page was deleted; decide whether loss of visibility should remove local content (recommended privacy default).
- **Content conversion fidelity:** Storage-format/ADF content may contain macros, tables, or embedded data not representable as Markdown. Define and test unsupported-content behavior; avoid claiming complete fidelity.
- **API behavior may evolve:** Recheck current v2 schemas, body formats, pagination, permission scopes, and rate limits at implementation time. The deprecated page-children route should not be the default.
- **Runtime dependency:** The companion pins a Git commit of local-docs-rag because there is no published release yet. A future index API change can require updating this dependency and its contract tests.
- **Normal index behavior:** The mirror stays under local-docs-rag's configured source directory, so its ordinary full-directory index retains pages and updates the same SQLite database.
- **Multiple roots and overlap:** Decide whether v1 supports one configured root or multiple. If multiple roots are allowed, define ownership and de-duplication for overlapping descendant trees before deletion reconciliation.
- **Official references:** [REST API v2 overview and pagination](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/); [Page API](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/); [Descendants API](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-descendants/); [Children API](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-children/); [Basic auth guidance](https://developer.atlassian.com/cloud/confluence/basic-auth-for-rest-apis/); [OAuth scopes](https://developer.atlassian.com/cloud/confluence/scopes-for-oauth-2-3LO-and-forge-apps/).