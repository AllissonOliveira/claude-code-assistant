"""Service installer for auto-starting the Claude Code Assistant daemon."""

import os
import subprocess
import sys

from .templates import LAUNCHAGENT_TEMPLATE, SYSTEMD_TEMPLATE

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _escolha_sim_nao(prompt: str) -> bool:
    """Pergunta sim/nao usando opcoes numeradas (padrao do wizard)."""
    print(f"\n{CYAN}  {prompt}{RESET}\n")
    print(f"  {BOLD}1{RESET} - Sim")
    print(f"  {BOLD}2{RESET} - Nao")
    while True:
        raw = input(f"\n  Escolha: ").strip()
        if raw == "1":
            return True
        if raw == "2":
            return False
        print(f"  {YELLOW}Por favor, digite 1 ou 2.{RESET}")


def _install_launchagent(project_dir: str, python_path: str) -> bool:
    """Install a macOS LaunchAgent plist."""
    plist_content = LAUNCHAGENT_TEMPLATE.substitute(
        python_path=python_path,
        project_dir=project_dir,
        home_dir=os.path.expanduser("~"),
    )

    # Ensure logs directory exists
    logs_dir = os.path.join(project_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(plist_dir, exist_ok=True)
    plist_path = os.path.join(plist_dir, "com.user.claude-assistant.plist")

    try:
        with open(plist_path, "w") as f:
            f.write(plist_content)
        print(f"{GREEN}  [OK] Plist salvo em {plist_path}{RESET}")
    except OSError as e:
        print(f"{RED}  [ERRO] Falha ao salvar plist: {e}{RESET}")
        return False

    # Load the agent
    try:
        subprocess.run(
            ["launchctl", "load", plist_path],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"{GREEN}  [OK] LaunchAgent carregado com sucesso!{RESET}")
        print(f"{GREEN}  O assistente vai iniciar automaticamente no login.{RESET}")
        print(f"\n  {BOLD}Comandos úteis:{RESET}")
        print(f"    Parar:   launchctl unload {plist_path}")
        print(f"    Iniciar: launchctl load {plist_path}")
        print(f"    Logs:    tail -f {logs_dir}/daemon.stderr.log")
        return True
    except subprocess.CalledProcessError as e:
        print(f"{RED}  [ERRO] Falha ao carregar LaunchAgent: {e.stderr}{RESET}")
        print(f"{YELLOW}  [!] Você pode carregar manualmente:{RESET}")
        print(f"    launchctl load {plist_path}")
        return False


def _install_systemd(project_dir: str, python_path: str) -> bool:
    """Generate and print a systemd user service file."""
    service_content = SYSTEMD_TEMPLATE.substitute(
        python_path=python_path,
        project_dir=project_dir,
        home_dir=os.path.expanduser("~"),
    )

    service_name = "claude-assistant.service"
    service_dir = os.path.expanduser("~/.config/systemd/user")
    service_path = os.path.join(service_dir, service_name)

    print(f"\n{BOLD}  Arquivo de serviço systemd gerado:{RESET}\n")
    for line in service_content.strip().split("\n"):
        print(f"    {line}")

    print(f"\n{BOLD}  Para instalar:{RESET}")
    print(f"    mkdir -p {service_dir}")
    print(f"    # Salve o conteúdo acima em: {service_path}")
    print(f"    systemctl --user daemon-reload")
    print(f"    systemctl --user enable {service_name}")
    print(f"    systemctl --user start {service_name}")
    print(f"    systemctl --user status {service_name}")

    # Try to write the file automatically
    if _escolha_sim_nao("Salvar o arquivo de serviço automaticamente?"):
        try:
            os.makedirs(service_dir, exist_ok=True)
            with open(service_path, "w") as f:
                f.write(service_content)
            print(f"{GREEN}  [OK] Arquivo de serviço salvo em {service_path}{RESET}")
            print(f"{YELLOW}  [!] Execute os comandos acima para ativar e iniciar o serviço.{RESET}")
            return True
        except OSError as e:
            print(f"{RED}  [ERRO] Falha ao salvar arquivo de serviço: {e}{RESET}")
            return False

    return True


def install_service(project_dir: str, python_path: str | None = None) -> bool:
    """Install the assistant as a system service.

    Args:
        project_dir: Absolute path to the project directory.
        python_path: Path to the Python interpreter. Defaults to sys.executable.

    Returns:
        True if installation succeeded or was skipped gracefully.
    """
    if python_path is None:
        python_path = sys.executable

    project_dir = os.path.abspath(project_dir)

    if sys.platform == "darwin":
        if not _escolha_sim_nao("Instalar como LaunchAgent do macOS (iniciar automaticamente no login)?"):
            print(f"{YELLOW}  [!] Ignorado. Você pode executar o assistente manualmente:{RESET}")
            print(f"    {python_path} {project_dir}/daemon.py")
            return True
        return _install_launchagent(project_dir, python_path)

    elif sys.platform == "linux":
        if not _escolha_sim_nao("Configurar serviço systemd de usuário?"):
            print(f"{YELLOW}  [!] Ignorado. Você pode executar o assistente manualmente:{RESET}")
            print(f"    {python_path} {project_dir}/daemon.py")
            return True
        return _install_systemd(project_dir, python_path)

    else:
        print(f"\n{YELLOW}  [!] Inicialização automática não suportada em {sys.platform}.{RESET}")
        print(f"  Execute o assistente manualmente:")
        print(f"    {python_path} {project_dir}/daemon.py")
        return True
