# -*- coding: utf-8 -*-
"""
语义代码搜索（RAG） - 基于 sentence-transformers 的代码语义检索

设计原则:
1. 首次搜索时自动构建索引（按文件分块 + 嵌入）
2. 索引缓存到内存，避免重复计算
3. 支持增量更新（文件修改后只重新索引变更部分）
4. 使用轻量级多语言模型，兼顾中英文代码和注释
"""
import os
import json
import hashlib
import threading
from typing import Optional

# 延迟导入，避免启动时加载大模型
_st = None
_model = None

def _get_model():
    """延迟加载 sentence-transformers 模型"""
    global _st, _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        # 使用轻量级多语言模型，支持中英文
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _model


class CodeIndex:
    """代码索引：管理文件分块、嵌入向量、缓存"""

    def __init__(self, project_path: str):
        self.project_path = os.path.abspath(project_path)
        self.chunks = []          # [{"id": ..., "file": ..., "start": ..., "end": ..., "text": ...}]
        self.embeddings = None    # numpy array
        self.file_hashes = {}     # {rel_path: md5} 用于增量更新
        self._lock = threading.Lock()

    def _should_index(self, rel_path: str) -> bool:
        """判断文件是否应该被索引"""
        # 跳过隐藏目录和常见非代码目录
        skip_dirs = {'.git', '__pycache__', 'node_modules', '.idea', 'target',
                     'build', '.gradle', 'venv', '.venv', 'env', 'dist', '.tox'}
        for part in rel_path.replace('\\', '/').split('/'):
            if part in skip_dirs:
                return False

        # 只索引文本文件
        code_exts = {'.py', '.js', '.ts', '.java', '.go', '.rs', '.c', '.cpp', '.h',
                     '.hpp', '.cs', '.rb', '.php', '.scala', '.kt', '.sql', '.sh',
                     '.yaml', '.yml', '.toml', '.json', '.xml', '.md', '.txt',
                     '.jsx', '.tsx', '.vue', '.svelte', '.css', '.scss', '.html'}
        _, ext = os.path.splitext(rel_path)
        return ext.lower() in code_exts

    def _chunk_file(self, rel_path: str, content: str, chunk_size: int = 50, overlap: int = 10):
        """将文件内容按行分块，带重叠"""
        lines = content.split('\n')
        chunks = []
        i = 0
        while i < len(lines):
            end = min(i + chunk_size, len(lines))
            chunk_text = '\n'.join(lines[i:end])
            if chunk_text.strip():  # 跳过空块
                chunks.append({
                    "id": f"{rel_path}:{i+1}-{end}",
                    "file": rel_path,
                    "start": i + 1,
                    "end": end,
                    "text": chunk_text,
                })
            i += chunk_size - overlap
        return chunks

    def build(self, force: bool = False):
        """构建或更新索引"""
        with self._lock:
            new_chunks = []
            new_hashes = {}

            for root, dirs, files in os.walk(self.project_path):
                # 过滤目录
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                          {'node_modules', '__pycache__', '.git', '.idea', 'target',
                           'build', '.gradle', 'venv', '.venv', 'env', 'dist', '.tox'}]

                for fname in files:
                    fpath = os.path.join(root, fname)
                    rel_path = os.path.relpath(fpath, self.project_path)

                    if not self._should_index(rel_path):
                        continue

                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                    except (IOError, OSError):
                        continue

                    # 计算文件hash用于增量更新
                    file_hash = hashlib.md5(content.encode()).hexdigest()
                    new_hashes[rel_path] = file_hash

                    if not force and rel_path in self.file_hashes and self.file_hashes[rel_path] == file_hash:
                        # 文件未变更，复用已有chunks
                        existing = [c for c in self.chunks if c["file"] == rel_path]
                        new_chunks.extend(existing)
                        continue

                    # 重新分块
                    file_chunks = self._chunk_file(rel_path, content)
                    new_chunks.extend(file_chunks)

            self.chunks = new_chunks
            self.file_hashes = new_hashes

            if not self.chunks:
                self.embeddings = None
                return

            # 计算嵌入
            model = _get_model()
            texts = [c["text"] for c in self.chunks]
            self.embeddings = model.encode(texts, show_progress_bar=False, batch_size=32)

    def search(self, query: str, top_k: int = 10) -> list:
        """语义搜索，返回最相关的代码块"""
        import numpy as np

        if not self.chunks or self.embeddings is None:
            return []

        model = _get_model()
        query_emb = model.encode([query], show_progress_bar=False)

        # 余弦相似度
        similarities = np.dot(self.embeddings, query_emb.T).flatten()
        norms = np.linalg.norm(self.embeddings, axis=1) * np.linalg.norm(query_emb)
        # 避免除以0
        norms[norms == 0] = 1e-8
        cosine_scores = similarities / norms

        # 获取top_k结果
        top_indices = np.argsort(cosine_scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(cosine_scores[idx])
            if score < 0.1:  # 最低阈值
                continue
            chunk = self.chunks[idx]
            results.append({
                "file": chunk["file"],
                "start": chunk["start"],
                "end": chunk["end"],
                "score": round(score, 4),
                "preview": chunk["text"][:300],
            })

        return results


# 全局索引缓存: project_path -> CodeIndex
_index_cache = {}

def semantic_search(project_path: str, query: str, top_k: int = 10, force_reindex: bool = False) -> str:
    """语义代码搜索入口"""
    project_path = os.path.abspath(project_path)

    if not os.path.exists(project_path):
        return f"路径不存在: {project_path}"

    # 获取或创建索引
    if project_path not in _index_cache or force_reindex:
        index = CodeIndex(project_path)
        index.build(force=force_reindex)
        _index_cache[project_path] = index
    else:
        index = _index_cache[project_path]

    if not index.chunks:
        return "未找到可索引的代码文件"

    results = index.search(query, top_k=top_k)

    if not results:
        return f"未找到与 '{query}' 相关的代码"

    # 格式化输出
    output_lines = [f"语义搜索结果 (query: '{query}'):\n"]
    for i, r in enumerate(results, 1):
        output_lines.append(f"--- 结果 {i} (相似度: {r['score']}) ---")
        output_lines.append(f"文件: {r['file']} (行 {r['start']}-{r['end']})")
        output_lines.append(r['preview'])
        output_lines.append("")

    return '\n'.join(output_lines)


def clear_index(project_path: str = None):
    """清除索引缓存"""
    if project_path:
        _index_cache.pop(os.path.abspath(project_path), None)
    else:
        _index_cache.clear()
