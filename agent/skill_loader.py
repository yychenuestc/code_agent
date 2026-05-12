# -*- coding: utf-8 -*-
"""
Skill 加载器 - 自动发现和加载外部 skill

每个 skill 是 skills/ 目录下的一个子目录，包含:
- manifest.json: skill 元信息和配置
- __init__.py: skill 实现，必须导出 get_tools(), get_hooks(), get_skill_prompt()

加载流程:
1. 扫描 skills/ 目录下的子目录
2. 读取 manifest.json 获取元信息
3. 导入 skill 模块，调用 configure() 注入配置
4. 收集 tools、hooks、skill_prompt
5. 提供给 graph.py 使用
"""
import os
import json
import importlib

# skills 目录（始终在项目根目录下）
SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills")

# 已加载的 skill 缓存
_loaded_skills = {}


def discover_skills():
    """发现所有可用的 skill"""
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        return skills

    for name in os.listdir(SKILLS_DIR):
        skill_dir = os.path.join(SKILLS_DIR, name)
        manifest_path = os.path.join(skill_dir, "manifest.json")
        init_path = os.path.join(skill_dir, "__init__.py")

        if os.path.isdir(skill_dir) and os.path.exists(manifest_path) and os.path.exists(init_path):
            skills.append(name)

    return skills


def load_skill(name: str, config_overrides: dict = None):
    """
    加载指定 skill

    Args:
        name: skill 目录名
        config_overrides: 覆盖 manifest.json 中的配置

    Returns:
        dict with keys: name, module, tools, hooks, skill_prompt, manifest
    """
    if name in _loaded_skills:
        return _loaded_skills[name]

    skill_dir = os.path.join(SKILLS_DIR, name)
    manifest_path = os.path.join(skill_dir, "manifest.json")

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Skill manifest not found: {manifest_path}")

    # 读取 manifest
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    # 导入 skill 模块
    module = importlib.import_module(f"skills.{name}")

    # 注入配置（config_overrides 按 skill 名称索引）
    config = manifest.get("config", {})
    if config_overrides:
        skill_config = config_overrides.get(name, {})
        config.update(skill_config)
    if hasattr(module, 'configure'):
        module.configure(config)

    # 收集 skill 提供的能力
    tools = module.get_tools() if hasattr(module, 'get_tools') else []
    hooks = module.get_hooks() if hasattr(module, 'get_hooks') else {}
    skill_prompt = module.get_skill_prompt() if hasattr(module, 'get_skill_prompt') else ""

    skill_info = {
        "name": name,
        "manifest": manifest,
        "module": module,
        "tools": tools,
        "hooks": hooks,
        "skill_prompt": skill_prompt,
    }

    _loaded_skills[name] = skill_info
    return skill_info


def load_all_skills(config_overrides: dict = None):
    """
    加载所有已发现的 skill

    Returns:
        list of skill_info dicts
    """
    skill_names = discover_skills()
    loaded = []
    for name in skill_names:
        try:
            skill_info = load_skill(name, config_overrides)
            loaded.append(skill_info)
        except Exception as e:
            print(f"[SkillLoader] 加载 skill '{name}' 失败: {e}")
    return loaded


def get_all_tools():
    """获取所有已加载 skill 的 LangChain Tool 列表"""
    if not _loaded_skills:
        load_all_skills()
    tools = []
    for skill_info in _loaded_skills.values():
        tools.extend(skill_info["tools"])
    return tools


def get_all_hooks():
    """获取所有已加载 skill 的 Hook 函数映射"""
    if not _loaded_skills:
        load_all_skills()
    hooks = {}
    for skill_info in _loaded_skills.values():
        hooks.update(skill_info["hooks"])
    return hooks


def get_all_skill_prompts():
    """获取所有已加载 skill 的技能提示拼接"""
    if not _loaded_skills:
        load_all_skills()
    prompts = []
    for skill_info in _loaded_skills.values():
        if skill_info["skill_prompt"]:
            prompts.append(skill_info["skill_prompt"])
    return "\n\n".join(prompts)
