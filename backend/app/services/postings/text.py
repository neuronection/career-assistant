"""Plain-text projection of connector payloads: untrusted third-party
markup becomes readable text (tags dropped, entities decoded, whitespace
collapsed) so no consumer ever parses board HTML."""

from __future__ import annotations

from html.parser import HTMLParser

_BLOCK_TAGS = frozenset(
    {
        "br",
        "p",
        "div",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "ul",
        "ol",
        "table",
    }
)
_SKIP_TAGS = frozenset({"script", "style"})


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def plain_text(value: str, *, limit: int = 8000) -> str:
    """Render untrusted markup as readable plain text.

    Tags are dropped (script/style content with them), character
    references are decoded, block tags become line breaks and runs of
    whitespace collapse. The result is capped at ``limit`` characters.
    """
    if not value:
        return ""
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line)
    return text[:limit].strip()
