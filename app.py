from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import json, os, re
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# === GEMINI CONFIG ===
API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDyKuHQHUJGR9hapcd60vxRDvRV-55Lupk")
genai.configure(api_key=API_KEY)
MODEL = genai.GenerativeModel("models/gemini-2.0-flash-exp")

# === ARQUIVOS JSON ===
USUARIOS_JSON = "usuarios.json"
ACOES_JSON = "acoes_usuarios.json"
CONQUISTAS_JSON = "conquistas.json"

for arquivo in [USUARIOS_JSON, ACOES_JSON, CONQUISTAS_JSON]:
    if not os.path.exists(arquivo):
        with open(arquivo, "w") as f:
            json.dump([] if arquivo != CONQUISTAS_JSON else {}, f)

# === CONQUISTAS ===
CONQUISTAS_DEFINICOES = {
    "primeira_acao": {"nome": "🌱 Primeira Ação", "descricao": "Fez sua primeira ação", "aura_bonus": 10},
    "consistente": {"nome": "🔥 Consistente", "descricao": "Fez 10 ações", "aura_bonus": 50},
    "imparavel": {"nome": "⚡ Imparável", "descricao": "Fez 50 ações", "aura_bonus": 200},
    "centuriao": {"nome": "💯 Centurião", "descricao": "Fez 100 ações", "aura_bonus": 500},
    "primeira_estrela": {"nome": "🌟 Primeira Estrela", "descricao": "Ganhou +100 aura em 1 ação", "aura_bonus": 50},
    "supernova": {"nome": "💫 Supernova", "descricao": "Ganhou +500 aura em 1 ação", "aura_bonus": 300},
    "sol_radiante": {"nome": "☀️ Sol Radiante", "descricao": "Atingiu 1000 de aura total", "aura_bonus": 100},
    "galaxia": {"nome": "🌌 Galáxia", "descricao": "Atingiu 5000 de aura total", "aura_bonus": 500},
    "primeira_queda": {"nome": "💀 Primeira Queda", "descricao": "Perdeu -100 aura em 1 ação", "aura_bonus": 0},
    "abismo": {"nome": "🔻 Abismo", "descricao": "Teve aura negativa", "aura_bonus": 0},
    "mentor": {"nome": "👨‍🏫 Mentor", "descricao": "Teve 5 ações corrigidas por admin", "aura_bonus": 100},
    "preciso": {"nome": "🎯 Preciso", "descricao": "10 ações sem correção necessária", "aura_bonus": 150}
}

# === FUNÇÕES DE ARQUIVO ===
def carregar_usuarios():
    try:
        with open(USUARIOS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def salvar_usuarios(usuarios):
    with open(USUARIOS_JSON, "w", encoding="utf-8") as f:
        json.dump(usuarios, f, ensure_ascii=False, indent=4)

def carregar_acoes():
    try:
        with open(ACOES_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def salvar_acoes(acoes):
    with open(ACOES_JSON, "w", encoding="utf-8") as f:
        json.dump(acoes, f, ensure_ascii=False, indent=4)

def carregar_conquistas():
    try:
        with open(CONQUISTAS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def salvar_conquistas(conquistas):
    with open(CONQUISTAS_JSON, "w", encoding="utf-8") as f:
        json.dump(conquistas, f, ensure_ascii=False, indent=4)

# === DECORATORS ===
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        usuarios = carregar_usuarios()
        user = next((u for u in usuarios if u['username'] == session['username']), None)
        if not user or user.get('role') != 'admin':
            flash('Acesso negado! Apenas administradores.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# === GEMINI ===
def gerar_aura_com_gemini(acao, historico):
    acoes_corrigidas = [item for item in historico if item.get("aura_corrigida") is not None]
    contexto = "Você é um avaliador de aura. Valores positivos = bom, negativos = ruim.\n\n"
    if acoes_corrigidas:
        contexto += "### APRENDA COM CORREÇÕES HUMANAS:\n"
        for item in acoes_corrigidas[-10:]:
            contexto += f"Ação: '{item['acao']}'\nVocê deu: {item['aura_gemini']} aura\nCorreção humana: {item.get('aura_corrigida',0)}\n\n"
    contexto += f"### NOVA AÇÃO:\n'{acao}'\nResponda apenas com JSON: {{'aura': numero, 'explicacao': 'texto'}}"
    
    try:
        resposta = MODEL.generate_content(contexto)
        json_str = re.search(r"\{.*\}", resposta.text, re.DOTALL).group(0)
        dados = json.loads(json_str)
        return int(dados.get("aura", 0)), dados.get("explicacao", "Sem explicação")
    except:
        return 0, "Erro na avaliação automática"

# === SISTEMA DE LIGAS ===
def calcular_liga(aura):
    if aura >= 5000: return "👑 Lendário"
    if aura >= 2000: return "💎 Diamante"
    if aura >= 1000: return "🥇 Ouro"
    if aura >= 500: return "🥈 Prata"
    return "🥉 Bronze"

# === CONQUISTAS ===
def verificar_conquistas(username):
    usuarios = carregar_usuarios()
    acoes = carregar_acoes()
    conquistas_user = carregar_conquistas()
    if username not in conquistas_user:
        conquistas_user[username] = []

    user = next((u for u in usuarios if u['username']==username), None)
    if not user: return []

    acoes_user = [a for a in acoes if a['username']==username]
    novas = []

    total_acoes = len(acoes_user)
    aura_total = user.get('aura_total',0)
    acoes_corrigidas = [a for a in acoes_user if a.get('aura_corrigida') is not None]

    if total_acoes>=1 and "primeira_acao" not in conquistas_user[username]: novas.append("primeira_acao")
    if total_acoes>=10 and "consistente" not in conquistas_user[username]: novas.append("consistente")
    if total_acoes>=50 and "imparavel" not in conquistas_user[username]: novas.append("imparavel")
    if total_acoes>=100 and "centuriao" not in conquistas_user[username]: novas.append("centuriao")
    if aura_total>=1000 and "sol_radiante" not in conquistas_user[username]: novas.append("sol_radiante")
    if aura_total>=5000 and "galaxia" not in conquistas_user[username]: novas.append("galaxia")
    if aura_total<0 and "abismo" not in conquistas_user[username]: novas.append("abismo")
    for acao in acoes_user:
        aura = acao.get('aura_corrigida', acao['aura_gemini'])
        if aura>=100 and "primeira_estrela" not in conquistas_user[username]: novas.append("primeira_estrela")
        if aura>=500 and "supernova" not in conquistas_user[username]: novas.append("supernova")
        if aura<=-100 and "primeira_queda" not in conquistas_user[username]: novas.append("primeira_queda")
    if len(acoes_corrigidas)>=5 and "mentor" not in conquistas_user[username]: novas.append("mentor")
    
    for c in novas:
        conquistas_user[username].append(c)
        user['aura_total'] += CONQUISTAS_DEFINICOES[c]['aura_bonus']
    
    if novas:
        salvar_conquistas(conquistas_user)
        salvar_usuarios(usuarios)
    return novas

# === ROTAS ===
@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        usuarios = carregar_usuarios()
        user = next((u for u in usuarios if u['username']==username), None)
        if user and check_password_hash(user['password'], password):
            session['username'] = username
            session['role'] = user.get('role','user')
            return jsonify({'sucesso': True, 'role': user.get('role','user')})
        return jsonify({'sucesso': False, 'erro':'Usuário ou senha inválidos'}), 401
    return render_template('login.html')

@app.route('/registrar', methods=['POST'])
def registrar():
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    if not username or not password or not email:
        return jsonify({'sucesso': False, 'erro':'Preencha todos os campos'}), 400
    usuarios = carregar_usuarios()
    if any(u['username']==username for u in usuarios):
        return jsonify({'sucesso': False, 'erro':'Usuário já existe'}), 400
    role = 'admin' if len(usuarios)==0 else 'user'
    novo = {'username': username, 'email': email, 'password': generate_password_hash(password),
            'role': role, 'aura_total': 0, 'liga': '🥉 Bronze', 'data_criacao': datetime.now().isoformat()}
    usuarios.append(novo)
    salvar_usuarios(usuarios)
    session['username'] = username
    session['role'] = role
    return jsonify({'sucesso': True, 'role': role})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    usuarios = carregar_usuarios()
    user = next((u for u in usuarios if u['username']==session['username']), None)
    acoes_user = [a for a in carregar_acoes() if a['username']==session['username']]
    conquistas_user = carregar_conquistas().get(session['username'], [])
    conquistas_info = [CONQUISTAS_DEFINICOES[c] for c in conquistas_user]
    return render_template('dashboard.html', user=user, total_acoes=len(acoes_user), conquistas=conquistas_info)

@app.route('/avaliar', methods=['POST'])
@login_required
def avaliar():
    data = request.json
    acao = data.get('acao','').strip()
    if not acao: return jsonify({'erro':'Ação vazia'}),400
    acoes = carregar_acoes()
    aura_gemini, explicacao = gerar_aura_com_gemini(acao, acoes)
    novo = {'id': len(acoes)+1, 'username': session['username'], 'acao': acao, 'aura_gemini': aura_gemini, 'explicacao': explicacao, 'timestamp': datetime.now().isoformat()}
    acoes.append(novo)
    salvar_acoes(acoes)

    usuarios = carregar_usuarios()
    user = next((u for u in usuarios if u['username']==session['username']), None)
    if user:
        user['aura_total'] += aura_gemini
        user['liga'] = calcular_liga(user['aura_total'])
        salvar_usuarios(usuarios)
    novas = verificar_conquistas(session['username'])
    conquistas_desbloqueadas = [CONQUISTAS_DEFINICOES[c] for c in novas]
    return jsonify({'aura':aura_gemini,'explicacao':explicacao,'id':novo['id'],'aura_total':user['aura_total'],'liga':user['liga'],'conquistas':conquistas_desbloqueadas})

@app.route('/historico')
@login_required
def historico():
    acoes_user = [a for a in carregar_acoes() if a['username']==session['username']]
    user = next((u for u in carregar_usuarios() if u['username']==session['username']), None)
    return jsonify({'historico': acoes_user[::-1], 'total': user['aura_total'] if user else 0})

@app.route('/ranking')
@login_required
def ranking():
    usuarios_ordenados = sorted(carregar_usuarios(), key=lambda x: x.get('aura_total',0), reverse=True)
    ranking_por_liga = {"👑 Lendário": [], "💎 Diamante": [], "🥇 Ouro": [], "🥈 Prata": [], "🥉 Bronze": []}
    for u in usuarios_ordenados:
        liga = u.get('liga','🥉 Bronze')
        ranking_por_liga[liga].append({'username':u['username'],'aura_total':u.get('aura_total',0),'posicao':len(ranking_por_liga[liga])+1})
    return render_template('ranking.html', ranking=ranking_por_liga, username=session['username'])

@app.route('/conquistas')
@login_required
def conquistas():
    conquistas_user = carregar_conquistas().get(session['username'], [])
    todas = [{'key':k,'nome':v['nome'],'descricao':v['descricao'],'desbloqueada':k in conquistas_user,'aura_bonus':v['aura_bonus']} for k,v in CONQUISTAS_DEFINICOES.items()]
    return render_template('conquistas.html', conquistas=todas)

# === ADMIN ===
@app.route('/admin')
@admin_required
def admin():
    acoes = carregar_acoes()
    usuarios = carregar_usuarios()
    total_usuarios = len(usuarios)
    total_acoes = len(acoes)
    acoes_corrigidas = len([a for a in acoes if a.get('aura_corrigida') is not None])
    acuracia = round((1 - acoes_corrigidas / total_acoes) * 100, 1) if total_acoes>0 else 100
    return render_template('admin.html', total_usuarios=total_usuarios, total_acoes=total_acoes, acuracia=acuracia, acoes=acoes[::-1][:50], usuarios=usuarios, username=session['username'])

@app.route('/admin/corrigir', methods=['POST'])
@admin_required
def admin_corrigir():
    data = request.json
    item_id = data.get('id')
    aura_corrigida = data.get('aura_corrigida')
    feedback = data.get('feedback_admin','')
    acoes = carregar_acoes()
    usuarios = carregar_usuarios()
    for acao in acoes:
        if acao.get('id')==item_id:
            aura_antiga = acao.get('aura_corrigida', acao['aura_gemini'])
            acao['aura_corrigida'] = int(aura_corrigida)
            acao['feedback_admin'] = feedback
            user = next((u for u in usuarios if u['username']==acao['username']), None)
            if user:
                user['aura_total'] += int(aura_corrigida)-aura_antiga
                user['liga'] = calcular_liga(user['aura_total'])
            break
    salvar_acoes(acoes)
    salvar_usuarios(usuarios)
    return jsonify({'sucesso': True})

@app.route('/admin/deletar_acao/<int:item_id>', methods=['DELETE'])
@admin_required
def admin_deletar_acao(item_id):
    acoes = carregar_acoes()
    usuarios = carregar_usuarios()
    acao_deletada = next((a for a in acoes if a.get('id')==item_id), None)
    if acao_deletada:
        user = next((u for u in usuarios if u['username']==acao_deletada['username']), None)
        if user:
            user['aura_total'] -= acao_deletada.get('aura_corrigida', acao_deletada['aura_gemini'])
            user['liga'] = calcular_liga(user['aura_total'])
        acoes = [a for a in acoes if a.get('id')!=item_id]
        salvar_acoes(acoes)
        salvar_usuarios(usuarios)
    return jsonify({'sucesso': True})

# === ADMIN GERENCIAR USUÁRIOS ===
@app.route('/admin/usuarios')
@admin_required
def admin_usuarios():
    usuarios = carregar_usuarios()
    return render_template('admin_usuarios.html', usuarios=usuarios, username=session['username'])

@app.route('/admin/usuarios/alterar_role', methods=['POST'])
@admin_required
def alterar_role_usuario():
    data = request.json
    target_username = data.get('username')
    nova_role = data.get('role')
    usuarios = carregar_usuarios()
    user = next((u for u in usuarios if u['username']==target_username), None)
    if not user: return jsonify({'sucesso': False, 'erro': 'Usuário não encontrado'}), 404
    user['role'] = nova_role
    salvar_usuarios(usuarios)
    return jsonify({'sucesso': True, 'nova_role': nova_role})

@app.route('/admin/usuarios/deletar', methods=['POST'])
@admin_required
def deletar_usuario():
    data = request.json
    target_username = data.get('username')
    if target_username == session['username']:
        return jsonify({'sucesso': False, 'erro': 'Você não pode deletar a si mesmo!'}), 400
    usuarios = carregar_usuarios()
    usuarios = [u for u in usuarios if u['username'] != target_username]
    salvar_usuarios(usuarios)
    return jsonify({'sucesso': True})

if __name__ == "__main__":
    app.run(debug=True)
