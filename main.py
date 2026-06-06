from flask import Flask, request, jsonify
import stripe
import os
from datetime import datetime, timedelta
import requests

app = Flask(__name__)

STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Identifica plano pelo valor em centavos
def identificar_plano(valor_centavos):
    if valor_centavos == 499:
        return {"nome": "express", "horas": 24}
    elif valor_centavos == 799:
        return {"nome": "24h", "horas": 24}
    elif valor_centavos == 999:
        return {"nome": "7dias", "horas": 168}
    elif valor_centavos == 1499:
        return {"nome": "premium", "horas": 720}
    else:
        return {"nome": "express", "horas": 24}

def gravar_usuario(email, plano, expira_em):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    data = {
        "Email": email,
        "Plano": plano,
        "expira_em": expira_em.isoformat(),
        "mensagem_grati": 0
    }
    url = f"{SUPABASE_URL}/rest/v1/Usuarios"
    response = requests.post(url, json=data, headers=headers)
    return response.status_code

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_details", {}).get("email")
        valor = session.get("amount_total", 0)

        plano = identificar_plano(valor)
        expira_em = datetime.utcnow() + timedelta(hours=plano["horas"])
        gravar_usuario(email, plano["nome"], expira_em)

    return jsonify({"status": "ok"}), 200

@app.route("/verificar", methods=["GET"])
def verificar():
    email = request.args.get("email")
    if not email:
        return jsonify({"ativo": False, "motivo": "email ausente"}), 400

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    url = f"{SUPABASE_URL}/rest/v1/Usuarios?Email=eq.{email}&select=Plano,expira_em,mensagem_grati"
    response = requests.get(url, headers=headers)
    dados = response.json()

    if not dados:
        return jsonify({"ativo": False, "motivo": "nao encontrado"})

    usuario = dados[0]
    expira_em = usuario.get("expira_em")

    if expira_em:
        expira = datetime.fromisoformat(expira_em.replace("Z", "+00:00")).replace(tzinfo=None)
        if datetime.utcnow() < expira:
            return jsonify({"ativo": True, "plano": usuario["Plano"]})
        else:
            return jsonify({"ativo": False, "motivo": "expirado"})

    msgs = usuario.get("mensagem_grati", 0)
    if msgs < 3:
        return jsonify({"ativo": True, "plano": "gratis", "mensagens": msgs})

    return jsonify({"ativo": False, "motivo": "limite gratis atingido"})

@app.route("/incrementar", methods=["POST"])
def incrementar():
    email = request.json.get("email")
    if not email:
        return jsonify({"error": "email ausente"}), 400

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    url = f"{SUPABASE_URL}/rest/v1/Usuarios?Email=eq.{email}&select=mensagem_grati"
    response = requests.get(url, headers=headers)
    dados = response.json()

    if not dados:
        requests.post(f"{SUPABASE_URL}/rest/v1/Usuarios", json={"Email": email, "mensagem_grati": 1}, headers=headers)
    else:
        atual = dados[0].get("mensagem_grati", 0)
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/Usuarios?Email=eq.{email}",
            json={"mensagem_grati": atual + 1},
            headers=headers
        )

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
