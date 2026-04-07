#!/bin/bash

# ============================================================================
# Claude Code Assistant — Instalador Completo
#
# Uso: ./install.sh
#
# Este script instala tudo do zero:
# 1. Dependencias (Python, Node, Go, uv, ffmpeg, git)
# 2. Claude Code CLI
# 3. Pacote do bot
# 4. Wizard de configuracao (perfil, Telegram, MCPs)
# ============================================================================

GREEN='\033[92m'
YELLOW='\033[93m'
CYAN='\033[96m'
RED='\033[91m'
BOLD='\033[1m'
RESET='\033[0m'

ok()    { echo -e "  ${GREEN}[OK]${RESET} $1"; }
aviso() { echo -e "  ${YELLOW}[!]${RESET} $1"; }
erro()  { echo -e "  ${RED}[X]${RESET} $1"; exit 1; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
IS_MAC=false
IS_LINUX=false
[[ "$(uname)" == "Darwin" ]] && IS_MAC=true
[[ "$(uname)" == "Linux" ]] && IS_LINUX=true

# Garante que ~/.local/bin esta no PATH (uv, pip scripts)
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

echo ""
echo -e "${CYAN}${BOLD}  ╔══════════════════════════════════════════════════════╗"
echo -e "  ║       Claude Code Assistant — Instalacao             ║"
echo -e "  ║       Vamos deixar tudo pronto para voce!            ║"
echo -e "  ╚══════════════════════════════════════════════════════╝${RESET}"
echo ""

# ============================================================================
# Fase 1: Dependencias do sistema
# ============================================================================

echo -e "${BOLD}  [1/4] Verificando dependencias do sistema${RESET}"
echo -e "${BOLD}  =================================================${RESET}"
echo ""

HAS_BREW=false
if command -v brew &>/dev/null; then HAS_BREW=true; fi

# --- Git ---
check_git() {
    if command -v git &>/dev/null; then
        ok "git encontrado"
        return 0
    fi
    aviso "git nao encontrado. Instalando..."
    if $IS_MAC && $HAS_BREW; then
        brew install git
    elif $IS_LINUX; then
        sudo apt-get update && sudo apt-get install -y git
    else
        erro "Instale git manualmente: https://git-scm.com"
    fi
    ok "git instalado"
}

# --- Python 3.12+ ---
check_python() {
    if command -v python3 &>/dev/null; then
        if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
            PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
            ok "Python $PY_VER"
            return 0
        fi
        aviso "Python encontrado, mas precisa 3.12+"
    fi

    aviso "Instalando Python..."
    if $IS_MAC && $HAS_BREW; then
        brew install python@3.12
    elif $IS_LINUX; then
        sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3-pip
    else
        erro "Instale Python 3.12+ manualmente: https://python.org/downloads"
    fi
    ok "Python instalado"
}

# --- Node.js ---
check_node() {
    if command -v node &>/dev/null; then
        NODE_VER=$(node --version 2>/dev/null || echo "?")
        ok "Node.js $NODE_VER"
        return 0
    fi

    aviso "Node.js nao encontrado. Instalando..."
    if $IS_MAC && $HAS_BREW; then
        brew install node
    elif $IS_LINUX; then
        sudo apt-get update && sudo apt-get install -y nodejs npm
    else
        erro "Instale Node.js: https://nodejs.org"
    fi
    ok "Node.js instalado"
}

# --- Go ---
check_go() {
    if command -v go &>/dev/null; then
        GO_VER=$(go version | grep -oE '[0-9]+\.[0-9]+' | head -1)
        ok "Go $GO_VER"
        return 0
    fi

    aviso "Go nao encontrado. Instalando..."
    if $IS_MAC && $HAS_BREW; then
        brew install go
    elif $IS_LINUX; then
        sudo apt-get update && sudo apt-get install -y golang
    else
        erro "Instale Go: https://go.dev/dl/"
    fi
    ok "Go instalado"
}

# --- uv ---
check_uv() {
    if command -v uv &>/dev/null; then
        ok "uv encontrado"
        return 0
    fi

    aviso "uv nao encontrado. Instalando..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if command -v uv &>/dev/null; then
        ok "uv instalado"
    else
        erro "Falha ao instalar uv. Instale manualmente: https://docs.astral.sh/uv/"
    fi
}

# --- ffmpeg ---
check_ffmpeg() {
    if command -v ffmpeg &>/dev/null; then
        ok "ffmpeg encontrado"
        return 0
    fi

    aviso "ffmpeg nao encontrado. Instalando..."
    if $IS_MAC && $HAS_BREW; then
        brew install ffmpeg
    elif $IS_LINUX; then
        sudo apt-get update && sudo apt-get install -y ffmpeg
    fi

    if command -v ffmpeg &>/dev/null; then
        ok "ffmpeg instalado"
    else
        aviso "ffmpeg nao instalado. Mensagens de voz nao vao funcionar."
    fi
}

# --- pip deps ---
check_pip_deps() {
    if python3 -m pip install --quiet requests "qrcode[pil]" 2>/dev/null; then
        ok "Bibliotecas Python (requests, qrcode)"
    elif pip3 install --quiet requests "qrcode[pil]" 2>/dev/null; then
        ok "Bibliotecas Python (requests, qrcode)"
    else
        aviso "Falha ao instalar bibliotecas Python. Tentando continuar..."
    fi
}

check_git
check_python
check_node
check_go
check_uv
check_ffmpeg
check_pip_deps

echo ""
ok "Todas as dependencias verificadas"

# ============================================================================
# Fase 2: Claude Code CLI
# ============================================================================

echo ""
echo -e "${BOLD}  [2/4] Claude Code CLI${RESET}"
echo -e "${BOLD}  =================================================${RESET}"
echo ""

if command -v claude &>/dev/null; then
    ok "Claude Code CLI encontrado"
else
    aviso "Claude Code CLI nao encontrado. Instalando..."
    if ! command -v npm &>/dev/null; then
        erro "npm nao encontrado. Instale Node.js primeiro: https://nodejs.org"
    fi
    npm install -g @anthropic-ai/claude-code 2>/dev/null
    if command -v claude &>/dev/null; then
        ok "Claude Code CLI instalado"
    else
        erro "Falha ao instalar Claude Code CLI. Instale manualmente: npm install -g @anthropic-ai/claude-code"
    fi
fi

# Verifica se o Claude Code ja foi usado (credenciais ficam no keychain do SO)
# Nao roda claude -p pra evitar travar ou abrir interativo
if [ -d "$HOME/.claude" ] && [ -f "$HOME/.claude/settings.json" ]; then
    ok "Claude Code configurado"
else
    aviso "Parece que o Claude Code nunca foi executado nesta maquina."
    echo -e "  Rode ${CYAN}${BOLD}claude${RESET} no terminal para autenticar antes de usar o bot."
    echo -e "  A instalacao vai continuar normalmente."
fi

# ============================================================================
# Fase 3: Instalar pacote do bot
# ============================================================================

echo ""
echo -e "${BOLD}  [3/4] Instalando pacote do bot${RESET}"
echo -e "${BOLD}  =================================================${RESET}"
echo ""

cd "$PROJECT_DIR"

if python3 -m pip install -e . --quiet 2>/dev/null; then
    ok "Pacote claude-code-assistant instalado"
elif pip3 install -e . --quiet 2>/dev/null; then
    ok "Pacote claude-code-assistant instalado"
else
    erro "Falha ao instalar pacote. Verifique sua instalacao do Python."
fi

# Verifica que o entry point existe
if ! command -v claude-assistant-setup &>/dev/null; then
    # Tenta com o path do Python
    SETUP_CMD="$(python3 -m site --user-base 2>/dev/null)/bin/claude-assistant-setup"
    if [ -x "$SETUP_CMD" ]; then
        export PATH="$(python3 -m site --user-base 2>/dev/null)/bin:$PATH"
    else
        aviso "claude-assistant-setup nao encontrado no PATH. Usando python -m diretamente."
    fi
fi

# Cria diretorios necessarios
for dir in logs sessions memory audio; do
    mkdir -p "$PROJECT_DIR/$dir"
done
ok "Diretorios criados"

# ============================================================================
# Fase 4: Wizard de configuracao
# ============================================================================

echo ""
echo -e "${BOLD}  [4/4] Configuracao do bot${RESET}"
echo -e "${BOLD}  =================================================${RESET}"
echo ""
echo -e "  O wizard vai te guiar pela configuracao completa."
echo -e "  Voce so vai precisar responder algumas perguntas."
echo ""

# Roda o wizard interativo
if command -v claude-assistant-setup &>/dev/null; then
    claude-assistant-setup
else
    python3 -m setup_wizard.wizard
fi

echo ""
echo -e "${GREEN}${BOLD}  ╔══════════════════════════════════════════════════════╗"
echo -e "  ║         Instalacao concluida com sucesso!            ║"
echo -e "  ╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  Para iniciar o bot: ${CYAN}python daemon.py${RESET}"
echo -e "  Ou ele ja esta rodando como servico automatico."
echo ""
