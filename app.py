import os
import dotenv
import json   
import requests
from flask import Flask, render_template, request, jsonify, session
from datetime import datetime

print("Iniciando aplicação Flask...")

app = Flask(__name__)

print("✅ App Flask criado")

# Carrega variáveis de ambiente
dotenv.load_dotenv()

print("✅ Variáveis de ambiente carregadas")

# Configurações - usa SECRET_KEY do .env ou gera uma
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', os.urandom(24).hex())

print("✅ SECRET_KEY configurada")

# --- HELPERS ---

def conversar_openai(mensagens, modelo='gpt-4o-mini'):
    """
    Faz requisição para a API da OpenAI
    """
    API_KEY = os.getenv('OPENAI_API_KEY')
    print(API_KEY)
    if not API_KEY:
        return {"error": {"message": "OPENAI_API_KEY não encontrada no arquivo .env"}}

    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": modelo,
        "messages": mensagens,
        "max_tokens": 300,
        "temperature": 0.1
    }

    try:
        resposta = requests.post(url, json=payload, headers=headers, timeout=30)
        resposta.raise_for_status()
        return resposta.json()
    except requests.exceptions.Timeout:
        return {"error": {"message": "Timeout: A API demorou muito para responder"}}
    except requests.exceptions.RequestException as e:
        return {"error": {"message": f"Erro na requisição: {str(e)}"}}

print("✅ Função conversar_openai definida")
def flowise_upsert(file_path, usage="exemplo", metadata=None):
    """
    Envia arquivos para indexação no Flowise (vector upsert)
    """
    url = os.getenv("FLOWISE_UPSERT_URL")
    api_key = os.getenv("FLOWISE_API_KEY")

    if not url:
        return {"error": "FLOWISE_UPSERT_URL não configurada no .env"}

    headers = {}

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Form-data file
    form_data = {
        "files": (os.path.basename(file_path), open(file_path, "rb"))
    }

    # Campos normais
    body_data = {
        "usage": usage,
        "legacyBuild": "true",  # EM FORM-DATA sempre string
        "metadata": json.dumps(metadata or {})  # também deve ser string
    }

    try:
        resp = requests.post(url, headers=headers, files=form_data, data=body_data)
        resp.raise_for_status()
        return resp.json()

    except Exception as e:
        return {"error": str(e)}


def criar_historico_inicial():
    """
    Cria o histórico inicial com a mensagem de sistema para cada nova sessão
    """
    hora_atual = datetime.now()

    system_prompt = (
        f"Você é um assistente juridico virtual"
        f"formado em direito e com especialiadade em concurso publico na area juridico"
        f"Horário atual: {hora_atual.strftime('%H:%M')}. "
    )

    return [{"role": "system", "content": system_prompt}]

print("✅ Função criar_historico_inicial definida")


def limitar_historico(mensagens, max_mensagens=20):
    """
    Limita o histórico de mensagens para não exceder o limite da API.
    Sempre mantém a mensagem de sistema (índice 0).
    """
    system_msg = mensagens[0]  # preserva o system prompt
    restante = mensagens[1:]
    if len(restante) > max_mensagens:
        restante = restante[-max_mensagens:]
    return [system_msg] + restante

print("✅ Função limitar_historico definida")

# --- ROTAS ---
@app.route('/enviar_arquivo', methods=['POST'])
def enviar_arquivo():
    if 'arquivo' not in request.files:
        return jsonify({"status": "erro", "mensagem": "Nenhum arquivo enviado"}), 400

    arquivo = request.files['arquivo']

    caminho_temp = f"./{arquivo.filename}"
    arquivo.save(caminho_temp)

    resposta = flowise_upsert(
        file_path=caminho_temp,
        usage="documento_juridico",
        metadata={"origem": "chatbot"}
    )

    # Remove o arquivo após o envio
    os.remove(caminho_temp)

    return jsonify(resposta)

@app.route('/')
def index():
    """Rota principal que carrega a interface do chatbot."""
    session['historico'] = criar_historico_inicial()
    return render_template('index.html')

print("✅ Rota / definida")

@app.route('/enviar_mensagem', methods=['POST'])
def enviar_mensagem():
    """Processa mensagem do usuário e retorna resposta da IA"""
    dados = request.get_json()
    mensagem_usuario = dados.get('mensagem', '').strip()

    if not mensagem_usuario:
        return jsonify({"resposta": "Mensagem vazia", "status": "erro"}), 400

    historico = session.get('historico')

    if not historico:
        historico = criar_historico_inicial()

    # Adiciona mensagem do usuário ao histórico
    historico.append({"role": "user", "content": mensagem_usuario})

    # Limita o histórico
    historico = limitar_historico(historico)

    # Chama a API da OpenAI
    resposta_json = conversar_openai(mensagens=historico)

    if resposta_json and 'choices' in resposta_json:
        try:
            texto_ia = resposta_json['choices'][0]['message']['content']

            # Adiciona resposta da IA ao histórico
            historico.append({"role": "assistant", "content": texto_ia})
            session['historico'] = historico

            return jsonify({
                "resposta": texto_ia,
                "status": "sucesso"
            })

        except (KeyError, IndexError) as e:
            print(f"Erro ao processar estrutura do JSON: {e}")
            print(f"Resposta completa: {resposta_json}")
            return jsonify({
                "resposta": "Erro ao processar resposta da IA.",
                "status": "erro"
            }), 500
    else:
        mensagem_erro = resposta_json.get('error', {}).get('message', 'Erro desconhecido na API')
        print(f"Falha na Resposta da API OpenAI: {mensagem_erro}")
        print(f"Resposta completa: {resposta_json}")

        return jsonify({
            "resposta": f"Ops! Tive um problema: {mensagem_erro}",
            "status": "erro"
        }), 500

print("✅ Rota /enviar_mensagem definida")

@app.route('/limpar_historico', methods=['POST'])
def limpar_historico():
    """Limpa o histórico da conversa e reinicia a sessão"""
    session['historico'] = criar_historico_inicial()
    return jsonify({"status": "sucesso", "mensagem": "Histórico limpo"})

print("✅ Rota /limpar_historico definida")

# --- TRATAMENTO DE ERROS ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html'), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"erro": "Erro interno do servidor"}), 500

print("✅ Error handlers definidos")

print("🔥 Chegando no if __name__ == '__main__'...")

if __name__ == '__main__':
    print("🎯 Dentro do if __name__ == '__main__'")

    if not os.getenv('OPENAI_API_KEY'):
        print("⚠️  ATENÇÃO: OPENAI_API_KEY não encontrada no arquivo .env")
        print("📝 Crie um arquivo .env com: OPENAI_API_KEY=sua_chave_aqui")

    print("🚀 Iniciando servidor Flask...")
    app.run(debug=True, port=5000)
