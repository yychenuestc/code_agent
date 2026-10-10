# -*- coding: utf-8 -*-
"""
Code Agent Web 界面后端（FastAPI）

复用 agent.graph.build_graph()，通过 SSE 把状态图逐节点执行过程流式推给前端，
并提供单页前端静态服务。入口命令：
    python web/server.py
或：
    uvicorn web.server:app --host 127.0.0.1 --port 8000

安全提示：本 Agent 具备读写文件、执行 Python/Java 代码等能力，Web 服务**默认仅绑定
127.0.0.1 且无鉴权**。请勿在未加认证的情况下将其暴露到公网或局域网。
"""
import os
import sys
import json
import uuid

# 将项目根目录加入模块搜索路径，便于直接运行 web/server.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from langchain_core.messages import HumanMessage

from agent.graph import build_graph
from agent.lang_skills import detect_language
import core.config as config

app = FastAPI(title="Code Agent Web")
_graph = build_graph()
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))


@app.get("/")
def index():
    """返回单页前端"""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/app.js")
def app_js():
    return FileResponse(os.path.join(STATIC_DIR, "app.js"), media_type="application/javascript")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def get_config_api():
    """返回脱敏后的模型/密钥配置状态（不含明文密钥）"""
    return config.get_config_status()


@app.post("/api/config")
async def set_config_api(request: Request):
    """保存 API Key。body: {provider?: 'deepseek'|'glm', api_key: str}"""
    payload = await request.json()
    provider = (payload.get("provider") or "deepseek").strip()
    api_key = payload.get("api_key") or ""
    try:
        config.set_model_api_key(api_key, provider=provider)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, "status": config.get_config_status()}


def _sse(event: str, data: dict) -> str:
    """格式化一条 SSE 消息"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extract_preview(node_output) -> str:
    """从节点输出中提取一段可读预览（对齐 REPL 的流式展示）"""
    if not isinstance(node_output, dict):
        return str(node_output)[:200]
    msgs = node_output.get("messages")
    if msgs:
        last = msgs[-1] if isinstance(msgs, list) else msgs
        content = getattr(last, "content", None)
        if content:
            return str(content)[:400]
    for key in ("task_type", "final_output", "implementation_error", "verify_result", "plan_reason"):
        if node_output.get(key):
            return f"{key}={str(node_output[key])[:200]}"
    return ""

def _run_stream(payload: dict):
    """同步生成器：驱动状态图并逐节点产出 SSE 事件"""
    user_input = (payload.get("message") or "").strip()
    task_type = payload.get("task_type") or None
    project_path = payload.get("project_path") or ""
    language = payload.get("language") or ""
    thread_id = payload.get("thread_id") or str(uuid.uuid4())

    if not language and user_input:
        language = detect_language(user_input) or ""

    config = {"configurable": {"thread_id": thread_id}}
    input_state = {
        "user_input": user_input,
        "project_path": project_path,
        "language": language,
        "iteration": 0,
        "messages": [HumanMessage(content=user_input)],
    }
    if task_type:
        input_state["task_type"] = task_type

    yield _sse("session", {"thread_id": thread_id, "language": language})
    try:
        for event in _graph.stream(input_state, config=config, stream_mode="updates"):
            for node_name, node_output in event.items():
                yield _sse("node", {"node": node_name, "preview": _extract_preview(node_output)})
        state = _graph.get_state(config)
        yield _sse("final", {"output": state.values.get("final_output", "")})
    except Exception as e:  # noqa: BLE001 - 把异常透传给前端展示
        yield _sse("error", {"message": str(e)})
    yield _sse("done", {})


@app.post("/api/stream")
async def stream(request: Request):
    """接收 {message, task_type, project_path, language, thread_id}，SSE 流式返回执行过程"""
    payload = await request.json()
    return StreamingResponse(_run_stream(payload), media_type="text/event-stream")


def main():
    import uvicorn
    host = os.environ.get("CODE_AGENT_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("CODE_AGENT_WEB_PORT", "8000"))
    print(f"Code Agent Web 启动于 http://{host}:{port}  (Ctrl+C 退出)")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
