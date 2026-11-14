"""HTML 본문을 평문으로. 표시용이 아니라 분류용이므로 글자만 남기고 줄바꿈 정도만 살린다."""

import re
from html.parser import HTMLParser

_SPACES = re.compile(r"\s+")
_SKIP = {"script", "style", "head", "title", "noscript", "template"}
_BLOCK = {
    "address", "article", "blockquote", "div", "dl", "dt", "dd", "footer", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "ol", "p", "pre", "section", "table", "tr", "ul",
}  # fmt: skip


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip_depth += 1
        elif tag == "br" or tag in _BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br" or tag == "hr":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            # HTML에서 소스의 줄바꿈·연속 공백은 공백 하나와 같다
            self.parts.append(_SPACES.sub(" ", data))


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)
