from flask import Flask, request, jsonify, render_template, session, Response
from pymongo import MongoClient, DESCENDING, ASCENDING
from bson import ObjectId
from bson.errors import InvalidId
import bcrypt
import datetime
import json

app = Flask(__name__)
app.secret_key = 'ecnu_survey_super_secret_key_2026_p2'

# ==================== 数据库连接 ====================
client = MongoClient("mongodb://localhost:27017/")
db = client["survey_system"]


# ==================== 页面路由 ====================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/survey/<survey_id>')
def survey_page(survey_id):
    return render_template('index.html')


# ==================== 用户模块 ====================

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


# ==================== 问卷核心模块 ====================

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

    uid = session['user_id']
    # 验证题库引用权限
    for q in survey_data.get('questions', []):
        bq_id = q.get('bank_question_id')
        if bq_id:
            try:
                bq = db.bank_questions.find_one({"_id": ObjectId(bq_id)})
            except Exception:
                return jsonify({"error": "无效的题库引用 ID"}), 400
            if not bq:
                return jsonify({"error": "引用的题库题目不存在"}), 404
            if (bq['creator_id'] != uid and
                    uid not in bq.get('shared_with', []) and
                    not bq.get('is_public', False)):
                return jsonify({"error": "您无权使用该题库题目"}), 403

    survey_data['creator_id'] = uid
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

    for q in survey['questions']:
        ans = next((item for item in answers if item["q_id"] == q["q_id"]), None)
        val = ans.get('value') if ans else None
        if q.get('is_required') and (val is None or val == '' or val == []):
            return jsonify({"error": f"「{q['title']}」为必填项，请完成填写"}), 400
        if val is not None and val != '':
            if q['type'] == 'multi_choice' and isinstance(val, list):
                if 'min_select' in q and len(val) < q['min_select']:
                    return jsonify({"error": f"「{q['title']}」至少需要选择 {q['min_select']} 项"}), 400
                if 'max_select' in q and len(val) > q['max_select']:
                    return jsonify({"error": f"「{q['title']}」最多只能选择 {q['max_select']} 项"}), 400
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
        "user_id": session.get('user_id'),
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

    pipeline = [
        {"$match": {"survey_id": survey_id}},
        {"$unwind": "$answers"}
    ]
    unwound_answers = list(db.responses.aggregate(pipeline))

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
            result[q_id]["answered"] += 1
            items = val if isinstance(val, list) else [str(val)] if val is not None else []
            for v in items:
                result[q_id]["options"][v] = result[q_id]["options"].get(v, 0) + 1

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


# ==================== 题库模块（Phase 2 新增）====================

@app.route('/api/question_bank', methods=['GET'])
def get_question_bank():
    """获取当前用户可见的所有题目（自己创建的 + 被分享的 + 公开的）"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    uid = session['user_id']
    questions = list(db.bank_questions.find(
        {"$or": [
            {"creator_id": uid},
            {"shared_with": uid},
            {"is_public": True}
        ]},
        sort=[("created_at", DESCENDING)]
    ))
    result = []
    for q in questions:
        q['_id'] = str(q['_id'])
        if 'created_at' in q:
            q['created_at'] = q['created_at'].strftime('%Y-%m-%d %H:%M')
        q['usage_count'] = db.surveys.count_documents(
            {"questions.bank_question_id": q['_id']}
        )
        q['is_owner'] = (q['creator_id'] == uid)
        result.append(q)
    return jsonify(result)


@app.route('/api/question_bank', methods=['POST'])
def create_bank_question():
    """创建新题目并加入题库（版本号 v1，q_template_id 自引用）"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    data = request.json
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({"error": "题目标题不能为空"}), 400
    q_type = data.get('type', '')
    if q_type not in ('single_choice', 'multi_choice', 'text_fill', 'number_fill'):
        return jsonify({"error": "无效的题型"}), 400

    doc = {
        "creator_id": session['user_id'],
        "creator_name": session['username'],
        "title": title,
        "type": q_type,
        "options": data.get('options', []),
        "is_required": bool(data.get('is_required', False)),
        "shared_with": [],
        "shared_with_names": {},
        "is_public": bool(data.get('is_public', False)),
        "created_at": datetime.datetime.now(),
        "version": 1,
        "parent_id": None,
        "q_template_id": None,
        "tags": data.get('tags', [])
    }
    if q_type == 'multi_choice':
        if data.get('min_select') is not None:
            doc['min_select'] = int(data['min_select'])
        if data.get('max_select') is not None:
            doc['max_select'] = int(data['max_select'])
    if q_type == 'number_fill':
        if data.get('min') is not None:
            doc['min'] = float(data['min'])
        if data.get('max') is not None:
            doc['max'] = float(data['max'])

    inserted = db.bank_questions.insert_one(doc)
    q_id = str(inserted.inserted_id)
    # q_template_id 自引用，标识同一逻辑题目的所有版本
    db.bank_questions.update_one(
        {"_id": inserted.inserted_id},
        {"$set": {"q_template_id": q_id}}
    )
    return jsonify({"msg": "题目已保存到题库", "q_id": q_id})


@app.route('/api/question_bank/<q_id>', methods=['GET'])
def get_bank_question(q_id):
    """获取某个题库题目的详情"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        q = db.bank_questions.find_one({"_id": ObjectId(q_id)})
    except InvalidId:
        return jsonify({"error": "无效的ID"}), 400
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    uid = session['user_id']
    if (q['creator_id'] != uid and
            uid not in q.get('shared_with', []) and
            not q.get('is_public', False)):
        return jsonify({"error": "无权访问此题目"}), 403
    q['_id'] = str(q['_id'])
    if 'created_at' in q:
        q['created_at'] = q['created_at'].strftime('%Y-%m-%d %H:%M')
    return jsonify(q)


@app.route('/api/question_bank/<q_id>/fork', methods=['POST'])
def fork_bank_question(q_id):
    """基于某题目版本创建新版本（仅原始创建者可操作，继承 q_template_id）"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        parent = db.bank_questions.find_one({"_id": ObjectId(q_id)})
    except InvalidId:
        return jsonify({"error": "无效的ID"}), 400
    if not parent:
        return jsonify({"error": "原题目不存在"}), 404

    uid = session['user_id']
    template_id = parent['q_template_id']
    # 仅允许该题目模板的原始创建者（v1 的创建者）创建新版本
    root_q = db.bank_questions.find_one({"q_template_id": template_id, "version": 1})
    if root_q and root_q['creator_id'] != uid:
        return jsonify({"error": "只有题目创建者才能创建新版本"}), 403

    data = request.json or {}
    max_doc = db.bank_questions.find_one(
        {"q_template_id": template_id},
        sort=[("version", DESCENDING)]
    )
    new_version = (max_doc['version'] if max_doc else 0) + 1

    q_type = data.get('type', parent['type'])
    doc = {
        "creator_id": uid,
        "creator_name": session['username'],
        "title": (data.get('title') or parent['title']).strip(),
        "type": q_type,
        "options": data.get('options', parent.get('options', [])),
        "is_required": bool(data.get('is_required', parent.get('is_required', False))),
        "shared_with": list(parent.get('shared_with', [])),
        "shared_with_names": dict(parent.get('shared_with_names', {})),
        "is_public": bool(data.get('is_public', parent.get('is_public', False))),
        "created_at": datetime.datetime.now(),
        "version": new_version,
        "parent_id": q_id,
        "q_template_id": template_id,
        "tags": data.get('tags', parent.get('tags', []))
    }
    if q_type == 'multi_choice':
        if 'min_select' in data and data['min_select'] is not None:
            doc['min_select'] = int(data['min_select'])
        elif 'min_select' in parent:
            doc['min_select'] = parent['min_select']
        if 'max_select' in data and data['max_select'] is not None:
            doc['max_select'] = int(data['max_select'])
        elif 'max_select' in parent:
            doc['max_select'] = parent['max_select']
    if q_type == 'number_fill':
        if 'min' in data and data['min'] is not None:
            doc['min'] = float(data['min'])
        elif 'min' in parent:
            doc['min'] = parent['min']
        if 'max' in data and data['max'] is not None:
            doc['max'] = float(data['max'])
        elif 'max' in parent:
            doc['max'] = parent['max']

    inserted = db.bank_questions.insert_one(doc)
    return jsonify({
        "msg": f"已创建新版本 v{new_version}",
        "q_id": str(inserted.inserted_id),
        "version": new_version
    })


@app.route('/api/question_bank/<q_id>', methods=['DELETE'])
def delete_bank_question(q_id):
    """删除题库题目（仅限创建者且未被任何问卷引用）"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        q = db.bank_questions.find_one({"_id": ObjectId(q_id)})
    except InvalidId:
        return jsonify({"error": "无效的ID"}), 400
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    if q['creator_id'] != session['user_id']:
        return jsonify({"error": "只有创建者才能删除题目"}), 403
    usage = db.surveys.count_documents({"questions.bank_question_id": q_id})
    if usage > 0:
        return jsonify({"error": f"该题目已被 {usage} 份问卷引用，无法删除。请先移除问卷中的引用。"}), 400
    db.bank_questions.delete_one({"_id": ObjectId(q_id)})
    return jsonify({"msg": "题目已从题库删除"})


@app.route('/api/question_bank/<q_id>/history', methods=['GET'])
def get_question_history(q_id):
    """获取某题目的所有历史版本（按版本号升序）"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        q = db.bank_questions.find_one({"_id": ObjectId(q_id)})
    except InvalidId:
        return jsonify({"error": "无效的ID"}), 400
    if not q:
        return jsonify({"error": "题目不存在"}), 404

    template_id = q['q_template_id']
    versions = list(db.bank_questions.find(
        {"q_template_id": template_id},
        sort=[("version", ASCENDING)]
    ))
    result = []
    for v in versions:
        v['_id'] = str(v['_id'])
        if 'created_at' in v:
            v['created_at'] = v['created_at'].strftime('%Y-%m-%d %H:%M')
        v['usage_count'] = db.surveys.count_documents(
            {"questions.bank_question_id": v['_id']}
        )
        result.append(v)
    return jsonify(result)


@app.route('/api/question_bank/<q_id>/share', methods=['POST'])
def share_question(q_id):
    """将题目分享给指定用户名的用户"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        q = db.bank_questions.find_one({"_id": ObjectId(q_id)})
    except InvalidId:
        return jsonify({"error": "无效的ID"}), 400
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    if q['creator_id'] != session['user_id']:
        return jsonify({"error": "只有创建者才能分享题目"}), 403

    data = request.json
    target_username = (data.get('username') or '').strip()
    if not target_username:
        return jsonify({"error": "请输入目标用户名"}), 400

    target_user = db.users.find_one({"username": target_username})
    if not target_user:
        return jsonify({"error": f"用户 {target_username} 不存在"}), 404

    target_id = str(target_user['_id'])
    if target_id == session['user_id']:
        return jsonify({"error": "不能分享给自己"}), 400

    db.bank_questions.update_one(
        {"_id": ObjectId(q_id)},
        {
            "$addToSet": {"shared_with": target_id},
            "$set": {f"shared_with_names.{target_id}": target_username}
        }
    )
    return jsonify({"msg": f"已成功分享给用户 {target_username}", "target_id": target_id, "target_name": target_username})


@app.route('/api/question_bank/<q_id>/share/<target_uid>', methods=['DELETE'])
def unshare_question(q_id, target_uid):
    """取消对某用户的分享"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        q = db.bank_questions.find_one({"_id": ObjectId(q_id)})
    except InvalidId:
        return jsonify({"error": "无效的ID"}), 400
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    if q['creator_id'] != session['user_id']:
        return jsonify({"error": "只有创建者才能取消分享"}), 403
    db.bank_questions.update_one(
        {"_id": ObjectId(q_id)},
        {
            "$pull": {"shared_with": target_uid},
            "$unset": {f"shared_with_names.{target_uid}": ""}
        }
    )
    return jsonify({"msg": "已取消分享"})


@app.route('/api/question_bank/<q_id>/usage', methods=['GET'])
def get_question_usage(q_id):
    """查询该题目模板的所有版本被哪些问卷引用"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        q = db.bank_questions.find_one({"_id": ObjectId(q_id)})
    except InvalidId:
        return jsonify({"error": "无效的ID"}), 400
    if not q:
        return jsonify({"error": "题目不存在"}), 404

    template_id = q['q_template_id']
    all_versions = list(db.bank_questions.find(
        {"q_template_id": template_id}, {"_id": 1, "version": 1}
    ))
    version_map = {str(v['_id']): v['version'] for v in all_versions}
    version_ids = list(version_map.keys())

    surveys = list(db.surveys.find(
        {"questions.bank_question_id": {"$in": version_ids}},
        {"title": 1, "status": 1, "creator_id": 1, "created_at": 1, "questions": 1}
    ))
    result = []
    for s in surveys:
        s_id = str(s['_id'])
        used_versions = []
        for sq in s.get('questions', []):
            if sq.get('bank_question_id') in version_ids:
                used_versions.append({
                    "bank_question_id": sq['bank_question_id'],
                    "version": version_map.get(sq['bank_question_id'], '?')
                })
        result.append({
            "_id": s_id,
            "title": s.get('title', ''),
            "status": s.get('status', ''),
            "created_at": s['created_at'].strftime('%Y-%m-%d %H:%M') if 'created_at' in s else '',
            "used_versions": used_versions
        })
    return jsonify(result)


@app.route('/api/question_bank/<q_id>/cross_stats', methods=['GET'])
def get_cross_stats(q_id):
    """跨问卷聚合统计：汇总该题目模板在所有问卷中的回答数据（仅创建者可查看）"""
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    try:
        q = db.bank_questions.find_one({"_id": ObjectId(q_id)})
    except InvalidId:
        return jsonify({"error": "无效的ID"}), 400
    if not q:
        return jsonify({"error": "题目不存在"}), 404
    if q['creator_id'] != session['user_id']:
        return jsonify({"error": "只有题目创建者可查看跨问卷统计"}), 403

    template_id = q['q_template_id']
    all_versions = list(db.bank_questions.find({"q_template_id": template_id}))
    version_ids = [str(v['_id']) for v in all_versions]

    # 找到所有使用该模板任意版本的问卷
    surveys = list(db.surveys.find(
        {"questions.bank_question_id": {"$in": version_ids}}
    ))

    # 建立 survey_id -> 该问卷中对应的 q_id 的映射
    survey_qid_map = {}
    for survey in surveys:
        s_id = str(survey['_id'])
        for sq in survey.get('questions', []):
            if sq.get('bank_question_id') in version_ids:
                survey_qid_map[s_id] = sq['q_id']
                break

    q_type = q['type']
    total_responses = 0
    surveys_count = len(survey_qid_map)

    if q_type in ('single_choice', 'multi_choice'):
        # 汇总所有版本的选项
        all_options = set()
        for v in all_versions:
            all_options.update(v.get('options', []))
        option_counts = {opt: 0 for opt in all_options}
        answered_count = 0

        for s_id, qid in survey_qid_map.items():
            responses = list(db.responses.find({"survey_id": s_id}))
            total_responses += len(responses)
            for resp in responses:
                for ans in resp.get('answers', []):
                    if ans.get('q_id') == qid:
                        val = ans.get('value')
                        answered_count += 1
                        items = val if isinstance(val, list) else ([val] if val else [])
                        for item in items:
                            key = str(item)
                            option_counts[key] = option_counts.get(key, 0) + 1

        return Response(json.dumps({
            "title": q['title'], "type": q_type,
            "total_responses": total_responses,
            "answered": answered_count,
            "options": option_counts,
            "surveys_count": surveys_count
        }, ensure_ascii=False, indent=2), mimetype='application/json; charset=utf-8')

    elif q_type == 'number_fill':
        raw_values = []
        for s_id, qid in survey_qid_map.items():
            responses = list(db.responses.find({"survey_id": s_id}))
            total_responses += len(responses)
            for resp in responses:
                for ans in resp.get('answers', []):
                    if ans.get('q_id') == qid:
                        try:
                            raw_values.append(float(ans['value']))
                        except (ValueError, TypeError):
                            pass

        result = {
            "title": q['title'], "type": q_type,
            "total_responses": total_responses,
            "count": len(raw_values),
            "surveys_count": surveys_count
        }
        if raw_values:
            result["avg"] = round(sum(raw_values) / len(raw_values), 2)
            result["min"] = round(min(raw_values), 2)
            result["max"] = round(max(raw_values), 2)
            result["values"] = [round(v, 2) for v in raw_values]
        return Response(json.dumps(result, ensure_ascii=False, indent=2),
                        mimetype='application/json; charset=utf-8')

    else:  # text_fill
        all_texts = []
        for s_id, qid in survey_qid_map.items():
            responses = list(db.responses.find({"survey_id": s_id}))
            total_responses += len(responses)
            for resp in responses:
                for ans in resp.get('answers', []):
                    if ans.get('q_id') == qid and ans.get('value'):
                        all_texts.append(str(ans['value']))

        return Response(json.dumps({
            "title": q['title'], "type": q_type,
            "total_responses": total_responses,
            "values": all_texts,
            "surveys_count": surveys_count
        }, ensure_ascii=False, indent=2), mimetype='application/json; charset=utf-8')


if __name__ == '__main__':
    app.run(debug=True)
