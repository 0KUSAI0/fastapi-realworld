# FastAPI RealWorld AI 拓展版项目说明

本文档用于说明本课程项目在原始 `fastapi-realworld-example-app` 基础上的拓展内容和快速启动方式。原项目 `README.md` 保留为开源项目原始说明，本文件重点介绍本仓库当前版本新增的 AI 写作、文章库问答、相关推荐和内容治理能力。

## 1. 项目来源

本项目基于开源项目 `nsidnev/fastapi-realworld-example-app` 进行二次开发。原项目实现了 RealWorld/Conduit 风格的文章社区后端，主要包含用户注册登录、文章发布、文章列表、文章详情、标签、评论等基础后端能力，并展示了 FastAPI、Pydantic、异步数据库访问、数据库迁移和 pytest 测试等工程实践。

本课程项目保留原项目的后端分层结构，在其基础上增加面向文章社区场景的 AI 辅助创作、AI 文章库问答、相关推荐、AI 内容审核和管理员治理功能。

## 2. 主要拓展功能

### 2.1 普通用户功能

- 文章列表、文章详情和评论浏览。
- 文章库小助手：用户可以用自然语言询问文章库，例如“有没有关于城市生活和注意力恢复的文章？”，系统先检索相关文章，再基于来源文章生成回答。
- 来源文章跳转：文章库助手返回来源文章后，用户可以点击进入对应阅读页。
- 相关推荐：在文章详情页根据当前文章内容推荐相关内容。
- 账号中心：集中查看个人文章、收藏、评论和通知。
- 举报机制：用户可以举报文章或评论，处理结果会通过通知反馈。

### 2.2 创作者功能

- AI 草稿分析：对标题、摘要、标签和正文进行分析，返回文章摘要、推荐标签、内容评分、风险标签和修改建议。
- 建议改写：用户选择某条修改建议后，系统只围绕该建议改写文章，并展示修改理由和前后差异。
- AI 润色：采用“批评、改写、验证”的多阶段流程，对文章段落进行润色，并返回改进分数和句子级差异。
- 发布前初审：当文章内容评分过低或存在风险标签时，文章会进入待审核状态，由管理员复核。

### 2.3 管理员功能

- 平台概览：展示用户、文章、评论、待审核内容、隐藏内容、AI 审核数量和高风险内容等统计信息。
- 文章管理：支持文章搜索、状态筛选、隐藏和恢复。
- 评论管理：支持评论搜索、状态筛选、隐藏和恢复。
- AI 审核队列：集中展示需要人工复核的文章和评论，并展示模型给出的风险类别、风险等级、原因、建议修改内容和置信度。
- 举报处理：管理员可以处理用户举报，选择忽略、解决或隐藏内容。
- 审计日志与通知：管理员处理结果会写入审计日志，并向相关用户发送通知。

## 3. AI 机制说明

### 3.1 文章分析

文章分析服务接收标题、摘要、正文和标签，整理为提示词后调用本地大语言模型。模型返回结构化结果，后端再进行数据校验，确保结果包含文章摘要、推荐标签、内容评分、风险标签和修改建议。

当启用发布前审核时，内容评分低于 50 分或存在风险标签的文章不会直接公开，而是进入待审核状态。

### 3.2 文章润色

文章润色不是一次性改写，而是分为三个阶段：

1. 批评：模型根据用户指令指出原文问题。
2. 改写：模型根据问题生成润色版本。
3. 验证：模型检查润色结果是否解决问题，并给出改进分数。

润色最多运行两轮，提前停止阈值为 0.65。最终返回改进分数更高的版本，并生成句子级差异，方便用户决定是否应用。

### 3.3 文章库 RAG 问答

文章库助手采用 RAG 流程：

1. 根据用户问题生成查询向量。
2. 从文章库召回候选文章。
3. 对候选文章进行本地重排。
4. 将排序靠前的文章片段交给模型生成回答。
5. 校验模型引用的来源文章，避免出现不存在的引用。

本地重排会综合原始向量相似度、标题命中、标签命中、摘要命中和正文命中。标题命中权重最高，标签其次，摘要和正文再次。对于明显的测试文章或占位内容，系统会额外降权，避免无关测试数据排在真实相关文章之前。

### 3.4 相关推荐

相关推荐先进行向量召回，再进行模型重排。系统将文章标题、摘要、标签和正文拼接后生成向量，并用 pgvector 计算余弦相似度。

候选召回数量取“展示数量的 4 倍”和“20”中的较大值。重排阶段会让模型判断当前文章与候选文章在主题和阅读延续性上的相关程度。最终分数采用加权方式：

```text
最终分数 = 0.35 × 向量相似度分数 + 0.65 × 模型相关性分数
```

如果本地没有语义模型缓存，系统可以回退到确定性的哈希向量表示，保证演示和测试不因模型文件缺失而中断。

### 3.5 AI 审核

评论审核会把评论内容、所属文章和用户信息交给模型，返回是否允许发布、风险类别、风险等级、审核原因、建议修改内容和置信度。

文章审核复用文章分析结果，重点依据内容评分和风险标签判断是否进入人工复核。模型只负责初筛，最终通过或拒绝由管理员处理。

## 4. 目录说明

```text
app/services/ai/                         AI 服务层
app/api/routes/articles/                 文章、推荐、文章库问答相关接口
app/api/routes/comments.py               评论和评论审核接口
app/api/routes/admin.py                  管理员治理接口
app/db/migrations/versions/              数据库迁移
demo/                                    静态演示前端
scripts/seed_demo_data.py                演示数据初始化脚本
tests/test_services/                     AI 服务层测试
tests/test_api/test_routes/              API 路由测试
docs/26项目报告-完成版.docx              项目报告
```

## 5. 快速启动

以下命令按当前项目的本地开发环境编写。默认使用 PostgreSQL + pgvector，应用数据库为 `rwdb`，测试数据库为 `rwtest`。

### 5.1 准备 Python 环境

如果仓库中已有 `.venv`，可以直接使用现有虚拟环境。否则可用 Poetry 安装依赖：

```bash
poetry install
poetry shell
```

### 5.2 启动 PostgreSQL + pgvector

```bash
docker run --name rw-pgvector \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=rwdb \
  -p 127.0.0.1:15432:5432 \
  -d pgvector/pgvector:pg16
```

创建测试数据库：

```bash
docker exec rw-pgvector createdb -U postgres rwtest
```

如果容器已存在，只需要启动：

```bash
docker start rw-pgvector
```

### 5.3 配置环境变量

复制示例配置：

```bash
cp .env.example .env
```

关键配置如下：

```env
APP_ENV=dev
DEBUG=true
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwdb
SECRET_KEY=secret
ADMIN_USERNAMES=["admin"]

LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=
LLM_MODEL=qwen3-8b
LLM_TIMEOUT_SECONDS=30

EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSIONS=384
EMBEDDING_ALLOW_DOWNLOAD=false
EMBEDDING_FALLBACK_ENABLED=true

AI_COMMENT_MODERATION_MODE=block
AI_ARTICLE_REVIEW_ON_PUBLISH=true
AI_ARTICLE_MIN_CONTENT_SCORE=50
```

说明：

- `LLM_BASE_URL` 需要指向 OpenAI-compatible 的本地模型服务。
- 如果没有启动真实模型服务，稳定测试仍然可以运行，但前端中依赖真实模型的 AI 功能会不可用。
- `EMBEDDING_FALLBACK_ENABLED=true` 可以在本地没有语义模型缓存时使用哈希向量回退。

### 5.4 执行数据库迁移

```bash
DEBUG=true .venv/bin/alembic upgrade head
```

### 5.5 初始化演示数据

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwdb \
DEBUG=true .venv/bin/python scripts/seed_demo_data.py
```

### 5.6 启动后端

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwdb \
DEBUG=true .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

后端接口地址：

```text
http://127.0.0.1:8010/api
```

接口文档：

```text
http://127.0.0.1:8010/docs
```

### 5.7 启动静态演示前端

```bash
cd demo
../.venv/bin/python -m http.server 5174 --bind 127.0.0.1
```

前端访问地址：

```text
http://127.0.0.1:5174
```

如果端口被占用，可以将 `5174` 换成其他端口。

## 6. 测试命令

### 6.1 AI 服务层稳定测试

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwtest \
DEBUG=true .venv/bin/python -m pytest \
tests/test_services/test_ai_services.py \
tests/test_services/test_article_polish.py \
tests/test_services/test_cross_reranker.py \
-q --no-cov -n 0
```

本地验证结果：`28 passed`。

### 6.2 管理员与评论治理测试

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwtest \
DEBUG=true .venv/bin/python -m pytest \
tests/test_api/test_routes/test_admin.py \
tests/test_api/test_routes/test_comments.py \
-q --no-cov -n 0
```

本地验证结果：`20 passed`。

### 6.3 文章 AI 与文章库问答接口测试

不开真实 AI 时，真实接口调用用例会跳过：

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwtest \
DEBUG=true .venv/bin/python -m pytest \
tests/test_api/test_routes/test_articles.py::test_user_can_analyze_article_with_ai \
tests/test_api/test_routes/test_articles.py::test_user_can_get_recommended_articles \
tests/test_api/test_routes/test_articles.py::test_user_can_ask_article_library_ai \
tests/test_api/test_routes/test_articles.py::test_user_can_get_recommendations_with_embedding_fallback \
tests/test_api/test_routes/test_articles_real_ai.py \
-q --no-cov -n 0
```

本地验证结果：`4 passed, 2 skipped`。

如果本地大语言模型服务已启动，可以开启真实 AI 调用：

```bash
RUN_REAL_AI_TESTS=1 \
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwtest \
DEBUG=true .venv/bin/python -m pytest \
tests/test_api/test_routes/test_articles.py::test_user_can_analyze_article_with_ai \
tests/test_api/test_routes/test_articles.py::test_user_can_get_recommended_articles \
tests/test_api/test_routes/test_articles.py::test_user_can_ask_article_library_ai \
tests/test_api/test_routes/test_articles.py::test_user_can_get_recommendations_with_embedding_fallback \
tests/test_api/test_routes/test_articles_real_ai.py \
-q --no-cov -n 0
```

### 6.4 真实 AI 服务层测试

该测试直接调用本地模型服务，默认不运行。

```bash
RUN_REAL_AI_TESTS=1 \
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwtest \
DEBUG=true .venv/bin/python -m pytest \
tests/test_services/test_real_ai_integration.py \
-q --no-cov -n 0
```

## 7. 演示建议

推荐按以下顺序向老师展示：

1. 打开文章列表和文章详情，展示普通阅读流程。
2. 点击顶部文章库助手图标，输入自然语言问题，展示 RAG 问答和来源文章跳转。
3. 进入写作页，展示草稿分析、建议改写和 AI 润色。
4. 进入管理员页面，展示平台概览、待审核队列、文章/评论管理、举报处理、审计日志和通知。
5. 运行上方三组测试命令，截图命令行结果和代表性测试代码。

## 8. 备注

- 原项目说明仍保留在 `README.md`。
- 本文件是课程项目拓展版说明，适合上传 GitHub 后供老师快速了解改动内容。
- 真实 AI 测试依赖本地 OpenAI-compatible 模型服务；如果模型服务未启动，请使用稳定测试命令或先启动模型服务。
