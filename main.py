from flask import Flask, request, jsonify
import stripe
import os
from datetime import datetime, timedelta
import requests

app = Flask(__name__)

STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

PLANOS = {
    "price_1TdHYoGc5T0Z5rAD7BaHQSZp": {"nome": "express",  "horas": 24},
    "price_1TdHYqGc5T0Z5rADJlbNkBvn": {"nome": "24h",      "horas": 24},
    "price_1TdHYpGc5T0Z5rAD4DQRthZI": {"nome": "7dias",    "horas": 168},
    "price_1TfPpqGc5T0Z5rADN7YDskWW": {"nome": "premium",  "horas": 720},
}

TOLERANCIA_MINUTOS = 10

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
        "mensagem_gratis": 0
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

        # Busca o price_id dentro dos line_items expandidos
        # O Stripe envia o price.id dentro de line_items quando expand está configurado
        # Alternativa segura: buscar via API
        session_id = session.get("id")

        try:
            line_items = stripe.checkout.Session.list_line_items(session_id, limit=1)
            price_id = line_items["data"][0]["price"]["id"]
        except Exception:
            price_id = None

        plano = PLANOS.get(price_id, {"nome": "express", "horas": 24})
        expira_em = datetime.utcnow() + timedelta(hours=plano["horas"]) + timedelta(minutes=TOLERANCIA_MINUTOS)
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
    url = f"{SUPABASE_URL}/rest/v1/Usuarios?Email=eq.{email}&select=Plano,expira_em,mensagem_gratis"

    try:
        response = requests.get(url, headers=headers)
        dados = response.json()
    except Exception as e:
        return jsonify({"ativo": False, "motivo": "erro banco"}), 500

    if not dados or not isinstance(dados, list) or len(dados) == 0:
        return jsonify({"ativo": True, "plano": "gratis", "mensagens": 0})

    usuario = dados[0]
    expira_em = usuario.get("expira_em")

    if expira_em:
        try:
            expira = datetime.fromisoformat(expira_em.replace("Z", "").replace("+00:00", ""))
            if datetime.utcnow() < expira:
                return jsonify({"ativo": True, "plano": usuario.get("Plano", "pago")})
            else:
                return jsonify({"ativo": False, "motivo": "expirado"})
        except Exception:
            return jsonify({"ativo": False, "motivo": "erro data"})

    msgs = usuario.get("mensagem_gratis", 0) or 0
    if msgs < 3:
        return jsonify({"ativo": True, "plano": "gratis", "mensagens": msgs})

    return jsonify({"ativo": False, "motivo": "limite gratis atingido"})

@app.route("/incrementar", methods=["POST"])
def incrementar():
    try:
        email = request.json.get("email")
    except Exception:
        return jsonify({"error": "json invalido"}), 400

    if not email:
        return jsonify({"error": "email ausente"}), 400

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    url = f"{SUPABASE_URL}/rest/v1/Usuarios?Email=eq.{email}&select=mensagem_gratis"
    response = requests.get(url, headers=headers)
    dados = response.json()

    if not dados or not isinstance(dados, list) or len(dados) == 0:
        headers_insert = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        requests.post(
            f"{SUPABASE_URL}/rest/v1/Usuarios",
            json={"Email": email, "mensagem_gratis": 1},
            headers=headers_insert
        )
    else:
        atual = dados[0].get("mensagem_gratis", 0) or 0
        novo = atual + 1
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/Usuarios?Email=eq.{email}",
            json={"mensagem_gratis": novo},
            headers=headers
        )
        if novo >= 3:
            return jsonify({"status": "limite_atingido"})

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
