#!/usr/bin/env python
"""n8n mcp server (n8n API + Ollama)"""
import os
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
import httpx

# === ログ設定: stderr には一切出力しない ===
# VS Code の MCP クライアントは stderr 出力を [warning] [server stderr] として
# 表示してしまうため、すべてのログをファイル (logs/mcp.log) へ送る。
_LOG_DIR = Path(os.getenv("MCP_LOG_DIR", str(Path(__file__).parent / "logs")))
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "mcp.log"

logger = logging.getLogger("n8n-mcp-server")
logger.setLevel(logging.INFO)
logger.propagate = False  # ルートロガー経由の stderr 伝播を遮断
if not logger.handlers:
    _fh = RotatingFileHandler(
        _LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    _fh.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_fh)

# 依存ライブラリ (mcp / uvicorn / anyio) の stderr 出力もファイルへ
for _n in ("mcp", "uvicorn", "anyio"):
    _lib = logging.getLogger(_n)
    _lib.setLevel(logging.ERROR)
    _lib.propagate = False
    if not _lib.handlers:
        _lib.addHandler(_fh)


"""Python3.14のSDKv2に対応"""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
mcp = MCPServer("n8n-mcp-server")


# === 設定 ===
__version__ = "1.0.0"

N8N_URL = os.getenv("N8N_URL", "http://127.0.0.1:5678")
N8N_API_KEY = os.getenv("N8N_API_KEY", "")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "minimax-m3:cloud")


def _validate_env() -> None:
    """必須環境変数の検証 (起動時に実行)"""
    missing = []
    if not N8N_API_KEY:
        missing.append("N8N_API_KEY")
    if not OLLAMA_HOST:
        missing.append("OLLAMA_HOST")
    if missing:
        logger.error(
            "[FATAL] 必須環境変数が未設定です: %s\n         MCP 設定 (settings.json / mcp.json) を確認してください。",
            ", ".join(missing),
        )
        sys.exit(1)


def _n8n_headers(json_body: bool = False) -> dict:
    """n8n API 用ヘッダ"""
    h = {"X-N8N-API-KEY": N8N_API_KEY} if N8N_API_KEY else {}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _err(tool: str, exc: Exception) -> str:
    """構造化エラーレスポンス"""
    return json.dumps(
        {
            "tool": tool,
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        },
        ensure_ascii=False,
    )


# === Ollama ===

@mcp.tool(
    annotations=ToolAnnotations(
        title="Ask Ollama",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def ask_ollama(prompt: str, model: str = "") -> str:
    """Ollama経由でローカルモデルに問い合わせる

    引数:
    - prompt: 問い合わせ内容
    - model: モデル名(省略時は OLLAMA_MODEL 環境変数または 'ローカルモデル')

    クラウドモデル 'minimax-m3:cloud' も指定可能。
    """
    target_model = model or OLLAMA_MODEL
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": target_model, "prompt": prompt, "stream": False},
            )
            r.raise_for_status()
            return r.json().get("response", "")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return json.dumps({"ok": False, "error": "model_not_found", "message": f"model '{target_model}' not found. `ollama list` で確認してください。"}, ensure_ascii=False)
        return json.dumps({"ok": False, "error": "http_status", "status_code": e.response.status_code, "message": e.text[:200]}, ensure_ascii=False)
    except Exception as e:
        return _err("ask_ollama", e)


# === n8n REST API ===

@mcp.tool(
    annotations=ToolAnnotations(
        title="List n8n Workflows",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_n8n_workflows() -> str:
    """n8n の全ワークフロー一覧を取得"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{N8N_URL}/api/v1/workflows",
                headers=_n8n_headers(),
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return _err("list_n8n_workflows", e)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get n8n Workflow",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_n8n_workflow(workflow_id: str) -> str:
    """特定のワークフロー詳細を取得"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{N8N_URL}/api/v1/workflows/{workflow_id}",
                headers=_n8n_headers(),
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return _err("get_n8n_workflow", e)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get n8n Executions",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_n8n_executions(workflow_id: str = "", limit: int = 20) -> str:
    """実行履歴を取得(workflow_id 空なら全件)"""
    try:
        url = f"{N8N_URL}/api/v1/executions"
        params = {"limit": limit}
        if workflow_id:
            params["workflowId"] = workflow_id
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                url,
                params=params,
                headers=_n8n_headers(),
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return _err("get_n8n_executions", e)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Activate n8n Workflow",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def activate_n8n_workflow(workflow_id: str, active: bool = True) -> str:
    """ワークフローの有効/無効を切り替え(公開済みバージョンが必要)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.patch(
                f"{N8N_URL}/api/v1/workflows/{workflow_id}",
                headers=_n8n_headers(json_body=True),
                json={"active": active},
            )
            r.raise_for_status()
            return json.dumps({"ok": True, "workflow_id": workflow_id, "active": active}, ensure_ascii=False)
    except Exception as e:
        return _err("activate_n8n_workflow", e)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Deactivate n8n Workflow",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def deactivate_n8n_workflow(workflow_id: str) -> str:
    """ワークフローを無効化"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.patch(
                f"{N8N_URL}/api/v1/workflows/{workflow_id}",
                headers=_n8n_headers(json_body=True),
                json={"active": False},
            )
            r.raise_for_status()
            return json.dumps({"ok": True, "workflow_id": workflow_id, "active": False}, ensure_ascii=False)
    except Exception as e:
        return _err("deactivate_n8n_workflow", e)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Publish n8n Workflow",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
async def publish_n8n_workflow(workflow_id: str) -> str:
    """ワークフローを公開+有効化(API 制限あり、UI 使用推奨)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{N8N_URL}/api/v1/workflows/{workflow_id}",
                headers=_n8n_headers(),
            )
            r.raise_for_status()
            wf = r.json()
            version_id = wf.get("versionId")
            if not version_id:
                return json.dumps({"ok": False, "error": "versionId_not_found", "workflow_id": workflow_id}, ensure_ascii=False)
            r2 = await client.patch(
                f"{N8N_URL}/api/v1/workflows/{workflow_id}",
                headers=_n8n_headers(json_body=True),
                json={"activeVersionId": version_id, "active": True},
            )
            r2.raise_for_status()
            return json.dumps({"ok": True, "workflow_id": workflow_id, "versionId": version_id, "status": r2.status_code}, ensure_ascii=False)
    except Exception as e:
        return _err("publish_n8n_workflow", e)


# === システム状態確認 ===

@mcp.tool(
    annotations=ToolAnnotations(
        title="Check n8n Status",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def check_n8n_status() -> str:
    """n8n と Ollama の稼働状態を確認"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # n8n ヘルスチェック
            try:
                health = await client.get(f"{N8N_URL}/healthz")
                health_status = health.status_code
            except Exception as e:
                health_status = f"error: {e}"

            # ワークフロー数
            try:
                wf = await client.get(
                    f"{N8N_URL}/api/v1/workflows",
                    headers=_n8n_headers(),
                )
                workflow_count = len(wf.json().get("data", [])) if wf.status_code < 300 else "unknown"
            except Exception:
                workflow_count = "unknown"

            # Ollama モデル一覧
            try:
                ollama = await client.get(f"{OLLAMA_HOST}/api/tags")
                if ollama.status_code == 200:
                    models_data = ollama.json().get("models", [])
                    models = [m.get("name") for m in models_data]
                else:
                    models = []
            except Exception:
                models = "unknown"

            return json.dumps({
                "ok": True,
                "n8n_url": N8N_URL,
                "n8n_health": health_status,
                "workflow_count": workflow_count,
                "ollama_host": OLLAMA_HOST,
                "ollama_models": models,
                "api_key_configured": bool(N8N_API_KEY),
            }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err("check_n8n_status", e)


# === ワークフロー作成 / 手動実行 ===

@mcp.tool(
    annotations=ToolAnnotations(
        title="Create n8n Workflow",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def create_n8n_workflow(name: str, nodes_json: str, connections_json: str = "{}") -> str:
    """ワークフローを作成(外部サービスの可能性あり)

    引数:
    - name: ワークフロー名
    - nodes_json: ノード配列(JSON 文字列)
    - connections_json: 接続(JSON 文字列)
    """
    try:
        payload = {
            "name": name,
            "nodes": json.loads(nodes_json),
            "connections": json.loads(connections_json),
            "settings": {"executionOrder": "v1"},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{N8N_URL}/api/v1/workflows",
                headers=_n8n_headers(json_body=True),
                json=payload,
            )
            r.raise_for_status()
            return r.text
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": "invalid_json", "message": str(e)}, ensure_ascii=False)
    except Exception as e:
        return _err("create_n8n_workflow", e)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Execute n8n Workflow Now",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def execute_workflow_now(workflow_id: str) -> str:
    """ワークフローを実行(外部サービスの可能性あり)"""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{N8N_URL}/api/v1/workflows/{workflow_id}/run",
                headers=_n8n_headers(json_body=True),
                json={},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return _err("execute_workflow_now", e)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Get n8n Execution",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def get_n8n_execution(execution_id: str, include_data: bool = True) -> str:
    """特定の実行履歴詳細を取得"""
    try:
        params = {"includeData": "true"} if include_data else {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{N8N_URL}/api/v1/executions/{execution_id}",
                params=params,
                headers=_n8n_headers(),
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return _err("get_n8n_execution", e)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Delete n8n Workflow",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def delete_n8n_workflow(workflow_id: str) -> str:
    """ワークフローを削除(外部サービスの可能性あり)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(
                f"{N8N_URL}/api/v1/workflows/{workflow_id}",
                headers=_n8n_headers(),
            )
            r.raise_for_status()
            return json.dumps({"ok": True, "workflow_id": workflow_id, "status": r.status_code}, ensure_ascii=False)
    except Exception as e:
        return _err("delete_n8n_workflow", e)


# === Credentials ===

@mcp.tool(
    annotations=ToolAnnotations(
        title="List n8n Credentials",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_n8n_credentials() -> str:
    """登録済み Credentials 一覧を取得(id, name, type)"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{N8N_URL}/api/v1/credentials",
                headers=_n8n_headers(),
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        return _err("list_n8n_credentials", e)


if __name__ == "__main__":
    _validate_env()
    mcp.run()
