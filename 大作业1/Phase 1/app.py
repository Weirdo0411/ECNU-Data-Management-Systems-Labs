from flask import Flask, request, jsonify, render_template, session, Response
from pymongo import MongoClient
from bson import ObjectId
import bcrypt
import datetime
import json

app = Flask(__name__)
# 设置 session 密钥，用于记住用户的登录状态
app.secret_key = 'ecnu_survey_super_secret_key' 

# ==================== 数据库连接 ====================
# 连接本地 MongoDB，如果报错说明你的黑窗口没开
client = MongoClient("mongodb://localhost:27017/")
db = client["survey_system"]

# ==================== 页面路由 ====================
@app.route('/')
def index():
    # 渲染 templates 文件夹下的 index.html
    return render_template('index.html')

# ==================== API 路由：用户模块 ====================

# 1. 用户注册
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    # 检查用户名是否已存在
    if db.users.find_one({"username": data['username']}):
        return jsonify({"error": "用户名已存在"}), 400
    
    # 使用 bcrypt 对密码进行加密（安全要求）
    hashed = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt())
    db.users.insert_one({
        "username": data['username'],
        "password": hashed,
        "created_at": datetime.datetime.now()
    })
    return jsonify({"msg": "注册成功，请登录！"})

# 2. 用户登录
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = db.users.find_one({"username": data['username']})
    # 验证密码
    if user and bcrypt.checkpw(data['password'].encode('utf-8'), user['password']):
        session['user_id'] = str(user['_id']) # 将用户ID存入 session
        session['username'] = user['username']
        return jsonify({"msg": "登录成功", "username": user['username']})
    return jsonify({"error": "用户名或密码错误"}), 401


# ==================== API 路由：问卷核心模块 ====================

# 3. 获取当前用户创建的所有历史问卷列表
@app.route('/api/my_surveys', methods=['GET'])
def get_my_surveys():
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    
    # 查询当前用户创建的问卷，第二个参数 {"title": 1} 表示只返回 _id 和 title 字段以节省带宽
    surveys = list(db.surveys.find({"creator_id": session['user_id']}, {"title": 1}))
    for s in surveys:
        s['_id'] = str(s['_id']) # ObjectId 需要转成字符串前端才能识别
    return jsonify(surveys)

# 4. 创建问卷 (接收前端动态设计的 JSON 数据)
@app.route('/api/surveys', methods=['POST'])
def create_survey():
    if 'user_id' not in session:
        return jsonify({"error": "请先登录"}), 401
    
    survey_data = request.json
    survey_data['creator_id'] = session['user_id']
    survey_data['created_at'] = datetime.datetime.now()
    survey_data['status'] = 'published' # 默认发布状态
    
    survey_id = db.surveys.insert_one(survey_data).inserted_id
    return jsonify({"msg": "问卷创建成功", "survey_id": str(survey_id)})

# 5. 获取问卷详情 (用于前端渲染填写页面)
@app.route('/api/surveys/<survey_id>', methods=['GET'])
def get_survey(survey_id):
    survey = db.surveys.find_one({"_id": ObjectId(survey_id)})
    if not survey:
        return jsonify({"error": "问卷不存在"}), 404
    survey['_id'] = str(survey['_id']) 
    return jsonify(survey)


# ==================== API 路由：填写与统计模块 ====================

# 6. 提交答卷 (包含复杂的动态校验逻辑)
@app.route('/api/surveys/<survey_id>/submit', methods=['POST'])
def submit_response(survey_id):
    data = request.json
    survey = db.surveys.find_one({"_id": ObjectId(survey_id)})
    answers = data.get('answers',[])
    
    # 遍历问卷的题目规则，校验用户的答案
    for q in survey['questions']:
        ans = next((item for item in answers if item["q_id"] == q["q_id"]), None)
        
        # 校验必填
        if q.get('is_required') and not ans:
            return jsonify({"error": f"题目 '{q['title']}' 是必填的"}), 400
            
        if ans:
            val = ans.get('value')
            # 校验多选题选项数量
            if q['type'] == 'multi_choice':
                if 'min_select' in q and len(val) < q['min_select']:
                    return jsonify({"error": f"题目 '{q['title']}' 至少选 {q['min_select']} 项"}), 400
                if 'max_select' in q and len(val) > q['max_select']:
                    return jsonify({"error": f"题目 '{q['title']}' 最多选 {q['max_select']} 项"}), 400
            
            # 校验数字填空题范围
            if q['type'] == 'number_fill':
                try:
                    num_val = float(val)
                    if 'min' in q and num_val < q['min']:
                        return jsonify({"error": f"题目 '{q['title']}' 不能小于 {q['min']}"}), 400
                    if 'max' in q and num_val > q['max']:
                        return jsonify({"error": f"题目 '{q['title']}' 不能大于 {q['max']}"}), 400
                except ValueError:
                    return jsonify({"error": f"题目 '{q['title']}' 必须填入纯数字"}), 400

    # 所有校验通过，保存数据到 responses 集合
    response_data = {
        "survey_id": survey_id,
        "user_id": session.get('user_id', None), # 没登录就是 None (匿名提交)
        "answers": answers,
        "submitted_at": datetime.datetime.now()
    }
    db.responses.insert_one(response_data)
    return jsonify({"msg": "答卷提交成功！"})

# 7. 获取问卷统计结果 (MongoDB 聚合管道 + Python 逻辑完善中文及多选题)
# 7. 获取问卷统计结果 (完美满足 PDF 要求：多选题拆分、填空题全量内容、数字题求平均值)
@app.route('/api/surveys/<survey_id>/stats', methods=['GET'])
def get_stats(survey_id):
    # 1. 查出问卷原始结构，了解每道题的题型
    survey = db.surveys.find_one({"_id": ObjectId(survey_id)})
    if not survey:
        return jsonify({"error": "问卷不存在"}), 404
    q_map = {q['q_id']: q for q in survey.get('questions',[])}

    # 2. 聚合管道：展开所有答卷的答案
    pipeline =[
        {"$match": {"survey_id": survey_id}}, 
        {"$unwind": "$answers"}               
    ]
    unwound_answers = list(db.responses.aggregate(pipeline))
    
    # 3. 按题型进行分类统计
    result = {}
    # 先初始化返回结构
    for q_id, q in q_map.items():
        if q['type'] == 'number_fill':
            result[q_id] = {"题名": q['title'], "题型": "数字填空", "所有填写内容": [], "平均值": 0}
        elif q['type'] == 'text_fill':
            result[q_id] = {"题名": q['title'], "题型": "文本填空", "所有填写内容":[]}
        else:
            result[q_id] = {"题名": q['title'], "题型": "选择题", "选项统计": {}}

    # 填充数据
    for doc in unwound_answers:
        ans = doc.get('answers', {})
        q_id = ans.get('q_id')
        val = ans.get('value')
        
        if not q_id or q_id not in q_map: continue
        q_type = q_map[q_id]['type']
        
        # 核心逻辑：按题型处理
        if q_type == 'number_fill':
            try:
                result[q_id]["所有填写内容"].append(float(val))
            except: pass
        elif q_type == 'text_fill':
            result[q_id]["所有填写内容"].append(str(val))
        else:
            if isinstance(val, list):
                for v in val:
                    result[q_id]["选项统计"][v] = result[q_id]["选项统计"].get(v, 0) + 1
            else:
                val_str = str(val)
                result[q_id]["选项统计"][val_str] = result[q_id]["选项统计"].get(val_str, 0) + 1
                
    # 4. 针对数字题计算平均值
    for q_id, stats in result.items():
        if stats.get("题型") == "数字填空":
            vals = stats["所有填写内容"]
            if len(vals) > 0:
                stats["平均值"] = round(sum(vals) / len(vals), 2) # 保留两位小数
            
    json_str = json.dumps(result, ensure_ascii=False, indent=4)
    return Response(json_str, mimetype='application/json')


if __name__ == '__main__':
    # debug=True 可以在代码修改后自动重启服务器
    app.run(debug=True)