"""Validate locally compiled static assets. Standard library only; no JS runtime."""
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.links.append(attrs["src"])
        if tag == "link" and attrs.get("rel") in ("stylesheet", "modulepreload"):
            self.links.append(attrs.get("href", ""))


def validate_static(directory: Path, manifest_path: Path | None = None) -> dict[str, str]:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Нет production-каталога miniapp/dist.")
    files = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlink в production frontend недопустим.")
        name = path.relative_to(directory).as_posix()
        if path.is_dir():
            if name != "assets":
                raise ValueError("Неожиданный каталог в production frontend.")
            continue
        if name != "index.html" and not re.fullmatch(r"assets/[A-Za-z0-9_-]+-[A-Za-z0-9_-]+\.(js|css)", name):
            raise ValueError("В production frontend найден непроизводственный файл.")
        raw = path.read_bytes()
        if not raw:
            raise ValueError("В production frontend найден пустой файл.")
        text = raw.decode("utf-8")
        if path.suffix in (".html", ".js") and any(marker in text for marker in (
            "preview.html", "demoClient", "ДЕМОНСТРАЦИЯ", "Пример интерфейса, данные вымышлены",
            "sourceMappingURL", "BOT_TOKEN", "BITRIX_WEBHOOK_URL",
        )):
            raise ValueError("В production frontend найдены demo, source map или секретные настройки.")
        if "sourceMappingURL" in text or re.search(r"\d{5,}:[A-Za-z0-9_-]{20,}|https?://[^\s\"']+/rest/\d+/[A-Za-z0-9_-]+/", text):
            raise ValueError("В production frontend найдены source map или credentials.")
        files[name] = hashlib.sha256(raw).hexdigest()
    if "index.html" not in files or not any(n.endswith(".js") for n in files) or not any(n.endswith(".css") for n in files):
        raise ValueError("Production frontend должен содержать index.html, JavaScript и CSS.")
    links = AssetLinks()
    links.feed((directory / "index.html").read_text(encoding="utf-8"))
    for link in links.links:
        if link == "https://telegram.org/js/telegram-web-app.js":
            continue
        if not link.startswith("/assets/") or link[1:] not in files:
            raise ValueError("HTML ссылается на отсутствующий или непроверенный frontend asset.")
    if not any(link.endswith(".js") and link.startswith("/assets/") for link in links.links):
        raise ValueError("В HTML нет ссылки на production JavaScript.")
    if manifest_path is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema") != 1 or manifest.get("assets") != files:
            raise ValueError("Production assets не совпадают с проверенной сборкой.")
    return files
