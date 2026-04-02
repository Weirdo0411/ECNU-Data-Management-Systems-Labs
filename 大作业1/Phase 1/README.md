# 基于 MongoDB 的全功能动态问卷系统 (SurveyHub)

华东师范大学 2026《数据管理系统》课程 Project 1 第一阶段作业

## 项目简介

本项目是一个功能完备的在线问卷系统，以 Python Flask 为后端、MongoDB 为数据库、原生 HTML5/CSS3/JavaScript 为前端，充分体现了 NoSQL 文档型数据库在**处理动态不规则数据**上的核心优势。

## 核心特性

| 特性 | 说明 |
|------|------|
| 动态 Schema-free 设计 | 题型、选项、校验规则全部动态内嵌在单份问卷文档中，无需多表联查 |
| 四种题型支持 | 单选题、多选题（含选项数量上下限）、文本填空、数字填空（含数值范围） |
| 跳转逻辑 | 前端实时解析 `选项->目标题ID` 规则，自动隐藏沿途题目 |
| 后端严格校验 | 必填、多选上下限、数字范围均在后端再次验证，防止脏数据写入 |
| 问卷全生命周期管理 | 发布 / 关闭 / 重开 / 删除，支持匿名填写 |
| 可分享链接 | 每份问卷生成独立访问 URL `/survey/<id>`，无需登录即可填写 |
| MongoDB 聚合统计 | `$unwind` 管道展开答案数组，按题型分别统计；多选独立计票，数字题计算均值/最值 |
| 现代化 UI | 卡片布局、Toast 通知、可视化统计条形图，无 `alert()` 弹窗 |
| 密码安全 | Bcrypt 哈希加密存储 |

## 技术栈

- **数据库**：MongoDB（PyMongo）
- **后端**：Python 3.11 + Flask
- **密码安全**：Bcrypt
- **前端**：原生 HTML5 + CSS3 + JavaScript（Fetch API，无框架依赖）

## 快速启动

### 1. 安装依赖

```bash
pip install flask pymongo bcrypt
```

### 2. 启动 MongoDB

确保本地 MongoDB 服务已运行（默认监听 `mongodb://localhost:27017/`）。

### 3. 启动后端

```bash
python app.py
```

浏览器访问 `http://127.0.0.1:5000`

## 数据库设计（MongoDB Collections）

### `users` 集合

```json
{
  "_id": ObjectId,
  "username": "string",
  "password": "<bcrypt hash>",
  "created_at": ISODate
}
```

### `surveys` 集合（Schema-free 核心）

```json
{
  "_id": ObjectId,
  "title": "string",
  "description": "string",
  "creator_id": "string (ObjectId ref)",
  "status": "published | closed",
  "created_at": ISODate,
  "questions": [
    {
      "q_id": "q1",
      "type": "single_choice | multi_choice | text_fill | number_fill",
      "title": "string",
      "is_required": true,
      "options": ["选项A", "选项B"],
      "min_select": 1,
      "max_select": 3,
      "min": 0,
      "max": 120,
      "jump_logic": "选项A->q3, 选项B->q5"
    }
  ]
}
```

### `responses` 集合

```json
{
  "_id": ObjectId,
  "survey_id": "string (ObjectId ref)",
  "user_id": "string | null",
  "submitted_at": ISODate,
  "answers": [
    {"q_id": "q1", "value": "选项A"},
    {"q_id": "q2", "value": ["选项1", "选项3"]},
    {"q_id": "q3", "value": "22"}
  ]
}
```

## API 接口说明

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/register` | 用户注册 |
| POST | `/api/login` | 用户登录 |
| POST | `/api/logout` | 退出登录 |
| GET  | `/api/me` | 获取当前登录用户信息 |
| GET  | `/api/my_surveys` | 获取当前用户的问卷列表（含回复数统计）|
| POST | `/api/surveys` | 创建并发布新问卷 |
| GET  | `/api/surveys/<id>` | 获取问卷详情（公开）|
| DELETE | `/api/surveys/<id>` | 删除问卷及所有答卷 |
| PATCH | `/api/surveys/<id>/status` | 修改问卷状态（published/closed）|
| POST | `/api/surveys/<id>/submit` | 提交答卷（含后端校验）|
| GET  | `/api/surveys/<id>/stats` | 获取问卷统计数据（仅创建者）|

## 关键逻辑说明

### 为何使用 MongoDB

问卷系统的每份问卷题目数量、题型、选项、校验规则各不相同，属于典型的动态不规则数据。若使用关系型数据库，需要设计复杂的 EAV（属性-值）多表结构，查询成本高；而 MongoDB 的文档模型允许将整套问卷（含所有题目规则）直接嵌入一个文档，**一次查询即可获取完整信息**，天然契合这类场景。

### 跳转逻辑实现

跳转规则以字符串形式（如 `男->q3`）保存在 `jump_logic` 字段中。前端 `evalLogic()` 函数在用户每次交互后遍历题目列表，若当前已作答题目触发了跳转规则，则将目标 ID 之前的所有题目隐藏（`display:none`），且提交时跳过隐藏题目，不收集其数据。

### 统计聚合管道

```
$match (survey_id) → $unwind ($answers) → Python 分题型统计
```

`$unwind` 将每份答卷中的 `answers` 数组展开为独立文档，使多选题的每个被选选项都能独立计票，避免了应用层循环嵌套，充分发挥 MongoDB 聚合管道的能力。
