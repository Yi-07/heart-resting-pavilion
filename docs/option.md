# 环境搭建操作手册（开工第一步）

> **图例**：〔✓〕= 本机已实测确认（工具在 PATH、版本查实、解析通过）；〔□〕= 计划，未实测——**人执行跑通即真**；跑不通 → 按 CLAUDE.md 护栏**停下问人**，不静默改。
> **分工**：第 0-4 步 + 语音栈（步骤 5，语音阶段）= **人做**；接缝定义与编码开发 = **交给 Claude Code**（文末两段提示词）。
> **依据**：依赖与资源以 `architecture/` 开发文档为标杆（frontend-plan / backend-plan / ws-contract / spec）；查证记录见 PROGRESS §六技术核查记录。

## 进度总览（跑通一项勾一项）

- [x] 0 前置检查
- [x] 1 后端：骨架 + 依赖 + .env
- [x] 2 Redis 容器
- [x] 3 前端：Node 升级 + 骨架 + 依赖
- [x] 4 预下载 RAG 模型（已迁 D 盘缓存）
- [ ] 5 语音栈（语音阶段才执行）
- [x] 检查点 0：git 提交

---

## 人做 · 0-4

### 0. 前置检查 〔✓〕

确认机器上已就位的东西：

| 项 | 版本/状态 |
|---|---|
| Python | 3.10.11（全套依赖的官方交汇版本，选型依据见 PROGRESS §六技术核查记录） |
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

### 1. 后端：骨架 + 依赖 + .env 〔✓〕（已完成并入库，commit 8bc57c6）

以下命令保留作复现/换机重建。在仓库根目录创建后端项目、锁 Python 3.10、装依赖：

```bash
mkdir backend && cd backend
uv init --bare --python 3.10
uv python pin 3.10
uv venv --python 3.10
uv add fastapi "uvicorn[standard]" loguru openai python-dotenv langgraph redis rank-bm25 jieba sentence-transformers chromadb funasr "onnxruntime<1.24"
uv add --dev mypy pytest ruff
```

配置文件以已入库的 `backend/.env.example` 为唯一模板：复制一份改名 `.env`，key 处填真实值（根 `.gitignore` 已含 `.env`，不会进 git）：

```bash
cp .env.example .env
```

**Smoke test（本步就绪判据）**：

```bash
uv run python -V
uv run python -c "import fastapi, langgraph, chromadb, funasr, redis, sentence_transformers, openai; print('deps ok')"
```

第一行必须显示 `Python 3.10.x`，第二行输出 `deps ok`。

**坏了怎么办**：`uv add` 解析失败/装不上 → 停下问人（onnxruntime 钉版原因见 PROGRESS §六技术核查记录，勿自行摘掉）。

**说明**：
- LangGraph 编排 = 确定性条件边 StateGraph；
- `funasr` 会连带装 torch，属正常；
- 全依赖树已在本机按 cp310 干跑解析通过，明细见 PROGRESS §六技术核查记录；
- `uv run uvicorn app.main:app` 本步**不跑**——`app/` 要等 Claude 写码后才存在，首次真启动是 Claude 的事。

---

### 2. Redis 容器 〔□〕

先启动 Docker Desktop（开始菜单/桌面图标，等鲸鱼图标稳定），然后：

```bash
docker run -d --name hrp-redis -p 6379:6379 --restart unless-stopped redis:7-alpine
docker exec hrp-redis redis-cli ping
```

第二条应答 `PONG`。

**说明**：`--restart unless-stopped` 使容器随 Docker 自启——日常开机只需开 Docker Desktop，无需重跑 `docker run`；后端启动顺序在 Docker 之后。

---

### 3. 前端：Node 升级 + 骨架 + 依赖 〔□〕

**先升 Node**（create-vue 要求 `^22.18.0 || >=24.12.0`，本机 22.15 不满足；选 24 LTS 的理由见 PROGRESS §六技术核查记录）：

```powershell
winget install OpenJS.NodeJS.LTS
```

装完**重开终端**验证：

```bash
node -v
```

应显示 v24 系列（≥24.12）。若仍显示 22.15 → 系统环境变量 PATH 里删除/后移 `D:\1.software\Node.js` 旧条目（旧 Node 是手动装的，非 winget 管理，所以用 `install` 不用 `upgrade`）。

**再建前端骨架**（仓库根目录）：

```bash
npm create vue@latest frontend -- --typescript --pinia --eslint --vitest
cd frontend
npm install
```

PowerShell 里第一条要写成 `npm create vue@latest frontend '--' --typescript --pinia --eslint --vitest`（引住双横线）。

**Smoke test（本步就绪判据）**：

```bash
npm run dev
```

浏览器开 `http://localhost:5173` 见 Vue 欢迎页即真，Ctrl+C 收掉。

**坏了怎么办**：create-vue 不认 flag → 去掉 flag 进交互模式，勾 **TypeScript / Pinia / ESLint / Vitest**，Router 及其余一律不勾。

**说明**：
- 脚手架勾选项自带 vue-tsc / eslint / vitest 及 `frontend/.gitignore`（含 node_modules/dist 等，防线依据见 PROGRESS §六技术核查记录），不要再手动安装或另写忽略规则；
- Live2D 相关依赖不在本步装——编码 agent 按 frontend-plan 在开发 l2d 模块时自行安装。

---

### 4. 预下载 RAG 模型 〔□〕

在 `backend/` 目录下载中文 embedding 与重排模型（共约 2.1GB，现在下好、开发阶段不等下载）。其中 bge-small-zh-v1.5 已在本机缓存，只缺重排模型：

```bash
uv run hf download BAAI/bge-reranker-v2-m3
```

**坏了怎么办**：下载失败/超时 → 切 HF 镜像（`hf` 命令来自 huggingface_hub，sentence-transformers 连带安装）：

```powershell
# PowerShell
$env:HF_ENDPOINT="https://hf-mirror.com"; uv run hf download BAAI/bge-reranker-v2-m3
```

```bash
# Git Bash
HF_ENDPOINT=https://hf-mirror.com uv run hf download BAAI/bge-reranker-v2-m3
```

**模型缓存挪 D 盘**〔✓〕（默认落 `C:\Users\<用户名>\.cache\huggingface\hub`，GB 级权重占 C 盘；改一次永久生效）：

1. 设**系统**环境变量（Win 搜索"编辑系统环境变量"→环境变量→用户变量新建）：`HF_HOME` = `D:\MetaverseStudy\hf_cache`
2. 迁移已有缓存：把 `C:\Users\<用户名>\.cache\huggingface\` 下的 `hub` 整个文件夹移动到 `D:\MetaverseStudy\hf_cache\`，得到 `D:\MetaverseStudy\hf_cache\hub\models--BAAI--...`（HF 在新路径按 `HF_HOME\hub` 找缓存，已下载内容直接识别，不用重下）
3. **重开终端**验证（在 `backend/` 下）：

```bash
uv run python -c "from huggingface_hub import constants; print(constants.HF_HUB_CACHE)"
```

输出以 `D:\MetaverseStudy\hf_cache` 开头即成。只想临时生效也可在命令前挂变量（PowerShell `$env:HF_HOME="D:\MetaverseStudy\hf_cache"` / Git Bash `HF_HOME=... `），但临时变量只影响当次命令，之后忘设又落回 C 盘——故推荐系统级。

### 检查点 0

0-4 全部跑通后提交基线。**提交前先自查忽略防线**：

```bash
git status --porcelain
```

输出不得包含 `node_modules` 与 `.venv`（防线依据见 PROGRESS §六技术核查记录）；出现了 → 停下问人，不要提交。确认干净后再：

```bash
git add -A && git commit -m "chore: 环境就绪(骨架+依赖+Redis+RAG模型)"
```

（`.env` 已被根 .gitignore 挡住，不会误提交。）

---

### 5. 语音栈（语音阶段才执行，人做）

**第一件事**：根 `.gitignore` 追加一行 `models/`（GB 级权重与第三方源码不进 git）。

**TTS · CosyVoice 2**〔□〕（官方仓库已从 FunAudioLLM 迁至 `QwenAudio`）：

```bash
git clone https://github.com/QwenAudio/CosyVoice.git models/voices/CosyVoice
cd models/voices/CosyVoice
uv venv --python 3.10
"setuptools<81" | Out-File -Encoding ascii build-constraints.txt
uv pip install --python .venv/Scripts/python.exe --index-strategy unsafe-best-match --build-constraints build-constraints.txt -r requirements.txt
```

- **必须独立 venv**：官方 requirements 钉版极狠（`numpy==1.26.4`、`fastapi==0.115.6`、torch cu121 extra-index 等），与应用 venv 混装必炸依赖地狱；
- `--index-strategy unsafe-best-match` 必带：requirements 挂 PyTorch/微软两个官方 extra-index，微软源里有 onnxruntime 包但缺 requirements 钉的 1.18.0，uv 默认"首个含该包的源定生死"会报 unsatisfiable；此 flag 允许跨源取最优版本（两源均官方，pip 默认行为即如此，不改变任何钉版）；
- `--build-constraints` 必带：`openai-whisper==20231117` 是源码包，构建时 import `pkg_resources`，而 setuptools≥81 已删该模块，uv 恒在隔离构建环境里装最新 setuptools → 构建必崩（[官方 issue #1938](https://github.com/QwenAudio/CosyVoice/issues/1938) 同错，社区定式=降 setuptools；实测 <81 即够）。此约束只作用于构建期临时环境，不动运行时任何钉版；
- requirements 含 GPU 向依赖（onnxruntime-gpu 等），Windows CPU 机器装不动 → **停下问人**，不静默换依赖；
- 模型权重（`CosyVoice2-0.5B`，ModelScope/HF）届时按官方 README 现行命令执行，先核对再跑。

**ASR · SenseVoice**〔□〕：引擎 `funasr` 第 1 步已装；权重（`iic/SenseVoiceSmall`）首次调用自动下载；音频链路：前端 webm/opus（base64）→ **ffmpeg 转码 wav 16k**（本机已验证）→ SenseVoice；转写即弃红线不变。

---

## 交给 Claude Code(环境就绪后)

会话一/二已完结(留档勿再开);编码期起每次开新窗口都用会话三提示词,整块粘贴:

### 会话一 · 接缝定义(已完结;定案已落 plans/schema)

```
你在心栖阁仓库工作,处理接缝定义专题:读 docs/research/seam-research-v1.md(7 项议程+深模块心智模型),
按其逐项定案;产出=定案回写两 plan 对应节(保持零不确定性,不写代码,范围照该文档声明);
样本回验须在队友全量灌库之前;全程存疑停下问人。
```

### 会话二 · 编码开发(已完结;步骤1~4 落库,后续走会话三接力)

```
你在心栖阁仓库工作,环境与设计均已就绪。按 CLAUDE.md 开发:构建顺序照 §8,每步完成跑对应验收
用例,停下汇报→人确认→commit→继续;护栏照 CLAUDE.md(命令失败/依赖装不上/契约冲突/需改架构
→停下问人,不静默改)。
```

### 会话三 · 跨会话接力(编码期窗口轮换;每次开新窗口都用这段)

上下文吃紧或一个步骤收尾后,旧窗口按看板 §3 收尾(kanban 勾选+handoff 重写+commit),再开新窗口粘贴:

```
你在心栖阁仓库工作,接续跨会话开发。开工顺序:CLAUDE.md → docs/task-kanbans/kanban-v1.md
→ docs/task-kanbans/handoff.md;按看板§0工作方式执行(高噪音步骤派子agent黑盒只收结论,
主会话只做决策/编码/commit),继续看板当前未完成步骤;每步完成跑 CLAUDE.md §8 对应用例,
停下汇报→人确认→commit(看板勾选+handoff 同步)→继续;护栏照 CLAUDE.md(命令失败/依赖
装不上/契约冲突/需改架构→停下问人,不静默改)。
```

### 编码期人介入环节

- RAG 种子语料(answer 步前):Claude 起草正念/焦虑/失眠 10~20 条问答(科普口吻,非医疗)→**人审核定稿**→存 `backend/data/rag_seeds.jsonl`(进 git)→灌 Chroma
- 语音阶段:按步骤 5 安装 CosyVoice(人做)

---

**边界**：本手册只列操作分工，不涉及实现代码；契约/数据流以架构文档为准。版本钉选与查证记录见 `architecture/ARCHITECTURE_PROGRESS.md` §六（技术核查记录）。人做完 0-4 即环境就绪，把提示词粘给 Claude Code 开工；语音栈（步骤 5）随语音阶段执行。
