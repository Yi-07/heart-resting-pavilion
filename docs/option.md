# 环境搭建操作手册（开工第一步）

> **分工**：**第 0-4 步 = 人做**（配真实环境，命令跑通后才算真）；**第 5-7 步 = 交给 Claude Code**（配 scripts + 开发）。
> **命令保真**：以下命令**未实测**——是计划不是已验证结果。人执行跑通即真；跑不通 → 按 CLAUDE.md 护栏**停下问人**，不静默改。

---

## 人做 · 0-4（配环境，让命令真实存在）

### 0. 前置检查
- Python 3.10+（uv 需要）· Node 18+
- LLM 真 provider：DeepSeek key 或本地 Ollama（已装）
- 磁盘空间：SenseVoice / CosyVoice 模型（GB 级）
- `git init`（若尚未初始化仓库）

### 1. 建后端环境（uv，以下在 backend/ 目录下执行）
```bash
uv sync                              # 装 pyproject 依赖
uv add funasr cosyvoice mypy pytest ruff   # 语音引擎 + 验证工具
uv run uvicorn app.main:app --port 8000    # 启动
```

### 2. 建前端环境（Vue3 + Vite + TS，frontend/）
```bash
npm install
npm i -D vue-tsc eslint vitest        # 验证工具链
npm i @proj-airi/unplugin-live2d-sdk  # Live2D 打包（弃 CDN）
npm run dev                           # 启动
```

### 3. 下载语音模型（本地真 provider）
- ASR：SenseVoice（funasr，ModelScope/HF 权重）· TTS：CosyVoice 2（阿里）
- 首次运行自动下载；确认 `asr.py`/`tts.py` 指向两者

### 4. 准备 RAG 种子语料
- 预置知识问答对（正念/焦虑/失眠，10~20 条）准备为灌入 Chroma 的种子数据

> **检查点 0**：环境就绪 → `git add -A && git commit -m "chore: 环境就绪(骨架+依赖+语音模型+种子语料)"`（或让 Claude 提交）

---

## 交给 Claude Code · 5-7（环境真实后）

- **5. 配验证命令**（scripts 写进 package.json / pyproject）——**Claude Code 做**，人不用碰文件
- **6. 验证命令手动追加进 CLAUDE.md §4**
- **7. 开发 + 验证自查 + 跑通验收**

### 提示词（复制粘贴给 Claude Code，它不用看本文件）

```
你在本项目（心理健康助手）仓库工作。环境已就绪（backend/、frontend/ 已建、依赖已装、
语音模型与 RAG 种子语料已备）。执行以下任务，按顺序：

1. 先读 CLAUDE.md（含护栏：命令失败/依赖装不上/契约冲突/需改架构 → 停下问人，不静默改）
   与 Architecture/ 下 architecture-spec-v3.md、ws-contract.md、frontend-plan.md、backend-plan.md。

2. 配验证命令（scripts）：
   - 前端 frontend/package.json：type-check=vue-tsc --noEmit · lint=eslint · test=vitest
   - 后端 backend/pyproject.toml：加 [tool.pytest.ini_options] / [tool.mypy] / [tool.ruff]；
     验证用 uv run mypy app / uv run pytest / uv run ruff check

3. 验证命令**手动**追加进 CLAUDE.md §4（前端 type-check/lint/test；后端 uv run mypy app/pytest/ruff check）。

4. 按架构文档开发，构建顺序：危机闸门 → answer → collect(核心路由) → 黑板 → 记忆 → Live2D → 语音 → 工具。

5. 每条改动用验证命令自查（前端 cd frontend && npm run type-check && npm run lint；
   后端 cd backend && uv run mypy app && uv run pytest）。

6. 跑通验收用例（CLAUDE.md §8，判据可 grep）：
   - answer「什么是正念」→ 无 first_frame、无 draw 帧
   - collect「最近很焦虑睡不着」→ seq 单调递增；draw=粗稿+每轮增量+精稿；充分度≥0.7 停采；信念留白
   - crisis「我不想活了」→ 日志 event=crisis_gate_hit(WARN)+热线横幅+无心情选择器

7. 每完成一个构建阶段：停下汇报 → 确认后 git commit 该阶段(如 "feat: 危机闸门+路由") → 再继续；任何命令失败/依赖装不上/契约冲突 → 停下问人，不静默改。
```

---

**边界**：本手册只列操作分工，不涉及实现代码；契约/数据流以架构文档为准。人做完 0-4 即环境就绪，把上面提示词粘给 Claude Code 开工。
