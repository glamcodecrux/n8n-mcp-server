"""server.py のツールに対するユニットテスト

- httpx.MockTransport で外部 HTTP を差し替え
- 正常系 / 異常系 (接続エラー, JSON 不正, HTTP エラー) を網羅
- 全 13 ツールを検証
- 起動時 env 検証も検証
"""
from __future__ import annotations

import json
import sys
import importlib
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def captured_tools():
    """server.py を import し、ツール関数を {name: callable} で返す"""
    import mcp.server.mcpserver as mcpserver_mod

    captured: dict[str, callable] = {}

    class FakeMCPServer:
        def __init__(self, name: str):
            self.name = name

        def tool(self, *args, **kwargs):
            def wrap(fn):
                captured[fn.__name__] = fn
                return fn
            return wrap

        def run(self):  # pragma: no cover
            raise RuntimeError("run() called in test")

    sys.path.insert(0, str(ROOT))
    if "server" in sys.modules:
        del sys.modules["server"]

    with patch.object(mcpserver_mod, "MCPServer", FakeMCPServer):
        import os
        os.environ["N8N_API_KEY"] = "test-key"
        os.environ["OLLAMA_HOST"] = "http://localhost:11434"
        os.environ["N8N_URL"] = "http://localhost:5678"

        mod = importlib.import_module("server")
    return mod, captured


@pytest.fixture
def patch_transport():
    """httpx.AsyncClient.__init__ をラップして MockTransport を強制注入する"""
    real_init = httpx.AsyncClient.__init__

    def _patch(handler):
        transport = httpx.MockTransport(handler)
        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            real_init(self, *args, **kwargs)
        return patch.object(httpx.AsyncClient, "__init__", patched_init)
    return _patch


# ============================================================
# 登録ツールの網羅性
# ============================================================

EXPECTED_TOOL_NAMES = {
    "ask_ollama", "list_n8n_workflows", "get_n8n_workflow",
    "get_n8n_executions", "get_n8n_execution", "check_n8n_status",
    "activate_n8n_workflow", "deactivate_n8n_workflow", "publish_n8n_workflow",
    "create_n8n_workflow", "delete_n8n_workflow", "execute_workflow_now",
    "list_n8n_credentials",
}


def test_all_tools_registered(captured_tools):
    """13 ツールが全て登録されている"""
    _, captured = captured_tools
    missing = EXPECTED_TOOL_NAMES - set(captured.keys())
    assert not missing, f"missing tools: {missing}"


# ============================================================
# Ollama 系
# ============================================================

@pytest.mark.asyncio
async def test_ask_ollama_success(captured_tools, patch_transport):
    _, captured = captured_tools
    ask_ollama = captured["ask_ollama"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"response": "hello"})

    with patch_transport(handler):
        result = await ask_ollama(prompt="hi")

    assert result == "hello"


@pytest.mark.asyncio
async def test_ask_ollama_404(captured_tools, patch_transport):
    _, captured = captured_tools
    ask_ollama = captured["ask_ollama"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="model not found")

    with patch_transport(handler):
        result = await ask_ollama(prompt="hi")

    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["error"] == "model_not_found"


@pytest.mark.asyncio
async def test_ask_ollama_connection_error(captured_tools, patch_transport):
    _, captured = captured_tools
    ask_ollama = captured["ask_ollama"]

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with patch_transport(handler):
        result = await ask_ollama(prompt="hi")

    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["error"] == "ConnectError"


# ============================================================
# n8n GET 系
# ============================================================

@pytest.mark.asyncio
async def test_list_n8n_workflows(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["list_n8n_workflows"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workflows"
        return httpx.Response(200, json={"data": [{"id": "1"}]})

    with patch_transport(handler):
        result = await fn()

    assert json.loads(result) == {"data": [{"id": "1"}]}


@pytest.mark.asyncio
async def test_get_n8n_workflow(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["get_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workflows/abc"
        return httpx.Response(200, json={"id": "abc", "name": "wf"})

    with patch_transport(handler):
        result = await fn("abc")

    assert json.loads(result)["name"] == "wf"


@pytest.mark.asyncio
async def test_get_n8n_workflow_http_error(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["get_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with patch_transport(handler):
        result = await fn("missing")

    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["tool"] == "get_n8n_workflow"


@pytest.mark.asyncio
async def test_get_n8n_executions_all(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["get_n8n_executions"]
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"data": []})

    with patch_transport(handler):
        await fn(limit=5)

    assert seen[0]["limit"] == "5"
    assert "workflowId" not in seen[0]


@pytest.mark.asyncio
async def test_get_n8n_executions_filtered(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["get_n8n_executions"]
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"data": []})

    with patch_transport(handler):
        await fn(workflow_id="wf1", limit=10)

    assert seen[0]["workflowId"] == "wf1"


@pytest.mark.asyncio
async def test_get_n8n_execution(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["get_n8n_execution"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/executions/exec1"
        return httpx.Response(200, json={"id": "exec1"})

    with patch_transport(handler):
        result = await fn("exec1", include_data=True)

    assert json.loads(result)["id"] == "exec1"


# ============================================================
# n8n 状態確認
# ============================================================

@pytest.mark.asyncio
async def test_check_n8n_status(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["check_n8n_status"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, text="ok")
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(200, json={"data": [{"id": "1"}, {"id": "2"}]})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.1"}]})
        return httpx.Response(404)

    with patch_transport(handler):
        result = await fn()

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["n8n_health"] == 200
    assert parsed["workflow_count"] == 2
    assert parsed["ollama_models"] == ["llama3.1"]


# ============================================================
# Activate / Deactivate / Publish
# ============================================================

@pytest.mark.asyncio
async def test_activate_n8n_workflow(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["activate_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        return httpx.Response(200, json={"active": True})

    with patch_transport(handler):
        result = await fn("wf1", active=True)

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["active"] is True


@pytest.mark.asyncio
async def test_activate_n8n_workflow_error(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["activate_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with patch_transport(handler):
        result = await fn("wf1")

    parsed = json.loads(result)
    assert parsed["ok"] is False


@pytest.mark.asyncio
async def test_deactivate_n8n_workflow(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["deactivate_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"active": False}
        return httpx.Response(200, json={"active": False})

    with patch_transport(handler):
        result = await fn("wf1")

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["active"] is False


@pytest.mark.asyncio
async def test_publish_n8n_workflow_success(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["publish_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"id": "wf1", "versionId": "v1"})
        return httpx.Response(200, json={"activeVersionId": "v1", "active": True})

    with patch_transport(handler):
        result = await fn("wf1")

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["versionId"] == "v1"


@pytest.mark.asyncio
async def test_publish_n8n_workflow_no_version(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["publish_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "wf1"})

    with patch_transport(handler):
        result = await fn("wf1")

    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["error"] == "versionId_not_found"


# ============================================================
# Create / Execute / Delete
# ============================================================

@pytest.mark.asyncio
async def test_create_n8n_workflow(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["create_n8n_workflow"]
    nodes = json.dumps([{"type": "noop"}])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["name"] == "my-wf"
        assert body["nodes"] == [{"type": "noop"}]
        return httpx.Response(200, json={"id": "new1"})

    with patch_transport(handler):
        result = await fn(name="my-wf", nodes_json=nodes)

    assert json.loads(result)["id"] == "new1"


@pytest.mark.asyncio
async def test_create_n8n_workflow_invalid_json(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["create_n8n_workflow"]

    with patch_transport(lambda r: httpx.Response(200)):
        result = await fn(name="x", nodes_json="not-json")

    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["error"] == "invalid_json"


@pytest.mark.asyncio
async def test_execute_workflow_now(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["execute_workflow_now"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/run")
        return httpx.Response(200, json={"executionId": "e1"})

    with patch_transport(handler):
        result = await fn("wf1")

    assert json.loads(result)["executionId"] == "e1"


@pytest.mark.asyncio
async def test_delete_n8n_workflow(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["delete_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(200)

    with patch_transport(handler):
        result = await fn("wf1")

    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["workflow_id"] == "wf1"


@pytest.mark.asyncio
async def test_delete_n8n_workflow_error(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["delete_n8n_workflow"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    with patch_transport(handler):
        result = await fn("missing")

    parsed = json.loads(result)
    assert parsed["ok"] is False


# ============================================================
# Credentials
# ============================================================

@pytest.mark.asyncio
async def test_list_n8n_credentials(captured_tools, patch_transport):
    _, captured = captured_tools
    fn = captured["list_n8n_credentials"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "1", "name": "cred"}]})

    with patch_transport(handler):
        result = await fn()

    assert json.loads(result)["data"][0]["name"] == "cred"


# ============================================================
# 起動時 env 検証
# ============================================================

def test_validate_env_missing(monkeypatch, capsys):
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    sys.path.insert(0, str(ROOT))
    if "server" in sys.modules:
        del sys.modules["server"]
    import server as fresh
    with pytest.raises(SystemExit) as exc:
        fresh._validate_env()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "N8N_API_KEY" in err


def test_validate_env_ok(monkeypatch):
    monkeypatch.setenv("N8N_API_KEY", "x")
    sys.path.insert(0, str(ROOT))
    if "server" in sys.modules:
        del sys.modules["server"]
    import server as fresh
    fresh._validate_env()
