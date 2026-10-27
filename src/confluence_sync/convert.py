from __future__ import annotations

from html.parser import HTMLParser


class _StorageMarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.text_buffer: list[str] = []
        self.heading_level: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {f"h{level}" for level in range(1, 7)}:
            self._flush()
            self.heading_level = min(int(tag[1]) + 1, 6)
        elif tag == "li":
            self._flush()
            self.text_buffer.append("- ")
        elif tag in {"p", "div", "pre", "tr", "br"}:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in {f"h{level}" for level in range(1, 7)}:
            self._flush()
            if self.heading_level is not None and self.output:
                heading = self.output.pop()
                self.output.append("\n" + "#" * self.heading_level + " " + heading + "\n\n")
            self.heading_level = None
        elif tag in {"p", "div", "li", "pre", "tr", "td", "th"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        self.text_buffer.append(data)

    def _flush(self) -> None:
        text = " ".join("".join(self.text_buffer).split())
        self.text_buffer.clear()
        if text:
            self.output.append(text)


def storage_to_markdown(storage_body: str) -> str:
    parser = _StorageMarkdownParser()
    parser.feed(storage_body)
    parser.close()
    parser._flush()
    markdown = "\n\n".join(part for part in parser.output if part.strip()).strip()
    if not markdown:
        raise ValueError("page body contains no indexable text")
    return markdown


def render_page(title: str, canonical_url: str, storage_body: str) -> bytes:
    body = storage_to_markdown(storage_body)
    return f"# {title} <{canonical_url}>\n\n{body}\n".encode("utf-8")