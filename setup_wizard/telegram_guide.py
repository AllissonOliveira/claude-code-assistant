"""Guia passo a passo para criacao do bot no Telegram e validacao do token."""

import time

import requests

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}[OK]{RESET} {msg}")


def _erro(msg: str) -> None:
    print(f"  {RED}[X]{RESET} {msg}")


def _aviso(msg: str) -> None:
    print(f"  {YELLOW}[!]{RESET} {msg}")


def _escolha(opcoes: list[str], prompt: str = "Escolha") -> int:
    """Exibe opcoes numeradas, retorna indice 0-based."""
    print()
    for i, op in enumerate(opcoes, 1):
        print(f"  {BOLD}{i}{RESET} - {op}")
    print()
    while True:
        raw = input(f"  {prompt}: ").strip()
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(opcoes):
                return n - 1
        print(f"  {YELLOW}Digite um numero entre 1 e {len(opcoes)}.{RESET}")


def _validate_token(token: str) -> dict | None:
    """Valida o token chamando getMe. Retorna info do bot ou None."""
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            return data["result"]
        return None
    except requests.RequestException:
        return None


def _poll_for_message(token: str, timeout: int = 120) -> dict | None:
    """Aguarda a primeira mensagem recebida pelo bot. Retorna a mensagem ou None."""
    start = time.time()
    last_update_id = 0

    # Descarta updates antigos
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": -1},
            timeout=10,
        )
        data = resp.json()
        if data.get("ok") and data.get("result"):
            last_update_id = data["result"][-1]["update_id"] + 1
    except requests.RequestException:
        pass

    print(f"\n  {YELLOW}Aguardando sua mensagem (tempo limite: {timeout} segundos)...{RESET}")

    while time.time() - start < timeout:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": last_update_id, "timeout": 2},
                timeout=15,
            )
            data = resp.json()
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    msg = update.get("message")
                    if msg and msg.get("chat"):
                        return msg
        except requests.RequestException:
            pass
        time.sleep(2)

    return None


def setup_telegram() -> dict:
    """Guia o usuario na criacao do bot e retorna {token, chat_id}."""

    print(f"""
  {BOLD}Vamos criar o seu bot no Telegram.{RESET}

  O Telegram usa "bots" para se comunicar com programas como este assistente.
  Voce vai criar um bot pelo proprio Telegram — e bem simples, leva 2 minutos.

  {BOLD}Siga os passos abaixo:{RESET}

  {CYAN}Passo 1:{RESET} Abra o Telegram no celular ou computador

  {CYAN}Passo 2:{RESET} Pesquise por  {BOLD}@BotFather{RESET}  (o criador oficial de bots)

  {CYAN}Passo 3:{RESET} Clique em "Iniciar" ou mande a mensagem  {BOLD}/newbot{RESET}

  {CYAN}Passo 4:{RESET} O BotFather vai perguntar um nome para o bot
            Exemplo: {BOLD}Meu Assistente{RESET}

  {CYAN}Passo 5:{RESET} Depois vai pedir um nome de usuario (termina sempre em "bot")
            Exemplo: {BOLD}meuassistente_bot{RESET}

  {CYAN}Passo 6:{RESET} O BotFather vai te mandar uma mensagem com o TOKEN do bot
            Parece com isso: {BOLD}7123456789:AAFdkj3j2k3...(texto longo){RESET}

  {CYAN}Passo 7:{RESET} Copie esse token e cole aqui abaixo.
""")

    # Coleta e valida o token
    while True:
        token = input(f"  Cole o token aqui: ").strip()
        if not token:
            print(f"  {YELLOW}Voce precisa colar o token para continuar.{RESET}")
            continue

        print(f"\n  {YELLOW}Verificando se o token e valido...{RESET}")
        bot_info = _validate_token(token)
        if bot_info:
            bot_name = bot_info.get("first_name", "")
            bot_username = bot_info.get("username", "")
            _ok(f"Bot encontrado: {BOLD}{bot_name}{RESET}{GREEN} (@{bot_username})")
            break

        _erro("Token invalido ou nao encontrado.")
        print(f"\n  O que voce quer fazer?\n")
        idx = _escolha([
            "Tentar novamente com outro token",
            "Cancelar a configuracao do Telegram",
        ])
        if idx == 1:
            print("\n  Telegram nao configurado. Voce pode configurar depois no config.json.\n")
            return {"token": "", "chat_id": None}

    # Aguarda mensagem para capturar o chat_id
    print(f"""
  {BOLD}Perfeito! Agora vamos conectar o bot a voce.{RESET}

  {CYAN}Passo 1:{RESET} Abra o link do seu bot no Telegram:
            {BOLD}https://t.me/{bot_info.get('username', '')}{RESET}

  {CYAN}Passo 2:{RESET} Clique em "Iniciar" e depois mande qualquer mensagem
            (pode ser um "oi" mesmo)

  Estou aguardando a mensagem...
""")

    msg = _poll_for_message(token)

    if msg is None:
        _aviso("Nao recebi nenhuma mensagem no tempo limite.")
        print(f"\n  O que voce quer fazer?\n")
        idx = _escolha([
            "Esperar mais 2 minutos",
            "Informar o chat_id manualmente",
            "Pular esta etapa (configuro depois)",
        ])

        if idx == 0:
            msg = _poll_for_message(token, timeout=120)

        if msg is None and idx == 1:
            print(f"\n  Voce pode descobrir seu chat_id acessando:")
            print(f"  {CYAN}https://t.me/userinfobot{RESET}  — mande /start para esse bot.")
            print()
            raw = input(f"  Digite seu chat_id (so os numeros): ").strip()
            chat_id = int(raw) if raw.isdigit() else None
            if not chat_id:
                _aviso("chat_id nao informado. Configure depois no config.json.")
                return {"token": token, "chat_id": None}
            return {"token": token, "chat_id": chat_id}

        if msg is None:
            _aviso("chat_id nao capturado. Configure depois no config.json.")
            return {"token": token, "chat_id": None}

    chat = msg["chat"]
    chat_id = chat["id"]
    sender = chat.get("first_name", "")
    _ok(f"Mensagem recebida de {BOLD}{sender}{RESET}{GREEN}! Tudo conectado.")

    return {"token": token, "chat_id": chat_id}
