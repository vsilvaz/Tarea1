from flask import Flask, request
import json
import requests
import base64

app = Flask(__name__)

#CREDENCIALES
TOKEN = "7972529424:AAFEPNXZ0_A-CfgxZpAYkWDhMyH4V8-3gXg"
SPOTIFY_CLIENT_ID = "0e8d42a6291e4b91aae5b53a1ed92198"
SPOTIFY_CLIENT_SECRET = "3a2fb5cf698048e2a0c9b600219ced43"
NGROK_URL = "https://c0e0d8f780f9.ngrok-free.app"

user_tokens = {}
message_to_track_map = {}

def enviar_mensaje(chat_id, texto):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': texto}
    response = requests.post(url, json=payload)
    return response.json()

def refresh_spotify_token(chat_id):
    if chat_id not in user_tokens or "refresh_token" not in user_tokens[chat_id]: return False
    refresh_token = user_tokens[chat_id]["refresh_token"]
    token_url = "https://accounts.spotify.com/api/token"
    auth_str = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {auth_b64}"}
    payload = {'grant_type': 'refresh_token', 'refresh_token': refresh_token}
    response = requests.post(token_url, headers=headers, data=payload)
    if response.status_code == 200:
        user_tokens[chat_id]["access_token"] = response.json()["access_token"]
        return True
    return False

def make_spotify_request(chat_id, method, url, json_data=None, params=None):
    if chat_id not in user_tokens: return None
    access_token = user_tokens[chat_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    response = requests.request(method, url, headers=headers, json=json_data, params=params)
    if response.status_code == 401:
        if refresh_spotify_token(chat_id):
            return make_spotify_request(chat_id, method, url, json_data, params)
        else: return None
    return response

def control_playback(chat_id, action):
    endpoints = {'play': ('PUT', 'https://accounts.spotify.com/authorize0'), 'pause': ('PUT', 'https://accounts.spotify.com/authorize0'), 'next': ('POST', 'https://accounts.spotify.com/authorize1'), 'previous': ('POST', 'https://accounts.spotify.com/authorize2')}
    method, url = endpoints[action]
    response = make_spotify_request(chat_id, method, url, json_data={})
    if response and response.status_code == 204: return f"Comando '{action}' ejecutado."
    elif response and response.status_code == 404: return "No se encontró un dispositivo activo."
    elif response and response.status_code == 403: return f"Permiso denegado por Spotify."
    else: return f"No se pudo ejecutar '{action}'. (Error: {response.status_code if response else 'N/A'})"

def get_current_song(chat_id):
    response = make_spotify_request(chat_id, 'GET', "https://api.spotify.com/v1/me/player/currently-playing")
    if not response or response.status_code not in [200, 204]: return "No pude obtener la canción."
    if response.status_code == 204 or not response.content: return "No hay ninguna canción sonando."
    try:
        data = response.json()
        if data and data.get('item'): return f"🎵 Sonando: '{data['item']['name']}' de {data['item']['artists'][0]['name']}"
        else: return "No se detecta un dispositivo activo. Abre Spotify y selecciona 'Este Dispositivo'."
    except: return "Error al procesar la respuesta."

def search_song(chat_id, query):
    params = {'q': query, 'type': 'track', 'limit': 5}
    response = make_spotify_request(chat_id, 'GET', "https://accounts.spotify.com/authorize3?q=", params=params)
    if not response or response.status_code != 200:
        enviar_mensaje(chat_id, "No se encontraron canciones.")
        return
    results = response.json()['tracks']['items']
    if not results:
        enviar_mensaje(chat_id, "No se encontraron canciones.")
        return
    enviar_mensaje(chat_id, f"Resultados para '{query}':\n(Reacciona para añadir a favoritos)")
    for track in results:
        track_info = f"'{track['name']}' de {track['artists'][0]['name']}"
        sent_message = enviar_mensaje(chat_id, track_info)
        if sent_message and sent_message.get('ok'):
            message_id = sent_message['result']['message_id']
            message_to_track_map[message_id] = track['id']

def like_song(chat_id, track_id):
    params = {'ids': track_id}
    response = make_spotify_request(chat_id, 'PUT', "https://accounts.spotify.com/authorize4?ids=", params=params)
    if response and response.status_code == 200: return "💚 ¡Canción añadida a tus favoritos!"
    return "No se pudo añadir la canción."

@app.route('/webhook', methods=['POST'])
def webhook_telegram():
    data = request.get_json(silent=True)
    if not data: return {"ok": True}
    if 'message_reaction' in data:
        reaction = data['message_reaction']
        chat_id = reaction['chat']['id']
        message_id = reaction['message_id']
        if message_id in message_to_track_map:
            track_id = message_to_track_map[message_id]
            enviar_mensaje(chat_id, like_song(chat_id, track_id))
        return {"ok": True}
    if 'message' in data and 'text' in data['message']:
        chat_id = data['message']['chat']['id']
        mensaje = data['message']['text']
        if chat_id not in user_tokens and mensaje != "/install":
            enviar_mensaje(chat_id, "Usa /install para conectar tu cuenta de Spotify.")
            return {"ok": True}
        
        if mensaje == "/install":
            redirect_uri = f"{NGROK_URL}/callback"
            scope = "user-read-private user-read-email user-library-read user-library-modify user-read-playback-state user-modify-playback-state user-read-currently-playing"
            state = str(chat_id)
            auth_url = (f"https://accounts.spotify.com/authorize?response_type=code&client_id={SPOTIFY_CLIENT_ID}" f"&scope={scope}&redirect_uri={redirect_uri}&state={state}")
            enviar_mensaje(chat_id, f"Para instalar, haz clic aquí: {auth_url}")
        elif mensaje == "/current": enviar_mensaje(chat_id, get_current_song(chat_id))
        elif mensaje == "/play": enviar_mensaje(chat_id, control_playback(chat_id, 'play'))
        elif mensaje == "/pause": enviar_mensaje(chat_id, control_playback(chat_id, 'pause'))
        elif mensaje == "/next": enviar_mensaje(chat_id, control_playback(chat_id, 'next'))
        elif mensaje == "/previous": enviar_mensaje(chat_id, control_playback(chat_id, 'previous'))
        elif mensaje.startswith("/search "): search_song(chat_id, mensaje.split(' ', 1)[1])
        elif mensaje == "/help": enviar_mensaje(chat_id, "Comandos:\n/current\n/play\n/pause\n/next\n/previous\n/search [término]")
        else: enviar_mensaje(chat_id, "Comando no reconocido. Usa /help.")
    return {"ok": True}

@app.route('/callback')
def spotify_callback():
    code = request.args.get('code')
    chat_id = request.args.get('state')
    token_url = "https://accounts.spotify.com/api/token"
    redirect_uri = f"{NGROK_URL}/callback"
    auth_str = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {auth_b64}"}
    payload = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri}
    response = requests.post(token_url, headers=headers, data=payload)
    if response.status_code == 200:
        token_data = response.json()
        user_tokens[int(chat_id)] = {"access_token": token_data["access_token"], "refresh_token": token_data["refresh_token"]}
        enviar_mensaje(chat_id, "Spotify conectado")
        return "¡Autorización completada!"
    else:
        enviar_mensaje(chat_id, "Hubo un error al conectar.")
        return "Error en la autorización."

if __name__ == '__main__':
    app.run(port=8000)