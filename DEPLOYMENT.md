# Deployment

本文件只處理 Web Application 部署。研究 pipeline、prompt、模型、OCR/ASR、prediction 格式、Ground Truth、Human–AI comparison 與 vote 行為保持原樣。

以下「專案根目錄」指同時包含 `package.json`、`requirements.txt`、`backend/` 的目錄；ZIP 解壓後可能位於另一個同名資料夾內。

## Development

使用既有可運作的 AI Python 環境。新環境須安裝 Python、Node.js（符合現有 Vite 版本的 engines）、FFmpeg/ffprobe、相容的 CUDA/PyTorch/bitsandbytes、PaddlePaddle/PaddleOCR，以及既有模型與 cache；不要為部署修改升級研究依賴。完整依賴仍為 `requirements.txt`，WSGI server 另行安裝。

在專案根目錄執行（PowerShell）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm install
Copy-Item .env.example .env
```

已有環境或 `.env` 時沿用，勿覆蓋。編輯根目錄 `.env`，填入真實 `GEMINI_API_KEY`。不要提交 `.env`。

| 變數 | 預設與用途 |
| --- | --- |
| `VITE_API_BASE_URL` | 空白或未設定：dev 為 `http://127.0.0.1:5000`，production build 為 `/api`。可填完整 `https://domain.com/api`。結尾 `/` 會移除。 |
| `APP_ENV` | `development`；部署時設 `production`。不控制 Vite build mode。 |
| `FLASK_HOST` | `127.0.0.1`；LAN/container 可設 `0.0.0.0`。只控制 `python backend/app.py`。 |
| `FLASK_PORT` | `5000`；只控制 `python backend/app.py`。 |
| `FLASK_DEBUG` | `0`；只有 development 可設 `1`。LAN／production 保持 `0`。 |
| `CORS_ALLOWED_ORIGINS` | 未設定時，development 允許 `localhost` 與 `127.0.0.1` 的 5173、4173 port；production 不允許跨 origin。明確空白表示停用 CORS。多個 origin 用逗號分隔，須包含 scheme 和 port（如有），不要包含 `/api` 或 wildcard。 |
| `GEMINI_API_KEY` | 既有 Retrieve 使用的後端 secret，必須自行提供。 |

Flask 明確讀取**專案根目錄 `.env`**，不依賴 terminal working directory，已設定的 process environment 優先。Flask 不讀 `.env.production`。既有 Retrieve 的 dotenv 行為保持原樣；若曾使用 `backend/.env`，請確認沒有與根目錄／process environment 衝突的 key。

Vite 讀取根目錄 `.env`、`.env.local` 與 mode 對應檔案（例如 `.env.production`）。`VITE_` 值會公開且在 **build 時固定**；不要把 key、token 或 credential 放進 `VITE_` 變數。修改後須重啟 dev server 或重新 build。範本故意不把 localhost 填入 `VITE_API_BASE_URL`，避免 `.env` 使 production bundle 指回 localhost。

後端 terminal（已啟用 AI 環境，根目錄）：

```powershell
python backend/app.py
```

原本的 `cd backend` 後 `python app.py` 也保留。預設後端為 `http://127.0.0.1:5000`。

另一個 terminal（根目錄）：

```powershell
npm run dev -- --port 5173 --strictPort
```

開啟 `http://localhost:5173`。固定 port 避免 Vite 自動改 port 後與 CORS 設定不符；自訂 port 時同步更新 allowed origins。

## LAN Testing

假設伺服器的 LAN IP 為 `192.168.1.20`，以下範例請換成實際 IP。前後端 terminal 都在根目錄執行。

後端（已啟用 AI 環境）：

```powershell
$env:FLASK_HOST = "0.0.0.0"
$env:FLASK_PORT = "5000"
$env:FLASK_DEBUG = "0"
$env:CORS_ALLOWED_ORIGINS = "http://192.168.1.20:5173,http://localhost:5173,http://127.0.0.1:5173"
python backend/app.py
```

前端（另一個 terminal）：

```powershell
$env:VITE_API_BASE_URL = "http://192.168.1.20:5000"
npm run dev -- --host 0.0.0.0 --port 5173 --strictPort
```

同一區網的電腦開啟 `http://192.168.1.20:5173`，API 可由 `http://192.168.1.20:5000/status` 檢查。伺服器防火牆須允許 LAN 的 TCP 5173／5000。`0.0.0.0` 是監聽位址；瀏覽器使用伺服器 IP。遠端瀏覽器的 localhost 是遠端電腦本身。

測試結束後關閉上述 terminal，避免殘留 process environment 影響後續 production build。這是 LAN 測試，不以 Vite dev server 或 Flask dev server 提供公開 production 服務。

## Production Deployment

```text
Internet → HTTPS → Reverse Proxy
                    ├─ /          → Vue static frontend (dist/)
                    └─ /api/...   → Flask WSGI backend → Existing AI Pipeline
```

瀏覽器載入 static frontend 後呼叫 `/api/...`。不綁定 cloud provider，也不要求安裝 Nginx。

### Frontend build

在乾淨的 build terminal、專案根目錄執行：

```powershell
$env:VITE_API_BASE_URL = "/api"
npm install
npm run build
```

也可設 `https://domain.com/api`，或在 `.env.production` 設定（留意 process environment 優先）。部署產物為 `dist/`；只將此目錄交給 static server，不公開 repository、`.env`、data、uploads 或模型檔。更換 API 網址需重新 build，不能只改 static server 的 runtime environment。

### WSGI backend

正確入口是 **`app:app`**，module 位於 `backend/app.py`。以 `--chdir` 指向 **backend 的絕對路徑**即可保留目前 imports，不需修改 pipeline，也不需新增 app factory。

Linux／WSL 範例（Bash；使用已安裝完整 AI 依賴的 Python environment）：

```bash
python -m pip install gunicorn
export APP_ENV=production
export FLASK_DEBUG=0
export CORS_ALLOWED_ORIGINS=https://domain.com
# GEMINI_API_KEY 由 process environment 或根目錄的私有 .env 提供
export WSGI_HOST=127.0.0.1
export WSGI_PORT=5000
gunicorn --chdir /absolute/path/to/project/backend --workers 1 --worker-class gthread --threads 4 --bind "${WSGI_HOST}:${WSGI_PORT}" app:app
```

`WSGI_HOST`／`WSGI_PORT` 在這個 shell 指令控制 WSGI bind；`FLASK_HOST`／`FLASK_PORT` 不會自動控制 Gunicorn。跨 container 網路可依實際拓樸設定 `WSGI_HOST=0.0.0.0`，後端 port 只供 proxy 所在網路連入。同 origin `/api` 部署可將 `CORS_ALLOWED_ORIGINS` 設為空白；分開 frontend origin 時須列出 frontend origin，並使用 HTTPS API URL。

Gunicorn 不支援原生 Windows；Windows development 繼續使用上面的 Flask 指令。原生 Windows production 可另裝 Waitress，在 `backend/` 以 `waitress-serve --listen=127.0.0.1:5000 app:app` 執行，同樣設定 `APP_ENV=production`／CORS，並只啟動一個 instance。WSGI server 不加入通用研究依賴檔。

**目前必須維持單一 worker、單一 instance。** 狀態存在 process 記憶體，輸出檔案全域共用，vote 使用 process 內的 lock。多 workers／replicas 會造成 polling 狀態不一致與檔案衝突。單 worker 也不等於多人隔離：多人同時上傳仍可能覆蓋目前分析。保持受控、一次一個分析工作；不要在分析進行中重啟、reload 或回收 worker。背景 ThreadPoolExecutor 與原有上傳行為未改變。

### Reverse proxy contract

| 公開 request | 傳給 Flask 的 request |
| --- | --- |
| `POST /api/upload` | `POST /upload` |
| `GET /api/status` | `GET /status` |
| `GET /api/result` | `GET /result` |
| `GET /api/student_result` | `GET /student_result` |
| `POST /api/vote` | `POST /vote` |
| `GET /api/vote/statistics?video_id=...` | `GET /vote/statistics?video_id=...` |

Proxy 必須**移除 `/api` 前綴**並保留 query string、method、multipart body 與 Content-Type；勿把 API error／404 改成 frontend index.html。Flask routes 不加 prefix。TLS 由 proxy 終止，靜態檔由 static server 提供。依預期影片大小設定 proxy upload body limit、buffer storage 與上傳 timeout；分析仍在背景執行並以 polling 取得進度，不需讓 upload request 等待整個 AI pipeline。

### Paths, secrets and AI prerequisites

| 資料 | 既有位置（相對專案根目錄） |
| --- | --- |
| Upload | `backend/uploads/` |
| Retrieve／student results | `backend/output/` |
| Preprocessing | `backend/preprocess_output/` |
| Votes／atomic temporary vote file | `data/votes.json`／`data/votes.json.tmp` |
| Ground Truth | `answer.jsonl` |
| LoRA / model config | `backend/model/best_model/`、`backend/config/student_bot_config.yaml` |

Web 的 upload/result/vote/answer 已由 `__file__` 推導絕對位置；既有 `pipeline.run_command()` 固定 `cwd=backend`，所以研究子程序的相對路徑不受啟動 terminal 影響。CA 暫存 bundle 使用系統 tempfile 並由既有 finally 清除。**沒有修改研究 scripts 的相對路徑**；如需手動執行研究腳本，仍需先進入 `backend/`。

部署帳號需要 runtime 目錄與系統 temp 的寫入權限，以及 answer/model/config 的讀取權限；需保留 votes 與需要保存的 runtime 資料。Container 可 mount 這些既有目錄，不改資料格式或引入新路徑設定。Pipeline 原本會清除／覆寫分析輸出，請保持原本操作假設。

本次 repository secret 搜尋未發現硬編碼真實 key。Retrieve 已使用 `GEMINI_API_KEY`，呼叫方式不變。它目前會在日誌列出 key 的末六碼，依「不修改研究 pipeline」要求保留，部署時不要公開研究日誌。現有 pipeline 強制 Hugging Face offline：必須事先備妥 Whisper、Gemma 基礎模型與相關 cache、LoRA 檔案、OCR 模型、FFmpeg 及相容 GPU 環境；只有 `app` import 成功不代表模型環境已就緒。

### Verification

```powershell
npm install
npm run build
python -m unittest discover -s tests -v
```

測試從非專案 CWD 載入 Flask，檢查六個 endpoints、upload 排程、result／confidence 相容欄位、投票讀寫、CORS 與 host/port/debug；上傳只使用暫存 fixture 並 mock executor.submit，不會呼叫 Gemini 或 GPU。投票與結果 fixture 使用獨立暫存目錄。

在完整 AI 環境部署前，仍須以已知影片實際驗收：upload/preview → Human Prediction → Vote Statistics → pipeline polling → evidence/external sources → AI prediction/confidence/reason → Ground Truth／Human–AI comparison。再透過正式 proxy 測試上傳與輪詢。

本次驗證（2026-09-10）：`npm install`、預設 `/api` production build、自訂 `https://domain.com/api/` build、7 項 Web 測試，以及非專案 CWD 的真實 `app:app` import 均通過。兩種 bundle 都不含固定 localhost API URL。原有 `package-lock.json` 與研究檔案 SHA-256 未變。測試使用暫存 Flask 依賴；未執行完整 GPU／Gemini 推論或實際公開 HTTPS 部署。

同次線上 `npm audit` 回報 6 項既有依賴漏洞：1 moderate（baseline-browser-mapping）、5 high（brace-expansion、browserslist、nanoid、postcss、vite）。此次未執行 `npm audit fix` 或升級依賴；公開上線前應另行評估修補與相容性驗證。

### Next phase

此次只完成 deployment readiness，不實作 authentication、帳號、queue、Redis/Celery/RQ、多使用者 job isolation、database migration 或 cloud infrastructure。現有共用狀態不適合無限制多人公開服務；多人併發、資源配額／rate limit、上傳容量／保留政策與完整 production 運維規劃留待下一階段。

參考官方說明：[Vite environment variables](https://vite.dev/guide/env-and-mode)、[Flask production deployment](https://flask.palletsprojects.com/en/stable/deploying/)、[Gunicorn WSGI entry point](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/)。
