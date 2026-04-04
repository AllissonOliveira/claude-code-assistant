"""Entry point for the installed package — delegates to root daemon."""
import subprocess
import sys
from pathlib import Path


def main():
    daemon_path = Path(__file__).parent.parent / "daemon.py"
    if not daemon_path.exists():
        print("Erro: daemon.py não encontrado. Execute a partir do diretório do projeto.")
        sys.exit(1)
    sys.exit(subprocess.call([sys.executable, str(daemon_path)]))
