import os
import requests
import dotenv
import datetime

def conversar_gemini(modelo='gemini-1.5-flash', payload=''):
    """
    Faz requisição para a API do Gemini com tratamento de erros
    """
    API_KEY = os.getenv('GEMINI_API_KEY')
    
    if not API_KEY:
        print("❌ ERRO: GEMINI_API_KEY não encontrada no arquivo .env")
        return None
    
    url_base = "https://generativelanguage.googleapis.com/v1beta/models"
    url = f"{url_base}/{modelo}:generateContent?key={API_KEY}"
    
    try:
        resposta = requests.post(url, json=payload, timeout=30)
        resposta.raise_for_status()  # Lança exceção para códigos de erro HTTP
        return resposta.json()
    except requests.exceptions.Timeout:
        print("❌ ERRO: A API demorou muito para responder (timeout)")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"❌ ERRO HTTP: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ ERRO na requisição: {e}")
        return None
    except Exception as e:
        print(f"❌ ERRO inesperado: {e}")
        return None


# Carrega variáveis de ambiente UMA ÚNICA VEZ
dotenv.load_dotenv()

# Captura hora atual e INCLUI no system instruction
hora_atual = datetime.datetime.now()
print(f'⏰ Hora atual: {hora_atual.hour}:{hora_atual.minute:02d}')

payload = {
    "systemInstruction": {
        "parts": [
            {
                "text": (
                    f"Você é um atendente virtual de uma lanchonete. "
                    f"Horário atual: {hora_atual.strftime('%H:%M')}. "
                    f"Regras: "
                    f"- Fale sempre em português "
                    f"- Seja educado e objetivo "
                    f"- Faça apenas uma pergunta por vez "
                    f"- Não crie promoções "
                    f"- Sempre confirme o pedido antes de finalizar "
                    f"- Se faltar alguma informação pergunte e não suponha "
                    f"- O horário de funcionamento é 24 horas"
                )
            }
        ]
    },
    "contents": [],
    "generationConfig": {
        "maxOutputTokens": 200,
        "temperature": 0.1,
    }
}

print("\n" + "="*50)
print("🤖 ATENDENTE VIRTUAL DA LANCHONETE")
print("="*50)

while True:
    print("\n📋 MENU:")
    opcao = input('1 - Converse com o atendente\n2 - Sair\nResposta: ').strip()
    
    if opcao == '1':
        mensagem = input('\n💬 Digite sua pergunta: ').strip()
        
        # Valida se a mensagem não está vazia
        if not mensagem:
            print("⚠️  Mensagem vazia! Digite algo para continuar.")
            continue

        # Adiciona mensagem do usuário
        content = {"role": "user", "parts": [{"text": mensagem}]}
        payload['contents'].append(content)

        # Chama a API
        print("\n⏳ Aguarde, processando...")
        resposta = conversar_gemini(payload=payload)

        # Verifica se houve erro
        if resposta is None:
            print("❌ Não foi possível obter resposta. Tente novamente.")
            # Remove a última mensagem do usuário do histórico
            payload['contents'].pop()
            continue

        # Processa a resposta
        try:
            resposta_gemini = resposta['candidates'][0]['content']
            
            # Extrai APENAS O TEXTO da resposta
            texto_resposta = resposta_gemini['parts'][0]['text']
            
            # Adiciona ao histórico
            payload['contents'].append(resposta_gemini)

            # Mostra apenas o texto formatado
            print(f'\n🤖 Atendente: {texto_resposta}')
            
        except (KeyError, IndexError) as e:
            print(f"❌ ERRO ao processar resposta: {e}")
            print(f"Resposta recebida: {resposta}")
            # Remove a última mensagem do usuário do histórico
            payload['contents'].pop()

    elif opcao == '2':
        print('\n👋 Saindo... Até logo!')
        break
    
    else:
        print('⚠️  Opção inválida! Por favor, escolha 1 ou 2.')