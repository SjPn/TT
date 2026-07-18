from pathlib import Path
import re

import markdown
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def md(text: str) -> str:
    return markdown.markdown(
        text or "",
        extensions=["fenced_code", "tables", "nl2br"],
    )


def mention_md(text: str, members=None) -> Markup:
    """Markdown + highlight @Name / @email for project members."""
    html = md(text)
    names: list[str] = []
    if members:
        for m in members:
            names.append(m.name)
            names.append(m.email)
            if m.name and " " in m.name:
                names.append(m.name.split()[0])
    for name in sorted(set(names), key=len, reverse=True):
        if not name:
            continue
        pattern = re.compile(rf"(?<![\w/])@{re.escape(name)}(?![\w])", re.IGNORECASE)
        html = pattern.sub(lambda m: f'<span class="mention">{escape(m.group(0))}</span>', html)
    return Markup(html)


templates.env.filters["md"] = md
templates.env.filters["mention_md"] = mention_md
