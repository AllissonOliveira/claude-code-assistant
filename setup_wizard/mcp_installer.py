"""Instalador de MCPs para o Claude Code Assistant."""

import base64
import json
import os
import re
import subprocess
from pathlib import Path

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

MCPS_DIR = Path(__file__).parent.parent / "mcps"
CLAUDE_JSON = Path.home() / ".claude.json"


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def load_available_mcps() -> list[dict]:
    """Le todos os JSONs de mcps/ e retorna lista ordenada."""
    mcps = []
    if not MCPS_DIR.exists():
        return mcps
    for f in sorted(MCPS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            mcps.append(data)
        except Exception:
            pass
    return sorted(mcps, key=lambda m: (m.get("priority", 99), m.get("name", "")))


def load_claude_json() -> dict:
    if CLAUDE_JSON.exists():
        try:
            return json.loads(CLAUDE_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_claude_json(data: dict) -> None:
    tmp = CLAUDE_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.chmod(0o600)
    tmp.replace(CLAUDE_JSON)


def is_mcp_installed(mcp: dict) -> bool:
    claude = load_claude_json()
    return mcp.get("id", "") in claude.get("mcpServers", {})


def find_existing_mcp(mcp: dict) -> str | None:
    """Verifica se o usuario ja tem um MCP equivalente instalado.

    Checa tanto o proprio ID do MCP quanto os IDs alternativos listados
    em 'existing_ids'. Retorna o ID do MCP existente ou None.
    """
    claude = load_claude_json()
    servers = claude.get("mcpServers", {})
    mcp_id = mcp.get("id", "")

    # Checa o proprio ID
    if mcp_id in servers:
        return mcp_id

    # Checa IDs alternativos
    for alt_id in mcp.get("existing_ids", []):
        if alt_id in servers:
            return alt_id

    return None


# ---------------------------------------------------------------------------
# Exibicao do menu
# ---------------------------------------------------------------------------

def display_mcp_menu(mcps: list[dict]) -> None:
    """Mostra menu numerado agrupado por categoria."""
    categories = {
        "essential": "Essenciais",
        "recommended": "Recomendados",
        "optional": "Opcionais",
    }
    current_cat = None
    for i, mcp in enumerate(mcps, 1):
        cat = mcp.get("category", "optional")
        if cat != current_cat:
            current_cat = cat
            label = categories.get(cat, cat)
            print(f"\n  {BOLD}-- {label} --{RESET}")

        difficulty = mcp.get("auth_difficulty", "easy")
        diff_label = {
            "easy": f"{GREEN}facil{RESET}",
            "medium": f"{YELLOW}medio{RESET}",
            "hard": f"{RED}dificil{RESET}",
        }.get(difficulty, difficulty)

        installed = is_mcp_installed(mcp)
        status = f" {GREEN}(ja instalado){RESET}" if installed else ""

        print(
            f"  {BOLD}{i:2d}.{RESET} {mcp['name']:<22s}"
            f" {mcp['description'][:50]:<52s} [{diff_label}]{status}"
        )
    print()


# ---------------------------------------------------------------------------
# Selecao
# ---------------------------------------------------------------------------

def select_mcps(mcps: list[dict]) -> list[dict]:
    """Usuario escolhe por numero. Retorna selecionados."""
    print(
        f"  Quais voce quer instalar?\n"
        f"  Digite os numeros separados por virgula (ex: 1, 3, 4)\n"
        f"  Ou pressione Enter para pular."
    )
    choice = input(f"\n  > ").strip()

    if not choice or choice.lower() in ("nenhum", "nenhuma", "0"):
        return []

    selected = []
    for part in choice.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(mcps):
                selected.append(mcps[idx])
        except ValueError:
            pass

    return selected


# ---------------------------------------------------------------------------
# Instalacao individual
# ---------------------------------------------------------------------------

def _escolha_local(opcoes: list[str], prompt: str = "Escolha") -> int:
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


def _install_whatsapp_mcp() -> bool:
    """Instalacao automatica do WhatsApp MCP: clona, compila, registra e conecta."""
    WA_DIR = Path.home() / ".claude" / "whatsapp-mcp-plus"

    # Clona se nao existe ou esta corrompido
    if WA_DIR.exists() and not (WA_DIR / ".git").exists():
        print(f"  {YELLOW}Diretorio existente mas corrompido. Removendo...{RESET}")
        import shutil
        shutil.rmtree(str(WA_DIR), ignore_errors=True)

    if not WA_DIR.exists():
        print(f"  {YELLOW}Clonando whatsapp-mcp-plus...{RESET}")
        result = subprocess.run(
            ["git", "clone", "https://github.com/AllissonOliveira/whatsapp-mcp-plus.git", str(WA_DIR)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  {RED}Erro ao clonar repositorio: {result.stderr}{RESET}")
            return False
        print(f"  {GREEN}Repositorio clonado.{RESET}")
    else:
        print(f"  {GREEN}Repositorio ja existe. Atualizando...{RESET}")
        subprocess.run(["git", "pull"], cwd=str(WA_DIR), capture_output=True)

    # Roda o install.sh do whatsapp-mcp-plus
    install_script = WA_DIR / "install.sh"
    if install_script.exists():
        print(f"  {YELLOW}Executando instalador do WhatsApp MCP...{RESET}")
        result = subprocess.run(
            ["bash", str(install_script)],
            cwd=str(WA_DIR),
        )
        return result.returncode == 0

    # Fallback: instalacao manual se install.sh nao existir
    print(f"  {YELLOW}install.sh nao encontrado, instalando manualmente...{RESET}")

    # Compila bridge
    bridge_dir = WA_DIR / "whatsapp-bridge"
    if bridge_dir.exists():
        print(f"  {YELLOW}Compilando bridge Go...{RESET}")
        result = subprocess.run(
            ["go", "build", "-o", "whatsapp-bridge", "main.go"],
            cwd=str(bridge_dir), capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  {RED}Erro ao compilar bridge: {result.stderr}{RESET}")
            return False

    # Registra no claude.json
    mcp_server_dir = str(WA_DIR / "whatsapp-mcp-server")
    claude = load_claude_json()
    claude.setdefault("mcpServers", {})["whatsapp"] = {
        "command": "uv",
        "args": ["--directory", mcp_server_dir, "run", "main.py"],
    }
    save_claude_json(claude)

    print(f"  {GREEN}[OK] WhatsApp MCP instalado!{RESET}")
    return True


def install_mcp(mcp: dict, shared_creds: dict) -> bool:
    """Instala um MCP: executa pre_install, coleta credenciais, salva no claude.json."""
    name = mcp["name"]
    mcp_id = mcp["id"]
    description = mcp.get("description", "")

    print(f"\n  {BOLD}{CYAN}{name}{RESET} - {description}")

    # Verifica se ja existe um MCP equivalente instalado
    existing = find_existing_mcp(mcp)
    if existing:
        print(f"  {GREEN}Voce ja tem '{existing}' instalado para essa funcao.{RESET}")
        idx = _escolha_local([
            "Usar o que ja tem (pular)",
            "Instalar a versao do bot",
        ])
        if idx == 0:
            return True  # Conta como sucesso, ja tem

    else:
        # Pergunta se quer instalar
        idx = _escolha_local([
            "Instalar",
            "Pular",
        ])
        if idx == 1:
            return False  # Pulou limpo, sem efeito colateral

    # WhatsApp tem instalacao especial
    if mcp_id == "whatsapp":
        return _install_whatsapp_mcp()

    if is_mcp_installed(mcp) and not existing:
        print(f"  {GREEN}Esta integracao ja esta instalada.{RESET}")
        print(f"\n  O que voce quer fazer?\n")
        idx = _escolha_local(["Manter como esta e pular", "Reconfigurar do zero"])
        if idx == 0:
            return True

    # Pre-install (sem shell=True por seguranca)
    pre = mcp.get("pre_install")
    if pre and isinstance(pre, str) and pre.strip().startswith(("pip", "apt", "brew", "curl")):
        # Rejeitar comandos com operadores shell perigosos
        if any(op in pre for op in ("&&", "||", ";", "|", ">", "<", "`", "$(")):
            print(f"  {YELLOW}Comando de pre-install contem operadores nao permitidos.{RESET}")
            print(f"  Execute manualmente: {pre}")
        else:
            print(f"  {YELLOW}Instalando dependencias automaticamente...{RESET}")
            result = subprocess.run(pre.split(), capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  {YELLOW}Aviso na instalacao de dependencias (pode ser ignorado).{RESET}")
            else:
                print(f"  {GREEN}Dependencias instaladas.{RESET}")
    elif pre:
        # Instrucoes manuais
        print(f"\n  {BOLD}Esta integracao precisa de alguns passos manuais:{RESET}\n")
        for linha in str(pre).split("\n"):
            if linha.strip():
                print(f"  {linha}")
        print(f"\n  {YELLOW}Siga os passos acima e depois volte aqui.{RESET}")
        input(f"\n  Pressione Enter quando terminar... ")

    # Coleta credenciais
    env_values = {}
    shared_key = mcp.get("shared_credentials")

    for key, info in mcp.get("env", {}).items():
        if shared_key and key in shared_creds:
            print(f"  {key}: usando credencial ja informada {GREEN}(compartilhada){RESET}")
            env_values[key] = shared_creds[key]
            continue

        print(f"\n  {CYAN}Preciso de uma informacao:{RESET}")
        print(f"  {BOLD}{info['description']}{RESET}")

        if info.get("instructions"):
            print(f"\n  {YELLOW}Como obter:{RESET}")
            for linha in info["instructions"].split("\n"):
                if linha.strip():
                    print(f"  {linha}")

        print()
        value = input(f"  Cole aqui o valor de {key}: ").strip()
        if not value and info.get("required", True):
            print(f"  {YELLOW}Sem essa informacao nao e possivel configurar {name}. Pulando.{RESET}")
            return False

        env_values[key] = value
        if shared_key:
            shared_creds[key] = value

    # Monta config
    server_config: dict = {
        "command": mcp["command"],
        "args": mcp["args"],
    }
    if env_values:
        server_config["env"] = env_values

    claude = load_claude_json()
    claude.setdefault("mcpServers", {})[mcp_id] = server_config
    save_claude_json(claude)

    # Post-install
    post = mcp.get("post_install")
    if post:
        print(f"\n  {BOLD}Proximos passos para ativar {name}:{RESET}\n")
        for linha in str(post).split("\n"):
            if linha.strip():
                print(f"  {linha}")

    print(f"\n  {GREEN}[OK] {name} configurado!{RESET}")
    return True


def install_selected_mcps(selected: list[dict]) -> list[dict]:
    """Instala todos os selecionados. Retorna os que deram certo."""
    installed = []
    shared_creds: dict = {}
    for mcp in selected:
        if install_mcp(mcp, shared_creds):
            installed.append(mcp)
    return installed


# ---------------------------------------------------------------------------
# MCP customizado via GitHub
# ---------------------------------------------------------------------------

def extract_repo_from_url(url: str) -> str | None:
    """Extrai 'owner/repo' de um URL do GitHub."""
    url = url.strip().rstrip("/")
    # Aceita: https://github.com/owner/repo, github.com/owner/repo, owner/repo
    patterns = [
        r"github\.com/([^/]+/[^/]+)",
        r"^([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)$",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def fetch_repo_info(repo: str) -> dict | None:
    """Busca README do repo via GitHub API e tenta extrair info de instalacao."""
    try:
        result = subprocess.run(
            [
                "curl", "-s", "-H", "Accept: application/vnd.github+json",
                f"https://api.github.com/repos/{repo}/readme",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        if "content" not in data:
            return None

        readme = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None

    # Tenta descobrir o comando de instalacao
    command = "npx"
    args: list[str] = []

    npx_match = re.search(r"npx\s+(-y\s+)?(@?[\w/@-]+)", readme)
    pip_match = re.search(r"pip install\s+([\w/-]+)", readme)
    uvx_match = re.search(r"uvx\s+([\w/@-]+)", readme)

    if npx_match:
        command = "npx"
        flag = npx_match.group(1) or ""
        pkg = npx_match.group(2)
        args = (["-y"] if flag.strip() == "-y" else []) + [pkg]
    elif uvx_match:
        command = "uvx"
        args = [uvx_match.group(1)]
    elif pip_match:
        command = sys.executable if False else "python3"
        args = ["-m", pip_match.group(1)]

    # Tenta descobrir env vars (padrao: UPPER_CASE_WITH_UNDERSCORES)
    env_vars = []
    seen: set = set()
    for m in re.finditer(r"\b([A-Z][A-Z0-9_]{3,})\b", readme):
        var = m.group(1)
        # Filtra falsos positivos comuns
        if var in ("README", "API", "URL", "HTTP", "JSON", "CLI", "SDK", "MCP", "ID"):
            continue
        if "KEY" in var or "TOKEN" in var or "SECRET" in var or "ID" in var or "URL" in var:
            if var not in seen:
                seen.add(var)
                env_vars.append(var)

    # Nome e descricao do repo
    name = repo.split("/")[-1]
    description = ""
    desc_match = re.search(r"^#\s+(.+)", readme, re.MULTILINE)
    if desc_match:
        name = desc_match.group(1).strip()

    # Primeiras linhas como descricao
    lines = [l.strip() for l in readme.split("\n") if l.strip() and not l.startswith("#")]
    if lines:
        description = lines[0][:120]

    return {
        "command": command,
        "args": args,
        "env_vars": env_vars[:5],  # limite razoavel
        "name": name,
        "description": description,
    }


def add_custom_mcp() -> dict | None:
    """Permite adicionar MCP por link do GitHub."""
    import sys as _sys  # noqa: F401 (usado acima indiretamente)

    print(f"\n  Cole o link do repositorio no GitHub do MCP:")
    print(f"  {YELLOW}Exemplo: https://github.com/autor/nome-do-mcp{RESET}\n")
    url = input("  > ").strip()

    if not url:
        return None

    repo = extract_repo_from_url(url)
    if not repo:
        print(f"  {RED}Link invalido. Use o formato: https://github.com/autor/nome-do-mcp{RESET}")
        return None

    print(f"\n  {YELLOW}Buscando informacoes do repositorio...{RESET}")
    info = fetch_repo_info(repo)

    if info:
        command = info["command"]
        args = info["args"]
        print(f"  {GREEN}Repositorio encontrado: {info['name']}{RESET}")
        if info.get("description"):
            print(f"  {info['description']}")
    else:
        print(f"  {YELLOW}Nao consegui ler o repositorio automaticamente.{RESET}")
        print(f"\n  Qual e o comando para instalar? (ex: npx -y @autor/pacote)\n")
        cmd_input = input("  > ").strip()
        if not cmd_input:
            print(f"  {RED}Sem comando, nao e possivel instalar.{RESET}")
            return None
        parts = cmd_input.split()
        command = parts[0]
        args = parts[1:]

    # Nome amigavel
    default_name = repo.split("/")[-1]
    print(f"\n  Que nome voce quer dar a essa integracao?")
    print(f"  {YELLOW}(pressione Enter para usar '{default_name}'){RESET}\n")
    name = input("  > ").strip() or default_name
    mcp_id = name.lower().replace(" ", "-").replace("_", "-")

    # Credenciais
    env_values = {}
    if info and info.get("env_vars"):
        print(f"\n  {YELLOW}Essa integracao pode precisar de algumas configuracoes:{RESET}")
        for var in info["env_vars"]:
            print(f"\n  {CYAN}Informe o valor de: {var}{RESET}")
            value = input(f"  {var}: ").strip()
            if value:
                env_values[var] = value

    # Salva no claude.json
    server_config: dict = {"command": command, "args": args}
    if env_values:
        server_config["env"] = env_values

    claude = load_claude_json()
    claude.setdefault("mcpServers", {})[mcp_id] = server_config
    save_claude_json(claude)

    print(f"\n  {GREEN}[OK] {name} instalado!{RESET}")
    return {"id": mcp_id, "name": name, "description": "MCP customizado"}


# ---------------------------------------------------------------------------
# Geracao do TOOLS.md
# ---------------------------------------------------------------------------

def generate_tools_md(installed: list[dict], output_path: Path) -> None:
    lines = ["# TOOLS.md\n", "Ferramentas disponiveis via MCP:\n"]
    for mcp in installed:
        lines.append(f"- {mcp['name']}: {mcp['description']}")
    lines.append("\nCada ferramenta e acessada automaticamente pelo Claude Code CLI.")
    lines.append("Voce nao precisa chamar nenhum comando especial para usa-las.")
    lines.append(
        "Quando voce pedir algo que envolva uma dessas ferramentas, "
        "o Claude usa automaticamente."
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")
