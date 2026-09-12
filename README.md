# n8n MCP Server

n8n の REST API とローカルの Ollama を、MCP (Model Context Protocol) ツールとして
公開する Python サーバーです。VS Code などの MCP クライアントから
ワークフローの作成・実行・監視を自然言語で指示できます。

## 特徴

- n8n のワークフロー一覧取得、詳細取得、作成、削除、復元、有効化、公開、実行
- 実行履歴の一覧取得と詳細取得
- 登録済み Credentials の一覧取得
- Ollama 経由でのローカル / クラウドモデルへの問い合わせ
- n8n と Ollama の稼働状態をまとめて確認するヘルスチェック
- すべての操作は非同期 (httpx.AsyncClient) で実装
- Self-hosted n8n / Cloud n8n 両対応 `N8N_URL` / `N8N_API_KEY` の差し替えで切替

## 必要環境

- macOS または Linux
- Python 3.14.7 以上
- 起動済みの n8n (デフォルト `http://127.0.0.1:5678`)
- 起動済みの Ollama (デフォルト `http://127.0.0.1:11434`)

## 構築手順

### 1. リポジトリを取得

```
git clone <このリポジトリのURL> ~/.n8n-mcp-server
cd ~/.n8n-mcp-server
```

`start.sh` と `stop.sh` はホームディレクトリの `~/.n8n-mcp-server` 配下を
前提にしているため、必ずこのパスに配置してください。

### 2. 仮想環境を作成して有効化

```
python -m venv venv
source venv/bin/activate
```

### 3. 依存パッケージをインストール

```
pip install -r requirements.txt
```

`requirements.txt` には以下が含まれます。

- `mcp[cli]>=1.0.0` — MCP サーバーフレームワーク
- `httpx>=0.27.0` — 非同期 HTTP クライアント

### 4. n8n の API キーを発行

1. n8n の Web UI (`http://127.0.0.1:5678`) を開く
2. 左メニューの `Settings` → `API` を開く
3. `Create an API key` をクリックしてキーを生成
4. 生成されたキーを後述の環境変数 `N8N_API_KEY` に設定

### 5. 環境変数を設定

> n8n REST API へのリクエストには `X-N8N-API-KEY` ヘッダが自動で付与されます(`server.py` の `_n8n_headers()`)。

シェルの rc ファイル (`~/.zshrc` など) に追記します。

```
export N8N_HOST=127.0.0.1
export N8N_PORT=5678
export N8N_URL="http://${N8N_HOST}:${N8N_PORT}"
export N8N_USER_FOLDER="${HOME}/.n8n"
export MCP_SERVER_DIR="${HOME}/.n8n-mcp-server"
export N8N_BASIC_AUTH_ACTIVE=false
export N8N_USER_MANAGEMENT_DISABLED=true
```

`OLLAMA_MODEL` はクラウドモデル `minimax-m3:cloud` なども指定可能です。
反映するには `source ~/.zshrc` を実行してください。

## 起動と停止

### 起動

```
./start.sh
```

実行内容:

1. ホームの `~/.n8n-mcp-server` に移動
2. `venv` を有効化
3. `python server.py` をバックグラウンド (`nohup`) で起動
4. ログを `logs/mcp.log` に出力
5. プロセス ID を `tmp/mcp.pid` に保存

起動後、エラーがあった場合のログは `tail -f logs/mcp.log` で確認できます。

### 停止

```
./stop.sh
```

`tmp/mcp.pid` のプロセスに `kill` を送って停止し、PID ファイルを削除します。

## VS Code からの接続

`settings.json` の `mcp.servers` に以下を追加します。
> VS Code 1.101+ では `settings.json` ではなく `mcp.json` に
> `{"servers": {"n8n-mcp-server": {...}}}` を書く形式もサポートされています。
> どちらを使うかは VS Code のバージョンに従ってください。

```json
{
  "mcp.servers": {
    "n8n-mcp-server": {
      "command": "python",
      "args": ["~/.n8n-mcp-server/server.py"],
      "env": {
        "N8N_URL": "http://127.0.0.1:5678",
        "N8N_API_KEY": "APIキー",
        "OLLAMA_HOST": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "minimax-m3:cloud"
      }
    }
  }
}
```

VS Code を再起動すると、Copilot Chat からツールとして呼び出せるようになります。

## 提供されるツール

すべて `server.py` の `@mcp.tool()` デコレータで定義されています。
ツール名と引数は MCP クライアント (VS Code Copilot Chat など) に表示されます。

### システム状態確認

- **check_n8n_status**
  n8n のヘルスチェック(`GET /healthz`)、登録済みワークフロー数(`GET /api/v1/workflows`)、
  Ollama のモデル一覧(`GET /api/tags`)、API キーの設定有無をまとめて JSON で返します。
  レスポンス形式: `{"ok", "n8n_url", "n8n_health", "workflow_count", "ollama_host", "ollama_models", "api_key_configured"}`。
  引数なし。

- **ask_ollama(prompt, model="")**
  Ollama 経由でモデルに問い合わせます。
  `model` を空文字列にすると環境変数 `OLLAMA_MODEL`、それも未設定なら `minimax-m3:cloud` を使用します。
  エンドポイントは `POST {OLLAMA_HOST}/api/generate`、リクエストは `{"model", "prompt", "stream": false}`。
  `ollama list` で利用可能なモデル名を確認できます。

### n8n ワークフロー操作

- **list_n8n_workflows()**
  すべてのワークフローの一覧を JSON 文字列で返します。

- **get_n8n_workflow(workflow_id)**
  指定 ID のワークフロー詳細 (ノードや接続を含む) を取得します。

- **create_n8n_workflow(name, nodes_json, connections_json="{}")**
  新規ワークフローを作成します。
  `nodes_json` はノード配列の JSON 文字列、
  `connections_json` は接続オブジェクトの JSON 文字列(既定 `"{}"`)です。
  リクエストには `settings: {"executionOrder": "v1"}` が自動付与されます。
  `nodes_json` / `connections_json` が JSON として不正な場合は `{"ok": false, "error": "invalid_json"}` を返します。
  成功時は作成されたワークフローの JSON を返します。

- **delete_n8n_workflow(workflow_id)**
  指定 ID のワークフローを削除します。

- **activate_n8n_workflow(workflow_id, active=True)**
  `PATCH /api/v1/workflows/{id}` に `{"active": active}` を送ります。
  公開済みバージョンが必要です。

- **deactivate_n8n_workflow(workflow_id)**
  ワークフローを無効化します (`active=false`)。公開済みバージョンは不要です。

- **publish_n8n_workflow(workflow_id)**
  1. `GET /api/v1/workflows/{id}` で現在の `versionId` を取得
  2. `versionId` を `activeVersionId` に設定し、`PATCH /api/v1/workflows/{id}` に `{"activeVersionId": versionId, "active": true}` を送る
  `versionId` が無い場合は `{"ok": false, "error": "versionId_not_found"}` を返します。
  API 制限により失敗することがあるため、UI での公開を推奨します。

### 実行 (Execution)

- **execute_workflow_now(workflow_id)**
  `POST /api/v1/workflows/{id}/run` で実行します。タイムアウトは 60 秒です。

- **get_n8n_executions(workflow_id="", limit=20)**
  `GET /api/v1/executions?limit=...&workflowId=...` で実行履歴を取得します。
  `workflow_id` を空にすると `workflowId` パラメータを送らず全件対象になります。

- **get_n8n_execution(execution_id, include_data=True)**
  `GET /api/v1/executions/{id}?includeData=true|false` で特定の実行履歴の詳細を取得します。
  `include_data=False` の場合は `includeData` パラメータを送りません。

### Credentials

- **list_n8n_credentials()**
  `GET /api/v1/credentials` の生レスポンス(JSON 文字列)を返します。
  各エントリには `id` / `name` / `type` などが含まれます。

## 使用例

### 稼働状態を一括確認する

Copilot Chat で次のように呼び出します。

```
check_n8n_status を使って n8n と Ollama の状態を確認して
```

### ワークフローの一覧と詳細を見る

```
list_n8n_workflows を実行して、ID が 123 のものを get_n8n_workflow で詳細を見せて
```

### ワークフローを新規作成する

`nodes_json` には n8n のノード定義配列を JSON 文字列で渡します。
例として、毎日 9 時に HTTP リクエストを送るだけの最小ワークフロー:

```
create_n8n_workflow を次の内容で実行して:
name: "Daily Ping"
nodes_json: '[{
  "parameters": {
    "url": "https://example.com",
    "method": "GET"
  },
  "id": "abc123",
  "name": "HTTP Request",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 1,
  "position": [240, 300]
}, {
  "parameters": {
    "rule": {"hour": 9}
  },
  "id": "def456",
  "name": "Schedule",
  "type": "n8n-nodes-base.scheduleTrigger",
  "typeVersion": 1,
  "position": [460, 300]
}]'
connections_json: '{}'
```

成功すると作成されたワークフローの JSON が返るので、その ID を使って
実行や有効化を行います。

```
execute_workflow_now を ID 123 で実行
activate_n8n_workflow を ID 123 で active=true に
```

### 実行履歴を調査する

```
get_n8n_executions を workflow_id=123, limit=5 で取得して
失敗しているものがあれば get_n8n_execution で詳細を見せて
```

### Ollama に問い合わせる

```
ask_ollama を使って「Python の非同期処理とは?」を教えて
```

モデル名を明示する場合は次のとおりです。

```
ask_ollama(prompt="俳句を一つ作って", model="minimax-m3:cloud")
```

## 環境変数まとめ

- `N8N_URL` — n8n のベース URL。省略時は `http://127.0.0.1:5678`
- `N8N_API_KEY` — n8n の API キー。**未設定だと `server.py` は起動時に exit 1 で停止** します
- `OLLAMA_HOST` — Ollama のベース URL。空文字だと起動時に exit 1。省略時は `http://127.0.0.1:11434`
- `OLLAMA_MODEL` — `ask_ollama` で既定で使うモデル名。省略時は `minimax-m3:cloud`

### 起動時の環境変数検証

`server.py` は `__main__` ブロック先頭で `_validate_env()` を呼び、以下の環境変数のうち
**空文字のものをエラー**にします。両方欠落の場合は両方がカンマ区切りで表示されます。


```
[FATAL] 必須環境変数が未設定です: N8N_API_KEY, OLLAMA_HOST
       シェル(rc ファイル) または MCP 設定 (settings.json / mcp.json) を確認してください。
```

## トラブルシューティング

- **`model 'xxx' not found` と返る**
  `ollama list` を実行し、表示されたモデル名を `model` 引数に渡してください。
  未インストールなら `ollama pull <モデル名>` で取得します。

- **n8n API が 401 / 403 を返す**
  環境変数 `N8N_API_KEY` が正しいか、`n8n restart` 後にキーが無効化されていないか確認します。

- **接続エラーが返る(`{"ok": false, "error": "ConnectError", ...}`)**
  `ask_ollama` などで `httpx.ConnectError` が発生した場合、`server.py` の `_err()` が
  例外クラス名(`ConnectError` 等)を `error` フィールドに入れて返します。
  `N8N_URL` と `OLLAMA_HOST` のホスト名・ポートで各サービスが起動しているか確認します。
  `curl http://127.0.0.1:5678/healthz` や
  `curl http://127.0.0.1:11434/api/tags` で疎通確認ができます。

- **起動はしたが VS Code でツールが出てこない**
  `settings.json` の `mcp.servers` または `mcp.json` の `servers` 設定を見直して、VS Code を再読み込みします。
  サーバーが標準出力に JSON-RPC を流しているか `tail -f logs/mcp.log` で確認してください。

- **`[FATAL] 必須環境変数が未設定です` で起動に失敗する**
  必須環境変数 (`N8N_API_KEY`, `OLLAMA_HOST`) のいずれかが空のまま起動しています。
  検証ロジックとエラーメッセージのフォーマットは「起動時の環境変数検証」を、
  `settings.json` または `mcp.json` への設定例は「VS Code からの接続」を参照してください。


## ファイル構成

- `server.py` — MCP サーバーの本体。各ツールの実装
- `tests/` — pytest ユニットテスト (httpx.MockTransport で外部 HTTP を差し替え)
- `pytest.ini` — pytest 設定 (`asyncio_mode = auto`, `testpaths = tests`)
- `.gitignore` — `__pycache__/`, `.pytest_cache/`, `venv/`, `.DS_Store` 等を除外
- `requirements.txt` — 依存パッケージ一覧
- `start.sh` — バックグラウンド起動スクリプト
- `stop.sh` — 停止スクリプト
- `logs/` — 実行ログの出力先
- `tmp/mcp.pid` — 起動中のプロセス ID
- `venv/` — Python 仮想環境

## テスト

全 13 ツールの正常系・異常系と、起動時の環境変数検証をカバーした 24 件の
テストが用意されています。

```
pip install pytest pytest-asyncio
pytest tests/ -v
```

### MCP Tool Annotations

すべてのツールに OpenAI Directory 互換の以下のヒントを宣言しています。

| Hint | 意味 |
|---|---|
| `readOnlyHint` | ツールが状態を変更せずに「見るだけ」なのかを示す |
| `destructiveHint` | 元に戻せない破壊的変更の可能性を予告する |
| `idempotentHint` | 同じ引数で複数回呼んだ時の副作用の有無を示す |
| `openWorldHint` | インターネット経由の外部サービスとの通信の有無を示す |

### エラーハンドリング

すべてのツールは `try/except` でラップされ、構造化エラー
(`{"ok": false, "error": ..., "message": ...}`) を返します。
