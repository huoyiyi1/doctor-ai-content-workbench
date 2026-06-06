# 医生公众号 AI 内容工作台

这是第一版可演示产品，用于本地运行。

它帮助医生或运营人员把「脱敏科普卡」整理成公众号文章，并完成风险审核、文章编辑、图片提示词生成和 Raphael 排版预览。

第一版不接：

- 飞书 API
- GPT Image API
- 公众号 API
- 自动发布
- 登录系统

## 核心边界

- 不处理原始心理咨询记录。
- 不使用真实来访者故事。
- 不做诊断。
- 不给药物建议。
- 不承诺疗效。
- 不制造焦虑。
- 不输出 `<think>`、`Thinking Process`、`推理过程`。
- 未审核通过，不进入排版发布页。
- 第一版只生成图片提示词，不生成图片。

正文结尾必须包含：

```text
本文由 AI 辅助整理，医生审核后发布。
本文仅作心理健康科普，不替代诊断、治疗或个体化心理咨询。
```

## 如何运行

在项目文件夹中运行：

```bash
pip install -r requirements.txt
streamlit run app.py
```

如果你使用本项目自带的虚拟环境，可以运行：

```bash
.venv/bin/streamlit run app.py
```

启动后打开本地网页：

```text
http://127.0.0.1:8501
```

## 如何部署给别人试用

当前项目已经支持两种运行方式：

- 本地运行：默认使用 `data/tasks.db` SQLite 数据库。
- 云端部署：如果配置了 `DATABASE_URL`，系统会自动使用 Postgres 数据库。

给别人试用时，推荐使用云端部署，不要再依赖你电脑上的 `127.0.0.1`。

### 方案 A：Streamlit Community Cloud，最快演示

适合：先发给少量朋友、同事、医生看演示。

步骤：

1. 把项目上传到 GitHub。
2. 确认不要上传 `.env`、`.streamlit/secrets.toml`、`data/tasks.db`、`outputs/*.md`。
3. 打开 Streamlit Community Cloud，新建 App。
4. 选择 GitHub 仓库。
5. 入口文件填写：

```text
app.py
```

6. 在 Streamlit Cloud 的 Secrets 中填写：

```toml
DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
DEEPSEEK_API_BASE = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 演示期可以先留空；多人连续试用建议填写外部 Postgres。
DATABASE_URL = ""
```

部署完成后，你会得到一个类似下面的公开地址：

```text
https://你的应用名.streamlit.app
```

注意：如果 `DATABASE_URL` 留空，云端会退回使用本地 SQLite。这个方式适合短期演示，但云端重启后数据可能丢失，不适合作为长期试用数据库。

### 方案 B：Streamlit Cloud + Supabase Postgres，推荐给别人连续试用

适合：你希望别人连续使用，任务数据不要因为云端重启而丢失。

步骤：

1. 创建一个 Supabase 项目。
2. 复制 Supabase 的 Postgres 连接串。
3. 在 Streamlit Cloud Secrets 中填写：

```toml
DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
DEEPSEEK_API_BASE = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
DATABASE_URL = "postgresql://用户名:密码@主机:端口/数据库名"
```

应用启动时会自动创建和迁移 `tasks` 表。

### 方案 C：Render，一体化部署

适合：你希望更接近正式产品部署。

项目里已经提供了 `render.yaml`。

步骤：

1. 把项目上传到 GitHub。
2. 在 Render 创建 Web Service。
3. 选择当前仓库。
4. Render 会读取 `render.yaml`。
5. 在 Render Environment Variables 里填写：

```text
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=你的 Postgres 连接串
```

Render 部署完成后，会生成一个公开 URL，可以直接发给别人试用。

## 部署前检查清单

上传 GitHub 前，确认：

- `.env` 没有上传。
- `.streamlit/secrets.toml` 没有上传。
- `.env.example` 里没有真实 API Key。
- `data/tasks.db` 没有上传。
- `outputs` 里没有真实业务内容。
- `input/tasks.csv` 里没有真实患者或来访者信息。

## DeepSeek 配置

确认 `.env` 里有：

```env
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=
```

不要把 `.env` 发给别人。

## 页面结构

界面设计和交互统一遵循：[医生公众号 AI 内容工作台设计规范](docs/design_guidelines.md)。

### 1. 新建文章页

只展示脱敏科普卡表单和“保存文章任务”按钮：

- article_topic：文章主题
- target_reader：目标读者
- doctor_name：医生署名
- safe_scene：脱敏场景
- common_misunderstanding：常见误区
- doctor_viewpoint：医生核心观点
- forbidden_info：禁止出现的信息
- risk_tags：风险标签
- writing_style：文章风格
- article_length：文章长度
- image_style：图片风格
- layout_style：排版风格

### 2. 任务列表页

查看所有文章任务、状态、风险等级和更新时间。

也可以选中一条任务进行统一管理：

- 打开任务详情 / 编辑页
- 快速编辑任务基础信息
- 删除整条任务

删除任务时，页面会展示即将删除的任务编号和文章主题。勾选“我理解删除后不可恢复”后，点击“删除该任务”即可删除。删除后，整条任务数据不可找回。

页面顶部有模块导航，会显示当前所在模块。列表页打开详情、医生审核通过进入排版等动作，会自动跳转到对应模块。

### 3. 任务详情 / 编辑页

可以完成：

- 生成文案
- 编辑标题、摘要、正文 Markdown
- 查看封面图提示词
- 查看正文配图提示词列表
- 查看风险审核报告
- 一键美化排版
- 重新生成排版
- 恢复原始 Markdown
- 复制美化 Markdown
- 输入修改意见，让 AI 定向优化全文
- 重新生成标题
- 重新生成摘要
- 重新生成图片提示词
- 提交医生审核
- 审核通过，进入排版

### 4. 排版发布页

医生审核通过后才能进入。

页面提供：

- 最终 Markdown，默认使用美化后的 `polished_markdown`
- 如果还没有美化版本，则自动使用 `original_markdown`
- 复制 Markdown 按钮
- 打开 Raphael 按钮
- 右侧 Raphael iframe 尝试内嵌
- 标记已复制到 Raphael
- 标记已粘贴公众号
- 标记已发布

Raphael 地址：

```text
https://publish.raphael.app
```

如果右侧无法显示，请点击“打开 Raphael”新窗口使用。

如果右侧 iframe 中选择款式、设备预览按钮没有反应，也属于第三方 iframe 限制。完整操作建议使用“打开 Raphael（新窗口，推荐）”。

## 任务状态

- 待输入
- 已生成
- 待修改
- 待审核
- 审核通过
- 排版中
- 已复制到 Raphael
- 已粘贴公众号
- 已发布

## 数据保存在哪里

任务保存在本地 SQLite：

```text
data/tasks.db
```

如果部署时设置了 `DATABASE_URL`，任务会保存到外部 Postgres，不再依赖本地 SQLite。

正文会保存两个版本：

- `original_markdown`：DeepSeek 初次生成或人工编辑后的原始正文。
- `polished_markdown`：经过“排版美化”后的正文，复制到 Raphael 时优先使用。

Markdown 交付包保存在：

```text
outputs/{task_id}_完整交付包.md
```

如果数据库为空，系统会从 `input/tasks.csv` 导入一次旧任务。之后主要使用 SQLite。

## 演示流程

1. 打开“新建文章页”，填写一个脱敏科普卡。
2. 到“任务详情 / 编辑页”，点击“生成文案”。
3. 查看标题、摘要、正文 Markdown、图片提示词和风险审核报告。
4. 点击“一键美化排版”，生成更适合 Raphael 的美化 Markdown。
5. 如需调整，输入修改意见，点击“根据修改意见优化全文”。
6. 医生确认内容安全后，点击“提交医生审核”。
7. 点击“审核通过，进入排版”。
8. 到“排版发布页”，复制 Markdown。
9. 点击“打开 Raphael”，粘贴 Markdown 做公众号排版预览。
10. 根据实际进度标记“已复制到 Raphael”“已粘贴公众号”“已发布”。

一句话原则：

AI 负责辅助生成和优化，医生负责专业审核，Raphael 负责排版预览，最终发布必须由人工完成。
