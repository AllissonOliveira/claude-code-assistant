#!/bin/bash
set -e

# ============================================================================
# Claude Code Assistant — Instalador Completo
#
# Uso: ./install.sh
#
# Este script instala tudo do zero:
# 1. Dependencias (Python, Node, Go, uv, ffmpeg)
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
erro()  { echo -e "  ${RED}[X]${RESET} $1"; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
IS_MAC=false
IS_LINUX=false
[[ "$(uname)" == "Darwin" ]] && IS_MAC=true
[[ "$(uname)" == "Linux" ]] && IS_LINUX=true

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

# --- Python 3.12+ ---
check_python() {
    if command -v python3 &>/dev/null; then
        PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 12 ]; then
            ok "Python $PY_VER"
            return 0
        fi
        aviso "Python $PY_VER encontrado, mas precisa 3.12+"
    fi

    aviso "Instalando Python..."
    if $IS_MAC && $HAS_BREW; then
        brew install python@3.12
    elif $IS_LINUX; then
        sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3-pip
    else
        erro "Instale Python 3.12+ manualmente: https://python.org/downloads"
        return 1
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
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        erro "Instale Node.js: https://nodejs.org"
        return 1
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
        return 1
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
    export PATH="$HOME/.local/bin:$PATH"
    ok "uv instalado"
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

# --- requests + qrcode ---
check_pip_deps() {
    python3 -m pip install --quiet requests "qrcode[pil]" 2>/dev/null || \
    pip3 install --quiet requests "qrcode[pil]" 2>/dev/null || true
    ok "Bibliotecas Python (requests, qrcode)"
}

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
    npm install -g @anthropic-ai/claude-code 2>/dev/null
    if command -v claude &>/dev/null; then
        ok "Claude Code CLI instalado"
    else
        erro "Falha ao instalar Claude Code CLI."
        echo -e "  Instale manualmente: ${CYAN}npm install -g @anthropic-ai/claude-code${RESET}"
        echo -e "  Depois execute este script novamente."
        exit 1
    fi
fi

# Verifica se esta autenticado
if ! claude --version &>/dev/null 2>&1; then
    echo ""
    aviso "O Claude Code precisa ser configurado antes de continuar."
    echo ""
    echo -e "  Execute o comando abaixo no terminal e siga as instrucoes:"
    echo ""
    echo -e "    ${CYAN}${BOLD}claude${RESET}"
    echo ""
    echo -e "  Depois de autenticar, execute este script novamente:"
    echo ""
    echo -e "    ${CYAN}${BOLD}./install.sh${RESET}"
    echo ""
    exit 0
fi

ok "Claude Code autenticado"

# ============================================================================
# Fase 3: Instalar pacote do bot
# ============================================================================

echo ""
echo -e "${BOLD}  [3/4] Instalando pacote do bot${RESET}"
echo -e "${BOLD}  =================================================${RESET}"
echo ""

cd "$PROJECT_DIR"
pip install -e . --quiet 2>/dev/null || pip3 install -e . --quiet 2>/dev/null
ok "Pacote claude-code-assistant instalado"

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
claude-assistant-setup

echo ""
echo -e "${GREEN}${BOLD}  ╔══════════════════════════════════════════════════════╗"
echo -e "  ║         Instalacao concluida com sucesso!            ║"
echo -e "  ╚══════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  Para iniciar o bot: ${CYAN}python daemon.py${RESET}"
echo -e "  Ou ele ja esta rodando como servico automatico."
echo ""
