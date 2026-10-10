"""RAG Remote Service — Chroma+BM25+reranker 独立 FastAPI 服务。

端点:
  GET  /live            — 进程存活(200 = 活着)
  GET  /ready           — 模型就绪(200 = ready, 503 = 未就绪)
  GET  /v1/health       — 详细健康状态
  POST /v1/retrieve     — 混合检索+重排
  GET  /metrics         — Prometheus 指标

启动:
  python -m app.rag_service
  uvicorn app.rag_service.server:app --host 0.0.0.0 --port 9003

环境变量:
  RAG_SERVICE_PORT       — 监听端口 (默认 9003)
  RAG_SERVICE_HOST       — 监听地址 (默认 0.0.0.0)
  SERVICE_AUTH_TOKEN     — Bearer 认证 token (空=跳过验证)
"""
