# SurveyHub Phase 2 · 题库与版本控制

华东师范大学 2026《数据管理系统》课程 Project 1 **第二阶段**作业 · 第六组

---

## 需求变更背景

Phase 1 完成了基础问卷系统的全部功能。Phase 2 基于用户反馈，新增以下核心能力：

| # | 需求 | 说明 |
|---|------|------|
| 1 | **题目库（Question Bank）** | 保存常用题目，可跨问卷复用 |
| 2 | **题目共享** | 将题目分享给指定用户 |
| 3 | **发布后不可变** | 已发布问卷中的题目不受后续修改影响 |
| 4 | **修改历史** | 记录题目的所有历史版本，支持查看与"基于旧版创建" |
| 5 | **版本分叉** | 同一题目的不同版本可独立存在于不同问卷 |
| 6 | **使用情况追踪** | 查看某题目被哪些问卷引用 |
| 7 | **题库管理 UI** | 完整的题目库界面，支持创建、版本、分享、删除 |
| 8 | **跨问卷统计** | 汇总同一题目在所有问卷中的回答数据 |

---

## 核心设计思路

### 版本控制模型

每个题目版本是 `bank_questions` 集合中的一个独立文档：

```
v1 (q_template_id = v1._id, parent_id = null)
 └─ v2 (q_template_id = v1._id, parent_id = v1._id)
     └─ v3 (q_template_id = v1._id, parent_id = v2._id)
```

- `q_template_id`：同族所有版本共享，作为"逻辑题目"的标识
- `parent_id`：指向上一版本的 `_id`，构成可追溯的版本链
- 创建"新版本"实质是 `fork` 操作：插入新文档，不修改已有文档

### 不可变性保证

问卷发布时，`surveys.questions` 数组中存储的是**完整快照**（包含题目全部字段），同时记录 `bank_question_id`（指向某个具体版本）和 `q_template_id`（用于跨问卷聚合）。

日后即使题目产生了 v2、v3，已发布问卷引用的仍是快照中的原始数据，**原有回答数据完全不受影响**。

### 跨问卷统计

通过 `q_template_id` 找到同族所有版本，再找到引用这些版本的所有问卷，最后聚合对应 `q_id` 的所有回答数据，实现跨问卷维度的统计。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 数据库 | MongoDB（PyMongo） |
| 后端 | Python 3.11 + Flask |
| 密码安全 | Bcrypt |
| 前端 | 原生 HTML5 + CSS3 + JavaScript（Fetch API，无框架） |

---

## 快速启动

### 1. 安装依赖

```bash
pip install flask pymongo bcrypt
```

### 2. 启动 MongoDB

确保本地 MongoDB 服务在 `mongodb://localhost:27017/` 正常运行。

### 3. 启动后端

```bash
cd "Phase 2"
python app.py
```

浏览器访问 `http://127.0.0.1:5000`

> Phase 2 与 Phase 1 共用同一数据库 `survey_system`，Phase 1 的数据可继续使用。

---

## 数据库设计

### 新增集合：`bank_questions`

```json
{
  "_id": ObjectId,
  "q_template_id": "string",        // 逻辑题目 ID（所有版本共享）
  "version": 1,                      // 版本号（整数，从 1 开始）
  "parent_id": "string | null",      // 上一版本的 _id
  "creator_id": "string",
  "creator_name": "string",
  "title": "string",
  "type": "single_choice | multi_choice | text_fill | number_fill",
  "options": ["选项A", "选项B"],
  "min_select": 1,
  "max_select": 3,
  "min": 0,
  "max": 120,
  "is_required": false,
  "is_public": false,
  "shared_with": ["user_id1"],
  "shared_with_names": {"user_id1": "alice"},
  "tags": ["人口统计"],
  "created_at": ISODate
}
```

### `surveys.questions` 新增字段（Phase 2 扩展）

```json
{
  "q_id": "q1",
  "bank_question_id": "ObjectId string",  // 引用的题库版本
  "q_template_id": "string",              // 用于跨问卷聚合
  "type": "...",                          // 以下为题目快照（不可变）
  "title": "...",
  "options": [],
  ...
}
```

---

## API 接口一览

### Phase 1 原有接口（完全保留）

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/register` | 用户注册 |
| POST | `/api/login` | 用户登录 |
| POST | `/api/logout` | 退出登录 |
| GET  | `/api/me` | 获取当前用户 |
| GET  | `/api/my_surveys` | 我的问卷列表 |
| POST | `/api/surveys` | 创建问卷（支持题库引用） |
| GET  | `/api/surveys/<id>` | 获取问卷详情 |
| DELETE | `/api/surveys/<id>` | 删除问卷 |
| PATCH | `/api/surveys/<id>/status` | 修改问卷状态 |
| POST | `/api/surveys/<id>/submit` | 提交答卷 |
| GET  | `/api/surveys/<id>/stats` | 问卷统计 |

### Phase 2 新增接口

| 方法 | 路径 | 功能 |
|------|------|------|
| GET  | `/api/question_bank` | 获取可见题目列表 |
| POST | `/api/question_bank` | 创建新题目（v1） |
| GET  | `/api/question_bank/<id>` | 获取题目详情 |
| DELETE | `/api/question_bank/<id>` | 删除题目（未被引用时） |
| POST | `/api/question_bank/<id>/fork` | 基于此版本创建新版本 |
| GET  | `/api/question_bank/<id>/history` | 获取版本历史链 |
| POST | `/api/question_bank/<id>/share` | 分享给指定用户 |
| DELETE | `/api/question_bank/<id>/share/<uid>` | 取消分享 |
| GET  | `/api/question_bank/<id>/usage` | 查看使用的问卷 |
| GET  | `/api/question_bank/<id>/cross_stats` | 跨问卷聚合统计 |

---

## 关键逻辑说明

### 版本不可变性

`fork` 接口只做 **插入**，永远不修改已有文档。这保证了：
1. 已发布问卷引用的 `bank_question_id` 对应版本数据永远不变
2. 可以安全地查看任意旧版本的原始内容
3. 每个版本的使用次数统计独立准确

### 共享机制

分享基于"版本"粒度（`bank_question_id`）：
- 共享 v1 不会自动共享 v2（但 `fork` 会继承 `shared_with` 列表）
- `shared_with_names` 字典同步维护 uid → username 映射，便于 UI 展示

### 跨问卷聚合

```
q_template_id → 所有版本 → 所有引用这些版本的问卷
→ 在每份问卷的 responses 中找到对应 q_id 的答案
→ 按题型汇总（选项计票 / 数字统计 / 文本列表）
```

这充分利用了 MongoDB 文档模型的灵活性：`q_template_id` 作为逻辑外键，无需数据库层面的 JOIN，在应用层完成聚合。
