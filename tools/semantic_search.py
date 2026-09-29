# -*- coding: utf-8 -*-
"""
语义代码搜索（RAG）- 基于 Chroma 向量库的持久化代码语义检索

设计原则:
1. 向量库使用 Chroma（PersistentClient），索引持久化到本地磁盘，进程重启不丢失
2. 嵌入向量由统一嵌入器生成（默认在线 Embedding API，可回退本地 sentence-transformers）
3. 增量更新：按文件 MD5 判断变更，仅重嵌入变更/新增文件，删除已移除文件的向量
4. 若 Chroma / 嵌入依赖不可用，自动回退到内存 numpy 实现，保证基本可用

对外仅暴露 semantic_search() / clear_index()，签名保持向后兼容。
"""
import os
import hashlib
import threading

from core.config import (
    VECTOR_DB_DIR, VECTOR_TOP_K, VECTOR_MIN_SCORE,
    CHUNK_SIZE, CHUNK_OVERLAP,
)

# 需要索引的文本/代码扩展名
CODE_EXTS = {'.py', '.js', '.ts', '.java', '.go', '.rs', '.c', '.cpp', '.h',
             '.hpp', '.cs', '.rb', '.php', '.scala', '.kt', '.sql', '.sh',
             '.yaml', '.yml', '.toml', '.json', '.xml', '.md', '.txt',
             '.jsx', '.tsx', '.vue', '.svelte', '.css', '.scss', '.html'}

# 遍历时跳过的目录
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.idea', 'target',
             'build', '.gradle', 'venv', '.venv', 'env', 'dist', '.tox', '.cache'}


# ============ 共享工具函数 ============

def _should_index(rel_path: str) -> bool:
    """判断文件是否应被索引"""
    for part in rel_path.replace('\\', '/').split('/'):
        if part in SKIP_DIRS:
            return False
    _, ext = os.path.splitext(rel_path)
    return ext.lower() in CODE_EXTS


def _chunk_file(rel_path: str, content: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """将文件内容按行分块，带重叠"""
    lines = content.split('\n')
    chunks = []
    i = 0
    while i < len(lines):
        end = min(i + chunk_size, len(lines))
        chunk_text = '\n'.join(lines[i:end])
        if chunk_text.strip():
            chunks.append({
                "id": f"{rel_path}:{i + 1}-{end}",
                "file": rel_path,
                "start": i + 1,
                "end": end,
                "text": chunk_text,
            })
        i += chunk_size - overlap
    return chunks


def _walk_files(project_path: str):
    """遍历项目下需索引的文件，产出 (rel_path, content, file_hash)"""
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in SKIP_DIRS]
        for fname in files:
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, project_path)
            if not _should_index(rel_path):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except (IOError, OSError):
                continue
            file_hash = hashlib.md5(content.encode('utf-8', errors='replace')).hexdigest()
            yield rel_path, content, file_hash


def _collection_name(project_path: str) -> str:
    """由项目绝对路径生成合法且稳定的 Chroma collection 名"""
    digest = hashlib.md5(os.path.abspath(project_path).encode('utf-8')).hexdigest()
    return f"code_{digest[:16]}"


# ============ Chroma 向量库实现 ============

_client = None
_client_lock = threading.Lock()
_embedding_fn = None


def _chroma_available() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except Exception:
        return False


def _make_embedding_function():
    """构造 Chroma EmbeddingFunction（继承官方 Protocol 以获得正确的 embed_query 等默认行为）。

    延迟导入 chromadb，把统一嵌入器 core.llm.get_embeddings 适配进来。
    """
    from chromadb.api.types import EmbeddingFunction
    from core.llm import get_embeddings

    embedder = get_embeddings()

    class _CodeAgentEF(EmbeddingFunction):
        def __call__(self, input):
            return embedder.embed_documents(list(input))

        @staticmethod
        def name():
            return "code_agent_embeddings"

        def get_config(self):
            return {}

        @classmethod
        def build_from_config(cls, config):
            return cls()

    return _CodeAgentEF()


def _get_client():
    global _client, _embedding_fn
    with _client_lock:
        if _client is None:
            import chromadb
            os.makedirs(VECTOR_DB_DIR, exist_ok=True)
            _client = chromadb.PersistentClient(path=VECTOR_DB_DIR)
            _embedding_fn = _make_embedding_function()
    return _client, _embedding_fn


def _get_collection(project_path: str):
    client, ef = _get_client()
    return client.get_or_create_collection(
        name=_collection_name(project_path),
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def _chroma_build(project_path: str, force: bool = False):
    """构建 / 增量更新 Chroma 索引，返回索引后的 chunk 总数"""
    client, _ = _get_client()
    col_name = _collection_name(project_path)

    if force:
        try:
            client.delete_collection(col_name)
        except Exception:
            pass

    collection = _get_collection(project_path)

    # 读取已存储的 file -> hash 映射
    stored_hashes = {}
    try:
        existing = collection.get(include=["metadatas"])
        for md in existing.get("metadatas", []) or []:
            if md and "file" in md:
                stored_hashes[md["file"]] = md.get("file_hash", "")
    except Exception:
        stored_hashes = {}

    current_files = {}
    add_ids, add_docs, add_metas = [], [], []

    for rel_path, content, file_hash in _walk_files(project_path):
        current_files[rel_path] = file_hash
        # 未变更则跳过
        if not force and stored_hashes.get(rel_path) == file_hash:
            continue
        # 变更 / 新增：先删旧块，再加新块
        if rel_path in stored_hashes:
            try:
                collection.delete(where={"file": rel_path})
            except Exception:
                pass
        for c in _chunk_file(rel_path, content):
            add_ids.append(c["id"])
            add_docs.append(c["text"])
            add_metas.append({
                "file": c["file"], "start": c["start"],
                "end": c["end"], "file_hash": file_hash,
            })

    # 删除已移除文件的向量
    for stale in set(stored_hashes) - set(current_files):
        try:
            collection.delete(where={"file": stale})
        except Exception:
            pass

    # 分批写入（嵌入在此触发）
    for i in range(0, len(add_ids), 64):
        collection.add(
            ids=add_ids[i:i + 64],
            documents=add_docs[i:i + 64],
            metadatas=add_metas[i:i + 64],
        )

    return collection.count()


def _chroma_search(project_path: str, query: str, top_k: int, force_reindex: bool) -> str:
    project_path = os.path.abspath(project_path)
    if not os.path.exists(project_path):
        return f"路径不存在: {project_path}"

    collection = _get_collection(project_path)
    # 空索引或强制重建时先构建
    if force_reindex or collection.count() == 0:
        _chroma_build(project_path, force=force_reindex)
        collection = _get_collection(project_path)

    if collection.count() == 0:
        return "未找到可索引的代码文件"

    res = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    lines = [f"语义搜索结果 (query: '{query}'，来源: Chroma 向量库):\n"]
    hit = 0
    for doc, md, dist in zip(docs, metas, dists):
        score = round(1.0 - float(dist), 4)  # cosine: distance = 1 - similarity
        if score < VECTOR_MIN_SCORE:
            continue
        hit += 1
        lines.append(f"--- 结果 {hit} (相似度: {score}) ---")
        lines.append(f"文件: {md.get('file')} (行 {md.get('start')}-{md.get('end')})")
        lines.append((doc or "")[:300])
        lines.append("")

    if hit == 0:
        return f"未找到与 '{query}' 相关的代码"
    return '\n'.join(lines)


# ============ 兜底：内存 numpy 实现（无 Chroma 时使用）============

_legacy_model = None
_legacy_cache = {}


def _get_legacy_model():
    global _legacy_model
    if _legacy_model is None:
        from core.llm import get_embeddings
        # 内存兜底始终用本地嵌入，避免离线场景仍强依赖 API
        _legacy_model = get_embeddings(provider="local")
    return _legacy_model


def _legacy_build(project_path: str, force: bool = False):
    chunks = []
    for rel_path, content, _ in _walk_files(project_path):
        chunks.extend(_chunk_file(rel_path, content))
    if not chunks:
        return None, None
    import numpy as np
    embedder = _get_legacy_model()
    embeddings = np.array(embedder.embed_documents([c["text"] for c in chunks]))
    return chunks, embeddings


def _legacy_search(project_path: str, query: str, top_k: int, force_reindex: bool) -> str:
    import numpy as np
    project_path = os.path.abspath(project_path)
    if not os.path.exists(project_path):
        return f"路径不存在: {project_path}"

    if project_path not in _legacy_cache or force_reindex:
        _legacy_cache[project_path] = _legacy_build(project_path, force=force_reindex)
    chunks, embeddings = _legacy_cache[project_path]

    if not chunks:
        return "未找到可索引的代码文件"

    embedder = _get_legacy_model()
    q = np.array(embedder.embed_query(query))
    sims = embeddings @ q
    norms = np.linalg.norm(embeddings, axis=1) * np.linalg.norm(q)
    norms[norms == 0] = 1e-8
    scores = sims / norms
    top = np.argsort(scores)[::-1][:top_k]

    lines = [f"语义搜索结果 (query: '{query}'，来源: 内存兜底):\n"]
    hit = 0
    for idx in top:
        score = float(scores[idx])
        if score < VECTOR_MIN_SCORE:
            continue
        hit += 1
        c = chunks[idx]
        lines.append(f"--- 结果 {hit} (相似度: {round(score, 4)}) ---")
        lines.append(f"文件: {c['file']} (行 {c['start']}-{c['end']})")
        lines.append(c["text"][:300])
        lines.append("")

    if hit == 0:
        return f"未找到与 '{query}' 相关的代码"
    return '\n'.join(lines)


def semantic_search(project_path: str, query: str, top_k: int = VECTOR_TOP_K,
                    force_reindex: bool = False) -> str:
    """语义代码搜索入口：优先 Chroma 持久化向量库，失败回退内存实现"""
    if _chroma_available():
        try:
            return _chroma_search(project_path, query, top_k, force_reindex)
        except Exception as e:
            print(f"[semantic_search] Chroma 检索失败，回退内存实现: {e}")
    return _legacy_search(project_path, query, top_k, force_reindex)


def clear_index(project_path: str = None):
    """清除索引：删除 Chroma collection 与内存缓存"""
    if project_path:
        _legacy_cache.pop(os.path.abspath(project_path), None)
        if _chroma_available():
            try:
                client, _ = _get_client()
                client.delete_collection(_collection_name(project_path))
            except Exception:
                pass
    else:
        _legacy_cache.clear()
        if _chroma_available():
            try:
                client, _ = _get_client()
                for col in client.list_collections():
                    client.delete_collection(col.name)
            except Exception:
                pass





