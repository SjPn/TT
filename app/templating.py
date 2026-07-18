from pathlib import Path

import markdown
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def md(text: str) -> str:
    return markdown.markdown(
        text or "",
        extensions=["fenced_code", "tables", "nl2br"],
    )


templates.env.filters["md"] = md
