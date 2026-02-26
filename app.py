import os
import json
import dotenv
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
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24).hex())
print("✅ SECRET_KEY configurada")

# --- HELPERS ---

def flowise_predict(question: str, chat_history=None, override_config=None):
    """
    Envia pergunta para o Flowise (/prediction) e retorna a resposta.
    Observação: dependendo do seu Flowise, o retorno pode vir em campos diferentes.
    """
    url = os.getenv("FLOWISE_CHAT_URL")
    api_key = os.getenv("FLOWISE_API_KEY")

    if not url:
        return {"error": {"message": "FLOWISE_CHAT_URL não configurada no .env"}}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "question": question
    }

    # Alguns fluxos suportam histórico / overrideConfig
    if chat_history is not None:
        payload["chatHistory"] = chat_history
    if override_config is not None:
        payload["overrideConfig"] = override_config

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        return {"error": {"message": "Timeout: Flowise demorou para responder"}}
    except requests.exceptions.RequestException as e:
        return {"error": {"message": f"Erro na requisição Flowise: {str(e)}"}}


def extract_flowise_text(data):
    """
    Normaliza a resposta do Flowise para texto.
    Flowise pode retornar:
    - {"text": "..."}
    - {"answer": "..."}
    - {"data": "..."} ou estruturas diferentes dependendo do fluxo
    """
    if not data:
        return None

    if isinstance(data, dict):
        if "text" in data and isinstance(data["text"], str):
            return data["text"]
        if "answer" in data and isinstance(data["answer"], str):
            return data["answer"]
        if "data" in data and isinstance(data["data"], str):
            return data["data"]

        # fallback: tenta achar algo útil
        for k in ["result", "output", "message", "response"]:
            if k in data and isinstance(data[k], str):
                return data[k]

        # último fallback: serializa
        return json.dumps(data, ensure_ascii=False)

    # se vier string direto
    if isinstance(data, str):
        return data

    return str(data)


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

    # IMPORTANTE: fechar o arquivo após enviar
    try:
        with open(file_path, "rb") as f:
            form_data = {
                "files": (os.path.basename(file_path), f)
            }

            body_data = {
                "usage": usage,
                "legacyBuild": "true",
                "metadata": json.dumps(metadata or {})
            }

            resp = requests.post(url, headers=headers, files=form_data, data=body_data, timeout=120)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


def criar_historico_inicial():
    """
    Histórico inicial (útil para exibir no front).
    OBS: No Flowise, o ideal é o "system prompt" estar configurado no próprio fluxo.
    """
    hora_atual = datetime.now()

    system_prompt = (
        f"Assistente jurídico virtual. Horário atual: {hora_atual.strftime('%H:%M')}."
    )
    return [{"role": "system", "content": system_prompt}]


def limitar_historico(mensagens, max_mensagens=20):
    system_msg = mensagens[0]
    restante = mensagens[1:]
    if len(restante) > max_mensagens:
        restante = restante[-max_mensagens:]
    return [system_msg] + restante


# --- ROTAS ---

@app.route("/enviar_arquivo", methods=["POST"])
def enviar_arquivo():
    if "arquivo" not in request.files:
        return jsonify({"status": "erro", "mensagem": "Nenhum arquivo enviado"}), 400

    arquivo = request.files["arquivo"]
    if not arquivo.filename:
        return jsonify({"status": "erro", "mensagem": "Arquivo inválido"}), 400

    caminho_temp = f"./{arquivo.filename}"
    arquivo.save(caminho_temp)

    resposta = flowise_upsert(
        file_path=caminho_temp,
        usage="documento_juridico",
        metadata={"origem": "chatbot"}
    )

    os.remove(caminho_temp)
    return jsonify(resposta)


@app.route("/")
def index():
    session["historico"] = criar_historico_inicial()
    return render_template("index.html")


@app.route("/enviar_mensagem", methods=["POST"])
def enviar_mensagem():
    dados = request.get_json(silent=True) or {}
    mensagem_usuario = (dados.get("mensagem") or "").strip()

    if not mensagem_usuario:
        return jsonify({"resposta": "Mensagem vazia", "status": "erro"}), 400

    historico = session.get("historico") or criar_historico_inicial()

    # guarda no histórico (para UI)
    historico.append({"role": "user", "content": mensagem_usuario})
    historico = limitar_historico(historico)

    # Chama o Flowise
    resposta_json = flowise_predict(question=mensagem_usuario)

    # Trata erro Flowise
    if isinstance(resposta_json, dict) and resposta_json.get("error"):
        msg = resposta_json["error"].get("message", "Erro desconhecido no Flowise")
        return jsonify({"resposta": f"Ops! Tive um problema: {msg}", "status": "erro"}), 500

    texto_ia = extract_flowise_text(resposta_json)
    if not texto_ia:
        return jsonify({"resposta": "Não consegui obter resposta do Flowise.", "status": "erro"}), 500

    # guarda resposta no histórico
    historico.append({"role": "assistant", "content": texto_ia})
    session["historico"] = historico

    return jsonify({"resposta": texto_ia, "status": "sucesso"})


@app.route("/limpar_historico", methods=["POST"])
def limpar_historico():
    session["historico"] = criar_historico_inicial()
    return jsonify({"status": "sucesso", "mensagem": "Histórico limpo"})


# --- TRATAMENTO DE ERROS ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template("index.html"), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"erro": "Erro interno do servidor"}), 500


if __name__ == "__main__":
    if not os.getenv("FLOWISE_CHAT_URL"):
        print("⚠️  ATENÇÃO: FLOWISE_CHAT_URL não encontrada no arquivo .env")

    if not os.getenv("FLOWISE_UPSERT_URL"):
        print("⚠️  ATENÇÃO: FLOWISE_UPSERT_URL não encontrada no arquivo .env")

    print("🚀 Iniciando servidor Flask...")
    app.run(debug=True, port=5000)