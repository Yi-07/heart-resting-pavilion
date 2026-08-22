# 环境搭建操作手册（开工第一步）

> **图例**：〔✓〕= 本机已实测确认（工具在 PATH、版本查实、解析通过）；〔□〕= 计划，未实测——**人执行跑通即真**；跑不通 → 按 CLAUDE.md 护栏**停下问人**，不静默改。
> **分工**：第 0-4 步 = **人做**；第 5-7 步 = **交给 Claude Code**（提示词整块复制即可，人不用读）。
> **依据**：本会话 grilling 定案 + `docs/architecture-research-v1.md` §7；查证记录与排障见文末附录 B。

## 进度总览（跑通一项勾一项）

- [ ] 0 前置检查
- [ ] 1 后端：骨架 + 依赖 + .env
- [ ] 2 Redis 容器
- [ ] 3 前端：Node 升级 + 骨架 + 依赖
- [ ] 4 预下载 RAG 模型
- [ ] 检查点 0：git 提交

---

## 人做 · 0-4

### 0. 前置检查 〔✓〕

确认机器上已就位的东西（2026-08-22 实测）：

| 项 | 版本/状态 |
|---|---|
| Python | 3.10.11（全套依赖的官方交汇版本，选型依据见附录 B） |
| uv | 0.11.31 |
| Node / npm | v22.15.0 / 10.9.2 —— 低于 create-vue 要求，第 3 步先升级 |
| git | 2.52，仓库已初始化 |
| Docker Desktop | 29.1.5（WSL2 后端） |
| ffmpeg | 8.0-full（`D:\Tools\ffmpeg-8.0-full_build`，含 libopus；ASR 转码用） |

```bash
ffmpeg -version
```

首行应显示 `ffmpeg version 8.0-full_build`。另自查：DeepSeek API key 已在手（第 1 步填入 .env）。

---

### 1. 后端：骨架 + 依赖 + .env 〔□〕

在仓库根目录创建后端项目、锁 Python 3.10、装依赖：

```bash
mkdir backend && cd backend
uv init --bare --python 3.10
uv python pin 3.10
uv venv --python 3.10
uv add fastapi "uvicorn[standard]" loguru openai python-dotenv langgraph redis rank-bm25 jieba sentence-transformers chromadb funasr "onnxruntime<1.24"
uv add --dev mypy pytest ruff
```

新建 `backend/.env`（真实 key；`.gitignore` 已含 `.env`，不会进 git）：

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-你的真实key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
REDIS_URL=redis://localhost:6379/0
# 可选：本地备选 provider（默认注释掉）
# OLLAMA_URL=http://localhost:11434/v1
# OLLAMA_MODEL=qwen3:8b
```

新建 `backend/.env.example`（占位模板，可提交 git）：同上结构，key 处写 `sk-xxx`。

**Smoke test（本步就绪判据）**：

```bash
uv run python -V
uv run python -c "import fastapi, langgraph, chromadb, funasr, redis, sentence_transformers, openai; print('deps ok')"
```

第一行必须显示 `Python 3.10.x`，第二行输出 `deps ok`。

**坏了怎么办**：`uv add` 解析失败/装不上 → 停下问人（onnxruntime 钉版原因见附录 B，勿自行摘掉）。

**说明**：
- 模型名 `deepseek-v4-flash` 是官方现行名（2026-08-22 核验），旧名 `deepseek-chat` 已废——详见附录 B；
- `langgraph` 不含 `langgraph-supervisor`（research-v1 Q2 已除名）；
- `funasr` 会连带装 torch，属正常；
- 依赖树已在本机按 cp310 干跑解析通过（166 包锁定），见附录 B；
- `uv run uvicorn app.main:app` 本步**不跑**——`app/` 要等 Claude 写码后才存在，首次真启动是 Claude 的事。

---

### 2. Redis 容器 〔□〕

先启动 Docker Desktop（开始菜单/桌面图标，等鲸鱼图标稳定），然后：

```bash
docker run -d --name mha-redis -p 6379:6379 --restart unless-stopped redis:7-alpine
docker exec mha-redis redis-cli ping
```

第二条应答 `PONG`。

**说明**：`--restart unless-stopped` 使容器随 Docker 自启——日常开机只需开 Docker Desktop，无需重跑 `docker run`；后端启动顺序在 Docker 之后。

---

### 3. 前端：Node 升级 + 骨架 + 依赖 〔□〕

**先升 Node**（create-vue 3.23.0 要求 `^22.18.0 || >=24.12.0`，本机 22.15 不满足；选 24 LTS 的理由见附录 B）：

```powershell
winget install OpenJS.NodeJS.LTS
```

装完**重开终端**验证：

```bash
node -v
```

应显示 `v24.19.0`。若仍显示 22.15 → 系统环境变量 PATH 里删除/后移 `D:\1.software\Node.js` 旧条目（旧 Node 是手动装的，非 winget 管理，所以用 `install` 不用 `upgrade`）。

**再建前端骨架**（仓库根目录）：

```bash
npm create vue@latest frontend -- --typescript --pinia --eslint --vitest
cd frontend
npm install
npm i -D @proj-airi/unplugin-live2d-sdk
```

PowerShell 里第一条要写成 `npm create vue@latest frontend '--' --typescript --pinia --eslint --vitest`（引住双横线）。

**Smoke test（本步就绪判据）**：

```bash
npm run dev
```

浏览器开 `http://localhost:5173` 见 Vue 欢迎页即真，Ctrl+C 收掉。

**坏了怎么办**：create-vue 不认 flag → 去掉 flag 进交互模式，勾 **TypeScript / Pinia / ESLint / Vitest**，Router 及其余一律不勾。

**说明**：
- `@proj-airi/unplugin-live2d-sdk` 包名已核实（npm 存在，latest 0.1.7，Vite 插件构建期拉 Live2D SDK，弃 CDN）；
- 不要再手动 `npm i -D vue-tsc eslint vitest`——create-vue 勾选后自带。

---

### 4. 预下载 RAG 模型 〔□〕

在 `backend/` 目录下载中文 embedding 与重排模型（共约 2.1GB，现在下好、开发阶段不等下载）：

```bash
uv run hf download BAAI/bge-small-zh-v1.5
uv run hf download BAAI/bge-reranker-v2-m3
```

**坏了怎么办**：下载失败/超时 → 切 HF 镜像（`hf` 命令来自 huggingface_hub，sentence-transformers 连带安装）：

```powershell
# PowerShell
$env:HF_ENDPOINT="https://hf-mirror.com"; uv run hf download BAAI/bge-small-zh-v1.5
$env:HF_ENDPOINT="https://hf-mirror.com"; uv run hf download BAAI/bge-reranker-v2-m3
```

```bash
# Git Bash
HF_ENDPOINT=https://hf-mirror.com uv run hf download BAAI/bge-small-zh-v1.5
HF_ENDPOINT=https://hf-mirror.com uv run hf download BAAI/bge-reranker-v2-m3
```

### 检查点 0

0-4 全部跑通后提交基线：

```bash
git add -A && git commit -m "chore: 环境就绪(骨架+依赖+Redis+RAG模型)"
```

（`.env` 已被 .gitignore 挡住，不会误提交。）

---

## 交给 Claude Code · 5-7（环境就绪后）

- **5. 配验证命令**（scripts 写进 package.json / pyproject）——Claude 做，人不碰文件；
- **6. 验证命令手动追加进 CLAUDE.md §4**；
- **7. 开发 + 验证自查 + 跑通验收**；RAG 种子语料（正念/焦虑/失眠 10~20 条）由 **Claude 起草 → 人审核定稿** → 存 `backend/data/rag_seeds.jsonl`（进 git）→ 灌 Chroma。

### 提示词（整块复制给 Claude Code，人不用读）

```
你在本项目（心理健康助手）仓库工作。环境已就绪：backend/ 骨架与依赖已装（uv + Python 3.10，
langgraph 无 supervisor，含 redis/rank-bm25/jieba/sentence-transformers/chromadb/funasr）；
backend/.env 已配（DeepSeek + REDIS_URL）；Redis 容器 mha-redis 已在跑（docker exec mha-redis
redis-cli ping 可验）；frontend/ 骨架已建（TS/Pinia/ESLint/Vitest + @proj-airi/unplugin-live2d-sdk）；
RAG 模型已预下载（bge-small-zh-v1.5 / bge-reranker-v2-m3）。执行以下任务，按顺序：

1. 先读 CLAUDE.md（含护栏：命令失败/依赖装不上/契约冲突/需改架构 → 停下问人，不静默改）、
   Architecture/ 下 architecture-spec-v3.1.md、ws-contract.md、frontend-plan.md、backend-plan.md，
   以及 docs/architecture-research-v1.md 的 §0 决策台账。

2. 配验证命令（scripts）：
   - 前端 frontend/package.json：type-check=vue-tsc --noEmit · lint=eslint · test=vitest
   - 后端 backend/pyproject.toml：加 [tool.pytest.ini_options] / [tool.mypy] / [tool.ruff]；
     验证用 uv run mypy app / uv run pytest / uv run ruff check

3. 验证命令手动追加进 CLAUDE.md §4（前端 type-check/lint/test；后端 mypy/pytest/ruff check）。

4. RAG 种子语料：起草正念/焦虑/失眠 10~20 条问答（科普口吻、非医疗定位）→ 停下等人审核定稿 →
   存 backend/data/rag_seeds.jsonl（进 git）→ 灌入 Chroma。

5. 按架构文档开发，构建顺序：危机闸门 → answer → collect(核心路由) → 黑板 → 记忆 → Live2D →
   语音（语音阶段按 docs/option.md 附录 A 在 model/voices/ 安装，CosyVoice 独立 venv）→ 工具。

6. 每条改动用验证命令自查（前端 cd frontend && npm run type-check && npm run lint；
   后端 cd backend && uv run mypy app && uv run pytest）。

7. 跑通验收用例（CLAUDE.md §8，判据可 grep）：
   - answer「什么是正念」→ 无 first_frame、无 draw 帧
   - collect「最近很焦虑睡不着」→ seq 单调递增；draw=粗稿+每轮增量+精稿；充分度≥0.7 停采；
     信念字段留白；精稿后=分析总结+心灵补给站邀请语（方案书=用户点击心灵补给站触发生成，不在回合内）
   - crisis「我不想活了」→ 日志 event=crisis_gate_hit(WARN)+热线横幅+无心情选择器

8. 每完成一个构建阶段：停下汇报 → 确认后 git commit 该阶段(如 "feat: 危机闸门+路由") → 再继续；
   任何命令失败/依赖装不上/契约冲突 → 停下问人，不静默改。
```

---

## 附录 A · 语音栈（语音阶段才执行，现在不要跑）

**第一件事**：`.gitignore` 追加一行 `model/`（GB 级权重与第三方源码不进 git）。

**TTS · CosyVoice 2**〔□〕（官方仓库已从 FunAudioLLM 迁至 `QwenAudio`）：

```bash
git clone https://github.com/QwenAudio/CosyVoice.git model/voices/CosyVoice
cd model/voices/CosyVoice
uv venv --python 3.10
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

- **必须独立 venv**：官方 requirements 钉版极狠（`numpy==1.26.4`、`fastapi==0.115.6`、torch cu121 extra-index 等），与应用 venv 混装必炸依赖地狱；
- requirements 含 GPU 向依赖（onnxruntime-gpu 等），Windows CPU 机器装不动 → **停下问人**，不静默换依赖；
- 模型权重（`CosyVoice2-0.5B`，ModelScope/HF）届时按官方 README 现行命令执行，先核对再跑。

**ASR · SenseVoice**〔□〕：引擎 `funasr` 第 1 步已装；权重（`iic/SenseVoiceSmall`）首次调用自动下载；音频链路：前端 webm/opus（base64）→ **ffmpeg 转码 wav 16k**（本机已验证）→ SenseVoice；转写即弃红线不变。

---

## 附录 B · 依据与排障（正文结论的查证记录，2026-08-22 当日实时核验）

<details>
<summary>B1 · Python 钉 3.10</summary>

全栈官方要求交汇于 3.10：CosyVoice 官方安装指引 `python=3.10`（仓库 `QwenAudio/CosyVoice`，2026-05-25 最后更新）；langgraph 1.2.11 / fastapi 0.141.1 `requires_python>=3.10`；funasr 1.4.2 宽松但生态实测 3.8–3.10；本机已有 3.10.11。详见 research-v1 §3。
</details>

<details>
<summary>B2 · onnxruntime 为什么钉 &lt;1.24</summary>

chromadb 硬依赖 `onnxruntime>=1.14.1`（无上限）→ uv 默认选最新 1.24.3，但 1.24 起**不再发 cp310 wheel**（实际 tag 仅 cp311–314），且其 `requires_python` 仍写 `>=3.10`（上游元数据未同步，解析能过、安装必炸——你已亲历）。1.23.2 是 cp310 末版，chromadb 兼容；全依赖树已在本机按 cp310 干跑解析通过（166 包锁定：onnxruntime==1.23.2、chromadb==1.5.9、torch==2.13.0、funasr==1.4.3、langgraph==1.2.11）。
</details>

<details>
<summary>B3 · DeepSeek 模型名已换代</summary>

官方现行名：`deepseek-v4-flash`（对话主力，当前指向 V4-Flash-0731）/ `deepseek-v4-pro`（推理，指向 V4-Pro-0813）；官方原话 "calling method remains unchanged — simply use deepseek-v4-flash or deepseek-v4-pro"。**旧名 `deepseek-chat` / `deepseek-reasoner` 已从官方文档全域消失（grep 零出现），勿再用**。另有 Anthropic 格式端点 `/anthropic`、实验视觉款 `deepseek-v4-flash-vision-exp`、Responses API——本项目不用。调用姿势（依赖树锁定 openai==3.3.1）：`OpenAI(api_key=..., base_url="https://api.deepseek.com")` → `chat.completions.create(model="deepseek-v4-flash", ...)`。⚠ `Architecture/backend-plan.md` §5 示例仍写旧名，属只读区待批准后同步。
</details>

<details>
<summary>B4 · Ollama 备选端点</summary>

OpenAI 兼容端点 `http://localhost:11434/v1`；`api_key="ollama"`（必填但被忽略）；`/v1/chat/completions` 支持流式 + JSON mode + tools；用前先 `ollama pull <模型>`；官方自标该兼容层 **experimental**。
</details>

<details>
<summary>B5 · Node 选 24 LTS（24.19.0）</summary>

create-vue 3.23.0 引擎要求 `^22.18.0 || >=24.12.0`，本机 22.15.0 不满足（EBADENGINE 警告）。官方时间表：v24 = Active LTS（2025-10 起，维护至 2028-04）；v22 已入维护期；v26 是 Current（2026-10 才转 LTS）不选。winget `OpenJS.NodeJS.LTS` 现版 24.19.0；flag 拼法已对本机 `create-vue --help`（3.23.0）逐条核实。
</details>

<details>
<summary>B6 · 其他包名/地址核实</summary>

`@proj-airi/unplugin-live2d-sdk`：npm registry 实时确认存在，latest 0.1.7（2026-04-14），Vite 插件。CosyVoice 仓库：`FunAudioLLM/CosyVoice` 已 301 迁至 `QwenAudio/CosyVoice`，clone 用新地址。
</details>

---

**边界**：本手册只列操作分工，不涉及实现代码；契约/数据流以架构文档为准。人做完 0-4 即环境就绪，把提示词粘给 Claude Code 开工。
