# -*- coding: utf-8 -*-
"""
评估框架 - 自动化测试 Agent 输出质量
覆盖 analyze / develop / review / chat 四类任务
"""
import json
import time
from typing import Callable

from graph import build_graph
from state import AgentState
from langchain_core.messages import HumanMessage


# ============ 评估用例 ============

EVAL_CASES = [
    # ---- analyze 任务 ----
    {
        "id": "analyze_01",
        "task_type": "analyze",
        "input": "分析当前项目 /Users/chenyangyi/Documents/dev_agent 的结构",
        "expected_keywords": ["Python", "入口点", "依赖"],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("exploration_result") is not None,
    },
    {
        "id": "analyze_02",
        "task_type": "analyze",
        "input": "这个项目用了哪些框架和构建工具？",
        "expected_keywords": [],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("task_type") == "analyze",
    },
    # ---- develop 任务 ----
    {
        "id": "develop_01",
        "task_type": "develop",
        "input": "为这个项目添加一个简单的健康检查接口 health_check()",
        "expected_keywords": [],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("design_options") is not None,
    },
    {
        "id": "develop_02",
        "task_type": "develop",
        "input": "写一个 Python 函数计算斐波那契数列第n项",
        "expected_keywords": ["fibonacci", "fib"],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("implementation") is not None,
    },
    # ---- review 任务 ----
    {
        "id": "review_01",
        "task_type": "review",
        "input": "审查以下代码:\ndef add(a,b): return a+b",
        "expected_keywords": [],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("review_issues") is not None,
    },
    {
        "id": "review_02",
        "task_type": "review",
        "input": "审查这段代码的质量: try: pass except: pass",
        "expected_keywords": ["except", "裸"],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("task_type") == "review",
    },
    # ---- chat 任务 ----
    {
        "id": "chat_01",
        "task_type": "chat",
        "input": "Python 中 list 和 tuple 的区别是什么？",
        "expected_keywords": ["可变", "不可变"],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("final_output") != "",
    },
    {
        "id": "chat_02",
        "task_type": "chat",
        "input": "Spark SQL 中如何做分区裁剪？",
        "expected_keywords": ["分区", "WHERE"],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("final_output") != "",
    },
    # ---- SQL 任务 ----
    {
        "id": "sql_01",
        "task_type": "chat",
        "input": "帮我写一个 Spark SQL 建表语句，用户表，按日期分区",
        "expected_keywords": ["CREATE TABLE", "PARTITIONED BY", "STORED AS"],
        "forbidden_keywords": ["SELECT *"],
        "check_state": lambda s: s.get("final_output") != "",
    },
    # ---- 分类测试 ----
    {
        "id": "classify_01",
        "task_type": "analyze",
        "input": "帮我分析一下这个 Java 项目的架构",
        "expected_keywords": [],
        "forbidden_keywords": [],
        "check_state": lambda s: s.get("task_type") == "analyze" and s.get("language") == "java",
    },
]


# ============ 评估执行器 ============

class EvalRunner:
    """评估执行器"""

    def __init__(self):
        self.app = build_graph()
        self.results = []

    def run_case(self, case: dict) -> dict:
        """运行单个评估用例"""
        case_id = case["id"]
        input_text = case["input"]
        task_type = case["task_type"]

        thread_id = f"eval_{case_id}"
        config = {"configurable": {"thread_id": thread_id}}

        input_state = {
            "user_input": input_text,
            "task_type": task_type,
            "project_path": "",
            "language": "",
            "iteration": 0,
            "messages": [HumanMessage(content=input_text)],
        }

        start_time = time.time()
        try:
            # 执行图
            final_state = self.app.invoke(input_state, config=config)
            elapsed = time.time() - start_time

            final_output = final_state.get("final_output", "")

            # 检查关键词
            keyword_pass = True
            missing_keywords = []
            for kw in case.get("expected_keywords", []):
                if kw.lower() not in final_output.lower():
                    keyword_pass = False
                    missing_keywords.append(kw)

            forbidden_hit = []
            for kw in case.get("forbidden_keywords", []):
                if kw.lower() in final_output.lower():
                    keyword_pass = False
                    forbidden_hit.append(kw)

            # 检查状态
            state_check = case.get("check_state", lambda s: True)
            state_pass = state_check(final_state)

            passed = keyword_pass and state_pass and not forbidden_hit

            return {
                "case_id": case_id,
                "passed": passed,
                "elapsed": round(elapsed, 2),
                "keyword_pass": keyword_pass,
                "missing_keywords": missing_keywords,
                "forbidden_hit": forbidden_hit,
                "state_pass": state_pass,
                "output_preview": final_output[:200],
            }

        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "case_id": case_id,
                "passed": False,
                "elapsed": round(elapsed, 2),
                "error": str(e),
            }

    def run_all(self, cases: list = None):
        """运行所有评估用例"""
        cases = cases or EVAL_CASES
        print(f"开始评估，共 {len(cases)} 个用例\n")

        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] 运行 {case['id']}...", end=" ", flush=True)
            result = self.run_case(case)
            self.results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status} ({result['elapsed']}s)")
            if not result["passed"]:
                if result.get("missing_keywords"):
                    print(f"  缺失关键词: {result['missing_keywords']}")
                if result.get("forbidden_hit"):
                    print(f"  禁止关键词命中: {result['forbidden_hit']}")
                if not result.get("state_pass", True):
                    print(f"  状态检查失败")
                if result.get("error"):
                    print(f"  错误: {result['error'][:100]}")

        # 汇总
        self.print_summary()

    def print_summary(self):
        """打印评估汇总"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed

        print("\n" + "=" * 60)
        print("评估汇总")
        print("=" * 60)
        print(f"总计: {total}  通过: {passed}  失败: {failed}  通过率: {passed/total*100:.1f}%")

        if failed > 0:
            print("\n失败用例:")
            for r in self.results:
                if not r["passed"]:
                    reason_parts = []
                    if r.get("missing_keywords"):
                        reason_parts.append(f"缺失: {r['missing_keywords']}")
                    if r.get("forbidden_hit"):
                        reason_parts.append(f"禁止: {r['forbidden_hit']}")
                    if not r.get("state_pass", True):
                        reason_parts.append("状态检查失败")
                    if r.get("error"):
                        reason_parts.append(f"错误: {r['error'][:80]}")
                    print(f"  {r['case_id']}: {'; '.join(reason_parts)}")

        # 平均耗时
        avg_time = sum(r["elapsed"] for r in self.results) / total if total > 0 else 0
        print(f"\n平均耗时: {avg_time:.2f}s")
        print("=" * 60)

        return passed, failed


# ============ 入口 ============

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Dev Agent 评估框架")
    parser.add_argument("--case", type=str, help="运行指定用例ID（如 analyze_01）")
    args = parser.parse_args()

    runner = EvalRunner()

    if args.case:
        case = next((c for c in EVAL_CASES if c["id"] == args.case), None)
        if case:
            runner.run_all([case])
        else:
            print(f"未找到用例: {args.case}")
            print(f"可用用例: {', '.join(c['id'] for c in EVAL_CASES)}")
    else:
        runner.run_all()
