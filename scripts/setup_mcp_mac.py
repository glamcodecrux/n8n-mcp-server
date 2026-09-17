#!/usr/bin/env python3
# filepath: /Users/seiji/Documents/github/n8n-mcp-server/scripts/setup_mcp_mac.py
"""mcp.json への N8N / Ollama 認証情報登録スクリプト(macOS)

1 ウィンドウ / 1 フォーム内で 4 項目を同時入力し、
すべて揃った場合のみ保存します(tkinter / CLI フォールバック)。

入力項目:
    - N8N_URL         (任意デフォルト: http://127.0.0.1:5678)
    - N8N_API_KEY     (デフォルトなし: 空のまま保存不可)
    - OLLAMA_HOST     (任意デフォルト: http://127.0.0.1:11434)
    - OLLAMA_MODEL    (デフォルトなし: 空のまま保存不可)

既定スキーマ:
    - トップレベル        : "mcp.servers"
    - command            : "python3"
    - args               : ["~/.n8n-mcp-server/server.py"]
    - 既存値は保持       : 既存 env の他キー/他 servers などは変更しない

保存先:
    - --out で任意パス指定可能(最優先)
    - ~/Library/Application Support/Code/User/mcp.json(存在する場合のみ)
    - ~/Library/Application Support/Code - Insiders/User/mcp.json(存在する場合のみ)
    - ~/Library/Application Support/Cursor/User/mcp.json(存在する場合のみ)
    - ~/Library/Application Support/VSCodium/User/mcp.json(存在する場合のみ)
    - ~/.vscode/mcp.json(ファイルの検索)
    - ~/Library/Application Support/Code/User/mcp.json(既定 / 新規作成)
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# tkinter (オプション)
try:
    import tkinter as tk
    _HAS_TK = True
except ImportError:
    _HAS_TK = False


DEFAULT_SERVER_KEY = "n8n-mcp-server"
ROOT_KEY = "mcp.servers"            # VS Code MCP 公式の親キー


@dataclass
class Values:
    n8n_url: str = ""
    n8n_api_key: str = ""
    ollama_host: str = ""
    ollama_model: str = ""

    def is_complete(self) -> bool:
        # 必須: N8N_URL / N8N_API_KEY / OLLAMA_HOST / OLLAMA_MODEL
        return all([self.n8n_url, self.n8n_api_key,
                    self.ollama_host, self.ollama_model])

    def as_dict(self) -> dict[str, str]:
        return {
            "N8N_URL":      self.n8n_url,
            "N8N_API_KEY":  self.n8n_api_key,
            "OLLAMA_HOST":  self.ollama_host,
            "OLLAMA_MODEL": self.ollama_model,
        }

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "Values":
        return cls(
            n8n_url      = env.get("N8N_URL",      ""),
            n8n_api_key  = env.get("N8N_API_KEY",  ""),
            ollama_host  = env.get("OLLAMA_HOST",  ""),
            ollama_model = env.get("OLLAMA_MODEL", ""),
        )


# =============================================================
# 事前条件
# =============================================================

def _assert_macos() -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            f"このスクリプトは macOS 専用です。現在の OS: {sys.platform}"
        )


# =============================================================
# 配置先の解決
# =============================================================

def resolve_target_path(explicit: str | None) -> Path:
    """優先順位:
        1. --out 明示指定
        2. ~/Library/Application Support 配下の VS Code 系 mcp.json(既存時のみ採用)
           (Code / Code - Insiders / Cursor / VSCodium)
        3. ~/.vscode/mcp.json(ファイルの検索)
        4. どれも無ければ ~/Library/Application Support/Code/User/mcp.json を新規作成
    """
    if explicit:
        return Path(explicit).expanduser().resolve()

    home = Path.home()
    for suffix in (
        "Library/Application Support/Code/User/mcp.json",
        "Library/Application Support/Code - Insiders/User/mcp.json",
        "Library/Application Support/Cursor/User/mcp.json",
        "Library/Application Support/VSCodium/User/mcp.json",
    ):
        candidate = home / suffix
        if candidate.exists():
            return candidate

    user_vscode = home / ".vscode" / "mcp.json"
    if user_vscode.exists():
        return user_vscode

    return home / "Library/Application Support/Code/User/mcp.json"


# =============================================================
# JSON 読み書き
# =============================================================

def _template() -> dict:
    return {
        ROOT_KEY: {
            DEFAULT_SERVER_KEY: {
                "command": "python3",
                "args":    ["~/.n8n-mcp-server/server.py"],
                "env":     {},
            }
        }
    }


def _root_servers_key(config: dict) -> str:
    """既存 JSON が 'mcp.servers' か 'servers' かを返す。"""
    if "mcp.servers" in config:
        return "mcp.servers"
    if "servers" in config:
        return "servers"
    return ROOT_KEY


def load_or_init(path: Path) -> tuple[dict, bool]:
    if not path.exists():
        return _template(), True
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("top level must be object")
        return data, False
    except (json.JSONDecodeError, ValueError) as e:
        print(f"⚠ {path} は無効な状態のため({e}). 新規テンプレートで上書きします。")
        return _template(), True


def get_existing_env(config: dict) -> dict[str, str]:
    key = _root_servers_key(config)
    server = (config.get(key) or {}).get(DEFAULT_SERVER_KEY, {})
    env = server.get("env", {}) or {}
    return {k: str(v) for k, v in env.items()}


def merge_env(config: dict, values: Values) -> None:
    """既存値を変更せず env をマージ(同名は上書き)。"""
    key = _root_servers_key(config)
    config.setdefault(key, {})
    server = config[key].setdefault(DEFAULT_SERVER_KEY, {})
    if "command" not in server:
        server["command"] = "python3"
        server["args"]    = ["~/.n8n-mcp-server/server.py"]
    server.setdefault("env", {}).update(values.as_dict())


def save(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# =============================================================
# 表示支援
# =============================================================

def _env_with_display() -> dict:
    return {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}


def _mask(label: str, value: str) -> str:
    """機微そうなキー名なら末尾 4 桁以外を伏字にする。"""
    if not value:
        return ""
    lname = label.upper()
    if any(t in lname for t in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
        if len(value) <= 4:
            return "****"
        return "****" + value[-4:]
    return value


# =============================================================
# 1 ウィンドウ 4 項目 GUI
# =============================================================

# 既定のデフォルト
DEFAULT_N8N_URL     = "http://127.0.0.1:5678"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
# N8N_API_KEY と OLLAMA_MODEL は「デフォルト無し」


def _ask_tk_form(title: str, defaults: Values) -> Values | None:
    if not _HAS_TK:
        return None
    result = Values()
    root = tk.Tk()
    root.title(title)
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    root.resizable(False, False)

    fields = [
        ("N8N_URL",      defaults.n8n_url,      False, DEFAULT_N8N_URL),
        ("N8N_API_KEY",  defaults.n8n_api_key,  True,  ""),
        ("OLLAMA_HOST",  defaults.ollama_host,  False, DEFAULT_OLLAMA_HOST),
        ("OLLAMA_MODEL", defaults.ollama_model, False, ""),
    ]
    vars_ = {}
    for i, (label, initial, hide, placeholder) in enumerate(fields):
        tk.Label(root, text=label).grid(row=i, column=0, sticky="e", padx=8, pady=6)
        v = tk.StringVar(value=initial or "")
        e = tk.Entry(root, textvariable=v, width=52, show="*" if hide else "")
        e.grid(row=i, column=1, padx=8, pady=6)
        if not initial and placeholder:
            v.set(placeholder)  # デフォルトを初期値に
        vars_[label] = v

    frame = tk.Frame(root)
    frame.grid(row=len(fields), column=0, columnspan=2, pady=(8, 8))
    submitted = {"ok": False}

    def on_ok() -> None:
        submitted["ok"] = True
        root.destroy()

    def on_cancel() -> None:
        submitted["ok"] = False
        root.destroy()

    tk.Button(frame, text="キャンセル", command=on_cancel, width=10).pack(
        side="right", padx=4
    )
    tk.Button(frame, text="保存", command=on_ok, width=10).pack(
        side="right", padx=4
    )
    root.bind("<Return>", lambda _e: on_ok())
    root.bind("<Escape>", lambda _e: on_cancel())
    for child in root.winfo_children():
        if isinstance(child, tk.Entry) and child.cget("show") == "*":
            child.focus_set()
            break

    root.mainloop()

    if not submitted["ok"]:
        return None
    result.n8n_url      = vars_["N8N_URL"].get().strip()
    result.n8n_api_key  = vars_["N8N_API_KEY"].get().strip()
    result.ollama_host  = vars_["OLLAMA_HOST"].get().strip()
    result.ollama_model = vars_["OLLAMA_MODEL"].get().strip()
    return result


def _ask_cli_form(title: str, defaults: Values) -> Values | None:
    def _ask(label: str, hide: bool, current: str, default_value: str) -> str:
        # 既存値 > 規定デフォルトの順で初期値を提示
        initial = current or default_value
        prompt = f"{label}" + (f" [{initial}]" if initial else "")
        if hide:
            v = getpass.getpass(f"{prompt}: ").strip()
        else:
            v = input(f"{prompt}: ").strip()
        if not v and initial:
            return initial
        return v

    try:
        url   = _ask("N8N_URL",     False, defaults.n8n_url,     DEFAULT_N8N_URL)
        if not url:    return None
        key   = _ask("N8N_API_KEY", True,  defaults.n8n_api_key, "")
        if not key:    return None
        host  = _ask("OLLAMA_HOST", False, defaults.ollama_host, DEFAULT_OLLAMA_HOST)
        if not host:   return None
        model = _ask("OLLAMA_MODEL",False, defaults.ollama_model,"")
        if not model:  return None
        return Values(url, key, host, model)
    except (EOFError, KeyboardInterrupt):
        return None


# =============================================================
# GUI 経路の優先順位
# =============================================================

def _candidates() -> list:
    """GUI 経路の優先順位(tkinter のみ)。"""
    return [_ask_tk_form]


def ask_form(title: str, defaults: Values, mode: str = "gui") -> Values | None:
    if mode == "cli":
        return _ask_cli_form(title, defaults)
    for fn in _candidates():
        try:
            v = fn(title, defaults)
        except Exception:
            v = None
        if v is not None:
            return v
    return _ask_cli_form(title, defaults)


# =============================================================
# サマリー出力
# =============================================================

def _print_summary(target: Path, config: dict, created: bool, values: Values) -> None:
    key = _root_servers_key(config)
    server = config[key].get(DEFAULT_SERVER_KEY, {})
    env = server.get("env", {})

    print(f"{'🆕 作成' if created else '✏️  更新'}: {target}")
    print(f"command = {server.get('command')}")
    print(f"args    = {server.get('args')}")
    print(f"スキーマ = {key}")
    print("env (主要 4 項目):")
    for k in ("N8N_URL", "N8N_API_KEY", "OLLAMA_HOST", "OLLAMA_MODEL"):
        v = str(env.get(k, ""))
        print(f"  {k:<13}= {_mask(k, v)}")
    extra = sorted(set(env) - {"N8N_URL", "N8N_API_KEY", "OLLAMA_HOST", "OLLAMA_MODEL"})
    if extra:
        print("env (既存の他キー):")
        for k in extra:
            print(f"  {k:<13}= {_mask(k, str(env[k]))}")


# =============================================================
# エントリポイント
# =============================================================

def main() -> int:
    _assert_macos()

    ap = argparse.ArgumentParser(
        description="mcp.json に N8N / Ollama 認証情報を登録"
    )
    ap.add_argument("--out", help="mcp.json の出力パス(省略時は自動検出)")
    ap.add_argument("--cli", action="store_true",
                    help="GUI ではなくコマンドラインで入力")
    args = ap.parse_args()

    target = resolve_target_path(args.out)
    config, created = load_or_init(target)

    # 既存 env を初期値に、欠片のデフォルトで補完
    defaults = Values.from_env(get_existing_env(config))
    if not defaults.n8n_url:
        defaults.n8n_url = DEFAULT_N8N_URL
    if not defaults.ollama_host:
        defaults.ollama_host = DEFAULT_OLLAMA_HOST
    # N8N_API_KEY / OLLAMA_MODEL は「デフォルトなし」→ 既存値があれば引き継ぎ

    print(f"デスクトップ環境: macOS (Aqua)")
    print(f"保存先: {target}")
    if not created:
        print("(既存ファイルに追記モード)")

    values = ask_form(
        "mcp.json N8N / Ollama 設定",
        defaults,
        mode="cli" if args.cli else "gui",
    )
    if values is None or not values.is_complete():
        print("キャンセルされました(入力が空か中止)。")
        return 1

    merge_env(config, values)
    save(target, config)

    _print_summary(target, config, created, values)
    return 0


if __name__ == "__main__":
    sys.exit(main())
