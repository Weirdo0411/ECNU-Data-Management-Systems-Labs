from flask import Flask, request, jsonify, render_template, session, Response
from pymongo import MongoClient
from bson import ObjectId
from bson.errors import InvalidId
import bcrypt
import datetime
import json

app = Flask(__name__)
app.secret_key = 'ecnu_survey_super_secret_key_2026'

# ==================== 数据库连接 ====================
client = MongoClient("mongodb://localhost:27017/")
db = client["survey_system"]

# ==================== 页面路由 ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/survey/<survey_id>')
def survey_page(survey_id):
    """公开问卷填写页，无需登录，通过 JS 解析 URL 自动加载对应问卷"""
    return render_template('index.html')


# ==================== API 路由：用户模块 ====================

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码长度不能少于 6 位"}), 400
    if db.users.find_one({"username": username}):
        return jsonify({"error": "用户名已存在"}), 400

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    db.users.insert_one({
        "username": username,
        "password": hashed,
        "created_at": datetime.datetime.now()
    })
    return jsonify({"msg": "注册成功，请登录！"})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = db.users.find_one({"username": data.get('username', '')})
    if user and bcrypt.checkpw(data.get('password', '').encode('utf-8'), user['password']):
        session['user_id'] = str(user['_id'])
        session['username'] = user['username']
        return jsonify({"msg": "登录成功", "username": user['username']})
    return jsonify({"error": "用户名或密码错误"}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"msg": "已退出登录"})


@app.route('/api/me', methods=['GET'])
def get_me():
    if 'user_id' not in session:
        return jsonify({"error": "未登录"}), 401
    return jsonify({"username": session['username'], "user_id": session['user_id']})


# ==================== API 路由：问卷核心模块 ====================

@app.route('/api/my_surveys', methods=['GET'])
def get_my_surveys():
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401

    surveys = list(db.surveys.find(
        {"creator_id": session['user_id']},
        {"title": 1, "description": 1, "status": 1, "created_at": 1}
    ))
    for s in surveys:
        s['_id'] = str(s['_id'])
        if 'created_at' in s:
            s['created_at'] = s['created_at'].strftime('%Y-%m-%d %H:%M')
        s['response_count'] = db.responses.count_documents({"survey_id": s['_id']})
    return jsonify(surveys)


@app.route('/api/surveys', methods=['POST'])
def create_survey():
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401

    survey_data = request.json
    if not (survey_data.get('title') or '').strip():
        return jsonify({"error": "问卷标题不能为空"}), 400
    if not survey_data.get('questions'):
        return jsonify({"error": "问卷至少需要一道题目"}), 400

    survey_data['creator_id'] = session['user_id']
    survey_data['created_at'] = datetime.datetime.now()
    survey_data['status'] = 'published'

    survey_id = db.surveys.insert_one(survey_data).inserted_id
    return jsonify({"msg": "问卷发布成功", "survey_id": str(survey_id)})


@app.route('/api/surveys/<survey_id>', methods=['GET'])
def get_survey(survey_id):
    try:
        survey = db.surveys.find_one({"_id": ObjectId(survey_id)})
    except InvalidId:
        return jsonify({"error": "无效的问卷 ID"}), 400
    if not survey:
        return jsonify({"error": "问卷不存在"}), 404
    survey['_id'] = str(survey['_id'])
    return jsonify(survey)


@app.route('/api/surveys/<survey_id>', methods=['DELETE'])
def delete_survey(survey_id):
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        result = db.surveys.delete_one({
            "_id": ObjectId(survey_id),
            "creator_id": session['user_id']
        })
    except InvalidId:
        return jsonify({"error": "无效的问卷 ID"}), 400
    if result.deleted_count == 0:
        return jsonify({"error": "问卷不存在或无权限删除"}), 404
    db.responses.delete_many({"survey_id": survey_id})
    return jsonify({"msg": "问卷及其全部答卷已删除"})


@app.route('/api/surveys/<survey_id>/status', methods=['PATCH'])
def update_survey_status(survey_id):
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    data = request.json
    new_status = data.get('status')
    if new_status not in ('published', 'closed'):
        return jsonify({"error": "无效的状态值"}), 400
    try:
        result = db.surveys.update_one(
            {"_id": ObjectId(survey_id), "creator_id": session['user_id']},
            {"$set": {"status": new_status}}
        )
    except InvalidId:
        return jsonify({"error": "无效的问卷 ID"}), 400
    if result.matched_count == 0:
        return jsonify({"error": "问卷不存在或无权限操作"}), 404
    label = "已关闭" if new_status == 'closed' else "已重新开放"
    return jsonify({"msg": f"问卷{label}"})


# ==================== API 路由：填写与统计模块 ====================

@app.route('/api/surveys/<survey_id>/submit', methods=['POST'])
def submit_response(survey_id):
    try:
        survey = db.surveys.find_one({"_id": ObjectId(survey_id)})
    except InvalidId:
        return jsonify({"error": "无效的问卷 ID"}), 400

    if not survey:
        return jsonify({"error": "问卷不存在"}), 404
    if survey.get('status') == 'closed':
        return jsonify({"error": "该问卷已关闭，不再接受填写"}), 403

    data = request.json
    answers = data.get('answers', [])

    # 遍历问卷规则，在后端进行严格校验
    for q in survey['questions']:
        ans = next((item for item in answers if item["q_id"] == q["q_id"]), None)
        val = ans.get('value') if ans else None

        # 必填校验
        if q.get('is_required') and (val is None or val == '' or val == []):
            return jsonify({"error": f"「{q['title']}」为必填项，请完成填写"}), 400

        if val is not None and val != '':
            # 多选题数量上下限校验
            if q['type'] == 'multi_choice' and isinstance(val, list):
                if 'min_select' in q and len(val) < q['min_select']:
                    return jsonify({"error": f"「{q['title']}」至少需要选择 {q['min_select']} 项"}), 400
                if 'max_select' in q and len(val) > q['max_select']:
                    return jsonify({"error": f"「{q['title']}」最多只能选择 {q['max_select']} 项"}), 400

            # 数字填空范围校验
            if q['type'] == 'number_fill':
                try:
                    num_val = float(val)
                    if 'min' in q and num_val < q['min']:
                        return jsonify({"error": f"「{q['title']}」的值不能小于 {q['min']}"}), 400
                    if 'max' in q and num_val > q['max']:
                        return jsonify({"error": f"「{q['title']}」的值不能大于 {q['max']}"}), 400
                except (ValueError, TypeError):
                    return jsonify({"error": f"「{q['title']}」必须填写纯数字"}), 400

    db.responses.insert_one({
        "survey_id": survey_id,
        "user_id": session.get('user_id'),  # 未登录时为 None（匿名提交）
        "answers": answers,
        "submitted_at": datetime.datetime.now()
    })
    return jsonify({"msg": "答卷提交成功！感谢您的参与。"})


@app.route('/api/surveys/<survey_id>/stats', methods=['GET'])
def get_stats(survey_id):
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401

    try:
        survey = db.surveys.find_one({"_id": ObjectId(survey_id)})
    except InvalidId:
        return jsonify({"error": "无效的问卷 ID"}), 400
    if not survey:
        return jsonify({"error": "问卷不存在"}), 404
    if survey.get('creator_id') != session['user_id']:
        return jsonify({"error": "仅问卷创建者可查看统计数据"}), 403

    q_map = {q['q_id']: q for q in survey.get('questions', [])}
    total_responses = db.responses.count_documents({"survey_id": survey_id})

    # MongoDB 聚合管道：$unwind 展开每份答卷中的 answers 数组
    pipeline = [
        {"$match": {"survey_id": survey_id}},
        {"$unwind": "$answers"}
    ]
    unwound_answers = list(db.responses.aggregate(pipeline))

    # 按题型初始化结果结构，并为选择题预填所有选项为 0
    result = {}
    for q_id, q in q_map.items():
        if q['type'] == 'number_fill':
            result[q_id] = {"title": q['title'], "type": "number_fill",
                            "_raw_values": [], "avg": 0, "count": 0, "values": []}
        elif q['type'] == 'text_fill':
            result[q_id] = {"title": q['title'], "type": "text_fill", "values": []}
        else:
            result[q_id] = {"title": q['title'], "type": q['type'],
                            "options": {opt: 0 for opt in q.get('options', [])},
                            "answered": 0}

    # 填充数据
    for doc in unwound_answers:
        ans = doc.get('answers', {})
        q_id = ans.get('q_id')
        val = ans.get('value')
        if not q_id or q_id not in q_map:
            continue
        q_type = q_map[q_id]['type']

        if q_type == 'number_fill':
            try:
                result[q_id]["_raw_values"].append(float(val))
            except (ValueError, TypeError):
                pass
        elif q_type == 'text_fill':
            if val:
                result[q_id]["values"].append(str(val))
        else:
            # 单选/多选：多选题需将列表中每个选项独立计票
            result[q_id]["answered"] += 1
            items = val if isinstance(val, list) else [str(val)] if val is not None else []
            for v in items:
                result[q_id]["options"][v] = result[q_id]["options"].get(v, 0) + 1

    # 对数字题计算统计量，清理内部字段
    for q_id, stats in result.items():
        if stats.get("type") == "number_fill":
            raw = stats.pop("_raw_values")
            if raw:
                stats["count"] = len(raw)
                stats["avg"] = round(sum(raw) / len(raw), 2)
                stats["min"] = round(min(raw), 2)
                stats["max"] = round(max(raw), 2)
                stats["values"] = [round(v, 2) for v in raw]

    output = {
        "survey_title": survey['title'],
        "total_responses": total_responses,
        "questions": result
    }
    return Response(
        json.dumps(output, ensure_ascii=False, indent=2),
        mimetype='application/json; charset=utf-8'
    )


if __name__ == '__main__':
    app.run(debug=True)
