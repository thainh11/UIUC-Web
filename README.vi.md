# Cổng nghiên cứu UIUC và trợ lý LLM

Một trang cho nghiên cứu của University of Illinois Urbana-Champaign trong hai năm gần nhất, cùng một trợ lý trả lời từ chính dữ liệu đó. Trợ lý nhằm trả lời các câu như "What are the most recent UIUC papers on AI in war conflict?" và "Which faculty members work on Computer Vision in Healthcare?"

English: [README.md](README.md)

## Mục lục

- [Tính năng](#tính-năng)
- [Công nghệ](#công-nghệ)
- [Bắt đầu nhanh](#bắt-đầu-nhanh)
- [Cấu hình](#cấu-hình)
- [Kiến trúc](#kiến-trúc)
- [Nguồn dữ liệu và ghi công](#nguồn-dữ-liệu-và-ghi-công)
- [API](#api)
- [Kiểm thử](#kiểm-thử)
- [Xử lý sự cố](#xử-lý-sự-cố)

## Tính năng

- **Tổng quan:** số liệu toàn trường (bài báo, hồ sơ tác giả, lượt trích dẫn, tỷ lệ truy cập mở, giảng viên) trong hai năm gần nhất.
- **Sản lượng và chủ đề:** biểu đồ công bố theo tháng và các lĩnh vực dùng để lọc danh sách bài.
- **Bài báo:** danh sách tìm kiếm và sắp xếp được, có liên kết DOI và giảng viên đã nối.
- **Danh bạ giảng viên:** thẻ và ngăn hồ sơ kèm các bài đã nối.
- **Trợ lý:** chat chỉ trả lời từ database, trích dẫn bài báo và giảng viên, và stream câu trả lời.

Video demo (quay toàn bộ trang và trợ lý) được gửi kèm link trong form nộp bài. Các file video không nằm trong repo này.

## Công nghệ

| Lớp | Công nghệ |
|---|---|
| Nguồn dữ liệu | OpenAlex API, CSV giảng viên |
| Database | PostgreSQL 16 + pgvector |
| Backend | Python 3.12+, FastAPI, psycopg, `uv` |
| Embedding | Qwen3-Embedding-0.6B (server local) |
| Model chat | Qwen3.8-27B AWQ-INT4 trên vLLM, hoặc Gemini |
| Đóng gói | Docker Compose, nginx |
| Frontend | React, Vite, TypeScript, Tailwind, Recharts |

## Bắt đầu nhanh

Repo đóng gói toàn bộ hệ thống trong `docker-compose.yml`:

| Service | Chạy gì | Cổng host | Cần GPU |
|---|---|---|---|
| `db` | PostgreSQL 16 + pgvector | 5432 | không |
| `embedding` | vLLM phục vụ Qwen3-Embedding-0.6B | 8032 | có |
| `llm` | vLLM phục vụ Qwen3.8-27B AWQ-INT4 | 8116 | có |
| `api` | Backend FastAPI (`Dockerfile`) | 8100 | không |
| `web` | Bản build React do nginx phục vụ, proxy `/api` tới `api` (`frontend/Dockerfile`) | 5180 | không |
| `ingest` | Pipeline dữ liệu chạy một lần, bật khi cần (profile `ingest`) | | không |

Yêu cầu: Docker với Compose v2, [OpenAlex API key](https://openalex.org), và GPU NVIDIA cùng [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) cho `embedding` và `llm`. Hai model cần khoảng 22 GB đĩa và, với cấu hình mặc định, GPU có từ 40 GB bộ nhớ trở lên (server chat giữ 74% bộ nhớ GPU của nó và server embedding giữ 15%; model chat là model 27B lượng tử hóa 4 bit).

```sh
# 1. Cấu hình
cp .env.example .env        # điền OPENALEX_API_KEY; chỉ thêm GEMINI_API_KEY nếu dùng Gemini

# 2. Tải checkpoint vào ./models (xem "Model")
export HF_HOME=$PWD/models
hf download Qwen/Qwen3-Embedding-0.6B
hf download cyankiwi/Qwen3.8-27B-AWQ-INT4

# 3. Bật toàn bộ hệ thống
docker compose up -d --build

# 4. Nạp dữ liệu khi server embedding đã healthy (xem "Quy trình dữ liệu")
docker compose --profile ingest run --rm ingest
```

Mở http://localhost:5180. Tài liệu API ở http://localhost:8100/docs. Lần đầu bật `llm` mất vài phút để vLLM nạp model; theo dõi bằng `docker compose logs -f llm`.

Trong Compose, `api` và `ingest` gọi các service khác theo tên (`db`, `embedding`, `llm`), nên các URL `localhost` trong `.env` không ảnh hưởng ở đó. `db`, `embedding`, `llm` và `api` chỉ mở cổng trên `127.0.0.1`, nên bạn vẫn chạy được `eval` và các bước kiểm tra trên cùng máy mà không để lộ database hay server model ra ngoài; chỉ `web` nghe trên mọi interface. Muốn đặt hai model lên hai GPU khác nhau, đặt `EMBEDDING_GPU` và `LLM_GPU` (chỉ số GPU, mặc định cả hai là `0`) trong `.env`. Muốn dùng Gemini cho chat, đặt `LLM_PROVIDER=gemini` và `GEMINI_API_KEY`, rồi bật hệ thống không kèm model chat: `docker compose up -d --build db embedding api web`.

### Chạy không dùng Docker

Cần thêm Python 3.12+, [`uv`](https://docs.astral.sh/uv/), Node, và tự bật hai server vLLM (xem "Model").

```sh
cp .env.example .env
docker compose up -d db
uv sync
cd frontend && npm install && cd ..

uv run python -m ingestion.fetch_openalex
uv run python -m ingestion.load_db
uv run python -m ingestion.build_embeddings
uv run python -m ingestion.link_authors

uv run uvicorn backend.app.main:app --reload --port 8100      # terminal 1
cd frontend && npm run dev                                    # terminal 2
```

### Model

| Vai trò | Repo Hugging Face | Dung lượng | Tên phục vụ |
|---|---|---|---|
| Embedding | [`Qwen/Qwen3-Embedding-0.6B`](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | 1,2 GB | `Qwen3-Embedding-0.6B` |
| Chat | [`cyankiwi/Qwen3.8-27B-AWQ-INT4`](https://huggingface.co/cyankiwi/Qwen3.8-27B-AWQ-INT4) | ~21 GB | `qwen3.8-27b` |

Tải bằng [`hf` CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) (`pip install -U huggingface_hub`). Với `HF_HOME=$PWD/models`, file nằm trong `models/hub/`; Compose mount thư mục này ở chế độ chỉ đọc vào cả hai container vLLM. Các container chạy offline, nên model chưa tải sẽ lỗi ngay lúc khởi động thay vì tự tải. `models/` đã được gitignore. Model chat dùng giấy phép Apache-2.0; hãy xem giấy phép của từng repo trước khi phân phối lại.

`LLM_MODEL` và `EMBEDDING_MODEL` phải bằng `--served-model-name` của server tương ứng. Khi không dùng Docker, bật hai server như sau (các cờ lấy từ `docker-compose.yml`):

```sh
vllm serve Qwen/Qwen3-Embedding-0.6B --served-model-name Qwen3-Embedding-0.6B \
  --runner pooling --convert embed --dtype bfloat16 --max-model-len 8192 \
  --max-num-seqs 16 --max-num-batched-tokens 8192 --gpu-memory-utilization 0.15 --port 8032

vllm serve cyankiwi/Qwen3.8-27B-AWQ-INT4 --served-model-name qwen3.8-27b \
  --quantization compressed-tensors --dtype bfloat16 --max-model-len 32768 \
  --gpu-memory-utilization 0.74 --max-num-seqs 8 --max-num-batched-tokens 8192 \
  --enable-prefix-caching --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 --trust-remote-code --port 8116
```

### Quy trình dữ liệu

| Bước | Module | Thời gian | Ghi chú |
|---|---|---|---|
| Tải | `ingestion.fetch_openalex` | ~6 phút, ~$0,02 | Chạy tiếp được. Ghi vào `data/raw/openalex/works/` |
| Nạp | `ingestion.load_db` | ~35 giây | Xóa và nạp lại các bảng dữ liệu. `chat_traces` được giữ |
| Embedding | `ingestion.build_embeddings` | ~5 phút | Cần server embedding. Chạy tiếp được |
| Nối | `ingestion.link_authors` | ~1,5 phút | Cần embedding. Chạy lại được |

`docker compose --profile ingest run --rm ingest` chạy bốn bước theo thứ tự này và giữ file trong `./data`. Embedding và liên kết giảng viên phải dựng lại sau mỗi lần `load_db`. Cửa sổ mặc định là 24 tháng gần nhất; dùng `--from-date`, `--to-date` và `--max-works` để chỉnh.

## Cấu hình

Đặt trong `.env`.

| Biến | Mặc định | Dùng cho |
|---|---|---|
| `OPENALEX_API_KEY` | | `ingestion.fetch_openalex` và `eval.faculty_recall` |
| `DATABASE_URL` | `postgresql://uiuc:uiuc@localhost:5432/uiuc` | API, ingestion, eval |
| `EMBEDDING_URL` | `http://localhost:8032/v1` | Embedding và mọi lượt tìm |
| `EMBEDDING_MODEL` | `Qwen3-Embedding-0.6B` | Cùng server đó. Vector 1024 chiều |
| `LLM_PROVIDER` | `vllm` | `vllm` hoặc `gemini` |
| `LLM_URL` | `http://localhost:8116/v1` | Chat vLLM |
| `LLM_MODEL` | `qwen3.8-27b` | Chat vLLM. Phải bằng `--served-model-name` |
| `EMBEDDING_GPU` | `0` | Chỉ Docker: chỉ số GPU của `embedding` |
| `LLM_GPU` | `0` | Chỉ Docker: chỉ số GPU của `llm` |
| `GEMINI_API_KEY` | | Bắt buộc khi `LLM_PROVIDER=gemini` |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Chat Gemini |
| `GEMINI_REASONING` | `low` | Gửi thành `reasoning_effort` |
| `TRACE_PAYLOADS` | tắt | `1` thì lưu câu hỏi và message gửi model vào trace |
| `TRACE_RETENTION_DAYS` | `7` | Trace cũ hơn số ngày này bị xóa khi API khởi động |
| `LOG_LEVEL` | `INFO` | Logger `uiuc` |

## Kiến trúc

Ingestion chạy ngoại tuyến và ghi một database Postgres. Trang và trợ lý đều đọc database đó. Request từ trình duyệt không gọi OpenAlex.

```text
OpenAlex                         illinois-researchers.csv
   |                                      |
   v                                      v
fetch_openalex                      load_db đọc file này
   |
   v
load_db -----------------> PostgreSQL + pgvector
                           papers, authors, topics, faculty, keywords
                           full-text; cột embedding còn trống
   |
   v
build_embeddings --------> server embedding local (Qwen3-Embedding-0.6B)
   |
   v
link_authors ------------> faculty_id trên authorship khớp
   |
   +--> FastAPI /api/*  -->  trang React ở cổng 5180 (nginx trong Compose, Vite khi dev)
   |
   +--> POST /api/chat
          ba tool đọc cùng database
          embedding của câu hỏi vẫn ở server local
          câu trả lời từ vLLM local, hoặc từ Gemini khi LLM_PROVIDER=gemini
```

`docker compose up` bật mọi thành phần ở trên, trừ job `ingest` chạy một lần. Server embedding, và với provider mặc định là server chat vLLM, là các container riêng.

| Đường dẫn | Nội dung |
|---|---|
| `data/raw/illinois-researchers.csv` | Danh sách giảng viên: email, tên, ảnh, chức danh, keyword |
| `data/raw/openalex/` | JSON OpenAlex đã tải (gitignored) |
| `docs/` | `architecture.md`: nạp dữ liệu, quy tắc nối tác giả, chat, trace, đánh giá. `design.md`: thiết kế trang |
| `ingestion/` | Tải OpenAlex, đọc CSV, nạp DB, embedding, nối tác giả |
| `db/schema.sql` | Schema Postgres, gồm `chat_traces` |
| `backend/app/` | FastAPI: `routers/`, `services/`, `schemas.py` |
| `backend/agent/` | Tìm kiếm, ba tool, vòng chat, trace |
| `backend/tests/` | Test API và agent trên database thật; model được giả lập |
| `eval/` | Retrieval, nối tác giả, đối chiếu giảng viên, chat trên model đang chạy |
| `frontend/` | React + Vite + TypeScript, một trang |
| `Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | Image cho API và trang web, và toàn bộ hệ thống |
| `models/` | Checkpoint đã tải, mount vào container vLLM (gitignored) |

## Nguồn dữ liệu và ghi công

| Dữ liệu | Nguồn | Giấy phép |
|---|---|---|
| Bài báo, tác giả, chủ đề | API works của [OpenAlex](https://openalex.org), institution `I157725225` | CC0 |
| Danh sách giảng viên | `data/raw/illinois-researchers.csv`, đi kèm đề bài | Theo đề bài |
| Ảnh khuôn viên | "Main Quad - UIUC" của Daderot, [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Main_Quad_-_UIUC_-_DSC09116.JPG) | Public domain |
| Vị trí | Urbana–Champaign, Illinois; ghim bản đồ mở [OpenStreetMap](https://www.openstreetmap.org/?mlat=40.1070&mlon=-88.2272#map=14/40.1070/-88.2272) tại Main Quad (40.1070, -88.2272) | ODbL |

## API

| Endpoint | Trả về |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/overview` | Số bài, trích dẫn, tỷ lệ truy cập mở, khoảng ngày, số topic, giảng viên, giảng viên đã nối, số author id OpenAlex gắn UIUC |
| `GET /api/stats/publications-by-month` | `{month, count, year_only}` theo tháng. Tháng đầu và tháng cuối bị cụt. `year_only` đếm bài mang ngày 1 tháng 1, gần như luôn là bài chỉ biết năm xuất bản |
| `GET /api/stats/topics?level=domain\|field\|subfield\|topic&limit=` | Số bài theo từng mức topic |
| `GET /api/papers?query=&topic=&subfield=&field=&domain=&sort=date\|citations\|relevance&page=&page_size=` | Bài có phân trang. `query` là full-text tiếng Anh trên tiêu đề và abstract, tối đa 300 ký tự. `page` từ 1 đến 100.000. `page_size` từ 1 đến 50, mặc định 20 |
| `GET /api/papers/{id}` | Abstract, topic, keyword, và đủ danh sách tác giả, kèm faculty id nếu đã nối |
| `GET /api/faculty?query=&page=&page_size=` | Khớp tên hoặc keyword, tối đa 300 ký tự. Nhiều bài đã nối xếp trước. `page` từ 1 đến 100.000. `page_size` từ 1 đến 100, mặc định 24 |
| `GET /api/faculty/{id}` | Hồ sơ, keyword, và tối đa 100 bài đã nối, mới nhất trước |
| `POST /api/chat` | `{message, history, context?, known?}`. Server-sent events. Header `X-Trace-Id` |

`message` tối đa 2.000 ký tự. Mỗi lượt trong `history` tối đa 6.000 ký tự, và `history` tối đa 20 lượt. `known` tối đa 30 bản ghi.

Stream chat gửi các sự kiện `status`, `sources`, `delta`, `reset`, `done` và `error`. Model có ba tool: `search_papers`, `search_faculty` và `get_faculty_papers`, và trích kết quả dạng `[P1]`, `[F2]`.

## Kiểm thử

```sh
uv run pytest                          # backend/tests; cần database đã nạp, cache OpenAlex từ bước fetch, và server embedding; model chat được giả lập
uv run python -m eval.run              # nối tác giả và retrieval, so với eval/gold/baseline.json
uv run python -m eval.chat             # model đang chạy; so với eval/gold/chat_baseline.json
uv run python -m eval.faculty_recall   # 30 giảng viên, bài đã nối so với số work trên OpenAlex (cần OPENALEX_API_KEY)
```

Frontend:

```sh
cd frontend
npm run dev        # http://localhost:5180, proxy /api tới API_URL (mặc định http://localhost:8100)
npm run gen:api    # sinh lại src/api/schema.d.ts từ OpenAPI của API đang chạy
npm run build && npm run lint
npm test           # vitest, src/**/*.test.ts
npm run e2e        # Playwright + axe trên API thật; cần DB và uvicorn ở cổng 8100
                   # lần đầu: npx playwright install chromium
```

## Xử lý sự cố

| Triệu chứng | Nguyên nhân và cách xử lý |
|---|---|
| Tìm kiếm hoặc chat lỗi, hoặc `build_embeddings` báo lỗi | Không kết nối được server embedding. Kiểm tra `EMBEDDING_URL`. Tìm kiếm cần server này kể cả khi chat dùng Gemini |
| Chat không gọi tool hoặc báo lỗi tool | Bật vLLM với `--enable-auto-tool-choice` và một tool-call parser |
| Chat lỗi ngay với `LLM_PROVIDER=gemini` | Thiếu `GEMINI_API_KEY` |
| Giảng viên không có bài, hoặc tìm không ra kết quả | Chưa dựng lại embedding và liên kết sau `load_db`. Chạy `build_embeddings` rồi `link_authors` |
| `fetch_openalex` dừng ngay khi chạy | Tham số ngày khác với lần chạy đã lưu. Dùng lại đúng ngày, hoặc xóa `data/raw/openalex/works/` |
| Lỗi chat kết thúc bằng id 12 ký tự | Tra bằng `uv run python -m backend.agent.trace_cli show <id>` |
| Database từ chối kết nối | `docker compose up -d db`, và kiểm tra `DATABASE_URL` |
| `llm` hoặc `embedding` thoát ngay với lỗi không tìm thấy model | Checkpoint chưa có trong `./models`. Chạy các lệnh `hf download` với `HF_HOME=$PWD/models` |
| `llm` thoát vì hết bộ nhớ | Tiến trình khác đang giữ GPU. Đặt `LLM_GPU` và `EMBEDDING_GPU` sang GPU khác nhau, hoặc giải phóng card |
| `docker compose up` không bật được `llm` hoặc `embedding` (thiếu driver GPU) | Cài NVIDIA Container Toolkit, hoặc dùng Gemini và chỉ bật `db embedding api web` |
| Cổng host 5432, 8032, 8100, 8116 hoặc 5180 đã bị chiếm | Tắt tiến trình kia, hoặc đổi cổng host trong mục `ports` của `docker-compose.yml` (số đứng trước cổng container, ví dụ `127.0.0.1:15432:5432`) |
