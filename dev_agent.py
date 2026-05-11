# -*- coding: utf-8 -*-
"""
Dev Agent - 多语言程序开发智能体
基于 LangGraph 状态图，支持结构化流程、并行审查、检查点持久化
支持: /analyze /develop /review /sql /python /java /project /lang /clear /help /exit
"""
import sys
import io
import uuid

from graph import build_graph
from lang_skills import detect_language
from langchain_core.messages import HumanMessage, AIMessage

# 修复Windows控制台Unicode输出
if sys.platform == 'win32' and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ============ 全局状态 ============

class SessionState:
    """管理会话状态"""
    def __init__(self):
        self.current_project: str = ""
        self.current_language: str = ""
        self.thread_id: str = str(uuid.uuid4())

    def set_project(self, path: str):
        self.current_project = path

    def set_language(self, lang: str):
        self.current_language = lang


session = SessionState()
app = build_graph()


# ============ 命令处理 ============

def handle_command(user_input: str):
    """处理斜杠命令，返回 (should_continue, response)"""
    parts = user_input.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        return True, """可用命令:
  /analyze <项目路径>     - 分析项目结构
  /develop <需求描述>     - 结构化开发流程
  /review <文件路径>      - 代码审查
  /sql <SQL语句>         - 执行Spark SQL查询
  /python <代码>         - 执行Python代码
  /java <代码>           - 编译运行Java代码
  /project               - 查看当前项目
  /lang <语言>           - 切换语言上下文(python/sql/java)
  /clear                 - 清空对话历史（新thread）
  /help                  - 显示帮助
  /exit                  - 退出"""

    elif cmd == "/project":
        lang = session.current_language or "未设置"
        proj = session.current_project or "未设置"
        return True, f"当前项目: {proj}\n当前语言: {lang}\nThread: {session.thread_id}"

    elif cmd == "/lang":
        if args.lower() in ("python", "sql", "java"):
            session.set_language(args.lower())
            return True, f"已切换语言上下文: {args.lower()}"
        return True, "用法: /lang python|sql|java"

    elif cmd == "/clear":
        session.thread_id = str(uuid.uuid4())
        return True, "对话历史已清空（新 thread）"

    elif cmd in ("/exit", "/quit"):
        return False, "再见!"

    return None, None  # 不是命令，交给图处理


# ============ 流式输出 ============

def stream_graph_invoke(user_input: str, task_type: str = None, language: str = None):
    """调用图并以流式方式输出节点执行过程"""
    config = {"configurable": {"thread_id": session.thread_id}}

    # 自动检测语言
    if not language and not session.current_language:
        detected = detect_language(user_input)
        if detected:
            session.set_language(detected)
            language = detected
    elif not language:
        language = session.current_language

    # 构建输入
    input_state = {
        "user_input": user_input,
        "project_path": session.current_project,
        "language": language or "",
        "iteration": 0,
        "messages": [HumanMessage(content=user_input)],
    }
    if task_type:
        input_state["task_type"] = task_type

    # 流式执行
    final_output = ""
    for event in app.stream(input_state, config=config, stream_mode="updates"):
        for node_name, node_output in event.items():
            # 打印节点执行信息
            print(f"  [{node_name}]", end=" ")

            # 提取关键信息
            if isinstance(node_output, dict):
                # 提取 messages 中的最后一条
                msgs = node_output.get("messages", [])
                if msgs:
                    last_msg = msgs[-1] if isinstance(msgs, list) else msgs
                    if hasattr(last_msg, 'content'):
                        preview = last_msg.content[:120] if last_msg.content else ""
                    elif isinstance(last_msg, dict):
                        preview = str(last_msg.get("content", ""))[:120]
                    else:
                        preview = str(last_msg)[:120]
                    print(preview)
                else:
                    # 尝试其他字段
                    for key in ["task_type", "final_output", "implementation_error", "verify_result"]:
                        if key in node_output and node_output[key]:
                            print(f"{key}={str(node_output[key])[:80]}")
                            break
                    else:
                        print()
            else:
                print()

    # 获取最终结果
    state = app.get_state(config)
    final_output = state.values.get("final_output", "")

    return final_output


# ============ 主交互循环 ============

def chat_loop():
    """交互式对话循环"""
    print("=" * 60)
    print("Dev Agent - 多语言程序开发智能体")
    print("精通 Python / Spark SQL / Java")
    print("基于 LangGraph 状态图，支持结构化流程与并行审查")
    print("=" * 60)
    print("命令:")
    print("  /analyze <路径>  分析项目  /review <路径>  代码审查")
    print("  /develop <需求>  开发流程  /sql <SQL>      执行SQL")
    print("  /python <代码>   执行Python /java <代码>    执行Java")
    print("  /project         当前项目  /lang <语言>    切换语言")
    print("  /clear           清空历史  /help           帮助")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n你: ").strip()
            if not user_input:
                continue

            # 处理命令
            should_continue, response = handle_command(user_input)
            if should_continue is not None:
                print(f"\n助手: {response}")
                if not should_continue:
                    break
                continue

            # 解析命令为任务类型
            task_type = None
            actual_input = user_input
            parts = user_input.strip().split(maxsplit=1)
            cmd = parts[0].lower()
            if cmd == "/analyze":
                task_type = "analyze"
                actual_input = parts[1] if len(parts) > 1 else user_input
                if actual_input:
                    session.set_project(actual_input.split()[0])
            elif cmd == "/develop":
                task_type = "develop"
                actual_input = parts[1] if len(parts) > 1 else user_input
            elif cmd == "/review":
                task_type = "review"
                actual_input = parts[1] if len(parts) > 1 else user_input
            elif cmd == "/sql":
                task_type = "chat"
                actual_input = f"执行以下SQL查询: {parts[1] if len(parts) > 1 else ''}"
                session.set_language("sql")
            elif cmd == "/python":
                task_type = "chat"
                actual_input = f"执行以下Python代码: {parts[1] if len(parts) > 1 else ''}"
                session.set_language("python")
            elif cmd == "/java":
                task_type = "chat"
                actual_input = f"编译运行以下Java代码: {parts[1] if len(parts) > 1 else ''}"
                session.set_language("java")

            print()
            answer = stream_graph_invoke(actual_input, task_type=task_type)

            if answer:
                print(f"\n助手: {answer}")
            else:
                print("\n助手: (未能获取响应)")

        except KeyboardInterrupt:
            print("\n已中断，再见!")
            break
        except Exception as e:
            print(f"错误: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    chat_loop()
