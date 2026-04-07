"""Orquestrador principal do setup wizard do Claude Code Assistant."""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .mcp_installer import (
    add_custom_mcp,
    generate_tools_md,
    install_selected_mcps,
    load_available_mcps,
)
from .profile_builder import (
    collect_from_document,
    collect_from_questions,
    generate_profile_files,
)
from .service_installer import install_service
from .telegram_guide import setup_telegram
from .templates import (
    CLAUDE_TEMPLATE,
    CORE_TEMPLATE,
    HEARTBEAT_TEMPLATE,
    MEMORY_TEMPLATE,
    USER_TEMPLATE,
)

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

BASE_DIR = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

def print_header() -> None:
    print(f"""
{CYAN}{BOLD}  ╔══════════════════════════════════════════════════════╗
  ║       Claude Code Assistant — Configuracao          ║
  ║       Vamos deixar tudo pronto para voce!           ║
  ╚══════════════════════════════════════════════════════╝{RESET}

  Ola! Este assistente vai configurar tudo automaticamente.
  Voce so vai precisar responder algumas perguntas simples.
""")


def print_step(n: int, total: int, title: str) -> None:
    print(f"\n{BOLD}  {'=' * 51}{RESET}")
    print(f"{BOLD}{CYAN}  [{n}/{total}] {title}{RESET}")
    print(f"{BOLD}  {'=' * 51}{RESET}\n")


def print_ok(msg: str) -> None:
    print(f"  {GREEN}[OK]{RESET} {msg}")


def print_aviso(msg: str) -> None:
    print(f"  {YELLOW}[!]{RESET} {msg}")


def print_erro(msg: str) -> None:
    print(f"  {RED}[X]{RESET} {msg}")


def escolha(opcoes: list[str], prompt: str = "Escolha") -> int:
    """Exibe opcoes numeradas e retorna o indice escolhido (0-based).

    opcoes: lista de strings descritivas
    Nunca retorna sem uma escolha valida.
    """
    for i, op in enumerate(opcoes, 1):
        print(f"  {BOLD}{i}{RESET} - {op}")
    while True:
        raw = input(f"\n  {prompt}: ").strip()
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(opcoes):
                return n - 1
        print(f"  {YELLOW}Por favor, digite um numero entre 1 e {len(opcoes)}.{RESET}")


# ---------------------------------------------------------------------------
# Etapa 1: Verificacao do sistema
# ---------------------------------------------------------------------------

def check_system() -> None:
    """Verifica e instala dependencias automaticamente."""
    all_ok = True

    # Python
    py = sys.version_info
    if py >= (3, 12):
        print_ok(f"Python {py.major}.{py.minor}.{py.micro}")
    else:
        print_erro(
            f"Python {py.major}.{py.minor}.{py.micro} instalado, mas precisa da versao 3.12 ou mais nova.\n"
            f"  Acesse https://www.python.org/downloads e instale a versao mais recente."
        )
        all_ok = False

    # Claude CLI
    if shutil.which("claude"):
        print_ok("Claude Code CLI encontrado")
    else:
        print_aviso("Claude Code CLI nao encontrado. Instalando automaticamente...")
        result = subprocess.run(
            ["npm", "install", "-g", "@anthropic-ai/claude-code"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print_ok("Claude Code CLI instalado com sucesso!")
        else:
            print_aviso(
                "Nao consegui instalar automaticamente.\n"
                "  Acesse https://docs.anthropic.com e siga as instrucoes de instalacao."
            )

    # ffmpeg
    if shutil.which("ffmpeg"):
        print_ok("ffmpeg encontrado (audio ativado)")
    else:
        print_aviso("ffmpeg nao encontrado. Instalando automaticamente...")
        sistema = platform.system()
        if sistema == "Darwin":
            r = subprocess.run(["brew", "install", "ffmpeg"], capture_output=True, text=True)
        else:
            r = subprocess.run(
                ["sudo", "apt-get", "install", "-y", "ffmpeg"],
                capture_output=True,
                text=True,
            )
        if r.returncode == 0:
            print_ok("ffmpeg instalado!")
        else:
            print_aviso("Nao consegui instalar ffmpeg. Mensagens de audio nao vao funcionar.")

    # Node.js
    if shutil.which("node"):
        try:
            ver = subprocess.check_output(["node", "--version"], text=True).strip()
            print_ok(f"Node.js {ver}")
        except Exception:
            print_ok("Node.js encontrado")
    else:
        print_aviso(
            "Node.js nao encontrado. Algumas integracoes podem nao funcionar.\n"
            "  macOS: instale pelo site https://nodejs.org\n"
            "  Linux: instale pelo site https://nodejs.org"
        )

    # requests
    try:
        import requests as _r  # noqa: F401
        print_ok("Biblioteca de rede (requests) ok")
    except ImportError:
        print_aviso("Instalando biblioteca de rede...")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "requests"],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            print_ok("Biblioteca instalada!")
        else:
            print_erro("Falha ao instalar biblioteca requests.")
            all_ok = False

    # OS
    print_ok(f"Sistema: {platform.system()} ({platform.machine()})")

    if not all_ok:
        print(f"\n  {YELLOW}Algumas verificacoes falharam.{RESET}")
        print(f"\n  Como voce quer continuar?\n")
        idx = escolha(
            ["Continuar mesmo assim", "Cancelar e corrigir os problemas primeiro"]
        )
        if idx == 1:
            print("\n  Configuracao cancelada. Corrija os problemas acima e execute novamente.\n")
            sys.exit(1)


# ---------------------------------------------------------------------------
# Etapa 3: MCPs
# ---------------------------------------------------------------------------

def run_mcp_setup() -> list[dict]:
    """Mostra cada MCP e pergunta se quer instalar. Pular e sempre uma opcao."""
    print(
        f"  Vamos configurar suas integracoes.\n"
        f"  Voce pode pular qualquer uma.\n"
    )

    mcps = load_available_mcps()
    installed = install_selected_mcps(mcps)
    if installed:
        generate_tools_md(installed, BASE_DIR / "TOOLS.md")
        print_ok(f"{len(installed)} integracao(oes) configurada(s) com sucesso!")
    else:
        print_aviso("Nenhuma integracao foi instalada.")

    # MCP customizado
    print(f"\n  Quer adicionar alguma integracao extra que nao esta na lista?\n")
    idx = escolha(["Sim, quero adicionar outra integracao", "Nao, pode continuar"])
    if idx == 0:
        extra = add_custom_mcp()
        if extra:
            installed.append(extra)

    return installed


# ---------------------------------------------------------------------------
# Etapa 4: Telegram
# ---------------------------------------------------------------------------

def setup_telegram_flow() -> dict:
    """Roda o guia do Telegram e retorna {token, chat_id}."""
    return setup_telegram()


# ---------------------------------------------------------------------------
# Geracao de config e arquivos finais
# ---------------------------------------------------------------------------

def generate_config(token: str, chat_id: int | None, profile: dict) -> None:
    project_dir = str(BASE_DIR)

    for subdir in ("logs", "sessions", "memory", "audio"):
        os.makedirs(os.path.join(project_dir, subdir), exist_ok=True)
    print_ok("Pastas criadas: logs, sessions, memory, audio")

    comm_label = profile.get("communication_label", "Direto e conciso")
    comm_style = profile.get("communication_style", "")
    comm_prefs = f"{comm_label}: {comm_style}"

    custom_block = ""
    if profile.get("custom_instructions"):
        custom_block = (
            f"\n## Instrucoes Personalizadas\n\n"
            f"{profile['custom_instructions']}\n"
        )

    can_disagree = profile.get("can_disagree", True)
    opinion_style = (
        "Se uma abordagem tem problemas, diga com respeito."
        if can_disagree else
        "Siga as instrucoes do usuario sem questionar. Sugira alternativas apenas se solicitado."
    )
    tone = profile.get("tone", "informal")
    tone_description = (
        "Informal e direto. Fale como um colega competente, nao como um robo."
        if tone == "informal" else
        "Formal e profissional. Mantenha a linguagem objetiva e respeitosa."
    )
    core_content = CORE_TEMPLATE.substitute(
        bot_name=profile.get("bot_name", "Claude Assistant"),
        preferred_name=profile.get("preferred_name", profile.get("user_name", profile.get("name", ""))),
        communication_style=profile.get("communication_style", ""),
        opinion_style=opinion_style,
        tone_description=tone_description,
    )
    _escrever(os.path.join(project_dir, "CORE.md"), core_content)

    contacts = profile.get("contacts", [])
    if contacts:
        contacts_lines = ["| Nome | Telefone | Email | Contexto |", "|---|---|---|---|"]
        for c in contacts:
            contacts_lines.append(
                f"| {c.get('name', '')} | {c.get('phone', '')} | {c.get('email', '')} | {c.get('context', '')} |"
            )
        contacts_section = "\n".join(contacts_lines)
    else:
        contacts_section = "_(Contatos serao adicionados automaticamente conforme mencionados)_"

    user_content = USER_TEMPLATE.substitute(
        user_name=profile.get("user_name", profile.get("name", "")),
        user_role=profile.get("user_role", profile.get("role", "")),
        timezone=profile.get("timezone", "America/Sao_Paulo"),
        language=profile.get("language", "Portugues"),
        help_description=profile.get("help_description", profile.get("use_cases", "")),
        communication_preferences=comm_prefs,
        contacts_section=contacts_section,
    )
    _escrever(os.path.join(project_dir, "USER.md"), user_content)

    heartbeat_content = HEARTBEAT_TEMPLATE.substitute(
        user_name=profile.get("user_name", profile.get("name", "")),
    )
    _escrever(os.path.join(project_dir, "HEARTBEAT.md"), heartbeat_content)

    tools_lines = ["- Telegram: enviar/receber mensagens, fotos, documentos"]
    claude_content = CLAUDE_TEMPLATE.substitute(
        tools_section="\n".join(tools_lines),
        custom_instructions=custom_block,
    )
    _escrever(os.path.join(project_dir, "CLAUDE.md"), claude_content)

    memory_content = MEMORY_TEMPLATE.substitute(project_dir=project_dir)
    _escrever(os.path.join(project_dir, "MEMORY.md"), memory_content)

    behavior_content = (
        "# BEHAVIOR.md -- Regras de Comportamento\n\n"
        "## Regras Especificas\n\n"
        "_(Registre aqui as preferencias de comportamento confirmadas pelo usuario)_\n\n"
        "## O que NUNCA fazer\n\n"
    )
    if profile.get("never_do"):
        for rule in profile["never_do"]:
            behavior_content += f"- {rule}\n"
    else:
        behavior_content += "_(Registre aqui o que o usuario pediu explicitamente para evitar)_\n"
    _escrever(os.path.join(project_dir, "BEHAVIOR.md"), behavior_content)

    config = {
        "telegram_token": token,
        "telegram_chat_id": chat_id,
        "user_name": profile.get("user_name", profile.get("name", "")),
        "claude_model": "sonnet",
        "project_dir": project_dir,
        "polling_interval_seconds": 2,
        "session_timeout_hours": 3,
        "max_retry_attempts": 3,
        "retry_backoff_seconds": [5, 10, 30],
        "heartbeat_interval_minutes": profile.get("heartbeat_interval", 30),
        "heartbeat_times": profile.get("heartbeat_times", ["09:00", "13:00", "18:00"]),
        "reasoning_gate_enabled": True,
        "whisper_bin": "",
        "whisper_model": "base",
        "whisper_language": profile.get("language_code", "pt"),
        "timezone": profile.get("timezone", "America/Sao_Paulo"),
    }
    config_path = os.path.join(project_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.chmod(config_path, 0o600)
    print_ok("config.json gerado (permissoes: apenas seu usuario pode ler)")


def _escrever(path: str, content: str) -> None:
    with open(path, "w") as f:
        f.write(content)
    print_ok(f"{os.path.basename(path)} gerado")


# ---------------------------------------------------------------------------
# Tela final
# ---------------------------------------------------------------------------

def print_success(service_installed: bool = False) -> None:
    project_dir = str(BASE_DIR)
    daemon_path = os.path.join(project_dir, "daemon.py")

    # Se o servico nao foi instalado, inicia o daemon em background
    if not service_installed:
        try:
            subprocess.Popen(
                [sys.executable, daemon_path],
                cwd=project_dir,
                stdout=open(os.path.join(project_dir, "logs", "daemon.stdout.log"), "a"),
                stderr=open(os.path.join(project_dir, "logs", "daemon.stderr.log"), "a"),
                start_new_session=True,
            )
            print_ok("Daemon iniciado em background")
        except Exception as e:
            print_aviso(f"Nao consegui iniciar o daemon: {e}")

    # Verifica se o daemon esta rodando
    time.sleep(2)
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"python.*{os.path.basename(daemon_path)}"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print_ok("Bot esta rodando!")
        else:
            print_aviso("Bot pode nao estar rodando. Verifique os logs.")
    except Exception:
        pass

    print(f"""
{GREEN}{BOLD}  ╔══════════════════════════════════════════════════════╗
  ║         Tudo pronto! Mande uma mensagem no Telegram ║
  ╚══════════════════════════════════════════════════════╝{RESET}

  {BOLD}Arquivos criados em:{RESET} {project_dir}

  O bot ja esta rodando. Mande uma mensagem para testar!

  {BOLD}Comandos uteis no chat:{RESET}
    /status   - mostra o estado atual
    /nova     - comeca uma nova conversa
    /memory   - exibe a memoria do assistente
    /configurar - edita as configuracoes

  {BOLD}Ver logs:{RESET}
    {CYAN}tail -f logs/daemon.stderr.log{RESET}
""")


# ---------------------------------------------------------------------------
# Main (4 etapas)
# ---------------------------------------------------------------------------

def main() -> None:
    print_header()

    # Etapa 1
    print_step(1, 5, "Verificando sistema")
    check_system()

    # Etapa 2
    print_step(2, 5, "Seu perfil")
    profile = collect_profile()
    generate_profile_files(profile)

    # Etapa 3
    print_step(3, 5, "Configuracao do bot")
    collect_bot_config(profile)

    # Etapa 4
    print_step(4, 5, "Integracoes")
    run_mcp_setup()

    # Etapa 5
    print_step(5, 5, "Telegram")
    telegram = setup_telegram_flow()
    token = telegram["token"]
    chat_id = telegram.get("chat_id")
    generate_config(token, chat_id, profile)
    service_ok = install_service(str(BASE_DIR))

    print_success(service_installed=service_ok)


def collect_bot_config(profile: dict) -> None:
    """Coleta nome do bot e idioma do audio. Atualiza o dict in-place."""
    # Nome do bot
    print(f"  {BOLD}Qual vai ser o nome do seu assistente?{RESET}")
    print(f"  Exemplos: 'Meu Assistente', 'Jarvis', 'Friday'\n")
    bot_name = input("  Nome: ").strip()
    if not bot_name:
        bot_name = "Claude Assistant"
        print_aviso(f"Usando nome padrao: {bot_name}")
    else:
        print_ok(f"Nome do bot: {bot_name}")
    profile["bot_name"] = bot_name

    # Idioma do audio (whisper)
    print(f"\n  {BOLD}Em qual idioma voce vai mandar mensagens de voz?{RESET}\n")
    lang_idx = escolha([
        "Portugues",
        "Ingles",
        "Espanhol",
        "Outro idioma",
    ])
    lang_map = {0: "pt", 1: "en", 2: "es"}
    if lang_idx in lang_map:
        profile["language_code"] = lang_map[lang_idx]
    else:
        code = input(f"\n  Codigo ISO 639-1 do idioma (ex: fr, de, it): ").strip().lower()
        profile["language_code"] = code if code else "pt"
    print_ok(f"Idioma de audio: {profile['language_code']}")

    # Avisos proativos (heartbeat)
    print(f"\n  {BOLD}O bot pode verificar sua agenda e emails periodicamente{RESET}")
    print(f"  {BOLD}e te avisar se tiver algo importante. Como quer configurar?{RESET}\n")
    hb_idx = escolha([
        "Avisos nos horarios padrao (9h, 13h, 18h)",
        "Definir meus proprios horarios",
        "Desligar avisos proativos",
    ])
    if hb_idx == 0:
        profile["heartbeat_times"] = ["09:00", "13:00", "18:00"]
        profile["heartbeat_interval"] = 30
        print_ok("Avisos configurados: 9h, 13h, 18h + verificacao a cada 30 min")
    elif hb_idx == 1:
        print(f"\n  Digite os horarios separados por virgula (ex: 08:00, 12:00, 17:00)")
        raw = input("  Horarios: ").strip()
        times = [t.strip() for t in raw.split(",") if t.strip()]
        if not times:
            times = ["09:00", "13:00", "18:00"]
            print_aviso("Nenhum horario informado, usando padrao")
        profile["heartbeat_times"] = times
        print(f"\n  {BOLD}Com que frequencia verificar entre esses horarios?{RESET}\n")
        freq_idx = escolha([
            "A cada 30 minutos",
            "A cada 1 hora",
            "Apenas nos horarios definidos",
        ])
        profile["heartbeat_interval"] = [30, 60, 0][freq_idx]
        print_ok(f"Horarios: {', '.join(times)}")
    else:
        profile["heartbeat_times"] = []
        profile["heartbeat_interval"] = 0
        print_ok("Avisos proativos desligados")


def collect_profile() -> dict:
    """Pergunta ao usuario como quer fornecer o perfil e retorna o dict."""
    print(f"  Voce tem um documento com informacoes sobre voce?\n"
          f"  (pode ser um curriculo, bio, apresentacao profissional, qualquer coisa)\n")
    idx = escolha([
        "Sim, tenho um documento",
        "Nao, prefiro responder as perguntas agora",
    ])
    if idx == 0:
        return collect_from_document()
    return collect_from_questions()


if __name__ == "__main__":
    main()
