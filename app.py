import os
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo
from datetime import datetime
import time
import ipdb
import json

from openai import AzureOpenAI

client = AzureOpenAI(
    api_key="02427719893b42868f349a4668288963",
    api_version='2023-12-01-preview',
    azure_endpoint="https://shuningz.openai.azure.com/"
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'

login_manager = LoginManager(app)
login_manager.login_view = 'login'

USER_DATA_FILE = 'users.txt'
CHAT_DATA_DIR = 'chats'

if not os.path.exists(CHAT_DATA_DIR):
    os.makedirs(CHAT_DATA_DIR)

class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

@login_manager.user_loader
def load_user(user_id):
    with open(USER_DATA_FILE, 'r') as f:
        users = f.readlines()
        for user in users:
            uid, username, password = user.strip().split(',')
            if uid == user_id:
                return User(uid, username, password)
    return None

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=20)])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        with open(USER_DATA_FILE, 'a') as f:
            user_id = str(len(open(USER_DATA_FILE).readlines()) + 1)
            f.write(f"{user_id},{form.username.data},{form.password.data}\n")
        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        with open(USER_DATA_FILE, 'r') as f:
            users = f.readlines()
            for user in users:
                uid, username, password = user.strip().split(',')
                if username == form.username.data and password == form.password.data:
                    login_user(User(uid, username, password))
                    # 创建用户的记忆文件
                    memory_file = f'{username}_memory.json'
                    if not os.path.exists(memory_file):
                        with open(memory_file, 'w') as f:
                            f.write(json.dumps([]))
                    return redirect(url_for('chat'))
        flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

system_memory_prompt = """Evaluate the following text and decide which text should be added to the memory.

[Output Format]
- Memory Text.
- Original text.
- Type:
- Confidence (a number between 0% and 100%).

- Memory Text.
- Original Text.
- Type:
- Confidence (a number between 0% and 100%).

...

[Rules]

MUST output memory text, original text, type, and confidence for each memory using the format above. 

Memory text refers to the key information that you infer the user wants you to remember from their prompt. 
This could be details such as their job title, the name of their company, the name of a project, etc.
Try to extract as many relevant pieces of information as possible. The Memory Text should be a concise summary of the key information.


Original text is the text from the user's original prompt from which the Memory Text was derived.
Correspond each piece of Memory Text with the Original Text from which it was inferred.

Type refers to the type of information that the Memory Text represents, for example, "职业信息", "地点信息", etc.
You need to prioritize using an existing memory_type: {}. If the current memoryText does not belong to any existing memory_type, only then should you use a new memory_type.

You could output nothing if there were no memories.
For confidence you should output a concrete number.
NEVER output any text I include in the output format such as 0% and 100%

Here are an example:
[Input]
帮我设计一份面试题库，候选人通常是中国985高校的CS方向的在读学生或者应届毕业生，我需要和他们一起开发类似腾讯的太极机器学习平台，Idex平台，US平台，以及亚马逊的SageMaker类似的东西，技术栈是Java，需要用到的Framework是SpringBoot，用到的ORM是 JPA
[Output]
- Memory Text. 你是中级技术经理
- Original Text. 机器学习平台，亚马逊，Java, SpringBoot, JPA
- Type: 职业信息
- Confidence 91.5%

- Memory Text. 你在阿里云工作
- Original Text. 类似腾讯
- Type: 地点信息
- Confidence 89.2%


Here is my Input:
[Input]
"""

@app.route('/memory_evaluation', methods=['POST'])
@login_required
def memory_evaluation():
    message = request.form.get('message')
    memory_type = request.form.get('memory_type') 
    print(f"Received message for evaluation: {message}")  # 调试信息

    # 使用 GPT 模型进行初步推理，判断需要存储到记忆的内容
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_memory_prompt.format(memory_type)},
            {"role": "user", "content": message}
        ]
    )
    # 假设 GPT 返回的内容是需要存入记忆的内容
    memory_suggestions = []
    raw_suggestions = response.choices[0].message.content.strip().split("\n\n")
    print(response.choices[0].message.content)
    for suggestion in raw_suggestions:
        parts = suggestion.split('- Original Text.')
        if len(parts) < 2:
            print("Warning: missing Original Text or Confidence part.")
            continue

        memory_text = parts[0].replace("- Memory Text.", "").strip()
        original_text = parts[1].strip().split('- Type:')[0].strip()
        type_confidence = parts[1].strip().split('- Type:')[1].strip()
        type_info = type_confidence.strip().split('- Confidence')[0].replace("\n", "")
        confidence = type_confidence.strip().split('- Confidence')[1].replace("%", "")

        print(type_info)
        try:
            confidence = int(confidence)
        except ValueError:
            print(f"Invalid confidence value: {confidence}")
            confidence = 0  # 或者设置一个默认值

        memory_suggestions.append({
            'memoryText': memory_text,
            'originalText': original_text,
            'type': type_info,
            'confidence': confidence
        })

    print(f"Memory suggestions: {memory_suggestions}")  # 调试信息
    return jsonify({'memory_suggestions': memory_suggestions})

@app.route('/process_plugin', methods=['POST'])
@login_required
def process_plugin():
    phrase = request.form.get('phrase')
    action = request.form.get('action')

    # 调用函数保存或修改Memory
    save_memory(current_user.username, phrase, action)

    return jsonify({'status': 'success'})

MEMORY_DIR = 'memory'

@app.route("/get_memory", methods=['GET'])
@login_required
def get_memory():
    username = current_user.username
    with open(f"{username}_memory.json", "r") as f:
        memory = f.read()
    return jsonify({'memory': memory})

@app.route('/update_memory', methods=['GET', 'POST'])
@login_required
def update_memory():
    memory = request.form.get('memory')
    print(f"Received memory: {memory}")
    with open(f"{current_user.username}_memory.json", "w") as f:
        f.write(memory)
    return jsonify({'status': 'success'})

if not os.path.exists(MEMORY_DIR):
    os.makedirs(MEMORY_DIR)

def save_memory(user_id, phrase, action):
    memory_file = os.path.join(MEMORY_DIR, f'{user_id}_memory.txt')
    with open(memory_file, 'a') as f:
        if action == "add_memory":
            f.write(f"Memory added: {phrase}\n")
        elif action == "modify":
            f.write(f"Memory modified: {phrase}\n")

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    chat_list = [f.split('__')[1].split(".")[0] for f in os.listdir(CHAT_DATA_DIR) if f.startswith(f"{current_user.username}__")]
    selected_chat = request.args.get('chat_name', '')

    if request.method == 'POST':
        new_chat_name = request.form.get('new_chat_name')
        if new_chat_name:
            # 创建新对话
            print(f"Creating new chat: {new_chat_name}")
            selected_chat = new_chat_name
            chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{selected_chat}.txt')
            # 确保文件存在
            if not os.path.exists(chat_file):
                open(chat_file, 'w').close()
            # 更新 chat_list 确保新对话立即显示
            chat_list = [f.split('__')[1] for f in os.listdir(CHAT_DATA_DIR) if f.startswith(f"{current_user.username}__")]
        else:
            print("Processing chat message")
            chat_name = request.form.get('chat_name', '')
            message = request.form.get('message', '')
            memory = request.form.get('memory', '')

            if chat_name and message:
                chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')
                log_message("user", message)
                save_message_to_file(chat_file, current_user.username, message)

                # 生成响应
                bot_response = generate_response([
                    {"role": "system", "content": "Your system prompt goes here"},
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": "You can use these memories to answer user's question: "+memory}
                ])
                log_message("assistant", bot_response)
                save_message_to_file(chat_file, "assistant", bot_response)

                selected_chat = chat_name

    chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{selected_chat}.txt')
    if os.path.exists(chat_file):
        with open(chat_file, 'r') as f:
            conversations = f.readlines()
    else:
        conversations = []
    print("========= chat list ========")
    print(chat_list)
    print("========= selected chat ========")
    print(selected_chat)
    print("========= ========== ========")
    # return jsonify({'chat_list': chat_list, 'conversations': conversations, 'selected_chat': selected_chat})
    return render_template('chat.html', chat_list=chat_list, conversations=conversations, selected_chat=selected_chat)

@app.route('/clear', methods=['POST'])
@login_required
def clear_history():
    selected_chat = request.form.get('chat_name', '')
    chat_file = os.path.join(CHAT_DATA_DIR, f'{selected_chat}.txt')
    if os.path.exists(chat_file):
        os.remove(chat_file)
    session['history'] = []
    return jsonify({'status': 'history cleared'})

def generate_response(history):
    # 调用Azure OpenAI的API生成响应
    deployment_name = "gpt-4o"  # 替换为你的实际部署名称
    response = client.chat.completions.create(
        model=deployment_name,
        messages=history,
        stream=False  # 设为False以获得完整响应
    )
    
    # 记录查询日志
    log_query(history, response.choices[0].message.content.strip())
    
    return response.choices[0].message.content.strip()

def save_message_to_file(chat_file, role, message):
    with open(chat_file, 'a') as f:
        f.write(f"{role}: {message}\n")

def read_chat_history(user_id):
    chat_history = []
    chat_files = [f for f in os.listdir(CHAT_DATA_DIR) if f.startswith(f"{user_id}_")]
    for chat_file in chat_files:
        with open(os.path.join(CHAT_DATA_DIR, chat_file), 'r') as f:
            chat_history.extend(f.readlines())
    return chat_history

def log_message(role, message):
    timestamp = datetime.now().isoformat()
    log_entry = {
        'timestamp': timestamp,
        'role': role,
        'message': message
    }
    
    # 使用当前用户的用户名作为日志文件的目录名称
    user_log_dir = os.path.join(CHAT_DATA_DIR, current_user.username)
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)

    with open(os.path.join(user_log_dir, "logging_with_time.log"), "a") as f:
        f.write("[LOG]: \n")
        f.write(str(log_entry) + "\n")
        f.write("=============================\n")

def log_query(history, response):
    # 使用当前用户的用户名作为日志文件的目录名称
    user_log_dir = os.path.join(CHAT_DATA_DIR, current_user.username)
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)

    with open(os.path.join(user_log_dir, "gpt_query.log"), "a+") as f:
        f.write(str(time.time()) + "\n")
        for hh in history:
            f.write(str(hh) + "\n")
        f.write(response + "\n")
        f.write("======================================== query \n")

if __name__ == '__main__':
    if not os.path.exists(USER_DATA_FILE):
        open(USER_DATA_FILE, 'w').close()
    app.run(debug=True, host='0.0.0.0', port=5005)
