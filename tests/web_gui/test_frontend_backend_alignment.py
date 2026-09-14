from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from eom_web_gui.gateways import EXPLORER_SPECS
from fastapi.routing import APIRoute

from tests.web_gui.helpers import make_client

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "apps/web_gui/eom_web_gui/static/app.js"
LOGIN_JS = ROOT / "apps/web_gui/eom_web_gui/static/login.js"
INDEX_HTML = ROOT / "apps/web_gui/eom_web_gui/static/index.html"
STATIC_ROOT = INDEX_HTML.parent
GATEWAYS = ROOT / "apps/web_gui/eom_web_gui/gateways.py"
APPLICATION_OPENAPI = ROOT / "api/openapi/eom-api-v1.openapi.json"
API_PREFIX = "/studio/api/v1"
HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


class _StaticHtmlInventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.identifiers: list[str] = []
        self.resources: list[str] = []

    def handle_starttag(self, _: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if identifier := values.get("id"):
            self.identifiers.append(identifier)
        for attribute in ("href", "src"):
            value = values.get(attribute)
            if value and value.startswith("/studio/assets/"):
                self.resources.append(value.removeprefix("/studio/assets/"))


def _matching_parenthesis(source: str, start: int) -> int:
    depth = 1
    quote: str | None = None
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'", "`"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError("unterminated frontend api() expression")


def _first_top_level_comma(expression: str) -> int | None:
    depth = 0
    quote: str | None = None
    escaped = False
    for index, character in enumerate(expression):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'", "`"}:
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == "," and depth == 0:
            return index
    return None


def _string_fragments(expression: str) -> str:
    values: list[str] = []
    quote: str | None = None
    escaped = False
    start = 0
    for index, character in enumerate(expression):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                values.append(expression[start:index])
                quote = None
            continue
        if character in {'"', "'", "`"}:
            quote = character
            start = index + 1
    if quote is not None:
        raise AssertionError("unterminated frontend route string")
    return "".join(values)


def _normalize(path: str) -> str:
    path = re.sub(r"\$\{query(?:\.toString\(\))?\}", "", path)
    path = re.sub(r"\$\{[^}]+\}", "{}", path).split("?", 1)[0]
    path = re.sub(r"\{[^}]+\}", "{}", path)
    return path


def _frontend_api_calls(source: str) -> set[tuple[str, str]]:
    calls: set[tuple[str, str]] = set()
    for match in re.finditer(r"\bapi\(", source):
        if "function api" in source[max(0, match.start() - 24) : match.end()]:
            continue
        end = _matching_parenthesis(source, match.end())
        expression = source[match.end() : end]
        comma = _first_top_level_comma(expression)
        first = expression if comma is None else expression[:comma]
        if first.strip() == "path":
            continue
        path = _string_fragments(first)
        if not path.startswith("/"):
            raise AssertionError(f"unrecognized frontend route expression: {first!r}")
        options = "" if comma is None else expression[comma + 1 :]
        method_match = re.search(r'\bmethod\s*:\s*"([A-Z]+)"', options)
        calls.add((method_match.group(1) if method_match else "GET", _normalize(path)))
    return calls


def _bff_routes() -> set[tuple[str, str]]:
    client, _ = make_client()
    return {
        (method, _normalize(route.path.removeprefix(API_PREFIX)))
        for route in client.app.routes
        if isinstance(route, APIRoute) and route.path.startswith(API_PREFIX)
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }


def _static_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value if isinstance(value, ast.Constant) else "{}" for value in node.values
        )
    return None


def _gateway_application_api_calls() -> set[tuple[str, str]]:
    """Extract every upstream operation and fail if a new dynamic shape is not audited."""

    tree = ast.parse(GATEWAYS.read_text(encoding="utf-8"))
    gateway = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HttpApplicationGateway"
    )
    calls: set[tuple[str, str]] = {
        ("GET", "/api/v1/health/live"),
        ("GET", "/api/v1/health/ready"),
    }
    unknown: list[int] = []
    for node in ast.walk(gateway):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        if name in {"_authorized", "_request"}:
            offset = 1 if name == "_authorized" else 0
            if len(node.args) <= offset + 1:
                unknown.append(node.lineno)
                continue
            method = _static_string(node.args[offset])
            path = _static_string(node.args[offset + 1])
            if method is not None and path is not None:
                calls.add((method, path))
                continue
            if (
                name == "_authorized"
                and isinstance(node.args[offset + 1], ast.Name)
                and node.args[offset + 1].id in {"media_path", "path"}
            ):
                continue
            if (
                name == "_authorized"
                and isinstance(node.args[offset + 1], ast.Call)
                and isinstance(node.args[offset + 1].func, ast.Attribute)
                and node.args[offset + 1].func.attr == "format"
                and isinstance(node.args[offset + 1].func.value, ast.Name)
                and node.args[offset + 1].func.value.id == "detail_template"
            ):
                continue
            unknown.append(node.lineno)
        elif name == "_application_request" and len(node.args) >= 2:
            method = _static_string(node.args[0])
            path = _static_string(node.args[1])
            if method is not None and path is not None:
                calls.add((method, path))
            elif not (
                isinstance(node.args[0], ast.Name)
                and node.args[0].id == "method"
                and isinstance(node.args[1], ast.Name)
                and node.args[1].id == "path"
            ):
                unknown.append(node.lineno)
        elif name == "_item_media_response":
            media_path = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "media_path"),
                None,
            )
            path = _static_string(media_path) if media_path is not None else None
            if path is None:
                unknown.append(node.lineno)
            else:
                calls.add(("GET", path))
    assert not unknown, f"unaudited dynamic Application API call at lines {sorted(unknown)}"
    for path, _, detail_template in EXPLORER_SPECS.values():
        calls.add(("GET", path))
        if detail_template is not None:
            calls.add(("GET", detail_template))
    return {(method.upper(), _normalize(path)) for method, path in calls}


def _application_api_operations() -> set[tuple[str, str]]:
    contract = json.loads(APPLICATION_OPENAPI.read_text(encoding="utf-8"))
    return {
        (method.upper(), _normalize(path))
        for path, definition in contract["paths"].items()
        for method in definition
        if method in HTTP_METHODS
    }


def test_every_frontend_api_call_has_a_method_matching_bff_route() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    frontend = _frontend_api_calls(source)
    frontend.add(("POST", "/admin/execution-presets/{}/deprecations"))
    frontend.add(("POST", "/session"))

    missing = frontend - _bff_routes()

    assert not missing
    assert (
        "const path = `/admin/execution-presets/${encodeURIComponent(identifier)}/deprecations`;"
        in source
    )
    assert sum(line.strip().startswith("await api(path,") for line in source.splitlines()) == 1
    assert 'method: "POST"' in LOGIN_JS.read_text(encoding="utf-8")


def test_direct_browser_stream_download_and_media_routes_exist() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    expected = {
        ("GET", "/workflows/{}/stream"),
        ("GET", "/mock-exam-hwpx/builds/{}/download"),
        ("GET", "/hwpx/builds/{}/download"),
        ("GET", "/admin/assessment-learning-corpus/exams/{}/pages/{}/image"),
        ("GET", "/items/{}/revisions/{}/media/{}"),
        ("GET", "/items/{}/revisions/{}/visuals/{}"),
    }
    assert expected <= _bff_routes()
    for fragment in (
        "/workflows/${encodeURIComponent(workflowId)}/stream",
        "/mock-exam-hwpx/builds/${encodeURIComponent(value.build_id)}/download",
        "/hwpx/builds/${encodeURIComponent(value.build_id)}/download",
        "/pages/${encodeURIComponent(page.page_input_id)}/image",
    ):
        assert fragment in source

    preview_schema = (ROOT / "schemas/web-gui/item-preview-v3.schema.json").read_text(
        encoding="utf-8"
    )
    assert "media/block_" in preview_schema
    assert "visuals/[01]" in preview_schema


def test_every_web_gateway_operation_exists_in_the_application_api_contract() -> None:
    missing = _gateway_application_api_calls() - _application_api_operations()

    assert not missing


def test_browser_dom_references_and_static_module_graph_are_closed() -> None:
    javascript = APP_JS.read_text(encoding="utf-8")
    parser = _StaticHtmlInventory()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    referenced_ids = set(re.findall(r'\$\(\s*["\']#([A-Za-z0-9_-]+)["\']\s*\)', javascript))

    assert len(parser.identifiers) == len(set(parser.identifiers))
    assert not referenced_ids - set(parser.identifiers)
    assert all((STATIC_ROOT / relative).is_file() for relative in parser.resources)

    modules = {APP_JS, LOGIN_JS}
    visited: set[Path] = set()
    while modules:
        module = modules.pop().resolve(strict=True)
        if module in visited:
            continue
        visited.add(module)
        source = module.read_text(encoding="utf-8")
        for relative in re.findall(r'\bfrom\s+["\'](\./[^"\']+)["\']', source):
            dependency = (module.parent / relative).resolve(strict=True)
            assert dependency.is_relative_to(STATIC_ROOT.resolve(strict=True))
            modules.add(dependency)


def test_preview_schema_discriminators_match_browser_acceptance_and_renderer() -> None:
    schema = json.loads(
        (ROOT / "schemas/web-gui/item-preview-v3.schema.json").read_text(encoding="utf-8")
    )
    schema_types = {
        schema["$defs"][reference["$ref"].rsplit("/", 1)[-1]]["properties"]["type"]["const"]
        for reference in schema["properties"]["blocks"]["items"]["oneOf"]
    }
    helper = (STATIC_ROOT / "item-preview.js").read_text(encoding="utf-8")
    accepted_match = re.search(
        r"const PREVIEW_BLOCK_TYPES = new Set\(\[(?P<values>.*?)\]\);",
        helper,
        flags=re.DOTALL,
    )
    assert accepted_match is not None
    accepted_types = set(re.findall(r'"([a-z_]+)"', accepted_match.group("values")))
    rendered_types = set(re.findall(r'block\.type === "([a-z_]+)"', APP_JS.read_text()))

    assert schema_types == accepted_types == rendered_types


def test_browser_javascript_is_syntactically_valid(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node is required for the browser release syntax gate")

    for source in sorted(STATIC_ROOT.rglob("*.js")):
        relative = source.relative_to(STATIC_ROOT).with_suffix(".mjs")
        staged = tmp_path / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(source.read_bytes())
        completed = subprocess.run(
            [node, "--check", str(staged)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, f"{relative}: {completed.stderr}"
