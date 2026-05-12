# -*- coding: utf-8 -*-
"""
语言专属技能提示 - Python/SQL/Java 各有专属技能指导
借鉴 Claude Code 的 Skills 机制：根据上下文自动激活对应语言的专业知识
"""

# ============================================================
# Python 技能
# ============================================================
PYTHON_SKILL = """## Python 开发专家技能

### 编码规范
- 遵循 PEP 8 风格指南
- 使用类型注解（type hints）
- 函数/类添加 docstring
- 优先使用 pathlib 替代 os.path
- 使用 f-string 替代 format/%
- 异常处理要具体，避免裸 except

### 常用库与模式
- 数据处理: pandas, numpy, polars
- HTTP请求: requests, httpx
- 异步: asyncio, aiohttp
- 数据库: SQLAlchemy, psycopg2, pymysql
- 配置: pydantic, python-dotenv
- 测试: pytest, unittest

### 项目结构识别
- setup.py / pyproject.toml → 包项目
- requirements.txt / Pipfile → 依赖管理
- .venv / venv → 虚拟环境
- conftest.py → pytest 配置
- manage.py → Django 项目
- app.py / main.py → Flask/FastAPI 入口

### 代码分析要点
- 入口点: if __name__ == "__main__", main()
- 依赖关系: import 链路
- 配置加载: 环境变量、配置文件
- 日志体系: logging 配置
- 测试覆盖: 测试目录和覆盖率
"""

# ============================================================
# Spark SQL 技能
# ============================================================
SQL_SKILL = """## Spark SQL 开发专家技能

### Spark SQL 特性
- 使用 Hive MetaStore 管理表元数据
- 分区表: PARTITIONED BY (dt string, hm string)
- 存储格式: ORC, Parquet, Text
- 日期变量: '${date:y-m-d}' 带-格式, '${date:ymd}' 不带-格式

### SQL 编写规范
- 大写关键字: SELECT, FROM, WHERE, JOIN
- 表名使用 库名.表名 全限定
- 分区过滤必须放在 WHERE 最前面
- 避免SELECT *，明确列出字段
- 大表JOIN注意数据倾斜，使用ROADCAST JOIN或分桶
- 字符串用单引号

### 性能优化
- 分区裁剪: WHERE dt = '2026-04-22'
- 谓词下推: 尽早过滤
- 避免笛卡尔积
- 使用 INSERT OVERWRITE 替代 INSERT INTO 做全量覆盖
- 合理使用 DISTRIBUTE BY / SORT BY

### 常用模式
- 拉链表: start_date/end_date 设计
- 增量更新: MERGE INTO / INSERT OVERWRITE
- 去重: ROW_NUMBER() OVER(PARTITION BY ... ORDER BY ...)
- 类型转换: CAST(expr AS type), STRING/BIGINT/DOUBLE
- JSON解析: get_json_object(json_col, '$.key')
- 条件聚合: COLLECT_SET, COLLECT_LIST

### SQL 查询工作流
（SQL 查询工作流提示由外部 skill 动态注入，此处不再重复）

### 建表模板
```sql
CREATE TABLE IF NOT EXISTS db.table_name (
    id BIGINT COMMENT '主键',
    name STRING COMMENT '名称'
) COMMENT '表注释'
PARTITIONED BY (dt STRING COMMENT '日期分区')
STORED AS ORC;
```
"""

# ============================================================
# Java 技能
# ============================================================
JAVA_SKILL = """## Java 开发专家技能

### 编码规范
- 遵循阿里巴巴Java开发手册
- 类名大驼峰，方法名小驼峰
- 常量全大写+下划线
- 接口定义与实现分离
- 异常处理：checked vs unchecked
- 日志使用 SLF4J + Logback

### 项目结构识别
- pom.xml → Maven 项目
- build.gradle / build.gradle.kts → Gradle 项目
- src/main/java → Java源码
- src/main/resources → 配置文件
- src/test/java → 测试代码
- application.yml / application.properties → Spring Boot配置

### Spring Boot 分析要点
- @SpringBootApplication 入口类
- @RestController / @Controller 控制层
- @Service 业务层
- @Repository 数据层
- @Component 通用组件
- @Configuration 配置类
- @Autowired / @Resource 依赖注入
- @Value 配置注入
- @Scheduled 定时任务
- @Transactional 事务管理

### 设计模式识别
- 工厂模式: XxxFactory
- 策略模式: XxxStrategy + XxxContext
- 观察者模式: Event/Listener
- 模板方法: AbstractXxx
- 单例模式: getInstance()
- 建造者模式: XxxBuilder
- 适配器模式: XxxAdapter

### 常用框架
- Web: Spring MVC, Spring WebFlux
- ORM: MyBatis, JPA/Hibernate
- 消息: Kafka, RabbitMQ
- 缓存: Redis, Caffeine
- 搜索: Elasticsearch
- RPC: Dubbo, gRPC
"""

# ============================================================
# 技能注册表 - 根据语言类型自动匹配
# ============================================================
SKILLS = {
    "python": PYTHON_SKILL,
    "sql": SQL_SKILL,
    "java": JAVA_SKILL,
}


def get_skill(language: str) -> str:
    """根据语言类型获取技能提示"""
    return SKILLS.get(language.lower(), "")


def detect_language(context: str) -> str:
    """根据上下文检测语言类型"""
    context_lower = context.lower()

    # SQL检测
    sql_keywords = ["select ", "from ", "where ", "join ", "group by",
                    "create table", "insert ", "partitioned by", "spark sql"]
    if sum(1 for kw in sql_keywords if kw in context_lower) >= 2:
        return "sql"

    # Java检测
    java_keywords = ["public class", "import java", "spring boot", "maven",
                     "gradle", "@service", "@controller", "pom.xml", ".java"]
    if any(kw in context_lower for kw in java_keywords):
        return "java"

    # Python检测
    python_keywords = ["import ", "def ", "class ", "pip ", "python",
                       ".py", "django", "flask", "fastapi", "pandas"]
    if any(kw in context_lower for kw in python_keywords):
        return "python"

    return ""
