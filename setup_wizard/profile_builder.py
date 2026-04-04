"""Coleta informacoes de perfil do usuario para gerar os arquivos de configuracao."""

import os
from datetime import datetime
from pathlib import Path

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Helpers de entrada
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    """Pede texto livre. Se default, aceita Enter."""
    if default:
        raw = input(f"  {CYAN}{prompt}{RESET} [{default}]: ").strip()
        return raw if raw else default
    while True:
        raw = input(f"  {CYAN}{prompt}{RESET}: ").strip()
        if raw:
            return raw
        print(f"  {YELLOW}Este campo e obrigatorio. Por favor, preencha.{RESET}")


def _ask_multiline(prompt: str) -> str:
    """Aceita multiplas linhas ate linha vazia."""
    print(f"  {CYAN}{prompt}{RESET}")
    print(f"  {YELLOW}(quando terminar, deixe uma linha em branco e pressione Enter){RESET}")
    lines = []
    while True:
        line = input("  ")
        if line.strip() == "":
            break
        lines.append(line)
    return "\n".join(lines)


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


def _detect_timezone() -> str:
    try:
        tz = datetime.now().astimezone().tzinfo
        return str(tz) or "UTC"
    except Exception:
        return "UTC"


# ---------------------------------------------------------------------------
# Coleta por documento
# ---------------------------------------------------------------------------

def collect_from_document() -> dict:
    """Le documento do usuario e extrai o perfil."""
    print(f"\n  Como voce quer fornecer o documento?\n")
    idx = _escolha([
        "Informar o caminho do arquivo no computador",
        "Colar o conteudo aqui mesmo",
    ])

    if idx == 0:
        while True:
            path = input(f"  {CYAN}Caminho do arquivo{RESET}: ").strip()
            if os.path.exists(path):
                content = Path(path).read_text(encoding="utf-8")
                print(f"  {GREEN}Arquivo lido com sucesso!{RESET}")
                break
            print(f"  {YELLOW}Arquivo nao encontrado. Verifique o caminho e tente novamente.{RESET}")
    else:
        print(f"\n  {CYAN}Cole o conteudo do documento abaixo.{RESET}")
        print(f"  {YELLOW}(quando terminar, deixe uma linha em branco e pressione Enter){RESET}\n")
        lines = []
        while True:
            line = input("  ")
            if line.strip() == "":
                break
            lines.append(line)
        content = "\n".join(lines)

    profile = parse_document(content)

    # Mostra resumo e confirma
    print(f"\n  {BOLD}Isso e o que entendi do seu documento:{RESET}")
    print(f"  Nome     : {profile.get('name', '(nao encontrado)')}")
    print(f"  Email    : {profile.get('email', '(nao encontrado)')}")
    print(f"  Funcao   : {profile.get('role', '(nao encontrado)')}")
    print()

    idx = _escolha([
        "Sim, esta correto",
        "Nao, prefiro responder as perguntas manualmente",
    ], prompt="Esta correto?")

    if idx == 1:
        return collect_from_questions()

    return profile


def parse_document(content: str) -> dict:
    """Extrai informacoes de um documento de texto livre."""
    profile: dict = {
        "name": "",
        "preferred_name": "",
        "email": "",
        "timezone": "America/Sao_Paulo",
        "role": "",
        "company": "",
        "responsibilities": "",
        "tools": "",
        "communication_style": "Seja direto e conciso. Va direto ao ponto.",
        "communication_label": "Direto e conciso",
        "tone": "informal",
        "can_disagree": True,
        "never_do": [],
        "calendar_email": "",
        "work_start": "08:00",
        "work_end": "18:00",
        "days_off": "sabado, domingo",
        "auto_meet": True,
        "contacts": [],
        "use_cases": "",
        "extras": "",
        "raw_document": content,
        "user_name": "",
        "user_role": "",
        "language": "Portugues",
        "help_description": "",
        "custom_instructions": "",
    }

    lines = content.split("\n")
    current_section = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped.lower()
            continue
        if not stripped or stripped.startswith("#") or stripped.startswith("---"):
            continue

        if ":" in stripped and not stripped.startswith("-") and not stripped.startswith("["):
            key, _, value = stripped.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if not value:
                continue
            if "nome completo" in key:
                profile["name"] = value
                profile["user_name"] = value
            elif "chamado" in key or "prefere ser" in key:
                profile["preferred_name"] = value
            elif "email" in key and "agenda" not in current_section:
                profile["email"] = value
            elif "fuso" in key or "timezone" in key:
                profile["timezone"] = value
            elif "cargo" in key or "funcao" in key:
                profile["role"] = value
                profile["user_role"] = value
            elif "empresa" in key:
                profile["company"] = value
            elif "email" in key and "agenda" in current_section:
                profile["calendar_email"] = value
            elif "comeca" in key or "inicio" in key:
                profile["work_start"] = value
            elif "para" in key or "termina" in key:
                profile["work_end"] = value
            elif "nao trabalha" in key:
                profile["days_off"] = value

        if "|" in stripped and stripped.startswith("-"):
            parts = [p.strip() for p in stripped.lstrip("- ").split("|")]
            if len(parts) >= 2:
                profile["contacts"].append({
                    "name": parts[0],
                    "phone": parts[1] if len(parts) > 1 else "",
                    "email": parts[2] if len(parts) > 2 else "",
                    "context": parts[3] if len(parts) > 3 else "",
                })

        if "nunca" in current_section or "never" in current_section:
            if stripped.startswith("-") and len(stripped) > 2:
                profile["never_do"].append(stripped.lstrip("- "))

    # Fallbacks
    if not profile["calendar_email"] and profile["email"]:
        profile["calendar_email"] = profile["email"]
    if not profile["preferred_name"] and profile["name"]:
        profile["preferred_name"] = profile["name"].split()[0]
    if not profile["user_name"] and profile["name"]:
        profile["user_name"] = profile["name"]
    if not profile["user_role"] and profile["role"]:
        profile["user_role"] = profile["role"]
    if not profile["help_description"] and profile["use_cases"]:
        profile["help_description"] = profile["use_cases"]

    return profile


# ---------------------------------------------------------------------------
# Coleta por perguntas
# ---------------------------------------------------------------------------

COMMUNICATION_STYLES = {
    "1": {
        "label": "Direto e conciso",
        "description": (
            "Seja direto e conciso. Sem enrolacao. "
            "Va direto ao ponto. Use frases curtas."
        ),
    },
    "2": {
        "label": "Detalhado e completo",
        "description": (
            "Seja detalhado e completo. Explique o raciocinio. "
            "Forneca contexto e alternativas quando relevante."
        ),
    },
    "3": {
        "label": "Depende da situacao",
        "description": (
            "Adapte o nivel de detalhe a complexidade do pedido. "
            "Respostas simples para perguntas simples, detalhadas para perguntas complexas."
        ),
    },
}

TON_OPTIONS = {
    "1": "informal",
    "2": "formal",
}


def collect_from_questions() -> dict:
    """Coleta perfil por perguntas interativas, uma por vez."""

    # 1. Nome completo
    print(f"\n  {BOLD}Qual e o seu nome completo?{RESET}\n")
    user_name = _ask("Seu nome")

    # 2. Como prefere ser chamado
    first = user_name.split()[0]
    print(f"\n  {BOLD}Como voce prefere ser chamado?{RESET}")
    print(f"  {YELLOW}(pressione Enter para usar '{first}'){RESET}\n")
    preferred_name = input(f"  Como te chamam: ").strip() or first

    # 3. Email principal
    print(f"\n  {BOLD}Qual e o seu email principal?{RESET}\n")
    email = _ask("Email")

    # 4. O que voce faz
    print(f"\n  {BOLD}O que voce faz?{RESET}")
    print(f"  Pode ser seu cargo, empresa, ou uma descricao do seu trabalho.")
    user_role = _ask_multiline("Descreva com suas proprias palavras")
    if not user_role:
        user_role = _ask("Descricao do seu trabalho")

    # 5. Estilo de comunicacao
    print(f"\n  {BOLD}Como voce prefere que o assistente responda?{RESET}")
    idx = _escolha([
        "Direto e conciso — respostas curtas e objetivas",
        "Detalhado e completo — explica tudo com contexto",
        "Depende da situacao — adapta conforme o assunto",
    ])
    style_key = str(idx + 1)
    style = COMMUNICATION_STYLES[style_key]

    # 6. Tom
    print(f"\n  {BOLD}Qual tom de linguagem voce prefere?{RESET}")
    idx_tom = _escolha([
        "Informal — mais descontraido, como conversa com amigo",
        "Formal — mais serio e profissional",
    ])
    tone = TON_OPTIONS[str(idx_tom + 1)]

    # 7. Pode discordar
    print(f"\n  {BOLD}O assistente pode discordar de voce quando achar necessario?{RESET}")
    idx_disc = _escolha([
        "Sim — quero opiniao honesta mesmo que discorde",
        "Nao — prefiro que siga minhas instrucoes sem questionar",
    ])
    can_disagree = idx_disc == 0

    # 8. Nunca fazer
    print(f"\n  {BOLD}Tem alguma coisa que o assistente NUNCA deve fazer?{RESET}")
    print(f"  Por exemplo: nao usar grias, nao mandar mensagens longas, etc.")
    print(f"  {YELLOW}(lista: uma por linha, linha vazia para terminar){RESET}\n")
    never_do = []
    while True:
        rule = input("  - ").strip()
        if not rule:
            break
        never_do.append(rule)

    # 9. Email da agenda
    print(f"\n  {BOLD}Qual email usar para criar eventos na sua agenda?{RESET}")
    print(f"  {YELLOW}(pressione Enter para usar o mesmo email: {email}){RESET}\n")
    calendar_email = input(f"  Email da agenda: ").strip() or email

    # 10. Horario de inicio
    print(f"\n  {BOLD}Que horas voce normalmente começa a trabalhar?{RESET}")
    print(f"  {YELLOW}(pressione Enter para usar 08:00){RESET}\n")
    work_start = input(f"  Horario de inicio: ").strip() or "08:00"

    # 11. Horario de fim
    print(f"\n  {BOLD}Que horas voce normalmente para de trabalhar?{RESET}")
    print(f"  {YELLOW}(pressione Enter para usar 18:00){RESET}\n")
    work_end = input(f"  Horario de termino: ").strip() or "18:00"

    # 12. Google Meet automatico
    print(f"\n  {BOLD}Quando criar reunioes com outras pessoas,{RESET}")
    print(f"  {BOLD}quer que o assistente adicione link de Google Meet automaticamente?{RESET}")
    idx_meet = _escolha([
        "Sim — adicionar link de Meet em reunioes com outras pessoas",
        "Nao — criar o evento sem link de video",
    ])
    auto_meet = idx_meet == 0

    # 13. Contatos principais
    print(f"\n  {BOLD}Quer cadastrar seus contatos mais importantes?{RESET}")
    print(f"  Isso ajuda o assistente a reconhecer pessoas pelos nomes.")
    print(f"  Formato: Nome | Telefone | Email | Contexto")
    print(f"  Exemplo:  Maria Silva | +55 11 99999-0000 | maria@empresa.com | Cliente VIP")
    print(f"  {YELLOW}(linha vazia para terminar){RESET}\n")
    contacts = []
    while True:
        raw = input("  > ").strip()
        if not raw:
            break
        parts = [p.strip() for p in raw.split("|")]
        contacts.append({
            "name": parts[0] if len(parts) > 0 else "",
            "phone": parts[1] if len(parts) > 1 else "",
            "email": parts[2] if len(parts) > 2 else "",
            "context": parts[3] if len(parts) > 3 else "",
        })

    # 14. Para que vai usar o bot
    print(f"\n  {BOLD}Para que voce vai usar o assistente principalmente?{RESET}")
    print(f"  Exemplos: gerenciar emails, organizar agenda, responder clientes, etc.")
    use_cases = _ask_multiline("Descreva como quiser")
    if not use_cases:
        use_cases = "Gestao de agenda, emails e tarefas do dia a dia"

    return {
        "name": user_name,
        "preferred_name": preferred_name,
        "email": email,
        "timezone": _detect_timezone(),
        "role": user_role,
        "company": "",
        "responsibilities": "",
        "tools": "",
        "communication_style": style["description"],
        "communication_label": style["label"],
        "tone": tone,
        "can_disagree": can_disagree,
        "never_do": never_do,
        "calendar_email": calendar_email,
        "work_start": work_start,
        "work_end": work_end,
        "days_off": "sabado, domingo",
        "auto_meet": auto_meet,
        "contacts": contacts,
        "use_cases": use_cases,
        "extras": "",
        "raw_document": "",
        # Campos de compatibilidade com generate_config
        "user_name": user_name,
        "user_role": user_role,
        "language": "Portugues",
        "help_description": use_cases,
        "custom_instructions": "",
    }


# ---------------------------------------------------------------------------
# Geracao de arquivos de perfil
# ---------------------------------------------------------------------------

def generate_profile_files(profile: dict) -> None:
    """Exibe resumo do perfil coletado."""
    name = profile.get("preferred_name") or profile.get("user_name", "")
    role = profile.get("user_role") or profile.get("role", "")
    print(f"\n  {GREEN}[OK]{RESET} Perfil registrado:")
    print(f"       Nome  : {BOLD}{name}{RESET}")
    if role:
        print(f"       Funcao: {role}")
    print(f"       TZ    : {profile.get('timezone', '')}")


# ---------------------------------------------------------------------------
# Alias de compatibilidade
# ---------------------------------------------------------------------------

def build_profile() -> dict:
    return collect_from_questions()
