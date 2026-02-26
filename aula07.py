import os
import json
import dotenv
import requests
from flask import Flask, render_template, request, jsonify, session
from datetime import datetime

print("Iniciando aplicação Flask...")

# Carrega variáveis de ambiente (.env) logo no começo
dotenv.load_dotenv()
print("✅ Variáveis de ambiente carregadas")

app = Flask(__name__)
print("✅ App Flask criado")

# Configurações - usa SECRET_KEY do .env ou gera uma aleatória
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(24).hex())
print("✅ SECRET_KEY configurada")

# --- HELPERS ---

def flowise_predict(question: str, chat_history=None, override_config=None):
    """
    Faz requisição para o Flowise (/prediction) com tratamento de erros.
    Usa FLOWISE_CHAT_URL e opcionalmente FLOWISE_API_KEY do .env.
    """
    url = os.getenv("FLOWISE_CHAT_URL")
    api_key = os.getenv("FLOWISE_API_KEY")

    if not url:
        msg = "FLOWISE_CHAT_URL não encontrada no arquivo .env"
        print(f"❌ {msg}")
        return {"error": {"message": msg}}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {"question": question}

    # Alguns fluxos suportam chatHistory / overrideConfig
    if chat_history is not None:
        payload["chatHistory"] = chat_history
    if override_config is not None:
        payload["overrideConfig"] = override_config

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()

    except requests.exceptions.Timeout:
        msg = "Timeout: Flowise demorou muito para responder"
        print(f"❌ {msg}")
        return {"error": {"message": msg}}

    except requests.exceptions.HTTPError as e:
        status = resp.status_code if resp is not None else "desconhecido"
        corpo = resp.text if resp is not None else "sem corpo"
        msg = f"Erro HTTP {status}: {e} | Corpo: {corpo}"
        print(f"❌ {msg}")
        return {"error": {"message": msg}}

    except requests.exceptions.RequestException as e:
        msg = f"Erro na requisição: {str(e)}"
        print(f"❌ {msg}")
        return {"error": {"message": msg}}

    except Exception as e:
        msg = f"Erro inesperado: {str(e)}"
        print(f"❌ {msg}")
        return {"error": {"message": msg}}


def extract_flowise_text(data):
    """
    Normaliza a resposta do Flowise para texto.
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

        # fallback
        return json.dumps(data, ensure_ascii=False)

    if isinstance(data, str):
        return data

    return str(data)


print("✅ Função flowise_predict definida")


def criar_historico_inicial():
    """
    Cria o histórico inicial com a mensagem de sistema para cada nova sessão.
    OBS: o ideal é este prompt estar configurado no próprio Flowise.
    """
    hora_atual = datetime.now()

    system_prompt = (
        f"Você é um assistente jurídico virtual renomado, com mestrado em diversas "
        f"disciplinas do Direito e especialista em concursos públicos da área jurídica. "
        f"Horário atual: {hora_atual.strftime('%H:%M')}. "
        f"Contexto: "
        f"- Você auxilia em dúvidas jurídicas gerais, em estudos para concursos (como OAB "
        f"e carreiras jurídicas) e na compreensão de temas de Direito. "
        f"- Você NÃO substitui um advogado ou defensor público e deve sempre lembrar o "
        f"usuário de buscar um profissional habilitado para casos concretos. "
        f"Regras de atendimento: "
        f"- Fale sempre em português brasileiro. "
        f"- Seja extremamente claro, educado, profissional e objetivo. "
        f"- Faça apenas uma pergunta por vez ao usuário. "
        f"- Se faltar alguma informação relevante para a análise, pergunte e não suponha. "
        f"- Quando a pergunta envolver caso concreto, responda em termos gerais, "
        f"sem afirmar que aquela é a única solução, e recomende consulta a um profissional. "
        f"- Quando a dúvida for de concurso público, identifique o nível do usuário "
        f"(iniciante, intermediário, avançado) e o tipo de prova (objetiva, discursiva, peça) "
        f"antes de sugerir estratégias de estudo. "
        f"- Sempre organize a resposta em tópicos quando o assunto for complexo. "
        f"- Cite a área do Direito envolvida (por exemplo, Direito Constitucional, "
        f"Administrativo, Penal, Civil, Processo Penal, Processo Civil, Trabalho etc.) "
        f"sempre que possível. "
        f"- Evite jargões excessivos; quando usar termos técnicos, explique de forma simples. "
        f"- Não invente artigos de lei ou súmulas; se não tiver certeza, diga que não tem "
        f"certeza e oriente a conferência na legislação atualizada. "
        f"- Nunca incentive práticas ilegais ou antiéticas em provas ou concursos. "
    )

    return [{"role": "system", "content": system_prompt}]


print("✅ Função criar_historico_inicial definida")


def limitar_historico(mensagens, max_mensagens=20):
    """
    Limita o histórico para não crescer demais.
    Sempre mantém a mensagem de sistema (índice 0).
    """
    if not mensagens:
        return criar_historico_inicial()

    system_msg = mensagens[0]
    restante = mensagens[1:]
    if len(restante) > max_mensagens:
        restante = restante[-max_mensagens:]
    return [system_msg] + restante


print("✅ Função limitar_historico definida")

# --- ROTAS ---

@app.route("/")
def index():
    session["historico"] = criar_historico_inicial()
    return render_template("index.html")


print("✅ Rota / definida")


@app.route("/enviar_mensagem", methods=["POST"])
def enviar_mensagem():
    dados = request.get_json(silent=True) or {}
    mensagem_usuario = (dados.get("mensagem") or "").strip()

    if not mensagem_usuario:
        return jsonify({"resposta": "Mensagem vazia", "status": "erro"}), 400

    historico = session.get("historico") or criar_historico_inicial()

    # histórico local (para UI)
    historico.append({"role": "user", "content": mensagem_usuario})
    historico = limitar_historico(historico)

    # Chama Flowise
    resposta_json = flowise_predict(question=mensagem_usuario)

    # erro estruturado
    if isinstance(resposta_json, dict) and resposta_json.get("error"):
        mensagem_erro = resposta_json["error"].get("message", "Erro desconhecido no Flowise")
        return jsonify({
            "resposta": f"Ops! Tive um problema: {mensagem_erro}",
            "status": "erro"
        }), 500

    texto_ia = extract_flowise_text(resposta_json)
    if not texto_ia:
        return jsonify({
            "resposta": "Não consegui obter resposta do Flowise.",
            "status": "erro"
        }), 500

    historico.append({"role": "assistant", "content": texto_ia})
    session["historico"] = historico

    return jsonify({"resposta": texto_ia, "status": "sucesso"})


print("✅ Rota /enviar_mensagem definida")


@app.route("/limpar_historico", methods=["POST"])
def limpar_historico():
    session["historico"] = criar_historico_inicial()
    return jsonify({"status": "sucesso", "mensagem": "Histórico limpo"})


print("✅ Rota /limpar_historico definida")

# --- TRATAMENTO DE ERROS ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template("index.html"), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"erro": "Erro interno do servidor"}), 500


print("✅ Error handlers definidos")


if __name__ == "__main__":
    if not os.getenv("FLOWISE_CHAT_URL"):
        print("⚠️  ATENÇÃO: FLOWISE_CHAT_URL não encontrada no arquivo .env")

    print("🚀 Iniciando servidor Flask...")
    app.run(debug=True, port=5000)