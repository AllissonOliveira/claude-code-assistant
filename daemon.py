#!/usr/bin/env python3
"""
Claude Terminal via Telegram
Monitora mensagens no bot do Telegram e processa via Claude Code CLI.
"""

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Caminhos base
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"
SESSIONS_DIR = BASE_DIR / "sessions"
AUDIO_TEMP_DIR = BASE_DIR / "audio" / "temp"
LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "daemon.log"
MEMORY_DIR = BASE_DIR / "memory"
MEMORY_FILE = BASE_DIR / "MEMORY.md"
FILES_TEMP_DIR = BASE_DIR / "files" / "temp"
REMINDERS_FILE = BASE_DIR / "reminders.json"
BOOTSTRAP_FILE = BASE_DIR / "BOOTSTRAP.md"
BOOTSTRAP_TEMPLATE = BASE_DIR / "setup_wizard" / "templates" / "BOOTSTRAP.md"
HEARTBEAT_FILE = BASE_DIR / "HEARTBEAT.md"

# ---------------------------------------------------------------------------
# Timezone helper
# ---------------------------------------------------------------------------
_UTC_MINUS_3 = timezone(timedelta(hours=-3))


def _get_local_tz(cfg: dict | None = None) -> timezone | ZoneInfo:
    """Retorna o timezone configurado.

    Lê cfg['timezone'] (ex: 'America/Sao_Paulo'). Se ausente ou inválido,
    usa UTC-3 como fallback.
    """
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            return _UTC_MINUS_3
    tz_name = cfg.get("timezone", "America/Sao_Paulo")
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return _UTC_MINUS_3


# ---------------------------------------------------------------------------
# Log local de conversa — fonte primária para salvamento de memória
# ---------------------------------------------------------------------------
# Cada turno (user + bot) é escrito em disco imediatamente.
# Isso garante que a memória pode ser salva mesmo que a sessão Claude expire.

def _conv_log_path(date: datetime | None = None) -> Path:
    """Retorna caminho do log de conversa do dia."""
    d = date or datetime.now()
    return MEMORY_DIR / f"conv-{d.strftime('%Y-%m-%d')}.md"


def _append_conv_log(user_text: str, bot_response: str) -> None:
    """Registra um turno de conversa no log local (thread-safe, melhor esforço)."""
    try:
        MEMORY_DIR.mkdir(exist_ok=True)
        now = datetime.now()
        entry = (
            f"\n[{now.strftime('%H:%M')}] USER: {user_text[:500]}\n"
            f"[{now.strftime('%H:%M')}] BOT: {bot_response[:1000]}\n"
        )
        with open(_conv_log_path(now), "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass  # Log não pode quebrar o fluxo principal


def _read_conv_logs(days: int = 2) -> str:
    """Lê os logs de conversa dos últimos N dias para uso no salvamento de memória."""
    parts = []
    now = datetime.now()
    for delta in range(days):
        dt = now - timedelta(days=delta)
        path = _conv_log_path(dt)
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"=== {dt.strftime('%Y-%m-%d')} ===\n{content}")
    return "\n\n".join(parts) if parts else ""

_state_lock = threading.Lock()
_checkpoint_lock = threading.Lock()
_background_tasks: list[threading.Thread] = []


# ---------------------------------------------------------------------------
# Config e estado
# ---------------------------------------------------------------------------
_config_cache: dict | None = None
_config_mtime: float = 0.0


def load_config() -> dict:
    global _config_cache, _config_mtime
    try:
        mtime = CONFIG_FILE.stat().st_mtime
        if _config_cache is not None and mtime == _config_mtime:
            return _config_cache
        with open(CONFIG_FILE) as f:
            _config_cache = json.load(f)
        _config_mtime = mtime
        return _config_cache
    except (FileNotFoundError, json.JSONDecodeError):
        if _config_cache is not None:
            return _config_cache
        raise


def validate_config(cfg: dict) -> None:
    required = ["telegram_token", "project_dir", "claude_model"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise SystemExit(f"[CONFIG] Campos obrigatórios ausentes: {missing}")
    if not Path(cfg["project_dir"]).exists():
        raise SystemExit(f"[CONFIG] project_dir não existe: {cfg['project_dir']}")
    if cfg.get("whisper_bin") and not Path(cfg["whisper_bin"]).exists():
        log(f"[AVISO] whisper_bin não encontrado: {cfg['whisper_bin']}")


def load_state() -> dict:
    with _state_lock:
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            log("[AVISO] state.json corrompido ou ausente — reiniciando estado")
            default = {
                "active": True,
                "last_update_id": None,
                "session_id": None,
                "session_started_at": None,
                "last_activity_at": None,
                "last_heartbeat_notification": "",
            }
            _save_state_locked(default)
            return default


def _save_state_locked(state: dict) -> None:
    """Escrita atômica: grava em temp e faz rename para evitar corrupção."""
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(STATE_FILE)


def save_state(state: dict) -> None:
    with _state_lock:
        _save_state_locked(state)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _get_logger() -> logging.Logger:
    logger = logging.getLogger("claude_terminal")
    if not logger.handlers:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        _get_logger().info(line)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Formatação de texto para Telegram (texto plano)
# ---------------------------------------------------------------------------
def strip_markdown(text: str) -> str:
    """Remove formatação markdown para envio como texto plano.

    O Telegram sem parse_mode exibe asteriscos como texto literal, então
    removemos toda formatação e entregamos texto limpo.
    """
    # Blocos de código primeiro: ```lang\n...\n``` → conteúdo
    text = re.sub(r'```[^\n]*\n(.*?)```', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'```(.*?)```', r'\1', text, flags=re.DOTALL)
    # Código inline: `código` → código
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Negrito+itálico combinado: ***texto*** → texto
    text = re.sub(r'\*{3}(.+?)\*{3}', r'\1', text, flags=re.DOTALL)
    # Negrito: **texto** → texto
    text = re.sub(r'\*{2}(.+?)\*{2}', r'\1', text, flags=re.DOTALL)
    # Itálico: *texto* → texto
    text = re.sub(r'\*(.+?)\*', r'\1', text, flags=re.DOTALL)
    # Itálico com underline: __texto__ → texto, _texto_ → texto
    text = re.sub(r'__(.+?)__', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text, flags=re.DOTALL)
    # Strikethrough: ~~texto~~ → texto
    text = re.sub(r'~~(.+?)~~', r'\1', text, flags=re.DOTALL)
    # Headers markdown: ## Título → Título
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Links: [texto](url) → texto
    text = re.sub(r'\[(.+?)\]\([^\)]+\)', r'\1', text)
    # Separadores: --- ou === → (remove)
    text = re.sub(r'^[-=]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Asteriscos soltos que sobraram (cleanup final)
    text = re.sub(r'(?<!\w)\*+(?!\w)', '', text)
    return text.strip()


def strip_thinking(text: str) -> str:
    """Remove blocos de raciocinio interno e extrai apenas o conteudo final."""
    cleaned = re.sub(r'<think[^>]*>.*?</think>', '', text, flags=re.DOTALL)
    final_match = re.search(r'<final[^>]*>(.*?)</final>', cleaned, flags=re.DOTALL)
    if final_match:
        return final_match.group(1).strip()
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------
_session = requests.Session()


def tg_request(token: str, method: str, payload: dict = None, retries: int = 3, timeout: int = 10) -> dict | None:
    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(retries):
        try:
            resp = _session.post(url, json=payload or {}, timeout=timeout)
            return resp.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                log(f"[ERRO] Telegram API {method} falhou após {retries} tentativas: {e}")
    return None


def send_typing(chat_id: int, token: str, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        tg_request(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
        stop_event.wait(4)


def send_telegram(chat_id: int, text: str, token: str, retries: int = 3) -> bool:
    text = strip_markdown(text)
    # Nunca envia tokens internos pro usuário
    stripped = text.strip()
    if stripped in ("HEARTBEAT_OK", "MEMORY_OK", "MEMORY_SAVED"):
        return True
    parts = [text[i:i + 4096] for i in range(0, len(text), 4096)]
    all_ok = True
    for part in parts:
        for attempt in range(retries):
            r = tg_request(token, "sendMessage", {"chat_id": chat_id, "text": part})
            if r and r.get("ok"):
                break
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        else:
            log(f"[ERRO] Falha ao enviar parte da mensagem após {retries} tentativas")
            all_ok = False
    return all_ok


def get_updates(token: str, offset: int | None) -> list[dict]:
    params = {"timeout": 20, "limit": 10}
    if offset is not None:
        params["offset"] = offset
    result = tg_request(token, "getUpdates", params, timeout=25)
    if result and result.get("ok"):
        return result.get("result", [])
    return []


def download_telegram_file(token: str, file_id: str, dest: Path) -> str | None:
    result = tg_request(token, "getFile", {"file_id": file_id})
    if not (result and result.get("ok")):
        log(f"[ERRO] getFile falhou: {result}")
        return None
    file_path = result["result"].get("file_path")
    if not file_path:
        return None

    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    ext = Path(file_path).suffix or ".ogg"
    out = dest / f"audio_{int(time.time())}{ext}"
    try:
        r = _session.get(url, timeout=30)
        r.raise_for_status()
        out.write_bytes(r.content)
        log(f"[ÁUDIO] Baixado: {out.name} ({len(r.content)} bytes)")
        return str(out)
    except Exception as e:
        log(f"[ERRO] Download do arquivo Telegram: {e}")
        return None


# ---------------------------------------------------------------------------
# Transcrição de áudio
# ---------------------------------------------------------------------------
def _convert_to_wav(audio_path: str) -> tuple[str, bool]:
    """Converte áudio para WAV 16kHz mono via ffmpeg (formato ideal para Whisper).

    Retorna (caminho_wav, criou_novo_arquivo). Se já for WAV, retorna o mesmo
    caminho com False. Se ffmpeg falhar, retorna o original para tentar assim mesmo.
    """
    path = Path(audio_path)
    if path.suffix.lower() == ".wav":
        return audio_path, False

    wav_path = path.with_suffix(".wav")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ar", "16000", "-ac", "1",
             "-sample_fmt", "s16", str(wav_path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and wav_path.exists():
            log(f"[ÁUDIO] Convertido {path.suffix} → WAV ({wav_path.stat().st_size} bytes)")
            return str(wav_path), True
        log(f"[AVISO] ffmpeg conversão falhou (código {result.returncode}): {result.stderr[:200]}")
    except FileNotFoundError:
        log("[AVISO] ffmpeg não encontrado — tentando Whisper com áudio original")
    except subprocess.TimeoutExpired:
        log("[AVISO] ffmpeg timeout na conversão")
    except Exception as e:
        log(f"[AVISO] Conversão ffmpeg: {e}")

    return audio_path, False  # fallback: tenta com o original


_faster_whisper_model = None
_faster_whisper_model_name: str | None = None


def transcribe_audio(audio_path: str, cfg: dict) -> str | None:
    """Transcreve áudio usando faster-whisper (5-10x mais rápido que o Whisper original).

    Mantém o modelo carregado em memória entre chamadas para evitar reload.
    Fallback automático para o whisper CLI se faster-whisper falhar.
    """
    global _faster_whisper_model, _faster_whisper_model_name

    model_name = cfg.get("whisper_model", "medium")

    # Converte para WAV antes de passar ao Whisper (Telegram envia .ogg/Opus)
    wav_path, converted = _convert_to_wav(audio_path)

    try:
        try:
            from faster_whisper import WhisperModel

            # Carrega o modelo só uma vez, reutiliza nas próximas chamadas
            if _faster_whisper_model is None or _faster_whisper_model_name != model_name:
                log(f"[ÁUDIO] Carregando faster-whisper ({model_name})...")
                _faster_whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
                _faster_whisper_model_name = model_name
                log(f"[ÁUDIO] faster-whisper ({model_name}) pronto")

            segments, info = _faster_whisper_model.transcribe(
                wav_path, language=cfg.get("whisper_language", "pt"), beam_size=5
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            log(f"[ÁUDIO] faster-whisper — idioma detectado: {info.language} ({info.language_probability:.0%})")

            if not text:
                log("[AVISO] faster-whisper: transcrição vazia (áudio silencioso?)")
                return None
            return text

        except ImportError:
            log("[AVISO] faster-whisper não disponível — usando whisper CLI")

        # Fallback: whisper CLI original
        whisper_bin = cfg.get("whisper_bin", "whisper")
        out_dir = str(AUDIO_TEMP_DIR)
        cmd = [whisper_bin, wav_path,
               "--model", model_name,
               "--language", cfg.get("whisper_language", "pt"),
               "--output_format", "txt",
               "--output_dir", out_dir]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=None)

        if result.returncode != 0:
            log(f"[ERRO] Whisper CLI falhou (código {result.returncode}): {result.stderr[:300]}")
            return None

        txt_file = AUDIO_TEMP_DIR / f"{Path(wav_path).stem}.txt"
        if txt_file.exists():
            text = txt_file.read_text().strip()
            txt_file.unlink(missing_ok=True)
            if not text:
                log("[AVISO] Whisper CLI: transcrição vazia")
                return None
            return text

        log(f"[ERRO] Whisper CLI não gerou .txt. stderr: {result.stderr[:200]}")
        return None

    except Exception as e:
        log(f"[ERRO] Transcrição: {e}")
        return None
    finally:
        if converted:
            Path(wav_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Contexto inteligente para sessão nova
# ---------------------------------------------------------------------------
MODEL_ALIASES = {
    "/opus": "opus",
    "/sonnet": "sonnet",
    "/haiku": "haiku",
}


def read_if_exists(path: Path) -> str | None:
    try:
        text = path.read_text().strip()
        return text if text else None
    except (FileNotFoundError, OSError):
        return None


def is_bootstrap_mode() -> bool:
    """Verifica se o bot ainda está em modo bootstrap (primeira conversa)."""
    return BOOTSTRAP_FILE.exists()


def _restore_bootstrap() -> bool:
    """Restaura BOOTSTRAP.md a partir do template para reiniciar a configuração."""
    if BOOTSTRAP_TEMPLATE.exists():
        BOOTSTRAP_FILE.write_text(BOOTSTRAP_TEMPLATE.read_text())
        return True
    return False


# Palavras-chave que indicam necessidade de ferramentas MCP
_TOOL_KEYWORDS = re.compile(
    r'\b(agenda|calendar|evento|reuniao|reunião|horario|horário|'
    r'email|gmail|mensagem|whatsapp|zap|'
    r'campanha|ads|meta|facebook|instagram|anuncio|anúncio|trafego|tráfego|'
    r'hubspot|crm|contato|deal|negocio|negócio|'
    r'notion|planilha|sheet|doc|drive|arquivo|pasta|'
    r'manychat|subscriber|flow|tag|'
    r'supabase|sql|banco|tabela|query|'
    r'monday|hackmd|puppeteer|navega|screenshot|formulario|formulário|'
    r'lembrete|lembra|agendar|agend|'
    r'envia|manda|cria|busca|procura|pesquisa)\b',
    re.IGNORECASE
)


def _needs_tools(text: str) -> bool:
    """Detecta se a mensagem provavelmente precisa de ferramentas MCP."""
    return bool(_TOOL_KEYWORDS.search(text))


def build_session_context(user_message: str | None = None) -> str | None:
    """Monta contexto rico para injetar na primeira mensagem de uma sessão nova.

    Se BOOTSTRAP.md existe, injeta ele como prioridade — o bot entra em modo
    de entrevista para conhecer o usuário.

    user_message: quando fornecido, usa lazy loading para TOOLS.md (só injeta
    se a mensagem parecer precisar de ferramentas MCP).
    """
    parts = []

    # Bootstrap mode: primeira conversa, foco em conhecer o usuário
    bootstrap = read_if_exists(BASE_DIR / "BOOTSTRAP.md")
    if bootstrap:
        parts.append(f"[MODO BOOTSTRAP — PRIMEIRA CONVERSA]\n{bootstrap}")
        tools = read_if_exists(BASE_DIR / "TOOLS.md")
        if tools:
            parts.append(f"[FERRAMENTAS DISPONÍVEIS]\n{tools}")
        return "[CONTEXTO DA SESSÃO]\n\n" + "\n\n---\n\n".join(parts) + "\n\n[FIM DO CONTEXTO]"

    # Define arquivos estáticos para leitura paralela
    # CORE.md contém tudo: identidade + raciocínio + standing orders
    # SOUL.md, AGENTS.md e IDENTITY.md foram absorvidos pelo CORE.md
    static_files: list[tuple[str, Path]] = [
        ("COMO PENSAR E AGIR", BASE_DIR / "CORE.md"),
        ("PERFIL DO USUÁRIO", BASE_DIR / "USER.md"),
        ("COMPORTAMENTO ATIVO", BASE_DIR / "BEHAVIOR.md"),
    ]

    # TOOLS.md: lazy loading — só injeta se mensagem precisar de ferramentas
    include_tools = (user_message is None) or _needs_tools(user_message)
    if include_tools:
        static_files.append(("FERRAMENTAS E AMBIENTE", BASE_DIR / "TOOLS.md"))

    # Leitura paralela dos arquivos estáticos
    def _read_labeled(item: tuple[str, Path]) -> tuple[str, str | None]:
        label, path = item
        return label, read_if_exists(path)

    with ThreadPoolExecutor(max_workers=max(len(static_files), 1)) as executor:
        read_results = list(executor.map(_read_labeled, static_files))

    for label, content in read_results:
        if content:
            parts.append(f"[{label}]\n{content}")

    # Data/hora do sistema (para o Claude saber quando e "hoje", "amanha", etc.)
    cfg_tz_name = load_config().get("timezone", "America/Sao_Paulo")
    tz_local = _get_local_tz()
    now_local = datetime.now(tz_local)
    parts.append(
        f"[DATA E HORA DO SISTEMA]\n"
        f"Agora: {now_local.strftime('%Y-%m-%d %H:%M')} ({cfg_tz_name})\n"
        f"Dia da semana: {['segunda','terca','quarta','quinta','sexta','sabado','domingo'][now_local.weekday()]}"
    )

    # Memória de longo prazo
    memory = read_if_exists(MEMORY_FILE)
    if memory:
        parts.append(f"[MEMÓRIA DE LONGO PRAZO]\n{memory}")

    # Notas de sessão dos últimos 7 dias (exclui conv- logs)
    if MEMORY_DIR.exists():
        today_str = datetime.now().strftime("%Y-%m-%d")
        all_note_files = sorted(
            [f for f in MEMORY_DIR.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*.md")],
            reverse=True
        )[:14]  # busca até 14 arquivos para cobrir 7 dias com múltiplos arquivos por dia

        notes_by_date: dict[str, list[str]] = {}
        for f in all_note_files:
            date_key = f.name[:10]  # YYYY-MM-DD
            if len(notes_by_date) >= 7 and date_key not in notes_by_date:
                break  # limite de 7 datas distintas
            content = f.read_text(encoding="utf-8").strip()
            if content:
                notes_by_date.setdefault(date_key, []).append(content)

        for date_key in sorted(notes_by_date.keys(), reverse=True):
            label = f"HOJE — {date_key}" if date_key == today_str else date_key
            combined = "\n\n---\n\n".join(notes_by_date[date_key])
            parts.append(f"[NOTAS — {label}]\n{combined}")

    # Histórico recente de conversas (últimos 3 dias, limite de ~6000 chars)
    if MEMORY_DIR.exists():
        conv_logs = sorted(MEMORY_DIR.glob("conv-[0-9]*.md"), reverse=True)[:3]
        conv_parts = []
        total_chars = 0
        max_conv_chars = 6000

        for f in conv_logs:
            content = f.read_text(encoding="utf-8").strip()
            if not content:
                continue
            if total_chars + len(content) > max_conv_chars:
                # Trunca para não exceder o limite
                content = content[:max_conv_chars - total_chars]
            date_label = f.stem[5:]  # remove prefixo "conv-"
            conv_parts.append(f"### {date_label}\n{content}")
            total_chars += len(content)
            if total_chars >= max_conv_chars:
                break

        if conv_parts:
            parts.append("[HISTÓRICO RECENTE DE CONVERSAS]\n\n" + "\n\n".join(conv_parts))

    if parts:
        return "[CONTEXTO DA SESSÃO]\n\n" + "\n\n---\n\n".join(parts) + "\n\n[FIM DO CONTEXTO]"
    return None


_context_injected_for_session: str | None = None


def inject_context_if_needed(prompt: str, session_id: str | None, user_message: str | None = None) -> str:
    """Injeta contexto na primeira mensagem REAL do usuário na sessão.

    Usa um flag interno para saber se já injetou — não depende de session_id
    existir, porque o prewarm cria session_id antes da primeira mensagem real.

    user_message: texto original do usuário, usado para lazy loading de TOOLS.md.
    """
    global _context_injected_for_session

    if _context_injected_for_session == session_id and session_id is not None:
        return prompt  # Já injetou nesta sessão

    context = build_session_context(user_message=user_message or prompt)
    if context:
        _context_injected_for_session = session_id
        return f"{context}\n\n---\n\n{prompt}"
    return prompt


# ---------------------------------------------------------------------------
# Salvamento de memória da sessão — daemon controla todas as escritas
# ---------------------------------------------------------------------------
_message_count: int = 0
_MEMORY_CHECKPOINT_INTERVAL: int = 5  # A cada N mensagens, salva memória

_EXTRACT_PROMPT_SUFFIX = (
    "\n\nRegra fundamental: so e FATO o que o usuario disse explicitamente nesta conversa.\n"
    "Inferencia, deducao e interpretacao de contexto NAO sao fatos. Sao hipoteses.\n"
    "Exemplos do que NAO e fato: interpretar exemplos hipoteticos como preferencias reais,\n"
    "deduzir profissao a partir de ferramentas mencionadas, assumir rotina a partir de horarios.\n\n"
    "Retorne SOMENTE um JSON. Para cada item, classifique como CONFIRMED ou INFERRED:\n"
    "{\n"
    '  "contacts": [{"name": "nome", "phone": "+55...", "email": "...", "context": "...", "confidence": "CONFIRMED"}],\n'
    '  "preferences": [{"rule": "regra de comportamento", "confidence": "CONFIRMED ou INFERRED", "source": "trecho da conversa"}],\n'
    '  "decisions": [{"text": "decisao ou fato", "confidence": "CONFIRMED ou INFERRED", "source": "trecho da conversa"}],\n'
    '  "tasks": [{"text": "tarefa pendente", "due_date": "YYYY-MM-DD ou null", "due_time": "HH:MM ou null", "confidence": "CONFIRMED"}]\n'
    "}\n"
    "CONFIRMED = o usuario disse isso explicitamente, sem ambiguidade.\n"
    "INFERRED = voce deduziu a partir do contexto. Pode estar errado.\n\n"
    "Se nao houver nada novo, retorne: {}\n"
    "Retorne APENAS o JSON, sem explicacao, sem blocos de codigo markdown."
)


def _parse_json_response(response: str) -> dict | None:
    """Extrai JSON de uma resposta do Claude, removendo markdown se necessário."""
    raw = response.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())
    raw = raw.strip()
    if not raw or raw == "{}":
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log(f"[MEMÓRIA] Resposta não é JSON válido: {raw[:120]}")
        return None


def _write_memory_extract(extract: dict, cfg: dict | None = None) -> list[str]:
    """Daemon escreve nos arquivos de memória com base no JSON extraído.

    Retorna lista descritiva do que foi salvo (para notificação Telegram).
    Todas as escritas são append — nunca sobrescreve conteúdo existente.
    """
    saved = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- Contatos → USER.md (só CONFIRMED) ---
    contacts = [c for c in extract.get("contacts", []) if isinstance(c, dict) and c.get("name")]
    contacts = [c for c in contacts if c.get("confidence", "CONFIRMED") == "CONFIRMED"]
    if contacts:
        lines = [f"\n## Contatos salvos em {now_str}"]
        for c in contacts:
            name = c.get("name", "").strip()
            phone = c.get("phone", "").strip()
            email = c.get("email", "").strip()
            context = c.get("context", "").strip()
            lines.append(f"- {name} | {phone} | {email} | {context}")
            saved.append(f"Contato: {name}")
        with open(BASE_DIR / "USER.md", "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # --- Preferências → USER.md (CONFIRMED direto, INFERRED com marcação) ---
    prefs = [p for p in extract.get("preferences", []) if isinstance(p, dict) and p.get("rule", "").strip()]
    if prefs:
        confirmed = [p for p in prefs if p.get("confidence") == "CONFIRMED"]
        inferred = [p for p in prefs if p.get("confidence") == "INFERRED"]
        lines = []
        if confirmed:
            lines.append(f"\n## Preferencias confirmadas em {now_str}")
            for p in confirmed:
                lines.append(f"- {p['rule'].strip()}")
                saved.append(f"Preferencia: {p['rule'][:70]}")
        if inferred:
            lines.append(f"\n## Inferencias nao confirmadas ({now_str})")
            for p in inferred:
                src = p.get("source", "contexto geral")
                lines.append(f"- [inferido] {p['rule'].strip()} (fonte: {src})")
                saved.append(f"Inferencia: {p['rule'][:70]}")
        if lines:
            with open(BASE_DIR / "USER.md", "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    # --- Decisões e fatos → MEMORY.md (CONFIRMED direto, INFERRED com marcação) ---
    decisions_raw = extract.get("decisions", [])
    decisions = []
    for d in decisions_raw:
        if isinstance(d, dict) and d.get("text", "").strip():
            decisions.append(d)
        elif isinstance(d, str) and d.strip():
            decisions.append({"text": d.strip(), "confidence": "CONFIRMED"})
    if decisions:
        confirmed = [d for d in decisions if d.get("confidence") == "CONFIRMED"]
        inferred = [d for d in decisions if d.get("confidence") == "INFERRED"]
        lines = [f"\n## Registrado em {now_str}"]
        for d in confirmed:
            lines.append(f"- {d['text']}")
            saved.append(f"Decisao: {d['text'][:70]}")
        for d in inferred:
            src = d.get("source", "contexto geral")
            lines.append(f"- [inferido] {d['text']} (fonte: {src})")
            saved.append(f"Inferencia: {d['text'][:70]}")
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # --- Tarefas → reminders.json ---
    # Só cria lembrete se o usuário informou data explícita; sem data = só nota em MEMORY.md
    tz_brt = _get_local_tz()
    tasks = [t for t in extract.get("tasks", []) if isinstance(t, dict) and t.get("text")]
    if tasks:
        reminders = load_reminders()
        for t in tasks:
            text = t.get("text", "").strip()
            due_date_raw = t.get("due_date")
            due_time_raw = t.get("due_time")
            due_date = str(due_date_raw).strip() if due_date_raw and str(due_date_raw).strip() not in ("null", "None", "") else ""
            due_time = str(due_time_raw).strip() if due_time_raw and str(due_time_raw).strip() not in ("null", "None", "") else ""
            if not text:
                continue
            # Sem data explícita: não criar lembrete automático
            if not due_date:
                continue
            try:
                time_part = due_time if due_time else "08:00"
                due_dt = datetime.strptime(f"{due_date} {time_part}", "%Y-%m-%d %H:%M")
                due_at = due_dt.replace(tzinfo=tz_brt).isoformat()
            except ValueError:
                due_at = (datetime.now(tz_brt) + timedelta(days=1)).replace(
                    hour=8, minute=0, second=0, microsecond=0).isoformat()
            reminders.append({
                "id": str(uuid.uuid4()),
                "text": f"{(cfg or {}).get('user_name', '')}, não esquece: {text}".lstrip(", "),
                "due_at": due_at,
                "action": "notify",
                "sent": False,
            })
            saved.append(f"Lembrete: {text[:70]}")

        # Valida que o JSON resultante é serializável antes de sobrescrever o arquivo
        try:
            json.dumps(reminders, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as json_err:
            log(f"[MEMÓRIA] reminders resultante inválido — abortando escrita: {json_err}")
        else:
            save_reminders(reminders)

    return saved


def run_memory_checkpoint(session_id: str | None, cfg: dict) -> None:
    """Checkpoint de memória: Claude extrai JSON, daemon escreve nos arquivos."""
    if not _checkpoint_lock.acquire(blocking=False):
        log("[MEMÓRIA] Checkpoint já em andamento, pulando")
        return

    def _worker():
        try:
            conv_log = _read_conv_logs(days=1)
            if not conv_log:
                log("[MEMÓRIA] Checkpoint: sem log de conversa")
                return

            today = datetime.now().strftime("%Y-%m-%d")
            prompt = (
                f"[LOG DE CONVERSA DE HOJE ({today})]\n{conv_log}\n\n"
                "---\n\n"
                "CHECKPOINT DE MEMÓRIA — analise o log acima."
                + _EXTRACT_PROMPT_SUFFIX
            )
            log("[MEMÓRIA] Checkpoint iniciado...")
            response, _ = call_claude(prompt, None, cfg)
            if not response:
                log("[MEMÓRIA] Checkpoint: sem resposta do Claude")
                return

            extract = _parse_json_response(response)
            if extract is None or extract == {}:
                log("[MEMÓRIA] Checkpoint: nada novo")
                return

            saved = _write_memory_extract(extract, cfg)
            if saved:
                log(f"[MEMÓRIA] Checkpoint salvou: {saved}")
            else:
                log("[MEMÓRIA] Checkpoint: JSON vazio, nada salvo")
        finally:
            _checkpoint_lock.release()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def save_session_to_memory(session_id: str | None, cfg: dict) -> None:
    """Encerramento de sessão: Claude extrai JSON, daemon escreve nos arquivos e cria nota diária."""
    MEMORY_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H%M")

    conv_log = _read_conv_logs(days=2)
    if not conv_log:
        log("[MEMÓRIA] Sem log de conversa para salvar")
        return

    prompt = (
        f"[LOG DE CONVERSA DOS ÚLTIMOS 2 DIAS]\n{conv_log}\n\n"
        "---\n\n"
        "ENCERRAMENTO DE SESSÃO — analise o log acima.\n"
        "Retorne SOMENTE um JSON:\n"
        "{\n"
        '  "contacts": [{"name": "nome", "phone": "+55...", "email": "...", "context": "...", "confidence": "CONFIRMED"}],\n'
        '  "preferences": [{"rule": "preferência ou regra descoberta", "confidence": "CONFIRMED ou INFERRED", "source": "trecho que justifica"}],\n'
        '  "decisions": [{"text": "decisão ou fato importante", "confidence": "CONFIRMED ou INFERRED", "source": "trecho que justifica"}],\n'
        '  "tasks": [{"text": "tarefa pendente", "due_date": "YYYY-MM-DD ou null", "due_time": "HH:MM ou null"}],\n'
        '  "summary": "resumo da sessão em 3-5 bullet points markdown"\n'
        "}\n"
        "Se não houver nada novo, retorne: {}\n"
        "Retorne APENAS o JSON, sem explicação, sem blocos de código markdown."
    )
    log("[MEMÓRIA] Salvando contexto da sessão...")
    response, _ = call_claude(prompt, None, cfg)
    if not response:
        log("[AVISO] Falha ao salvar memória da sessão")
        return

    extract = _parse_json_response(response)
    if extract is None or extract == {}:
        log("[MEMÓRIA] Nada novo para salvar")
        return

    saved = _write_memory_extract(extract, cfg)

    # Cria nota diária se tem resumo
    summary = extract.get("summary", "").strip()
    if summary:
        daily_file = MEMORY_DIR / f"{today}-{ts}.md"
        daily_file.write_text(
            f"# Sessão {today} {ts[:2]}h{ts[2:]}\n\n{summary}\n",
            encoding="utf-8",
        )
        saved.append("Nota diária criada")
        log(f"[MEMÓRIA] Nota diária: {daily_file.name}")

    if saved:
        log(f"[MEMÓRIA] Sessão encerrada e salva: {saved}")
    else:
        log("[MEMÓRIA] Encerramento: nada novo para salvar")

    # Consolida notas antigas se acumularam muitos arquivos
    _consolidate_memory_if_needed(cfg)


def _flush_memory_before_reset(session_id: str | None, cfg: dict, label: str = "reset") -> bool:
    """Garante flush de memória antes de qualquer reset de sessão.

    Executa save_session_to_memory de forma síncrona e confirma que terminou.
    Se falhar, loga aviso mas não bloqueia o reset.

    Retorna True se o flush foi bem-sucedido, False se falhou.
    """
    if not session_id and not _read_conv_logs(days=1):
        log(f"[FLUSH] {label}: sem sessão nem conv-log — nada a salvar")
        return True

    try:
        log(f"[FLUSH] {label}: iniciando memory flush antes de limpar sessão...")
        save_session_to_memory(session_id, cfg)
        log(f"[FLUSH] {label}: memory flush concluído")
        return True
    except Exception as e:
        log(f"[AVISO] {label}: memory flush falhou ({e}) — reset prosseguirá assim mesmo")
        return False


def _consolidate_memory_if_needed(cfg: dict, threshold: int = 30) -> None:
    """Consolida as notas de sessão mais antigas quando há muitos arquivos.

    Quando o número de notas diárias supera `threshold`, as 10 mais antigas
    são fundidas em um único arquivo de sumário mensal pelo Claude. Os
    originais só são removidos após o sumário ser salvo com sucesso.
    """
    if not MEMORY_DIR.exists():
        return

    note_files = sorted(
        [f for f in MEMORY_DIR.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*.md")],
        reverse=False,  # mais antigas primeiro
    )
    if len(note_files) <= threshold:
        return

    to_consolidate = note_files[:10]
    combined = "\n\n---\n\n".join(f.read_text(encoding="utf-8") for f in to_consolidate)
    oldest_date = to_consolidate[0].name[:7]  # YYYY-MM
    summary_file = MEMORY_DIR / f"summary-{oldest_date}.md"

    prompt = (
        f"[CONSOLIDAÇÃO DE MEMÓRIA]\n{combined}\n\n"
        "---\nResuma as informações acima em um único documento markdown conciso. "
        "Preserve decisões importantes, aprendizados sobre o usuário e fatos relevantes. "
        "Elimine redundâncias. Formato: bullet points agrupados por tema. "
        "Retorne APENAS o markdown, sem explicação."
    )
    log(f"[MEMÓRIA] Consolidando {len(to_consolidate)} notas antigas em {summary_file.name}...")
    response, _ = call_claude(prompt, None, cfg)
    if response and len(response) > 100:
        summary_file.write_text(
            f"# Sumário consolidado — {oldest_date}\n\n{response}\n",
            encoding="utf-8",
        )
        for f in to_consolidate:
            f.unlink(missing_ok=True)
        log(f"[MEMÓRIA] Consolidação concluída: {len(to_consolidate)} notas → {summary_file.name}")
    else:
        log("[MEMÓRIA] Consolidação falhou — originais mantidos")


# ---------------------------------------------------------------------------
# Lembretes agendados
# ---------------------------------------------------------------------------
def load_reminders() -> list[dict]:
    try:
        if REMINDERS_FILE.exists():
            return json.loads(REMINDERS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log(f"[LEMBRETE] Erro ao ler reminders.json: {e}")
    return []


def save_reminders(reminders: list[dict]) -> None:
    tmp = REMINDERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(reminders, indent=2, ensure_ascii=False, default=str))
    tmp.replace(REMINDERS_FILE)


def check_reminders(cfg: dict, session_id: str | None = None) -> None:
    """Verifica lembretes vencidos e envia pro Telegram."""
    reminders = load_reminders()
    if not reminders:
        return

    now = datetime.now(timezone.utc)
    pending = []
    sent_any = False

    for r in reminders:
        if r.get("sent"):
            continue

        try:
            due = datetime.fromisoformat(r["due_at"])
            # Normaliza pra UTC se não tem timezone
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError) as e:
            log(f"[LEMBRETE] Formato inválido, ignorando: {e}")
            r["sent"] = True
            sent_any = True
            continue

        if now >= due:
            chat_id = cfg.get("telegram_chat_id")
            token = cfg.get("telegram_token")
            action = r.get("action", "notify")

            if action == "execute" and chat_id and token:
                # Ação automática: roda em thread pra não bloquear o loop
                reminder_text = r.get("text", "")
                log(f"[LEMBRETE] Executando ação em background: {reminder_text[:60]}")
                send_telegram(chat_id, f"⏰ Executando agendamento:\n{reminder_text[:100]}", token)

                def _exec_reminder(text=reminder_text, cid=chat_id, tk=token):
                    try:
                        # Sessão própria — não contamina a conversa do usuário
                        resp, _ = call_claude(text, None, cfg)
                        if resp:
                            send_telegram(cid, resp, tk)
                    except Exception as ex:
                        log(f"[LEMBRETE] Erro na execução: {ex}")
                        send_telegram(cid, f"Erro ao executar agendamento: {text[:60]}", tk)

                threading.Thread(target=_exec_reminder, daemon=True).start()
            elif chat_id and token:
                # Lembrete simples: só notifica
                msg = f"🔔 **Lembrete**\n\n{r.get('text', '(sem texto)')}"
                send_telegram(chat_id, msg, token)
                log(f"[LEMBRETE] Enviado: {r.get('text', '')[:60]}")

            r["sent"] = True
            sent_any = True
        else:
            pending.append(r)

    if sent_any:
        # Salva apenas os não enviados
        save_reminders([r for r in reminders if not r.get("sent")])


# ---------------------------------------------------------------------------
# Heartbeat proativo
# ---------------------------------------------------------------------------
_last_heartbeat_at: float = 0.0
_heartbeat_sent_today: set = set()   # horários "HH:MM" já enviados hoje
_heartbeat_today_date: str = ""       # data atual (para resetar o set diariamente)


def _heartbeat_times_due(cfg: dict) -> bool:
    """Verifica se algum horário pré-definido está vencido e ainda não foi enviado hoje."""
    global _heartbeat_sent_today, _heartbeat_today_date
    tz_brt = _get_local_tz(cfg)
    now_brt = datetime.now(tz_brt)
    today = now_brt.strftime("%Y-%m-%d")

    # Reseta os enviados quando vira o dia
    if today != _heartbeat_today_date:
        _heartbeat_today_date = today
        _heartbeat_sent_today = set()

    times = cfg.get("heartbeat_times", [])
    current_hhmm = now_brt.strftime("%H:%M")

    for t in times:
        if t <= current_hhmm and t not in _heartbeat_sent_today:
            _heartbeat_sent_today.add(t)
            return True
    return False


def should_run_heartbeat(cfg: dict) -> bool:
    global _last_heartbeat_at
    tz_brt = _get_local_tz(cfg)
    hora_brt = datetime.now(tz_brt).hour

    # Quiet hours: 23h-8h BRT — sem heartbeat de madrugada
    if hora_brt >= 23 or hora_brt < 8:
        return False

    # Modo horários pré-definidos (1x/dia ou 3x/dia)
    if cfg.get("heartbeat_times"):
        return _heartbeat_times_due(cfg)

    # Modo intervalo fixo (a cada N minutos)
    interval = cfg.get("heartbeat_interval_minutes", 30) * 60
    if interval <= 0:
        return False
    return (time.time() - _last_heartbeat_at) > interval


_heartbeat_running = False
_last_heartbeat_notification: str = ""
_rate_limited_until: float = 0.0  # timestamp até quando está em rate limit
_pending_intervalo: str = ""       # estado do fluxo /intervalo: "" | "aguarda_modo" | "aguarda_1x" | "aguarda_3x"


def run_heartbeat(cfg: dict, state: dict) -> None:
    """Verifica proativamente se há algo que o usuário precisa saber.
    Roda em thread separada para não bloquear o loop de mensagens."""
    global _last_heartbeat_at, _heartbeat_running

    if _heartbeat_running:
        return  # Já tem um heartbeat rodando

    _last_heartbeat_at = time.time()
    _heartbeat_running = True

    def _heartbeat_worker():
        global _heartbeat_running
        try:
            # Lê HEARTBEAT.md como fonte de verdade do que verificar
            heartbeat_instructions = read_if_exists(HEARTBEAT_FILE)
            if not heartbeat_instructions:
                heartbeat_instructions = (
                    "Verifique Google Calendar (próximos 60min) e Gmail (urgente hoje). "
                    "Se nada relevante, responda apenas: HEARTBEAT_OK"
                )

            # Contexto mínimo: apenas HEARTBEAT.md + TOOLS.md
            # Não usa build_session_context() completo para não desperdiçar tokens
            tools_content = read_if_exists(BASE_DIR / "TOOLS.md")
            context_parts = [f"[INSTRUÇÕES DE HEARTBEAT]\n{heartbeat_instructions}"]
            if tools_content:
                context_parts.append(f"[FERRAMENTAS DISPONÍVEIS]\n{tools_content}")
            minimal_context = "[CONTEXTO HEARTBEAT]\n\n" + "\n\n---\n\n".join(context_parts) + "\n\n[FIM DO CONTEXTO]"

            prompt = "HEARTBEAT PROATIVO — verificação automática. Siga as instruções acima."
            enriched_prompt = f"{minimal_context}\n\n---\n\n{prompt}"

            log("[HEARTBEAT] Verificação proativa iniciada...")

            # Roda com timeout de 90s — se travar, abandona silenciosamente
            result: list = [None, None]

            def _call():
                result[0], result[1] = call_claude(enriched_prompt, None, cfg)

            call_thread = threading.Thread(target=_call, daemon=True)
            call_thread.start()
            call_thread.join(timeout=90)

            if call_thread.is_alive():
                log("[HEARTBEAT] Timeout — verificação demorou mais de 90s, ignorando")
                return

            response = result[0]

            if response and "HEARTBEAT_OK" not in response:
                response = strip_thinking(response)
                global _last_heartbeat_notification
                response_key = response[:50].strip()
                if response_key == _last_heartbeat_notification:
                    log(f"[HEARTBEAT] Notificação duplicada, ignorando: {response[:60]}...")
                else:
                    chat_id = cfg.get("telegram_chat_id")
                    if chat_id:
                        send_telegram(chat_id, response, cfg["telegram_token"])
                        _last_heartbeat_notification = response_key
                        # Persiste no state para sobreviver a restarts
                        try:
                            s = load_state()
                            s["last_heartbeat_notification"] = response_key
                            save_state(s)
                        except Exception:
                            pass
                        log(f"[HEARTBEAT] Notificação enviada: {response[:80]}...")
            else:
                log("[HEARTBEAT] Nada relevante")
        except Exception as e:
            log(f"[HEARTBEAT] Erro no worker: {e}")
        finally:
            _heartbeat_running = False

    t = threading.Thread(target=_heartbeat_worker, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Background tasks (sub-agente paralelo)
# ---------------------------------------------------------------------------
def run_in_background(prompt: str, chat_id: int, state: dict, cfg: dict) -> None:
    """Executa tarefa pesada em background com sessão isolada e notifica quando pronta."""
    def worker():
        log(f"[BACKGROUND] Tarefa iniciada: {prompt[:60]}...")
        # Sessão isolada (None) para não contaminar a sessão principal do usuário
        enriched = inject_context_if_needed(prompt, None, user_message=prompt)
        response, _ = call_claude(enriched, None, cfg)

        if response:
            response = strip_thinking(response)
            send_telegram(chat_id, response, cfg["telegram_token"])
            log("[BACKGROUND] Tarefa concluída e entregue")
        else:
            send_telegram(chat_id, "Tarefa em background falhou.", cfg["telegram_token"])
            log("[BACKGROUND] Tarefa falhou")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # Remove threads já terminadas antes de adicionar a nova (evita memory leak)
    _background_tasks[:] = [bt for bt in _background_tasks if bt.is_alive()]
    _background_tasks.append(t)


# ---------------------------------------------------------------------------
# Sessão: timeout e reset
# ---------------------------------------------------------------------------
def check_session_timeout(state: dict, cfg: dict) -> dict:
    """Reseta sessão se inativa por mais de session_timeout_hours."""
    timeout_h = cfg.get("session_timeout_hours", 3)
    last = state.get("last_activity_at")
    if not last or not state.get("session_id"):
        return state

    try:
        last_dt = datetime.fromisoformat(last)
        if datetime.now(timezone.utc) - last_dt > timedelta(hours=timeout_h):
            log(f"[SESSÃO] Timeout de {timeout_h}h atingido — salvando memória e resetando sessão")
            old_id = state["session_id"]

            # Flush de memória antes de limpar sessão
            _flush_memory_before_reset(old_id, cfg, label="timeout")

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            (SESSIONS_DIR / f"session_{ts}.md").write_text(
                f"# Sessão expirada em {ts}\n\n"
                f"Session ID: {old_id}\n"
                f"Iniciada em: {state.get('session_started_at', '—')}\n"
                f"Última atividade: {last}\n"
            )
            state.update({"session_id": None, "session_started_at": None, "last_activity_at": None})
            state["needs_context_refresh"] = True
            global _context_injected_for_session
            _context_injected_for_session = None
            save_state(state)
    except Exception as e:
        log(f"[AVISO] Erro ao verificar timeout de sessão: {e}")

    return state


# ---------------------------------------------------------------------------
# Chamada ao Claude CLI (com retry)
# ---------------------------------------------------------------------------
_RETRY_AUDIO_PATTERN = re.compile(
    r'\b(retranscrever|retranscrev|tenta\s+(de\s+novo|novamente)|tentar\s+de\s+novo'
    r'|transcreve\s+de\s+novo|transcrev\s+novamente)\b',
    re.IGNORECASE
)

_FAST_PATTERNS = re.compile(
    r'^('
    r'(bom\s+dia|boa\s+(tarde|noite)|oi+|e\s*a[ií]|fala(\s+\w+)?|eai|hey|hello?)'
    r'|obrigad[oa]|valeu|vlw|tmj|show|blz|beleza|top|massa|nice|ok'
    r'|sim|não|nao|pode\s*ser|bora|vamos|ta\s*bom|tá\s*bom'
    r'|h[aeiou]h[aeiou]+(h[aeiou])*|kk+|rs+'
    r'|entendi|perfeito|fechou|combinado'
    r')[!.,\s]*$',
    re.IGNORECASE
)


_CORRECTION_PATTERN = re.compile(
    r'\b(nao era isso|errado|errou|incorreto|'
    r'entendeu errado|interpretou errado|'
    r'nao foi o que (eu )?pedi|diferente do que pedi|'
    r'ta errado|tava errado|nao e isso|nao era isso)\b',
    re.IGNORECASE
)


def capture_feedback(user_text: str, state: dict) -> None:
    """Detecta correcao explicita e registra no conv-log."""
    if not _CORRECTION_PATTERN.search(user_text):
        return
    last_response = state.get("last_bot_response", "")
    if not last_response:
        return
    log(f"[FEEDBACK] Correcao detectada: {user_text[:80]}")
    # Registra no conv-log com marcacao
    try:
        now = datetime.now()
        with open(_conv_log_path(now), "a", encoding="utf-8") as f:
            f.write(f"[{now.strftime('%H:%M')}] [CORRECAO DETECTADA]\n")
            f.write(f"  Resposta anterior: {last_response[:500]}\n")
            f.write(f"  Correcao: {user_text[:500]}\n\n")
    except Exception:
        pass


def _is_simple_message(text: str) -> bool:
    """Detecta mensagens simples que não precisam de ferramentas/memória.

    Mensagens simples usam --max-turns 1 (sem tool use) para resposta rápida.
    """
    clean = text.strip()
    # Mensagens internas do daemon nunca são simples
    if clean.startswith("["):
        return False
    # Mensagens curtas que batem com padrões de saudação/confirmação
    if len(clean) < 40 and _FAST_PATTERNS.match(clean):
        return True
    return False


# ---------------------------------------------------------------------------
# Classificacao de mensagem e Reasoning Gate
# ---------------------------------------------------------------------------
class MessageType(Enum):
    SIMPLE = "simple"
    QUESTION = "question"
    TASK = "task"
    DESTRUCTIVE = "destructive"
    MEMORY_QUERY = "memory_query"


_DESTRUCTIVE_PATTERNS = re.compile(
    r'\b(envia\s+(mensagem|email|msg)|manda\s+(mensagem|email|msg)|'
    r'send|deleta|remove|apaga|sobrescreve|exclui)\b', re.IGNORECASE)

_TASK_PATTERNS = re.compile(
    r'\b(agenda|cria|faz|escreve|analisa|configura|atualiza|'
    r'verifica|checa|ve\s+minh|veja\s+minh|puxa|busca|pesquisa)\b', re.IGNORECASE)


def classify_message(text: str) -> MessageType:
    clean = text.strip()
    if _FAST_PATTERNS.match(clean):
        return MessageType.SIMPLE
    if clean.lower().startswith("/buscar"):
        return MessageType.MEMORY_QUERY
    if _DESTRUCTIVE_PATTERNS.search(clean):
        return MessageType.DESTRUCTIVE
    if _TASK_PATTERNS.search(clean):
        return MessageType.TASK
    return MessageType.QUESTION


def build_turn_context(msg_type: MessageType, state: dict) -> str:
    """Monta contexto adicional especifico para o tipo de mensagem atual."""
    parts = []

    now = datetime.now()

    if msg_type in (MessageType.TASK, MessageType.DESTRUCTIVE):
        tz_brt = _get_local_tz()
        now_brt = now.astimezone(tz_brt) if now.tzinfo else now.replace(tzinfo=tz_brt)
        cfg_tz_name = load_config().get("timezone", "America/Sao_Paulo")
        parts.append(f"[DATA/HORA ATUAL] {now_brt.strftime('%Y-%m-%d %H:%M')} ({cfg_tz_name})")

        try:
            reminders = load_reminders()
            pending = [r for r in reminders if not r.get("sent")]
            if pending:
                lines = [f"- {r.get('text', '?')[:80]} ({r.get('due_at', '?')[:16]})" for r in pending[:5]]
                parts.append("[LEMBRETES PENDENTES]\n" + "\n".join(lines))
        except Exception:
            pass

    if msg_type == MessageType.DESTRUCTIVE:
        behavior = read_if_exists(BASE_DIR / "BEHAVIOR.md")
        if behavior:
            parts.append(f"[REGRAS DE COMPORTAMENTO]\n{behavior}")

    return "\n\n".join(parts) if parts else ""


_REASONING_PROMPT = (
    "[ANALISE PREVIA -- nao e a resposta final]\n\n"
    "Mensagem: {mensagem}\n\n"
    "Complete este scratchpad:\n\n"
    "ENTENDIMENTO: O que esta sendo pedido, em uma frase.\n"
    "DEPENDENCIAS: Que informacoes ou ferramentas sao necessarias?\n"
    "RISCOS: Algo pode dar errado? Sim/Nao. Se sim, o que?\n"
    "ABORDAGEM: Como resolver? Passos concretos.\n"
    "CONFIANCA: Alta / Media / Baixa. Por que?\n\n"
    "Se confianca Baixa: termine com CLARIFY: <pergunta precisa ao usuario>\n"
    "Se confianca Alta ou Media: termine com PROCEED"
)


def run_reasoning_gate(text: str, cfg: dict) -> tuple[str | None, bool]:
    """Executa analise previa antes da acao. Retorna (scratchpad, should_clarify)."""
    prompt = _REASONING_PROMPT.format(mensagem=text)
    response, _ = call_claude(prompt, None, cfg)
    if not response:
        return None, False
    should_clarify = "CLARIFY:" in response
    return response, should_clarify


_REVIEW_PROMPT = (
    "[AUTO-REVISAO]\n\n"
    "Resposta gerada:\n{resposta}\n\n"
    "Verifique:\n"
    "1. FACTUAL: ha afirmacao sem certeza de que e verdadeira?\n"
    "2. IRREVERSIVEL: instrui acao que nao pode ser desfeita sem confirmacao explicita do usuario?\n"
    "3. COMPLETO: falta informacao que o usuario precisaria?\n\n"
    "Se tudo OK: responda exatamente APPROVED\n"
    "Se ha problema: responda REVISE: <problema em uma frase>"
)


def run_self_review(response: str, cfg: dict) -> tuple[str, bool]:
    """Auto-revisao da resposta antes de enviar. Retorna (response, was_revised)."""
    prompt = _REVIEW_PROMPT.format(resposta=response)
    review, _ = call_claude(prompt, None, cfg)
    if not review:
        return response, False
    if "REVISE:" in review:
        reason = review.split("REVISE:", 1)[1].strip()
        log(f"[REVIEW] Revisao solicitada: {reason[:80]}")
        return response, True  # Sinaliza que precisa revisao
    log("[REVIEW] APPROVED")
    return response, False


def call_claude(
    prompt: str,
    session_id: str | None,
    cfg: dict,
    on_progress: callable = None,
    force_full_turns: bool = False,
) -> tuple[str | None, str | None]:
    """Chama Claude CLI. Sem timeout artificial — deixa o Claude trabalhar.

    Args:
        on_progress: callback(seconds_elapsed) chamado a cada 15s durante execução.
                     Serve pra atualizar o usuário, não pra matar o processo.
        force_full_turns: desabilita o fast path (--max-turns 1). Usado no bootstrap
                          para garantir que o Claude pode usar ferramentas (ex: salvar arquivos).

    Na última tentativa, descarta --resume se a sessão parece podre, criando
    uma nova sessão ao invés de falhar silenciosamente por horas.

    Mensagens simples (saudações, confirmações) usam --max-turns 1 para
    resposta rápida sem tool use.
    """
    project_dir = cfg["project_dir"]
    max_retries = cfg.get("max_retry_attempts", 3)
    backoff = cfg.get("retry_backoff_seconds", [5, 10, 30])

    # Injeta timestamp atual para que o Claude calcule horários relativos corretamente
    tz_brt = _get_local_tz(cfg)
    now_brt = datetime.now(tz_brt)
    cfg_tz_name = cfg.get("timezone", "America/Sao_Paulo")
    ts_header = f"[Agora: {now_brt.strftime('%Y-%m-%d %H:%M')} ({cfg_tz_name})]\n\n"
    prompt_with_ts = ts_header + prompt

    # Roteamento: mensagens simples → resposta rápida sem tools
    # Desabilitado no bootstrap: Claude precisa de tool use para salvar arquivos
    fast_mode = _is_simple_message(prompt) and not force_full_turns

    base_cmd = [
        "claude", "-p", prompt_with_ts,
        "--output-format", "json",
        "--model", cfg.get("claude_model", "sonnet"),
    ]
    if fast_mode:
        base_cmd += ["--max-turns", "1"]

    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    for attempt in range(max_retries):
        # Na última tentativa: se havia sessão e ela causou falhas nas tentativas
        # anteriores, descarta o --resume para recuperar automaticamente
        use_session = session_id
        if attempt == max_retries - 1 and session_id and attempt > 0:
            log("[RETRY] Última tentativa sem --resume — sessão pode estar corrompida")
            use_session = None

        cmd = base_cmd[:]
        if use_session:
            cmd += ["--resume", use_session]

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, cwd=project_dir, env=env,
            )

            start_time = time.time()
            last_progress = start_time

            # Deixa o Claude trabalhar — sem timeout artificial
            while proc.poll() is None:
                elapsed = time.time() - start_time

                # Callback de progresso a cada 15s
                if on_progress and (time.time() - last_progress) >= 15:
                    on_progress(int(elapsed))
                    last_progress = time.time()

                time.sleep(0.5)

            elapsed_total = int(time.time() - start_time)
            stdout = proc.stdout.read()
            stderr = proc.stderr.read()

            if proc.returncode != 0:
                log(f"[ERRO] claude código {proc.returncode} ({elapsed_total}s) | stderr: {stderr[:200]} | stdout: {stdout[:200]}")
                combined = (stderr + stdout).lower()
                if "rate" in combined or "limit" in combined:
                    raise RuntimeError("rate_limit")
                if attempt < max_retries - 1:
                    wait = backoff[min(attempt, len(backoff) - 1)]
                    log(f"[RETRY] Tentativa {attempt + 2}/{max_retries} em {wait}s")
                    time.sleep(wait)
                    continue
                # Se a última tentativa foi sem sessão, retorna None pra forçar nova sessão
                return None, use_session

            raw = stdout.strip()
            if not raw:
                log(f"[ERRO] claude retornou output vazio ({elapsed_total}s)")
                return None, use_session

            response_text = None
            new_session_id = use_session

            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "result":
                        response_text = obj.get("result", "")
                        new_session_id = obj.get("session_id", use_session)
                        if obj.get("is_error") and "rate" in str(response_text).lower():
                            raise RuntimeError("rate_limit")
                except json.JSONDecodeError:
                    continue

            if response_text is None:
                response_text = raw

            log(f"[CLAUDE] Resposta em {elapsed_total}s")
            return response_text, new_session_id

        except RuntimeError as e:
            if "rate_limit" in str(e):
                if attempt < max_retries - 1:
                    wait = backoff[min(attempt, len(backoff) - 1)]
                    log(f"[RETRY] Rate limit — aguardando {wait}s")
                    time.sleep(wait)
                    continue
                # Registra rate limit para bloquear novas tentativas por 3 minutos
                global _rate_limited_until
                _rate_limited_until = time.time() + 180
                return "⏳ Rate limit atingido. Aguarde alguns minutos.", session_id
        except FileNotFoundError:
            log("[ERRO] `claude` não encontrado no PATH")
            return None, session_id
        except Exception as e:
            log(f"[ERRO] Falha ao chamar claude: {e}")
            if attempt < max_retries - 1:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
                continue
            return None, session_id

    return None, session_id


# ---------------------------------------------------------------------------
# Pré-aquecimento de sessão
# ---------------------------------------------------------------------------
def prewarm_session(cfg: dict, state: dict) -> dict:
    """Cria sessão Claude com contexto completo pré-carregado.

    Injeta CORE.md, USER.md, BEHAVIOR.md e MEMORY.md no prewarm para que
    a primeira mensagem do usuário seja processada rapidamente — o contexto
    já está na sessão.
    """
    if state.get("session_id"):
        log(f"[INIT] Sessão existente: {state['session_id'][:16]}...")
        return state

    log("[INIT] Pré-aquecendo sessão com contexto completo...")
    context = build_session_context()
    if context:
        prompt = (
            f"{context}\n\n---\n\n"
            "Sistema iniciado com contexto carregado. "
            "Você já tem a identidade, perfil do usuário, comportamento e memória. "
            "Aguarde a primeira mensagem do usuário."
        )
    else:
        prompt = "Sistema iniciado. Aguarde instruções."

    _, new_session_id = call_claude(prompt, None, cfg)
    if new_session_id:
        state["session_id"] = new_session_id
        state["session_started_at"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        # Marca que o contexto já foi injetado nesta sessão
        global _context_injected_for_session
        _context_injected_for_session = new_session_id
        log(f"[INIT] Sessão pré-aquecida com contexto: {new_session_id[:16]}...")
    else:
        log("[AVISO] Pré-aquecimento falhou — contexto será injetado na primeira mensagem")
    return state


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_message_context(msg: dict) -> str:
    """Extrai contexto extra de reply e forward para enriquecer o prompt."""
    parts = []

    # Mensagem encaminhada: identifica a origem
    fwd_from = msg.get("forward_from")
    fwd_chat = msg.get("forward_from_chat")
    fwd_name = msg.get("forward_sender_name")
    if fwd_from:
        name = f"{fwd_from.get('first_name', '')} {fwd_from.get('last_name', '')}".strip()
        parts.append(f"[Mensagem encaminhada de: {name}]")
    elif fwd_chat:
        parts.append(f"[Mensagem encaminhada do canal/grupo: {fwd_chat.get('title', '?')}]")
    elif fwd_name:
        parts.append(f"[Mensagem encaminhada de: {fwd_name}]")

    # Reply: inclui a mensagem original como contexto
    reply = msg.get("reply_to_message")
    if reply:
        reply_text = reply.get("text", "")
        reply_from = reply.get("from", {})
        is_bot = reply_from.get("is_bot", False)
        if reply_text:
            origin = "bot (sua resposta anterior)" if is_bot else "usuário"
            # Trunca replies muito longas
            snippet = reply_text[:1000] + ("..." if len(reply_text) > 1000 else "")
            parts.append(f"[Em resposta a mensagem do {origin}: \"{snippet}\"]")

    return "\n".join(parts) if parts else ""


def _safe_send(chat_id: int, text: str, token: str) -> None:
    """Envia mensagem ao Telegram com fallback garantido — nunca falha silenciosamente."""
    try:
        send_telegram(chat_id, text, token)
    except Exception as e:
        log(f"[ERRO] Falha crítica ao enviar mensagem: {e}")


def _save_heartbeat_cfg(times: list, interval: int, cfg: dict) -> None:
    """Persiste configuração de heartbeat no config.json."""
    cfg["heartbeat_times"] = times
    cfg["heartbeat_interval_minutes"] = interval
    full_cfg = load_config()
    full_cfg["heartbeat_times"] = times
    full_cfg["heartbeat_interval_minutes"] = interval
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(full_cfg, indent=2))
    tmp.replace(CONFIG_FILE)


def _validate_time(t: str) -> bool:
    try:
        h, m = t.split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except Exception:
        return False


def handle_intervalo_flow(text: str, chat_id: int, cfg: dict) -> bool:
    """Processa respostas do fluxo conversacional do /intervalo.

    Retorna True se a mensagem foi consumida pelo fluxo (não deve ir pro Claude).
    """
    global _pending_intervalo
    token = cfg["telegram_token"]
    t = text.strip()

    if _pending_intervalo == "aguarda_modo":
        if t == "1":
            _pending_intervalo = "aguarda_1x"
            send_telegram(chat_id, "Qual horário? (ex: 09:00)", token)
        elif t == "2":
            _pending_intervalo = "aguarda_3x"
            send_telegram(chat_id, "Informe os 3 horários separados por espaço.\n(ex: 09:00 13:00 18:00)", token)
        elif t == "3":
            _save_heartbeat_cfg([], 60, cfg)
            _pending_intervalo = ""
            send_telegram(chat_id, "Avisos proativos: a cada hora.", token)
            log("[INTERVALO] Configurado: 1h")
        elif t == "4":
            _save_heartbeat_cfg([], 0, cfg)
            _pending_intervalo = ""
            send_telegram(chat_id, "Avisos proativos desativados.", token)
            log("[INTERVALO] Desativado")
        else:
            send_telegram(chat_id, "Digite 1, 2, 3 ou 4.", token)
        return True

    if _pending_intervalo == "aguarda_1x":
        if _validate_time(t):
            _save_heartbeat_cfg([t], 0, cfg)
            _pending_intervalo = ""
            send_telegram(chat_id, f"Avisos proativos: 1x ao dia às {t}.", token)
            log(f"[INTERVALO] Configurado: 1x {t}")
        else:
            send_telegram(chat_id, "Formato inválido. Use HH:MM, ex: 09:00", token)
        return True

    if _pending_intervalo == "aguarda_3x":
        parts = t.split()
        if len(parts) == 3 and all(_validate_time(p) for p in parts):
            times = sorted(parts)
            _save_heartbeat_cfg(times, 0, cfg)
            _pending_intervalo = ""
            send_telegram(chat_id, f"Avisos proativos: 3x ao dia — {', '.join(times)}.", token)
            log(f"[INTERVALO] Configurado: 3x {times}")
        else:
            send_telegram(chat_id, "Informe exatamente 3 horários no formato HH:MM.\n(ex: 09:00 13:00 18:00)", token)
        return True

    return False


def handle_text(text: str, chat_id: int, state: dict, cfg: dict) -> None:
    """Processa mensagem de texto. GARANTE que o usuário sempre recebe resposta."""
    token = cfg["telegram_token"]
    stop_typing = threading.Event()

    try:
        log(f"[MSG] Processando: {text[:80]}")

        # Captura feedback/correcao antes de qualquer processamento
        capture_feedback(text, state)

        # Retry de áudio: se usuário pedir retranscrição e tiver file_id pendente
        pending_fid = state.get("pending_audio_file_id")
        if pending_fid and _RETRY_AUDIO_PATTERN.search(text):
            log(f"[ÁUDIO] Retry solicitado para file_id={pending_fid[:20]}...")
            state["pending_audio_file_id"] = None
            save_state(state)
            handle_audio(pending_fid, chat_id, state, cfg)
            return

        # Fluxo conversacional do /intervalo — intercepta antes de ir pro Claude
        if _pending_intervalo:
            handle_intervalo_flow(text, chat_id, cfg)
            return

        # Se ainda está em rate limit, avisa sem tentar chamar o Claude
        global _rate_limited_until
        if time.time() < _rate_limited_until:
            remaining = int(_rate_limited_until - time.time())
            _safe_send(chat_id,
                f"Ainda em rate limit. Aguarde mais {remaining}s antes de tentar novamente.", token)
            return

        t = threading.Thread(target=send_typing, args=(chat_id, token, stop_typing), daemon=True)
        t.start()

        # Mensagens de progresso — mantém o usuário informado durante tarefas longas
        _progress_msgs = [
            (30, "⏳ Ainda trabalhando..."),
            (60, "⏳ Tarefa mais complexa, aguarde..."),
            (120, "⏳ Processamento longo. Ainda estou aqui, trabalhando..."),
            (240, "⏳ Quase lá, já estou finalizando..."),
        ]
        _progress_sent = [0]

        def on_progress(elapsed_seconds):
            for threshold, msg in _progress_msgs:
                if elapsed_seconds >= threshold and _progress_sent[0] < threshold:
                    _safe_send(chat_id, msg, token)
                    _progress_sent[0] = threshold
                    break

        # Classifica a mensagem
        msg_type = classify_message(text)
        log(f"[ROUTER] Tipo: {msg_type.value}")

        # Reasoning Gate para TASK e DESTRUCTIVE
        scratchpad = None
        if msg_type in (MessageType.TASK, MessageType.DESTRUCTIVE):
            if cfg.get("reasoning_gate_enabled", True):
                log("[REASONING] Executando analise previa...")
                scratchpad, should_clarify = run_reasoning_gate(text, cfg)
                if should_clarify and scratchpad:
                    # Extrai a pergunta de clarificacao
                    clarify_idx = scratchpad.find("CLARIFY:")
                    clarify_msg = scratchpad[clarify_idx + 8:].strip() if clarify_idx >= 0 else "Pode detalhar melhor?"
                    send_telegram(chat_id, clarify_msg, token)
                    log(f"[REASONING] Pediu clarificacao: {clarify_msg[:80]}")
                    stop_typing.set()
                    return
                if scratchpad:
                    log(f"[REASONING] Analise concluida: PROCEED")

        # Injeta contexto completo (CORE, USER, BEHAVIOR, MEMORY) na primeira msg real
        enriched = inject_context_if_needed(text, state.get("session_id"), user_message=text)

        # Post-Compaction Refresh: re-injeta standing orders apos reset de sessao
        if state.get("needs_context_refresh"):
            core_content = read_if_exists(BASE_DIR / "CORE.md")
            if core_content:
                refresh_sections = []
                for section in ["## Protocolo de Processamento", "## Standing Orders", "## Portoes de Aprovacao"]:
                    idx = core_content.find(section)
                    if idx >= 0:
                        next_section = core_content.find("\n## ", idx + len(section))
                        end = next_section if next_section >= 0 else len(core_content)
                        refresh_sections.append(core_content[idx:end].strip())
                if refresh_sections:
                    refresh_text = "[CONTEXT REFRESH - Regras criticas re-injetadas apos reset de sessao]\n\n" + "\n\n".join(refresh_sections)
                    enriched = f"{refresh_text}\n\n---\n\n{enriched}"
                    log("[REFRESH] Standing orders re-injetadas apos reset")
            state["needs_context_refresh"] = False
            save_state(state)

        # Contexto adicional especifico para o tipo de mensagem
        turn_context = build_turn_context(msg_type, state)
        if turn_context:
            enriched = f"{turn_context}\n\n---\n\n{enriched}"

        # Bootstrap: em cada mensagem subsequente, lembra o Claude que está em modo setup
        if is_bootstrap_mode() and _context_injected_for_session == state.get("session_id"):
            enriched = (
                "[LEMBRETE: BOOTSTRAP AINDA NÃO CONCLUÍDO — "
                "foque em completar a configuração inicial. "
                "Recuse outras tarefas e redirecione gentilmente se necessário.]\n\n"
                + enriched
            )

        # Pre-fixa o raciocinio previo se disponivel
        if scratchpad:
            enriched = f"[RACIOCINIO PREVIO]\n{scratchpad}\n\n---\n\n[AGIR AGORA]\n{enriched}"

        # Sem timeout — deixa o Claude trabalhar o tempo que precisar
        response, new_session_id = call_claude(
            enriched, state.get("session_id"), cfg,
            on_progress=on_progress,
            force_full_turns=is_bootstrap_mode(),
        )

        stop_typing.set()

        # Remove blocos de raciocinio interno antes de entregar ao usuario
        if response:
            response = strip_thinking(response)

        # Self-review para mensagens DESTRUCTIVE (max 1 retry)
        if response and msg_type == MessageType.DESTRUCTIVE:
            response, was_revised = run_self_review(response, cfg)
            if was_revised:
                # Monta prompt de revisao com o motivo e refaz a chamada
                review_prompt = f"[REVISAO NECESSARIA]\n\nResposta anterior necessita correcao. Reescreva levando em conta o problema identificado.\n\n{enriched}"
                revised_response, _ = call_claude(
                    review_prompt, state.get("session_id"), cfg,
                    force_full_turns=False,
                )
                if revised_response:
                    response = strip_thinking(revised_response)

        if response and response.strip():
            # Atualiza sessão
            if new_session_id and new_session_id != state.get("session_id"):
                state["session_id"] = new_session_id
                if not state.get("session_started_at"):
                    state["session_started_at"] = now_iso()
                log(f"[SESSÃO] ID: {new_session_id[:16]}...")

            state["last_activity_at"] = now_iso()
            save_state(state)
            _safe_send(chat_id, response, token)
            log(f"[RESP] OK: {response[:80]}...")

            # Salva resposta no state para captura de feedback no proximo turno
            state["last_bot_response"] = response[:1000] if response else ""
            save_state(state)

            # Log local de conversa — fonte primária para salvamento de memória
            _append_conv_log(text, response)

            # Checkpoint de memória a cada N mensagens
            global _message_count
            _message_count += 1
            if _message_count % _MEMORY_CHECKPOINT_INTERVAL == 0:
                run_memory_checkpoint(state.get("session_id"), cfg)
        else:
            # Falha total após todas as tentativas
            _safe_send(chat_id,
                "❌ Não consegui processar sua mensagem.\n\n"
                "Possíveis causas:\n"
                "- Claude CLI sobrecarregado ou fora do ar\n"
                "- Rate limit do plano (aguarde alguns minutos)\n"
                "- Sessão corrompida (use /nova)\n\n"
                "Tente novamente em alguns instantes.", token)
            log("[ERRO] Falha total — todas as tentativas esgotadas")

    except Exception as e:
        # Blindagem absoluta: qualquer exceção não prevista ainda gera resposta
        stop_typing.set()
        log(f"[ERRO] Exceção não tratada em handle_text: {e}")
        _safe_send(chat_id,
            "❌ Erro inesperado. O bot vai se recuperar automaticamente.\n"
            "Tente novamente em alguns segundos.", token)


def handle_audio(file_id: str, chat_id: int, state: dict, cfg: dict,
                  extra_context: str = "") -> None:
    """Processa áudio. GARANTE que o usuário sempre recebe resposta."""
    token = cfg["telegram_token"]
    stop_typing = threading.Event()

    try:
        log(f"[ÁUDIO] Recebido file_id={file_id[:20]}...")

        t = threading.Thread(target=send_typing, args=(chat_id, token, stop_typing), daemon=True)
        t.start()

        audio_path = download_telegram_file(token, file_id, AUDIO_TEMP_DIR)
        if not audio_path:
            stop_typing.set()
            _safe_send(chat_id, "❌ Não consegui baixar o áudio. Tente enviar novamente.", token)
            return

        text = transcribe_audio(audio_path, cfg)
        stop_typing.set()

        try:
            Path(audio_path).unlink(missing_ok=True)
        except Exception:
            pass

        if not text:
            # Salva o file_id para tentar de novo se o usuário pedir
            state["pending_audio_file_id"] = file_id
            save_state(state)
            _safe_send(chat_id,
                "❌ Não consegui transcrever o áudio. "
                "Diga \"retranscrever\" ou \"tenta de novo\" que eu baixo e tento novamente.", token)
            return

        log(f"[ÁUDIO] Transcrição: {text[:80]}")
        if extra_context:
            text = f"{extra_context}\n\n[Transcrição de áudio]:\n{text}"
        handle_text(text, chat_id, state, cfg)

    except Exception as e:
        stop_typing.set()
        log(f"[ERRO] Exceção não tratada em handle_audio: {e}")
        _safe_send(chat_id,
            "❌ Erro ao processar áudio. Tente enviar como texto.", token)


def handle_file(file_id: str, file_name: str, mime_type: str,
                 caption: str | None, chat_id: int, state: dict, cfg: dict,
                 extra_context: str = "") -> None:
    """Processa documentos e arquivos (PDF, DOCX, etc). Salva em disco e pede ao Claude pra ler."""
    token = cfg["telegram_token"]
    stop_typing = threading.Event()

    try:
        log(f"[ARQUIVO] {file_name} ({mime_type})")

        t = threading.Thread(target=send_typing, args=(chat_id, token, stop_typing), daemon=True)
        t.start()

        FILES_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        dest = FILES_TEMP_DIR / Path(file_name).name
        result = tg_request(token, "getFile", {"file_id": file_id})
        if not (result and result.get("ok")):
            stop_typing.set()
            _safe_send(chat_id, "❌ Não consegui baixar o arquivo.", token)
            return

        file_path = result["result"].get("file_path")
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        r = _session.get(url, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        log(f"[ARQUIVO] Salvo: {dest} ({len(r.content)} bytes)")

        user_msg = caption or f"Analise este arquivo: {file_name}"
        ctx = f"{extra_context}\n\n" if extra_context else ""
        prompt = (
            f"{ctx}O usuário enviou um arquivo.\n"
            f"- Nome: {file_name}\n"
            f"- Tipo: {mime_type}\n"
            f"- Caminho: {dest}\n"
            f"- Instrução do usuário: {user_msg}\n\n"
            f"Leia o arquivo no caminho acima e processe conforme solicitado."
        )

        handle_text(prompt, chat_id, state, cfg)
        stop_typing.set()

    except Exception as e:
        stop_typing.set()
        log(f"[ERRO] handle_file: {e}")
        _safe_send(chat_id, "❌ Erro ao processar arquivo. Tente novamente.", token)


def handle_photo(photo_sizes: list, caption: str | None,
                 chat_id: int, state: dict, cfg: dict,
                 extra_context: str = "") -> None:
    """Processa fotos/imagens. Baixa a maior resolução e pede ao Claude pra analisar."""
    token = cfg["telegram_token"]
    stop_typing = threading.Event()

    try:
        # Pega a maior resolução (último item no array)
        best = photo_sizes[-1]
        file_id = best["file_id"]
        log(f"[IMAGEM] Resolução: {best.get('width', '?')}x{best.get('height', '?')}")

        t = threading.Thread(target=send_typing, args=(chat_id, token, stop_typing), daemon=True)
        t.start()

        FILES_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        dest = FILES_TEMP_DIR / f"photo_{ts}.jpg"

        result = tg_request(token, "getFile", {"file_id": file_id})
        if not (result and result.get("ok")):
            stop_typing.set()
            _safe_send(chat_id, "❌ Não consegui baixar a imagem.", token)
            return

        file_path = result["result"].get("file_path")
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        r = _session.get(url, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        log(f"[IMAGEM] Salva: {dest} ({len(r.content)} bytes)")

        user_msg = caption or "O que você vê nesta imagem?"
        ctx = f"{extra_context}\n\n" if extra_context else ""
        prompt = (
            f"{ctx}O usuário enviou uma imagem.\n"
            f"- Caminho: {dest}\n"
            f"- Instrução do usuário: {user_msg}\n\n"
            f"Leia a imagem no caminho acima e processe conforme solicitado."
        )

        handle_text(prompt, chat_id, state, cfg)
        stop_typing.set()

    except Exception as e:
        stop_typing.set()
        log(f"[ERRO] handle_photo: {e}")
        _safe_send(chat_id, "❌ Erro ao processar imagem. Tente novamente.", token)


def handle_sticker(sticker: dict, chat_id: int, state: dict, cfg: dict) -> None:
    """Processa stickers como imagens."""
    token = cfg["telegram_token"]
    try:
        # Stickers têm thumb ou file_id. Usa o arquivo principal.
        file_id = sticker.get("file_id")
        if not file_id:
            return

        FILES_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        ext = ".webp" if not sticker.get("is_animated") and not sticker.get("is_video") else ".webm"
        dest = FILES_TEMP_DIR / f"sticker_{ts}{ext}"

        result = tg_request(token, "getFile", {"file_id": file_id})
        if not (result and result.get("ok")):
            return

        file_path = result["result"].get("file_path")
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        r = _session.get(url, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)

        emoji = sticker.get("emoji", "")
        prompt = (
            f"O usuário enviou um sticker{f' (emoji: {emoji})' if emoji else ''}.\n"
            f"- Caminho: {dest}\n\n"
            f"Leia a imagem e responda ao contexto do sticker."
        )
        handle_text(prompt, chat_id, state, cfg)
    except Exception as e:
        log(f"[ERRO] handle_sticker: {e}")


def handle_location(location: dict, chat_id: int, state: dict, cfg: dict) -> None:
    """Processa localização compartilhada."""
    lat = location.get("latitude")
    lng = location.get("longitude")
    prompt = (
        f"O usuário compartilhou uma localização:\n"
        f"- Latitude: {lat}\n"
        f"- Longitude: {lng}\n\n"
        f"O que tem nesse local? Se tiver ferramentas de mapa disponíveis, use."
    )
    handle_text(prompt, chat_id, state, cfg)


def handle_contact(contact: dict, chat_id: int, state: dict, cfg: dict) -> None:
    """Processa contato compartilhado. Daemon persiste imediatamente, Claude interpreta."""
    name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
    phone = contact.get("phone_number", "")
    email = contact.get("email", "")

    # Daemon persiste o contato agora, sem depender de checkpoint futuro
    if name or phone:
        _write_memory_extract({"contacts": [{"name": name, "phone": phone, "email": email, "context": "compartilhado via Telegram"}]})
        log(f"[CONTATO] Salvo imediatamente: {name} {phone}")

    prompt = (
        f"O usuário compartilhou um contato:\n"
        f"- Nome: {name}\n"
        f"- Telefone: {phone}\n\n"
        f"Contato já foi salvo em USER.md. Confirme e pergunte se quer fazer algo com ele."
    )
    handle_text(prompt, chat_id, state, cfg)


def _search_memory(query: str, max_results: int = 5) -> str:
    """Busca por palavra-chave nos arquivos de memória.

    Percorre notas de sessão, conv-logs, USER.md e MEMORY.md e retorna
    trechos relevantes com contexto. Usado pelo /buscar e internamente
    quando Claude precisa responder sobre histórico passado.
    """
    if not MEMORY_DIR.exists():
        return "Nenhuma memória salva ainda."

    query_lower = query.lower()
    hits: list[tuple[str, str]] = []  # (nome_arquivo, trecho)
    context_chars = 200  # chars de contexto ao redor do match

    # Arquivos de memória raiz
    root_files = [MEMORY_FILE, BASE_DIR / "USER.md"]
    memory_files = [f for f in root_files if f.exists()]
    # Notas de sessão e conv-logs
    memory_files += sorted(MEMORY_DIR.glob("*.md"), reverse=True)

    for f in memory_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue

        text_lower = text.lower()
        pos = text_lower.find(query_lower)
        if pos == -1:
            continue

        # Extrai trecho ao redor da primeira ocorrência
        start = max(0, pos - context_chars // 2)
        end = min(len(text), pos + len(query) + context_chars // 2)
        snippet = text[start:end].strip().replace("\n", " ")
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        hits.append((f.name, snippet))
        if len(hits) >= max_results:
            break

    if not hits:
        return f"Nenhuma memória encontrada para '{query}'."

    lines = [f"Resultados para '{query}' ({len(hits)} encontrado(s)):\n"]
    for name, snippet in hits:
        lines.append(f"[{name}]\n{snippet}\n")
    return "\n".join(lines)


def search_memory_semantic(query: str, cfg: dict) -> str:
    """Busca semântica nas memórias usando Claude como ranqueador.

    Primeiro faz grep textual para montar contexto relevante, depois pede ao
    Claude para interpretar e responder com base nesse contexto. Se não houver
    matches textuais, passa os últimos 7 dias de notas para Claude buscar.
    """
    # Coleta contexto: primeiro tenta grep, depois fallback para notas recentes
    hits_text = _search_memory(query, max_results=8)
    no_grep_match = "Nenhuma memória encontrada" in hits_text

    if no_grep_match:
        # Fallback: últimas 7 notas como contexto
        if not MEMORY_DIR.exists():
            return f"Nenhuma memória salva para buscar '{query}'."
        recent_files = sorted(MEMORY_DIR.glob("*.md"), reverse=True)[:7]
        if not recent_files:
            return f"Nenhuma memória salva para buscar '{query}'."
        context_parts = [f.read_text(encoding="utf-8") for f in recent_files]
        context = "\n\n---\n\n".join(context_parts)
    else:
        context = hits_text

    prompt = (
        f"[BUSCA NAS MEMÓRIAS]\n"
        f"Pergunta/termo: {query}\n\n"
        f"Contexto encontrado:\n{context}\n\n"
        "---\nResponda de forma direta e concisa o que você encontrou sobre esse tema nas memórias. "
        "Se não houver nada relevante, diga claramente. Máximo 10 linhas."
    )
    response, _ = call_claude(prompt, None, cfg)
    return response or hits_text


def handle_command(cmd_text: str, chat_id: int, state: dict, cfg: dict) -> None:
    global _context_injected_for_session, _pending_intervalo
    token = cfg["telegram_token"]
    cmd = cmd_text.strip().lower().split()[0]

    # Bootstrap: bloqueia comandos até configuração inicial ser concluída
    if is_bootstrap_mode() and cmd not in ("/status", "/pular"):
        send_telegram(chat_id,
            "Vi que ainda não finalizamos sua configuração. "
            "Podemos continuar? Vai levar só alguns minutos.", token)
        return

    # /pular: pula a configuração inicial
    if cmd == "/pular":
        if BOOTSTRAP_FILE.exists():
            BOOTSTRAP_FILE.unlink()
        send_telegram(chat_id,
            "Tudo bem! Quando quiser configurar suas preferências, "
            "é só dizer 'quero atualizar minha configuração' ou usar /configurar.", token)
        log("[CMD] Bootstrap pulado pelo usuário")
        return

    # /configurar: reinicia o fluxo de configuração
    if cmd == "/configurar":
        if _restore_bootstrap():
            state.update({"session_id": None, "session_started_at": None, "last_activity_at": None})
            save_state(state)
            send_telegram(chat_id,
                "Ok! Vamos atualizar sua configuração. Me manda uma mensagem pra começar.", token)
            log("[CMD] Bootstrap restaurado para reconfiguração")
        else:
            send_telegram(chat_id,
                "Não encontrei o template de configuração. "
                "Verifique se setup_wizard/templates/BOOTSTRAP.md existe.", token)
        return

    # Troca de modelo: /opus, /sonnet, /haiku
    if cmd in MODEL_ALIASES:
        new_model = MODEL_ALIASES[cmd]
        cfg["claude_model"] = new_model
        state["claude_model"] = new_model
        save_state(state)
        # Persiste no config.json também
        full_cfg = load_config()
        full_cfg["claude_model"] = new_model
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(full_cfg, indent=2))
        tmp.replace(CONFIG_FILE)
        send_telegram(chat_id, f"Modelo alterado para **{new_model}**.", token)
        log(f"[CMD] Modelo alterado para {new_model}")
        return

    if cmd == "/modelo":
        current = cfg.get("claude_model", "sonnet")
        send_telegram(chat_id, (
            f"Modelo atual: **{current}**\n\n"
            "Trocar: /opus /sonnet /haiku"
        ), token)
        return

    if cmd == "/status":
        session_id = state.get("session_id")
        last = state.get("last_activity_at") or ""
        modelo = cfg.get("claude_model", "sonnet")

        duracao = "sem sessao ativa"
        if session_id and state.get("session_started_at"):
            try:
                dt = datetime.fromisoformat(state["session_started_at"])
                delta = datetime.now(timezone.utc) - dt
                h, m = divmod(int(delta.total_seconds()) // 60, 60)
                duracao = f"{h}h{m:02d}m"
            except Exception:
                duracao = "ativa"

        # Notas de sessao (exclui logs conv-)
        notes_count = len([f for f in MEMORY_DIR.glob("*.md")
                           if not f.name.startswith("conv-")]) if MEMORY_DIR.exists() else 0
        rem_count = len([r for r in load_reminders() if not r.get("sent")])

        # Heartbeat
        tz_brt = _get_local_tz(cfg)
        interval = cfg.get("heartbeat_interval_minutes", 0)
        hb_times = cfg.get("heartbeat_times", [])
        if hb_times:
            hb_status = f"horarios fixos: {', '.join(hb_times)}"
        elif interval > 0:
            elapsed = int((time.time() - _last_heartbeat_at) / 60)
            restante = max(0, interval - elapsed)
            hb_status = f"a cada {interval}min (proximo em ~{restante}min)"
        else:
            hb_status = "desativado"

        contexto = "injetado" if (_context_injected_for_session and
                                   _context_injected_for_session == session_id) else "pendente"
        bootstrap = "ativo" if is_bootstrap_mode() else "concluido"
        last_str = last[11:16] + " UTC" if len(last) > 16 else "nunca"

        send_telegram(chat_id, (
            f"Modelo: {modelo}\n"
            f"Sessao: {duracao}\n"
            f"Contexto: {contexto}\n"
            f"Bootstrap: {bootstrap}\n"
            f"Notas salvas: {notes_count}\n"
            f"Lembretes: {rem_count} pendentes\n"
            f"Heartbeat: {hb_status}\n"
            f"Ultima atividade: {last_str}"
        ), token)

    elif cmd == "/nova":
        old = state.get("session_id")
        if old:
            send_telegram(chat_id, "Salvando memória da sessão...", token)
            ok = _flush_memory_before_reset(old, cfg, label="/nova")

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            (SESSIONS_DIR / f"session_{ts}.md").write_text(
                f"# Sessão encerrada em {ts}\n\n"
                f"Session ID: {old}\n"
                f"Iniciada em: {state.get('session_started_at', '—')}\n"
                f"Última atividade: {state.get('last_activity_at', '—')}\n"
                f"Memory flush: {'ok' if ok else 'falhou — verificar logs'}\n"
            )
        state.update({"session_id": None, "session_started_at": None, "last_activity_at": None})
        _context_injected_for_session = None
        save_state(state)
        send_telegram(chat_id, "Nova sessão iniciada. Memória salva.", token)
        log("[CMD] Sessão resetada com salvamento de memória")

    elif cmd == "/memoria":
        lines = []

        # Memoria principal
        if MEMORY_FILE.exists():
            snippet = MEMORY_FILE.read_text(encoding="utf-8").strip()[:120].replace("\n", " ")
            lines.append(f"MEMORY.md: {snippet}...")

        # Notas de sessao (exclui conv- logs)
        if MEMORY_DIR.exists():
            notes = sorted(
                [f for f in MEMORY_DIR.glob("*.md") if not f.name.startswith("conv-")],
                reverse=True
            )[:5]
            if notes:
                lines.append("\nNotas de sessao (recentes):")
                for f in notes:
                    snippet = f.read_text(encoding="utf-8").strip()[:80].replace("\n", " ")
                    lines.append(f"- {f.name}: {snippet}")

        if lines:
            send_telegram(chat_id, "\n".join(lines), token)
        else:
            send_telegram(chat_id, "Nenhuma memoria salva ainda.", token)

    elif cmd == "/lembretes":
        reminders = [r for r in load_reminders() if not r.get("sent")]
        if reminders:
            lines = []
            for r in sorted(reminders, key=lambda x: x.get("due_at", "")):
                try:
                    due = datetime.fromisoformat(r["due_at"])
                    due_str = due.strftime("%d/%m %H:%M")
                except (KeyError, ValueError):
                    due_str = "?"
                lines.append(f"- {due_str} — {r.get('text', '?')[:60]}")
            send_telegram(chat_id, f"🔔 **Lembretes pendentes ({len(reminders)}):**\n\n" + "\n".join(lines), token)
        else:
            send_telegram(chat_id, "Nenhum lembrete pendente.\n\nPeça naturalmente: \"me lembra quinta às 9h sobre a reunião\"", token)

    elif cmd == "/intervalo":
        times = cfg.get("heartbeat_times", [])
        interval = cfg.get("heartbeat_interval_minutes", 30)
        if times:
            atual = f"{len(times)}x ao dia — {', '.join(times)}"
        elif interval > 0:
            atual = f"a cada {interval} minutos"
        else:
            atual = "desativado"
        _pending_intervalo = "aguarda_modo"
        send_telegram(chat_id,
            f"Configuração atual: {atual}\n\n"
            "Como você quer receber os avisos?\n\n"
            "1 — 1x ao dia\n"
            "2 — 3x ao dia\n"
            "3 — A cada hora\n"
            "4 — Desativar", token)
        log("[CMD] /intervalo — aguardando escolha do modo")

    elif cmd == "/bg":
        rest = cmd_text.strip()[3:].strip()
        if rest:
            send_telegram(chat_id, "Executando em background. Te aviso quando terminar.", token)
            run_in_background(rest, chat_id, state, cfg)
        else:
            send_telegram(chat_id, "Use: /bg <tarefa>\nExemplo: /bg analise todas as campanhas ativas", token)

    elif cmd == "/buscar":
        query = cmd_text.strip()[7:].strip()  # remove "/buscar "
        if query:
            send_telegram(chat_id, "Buscando...", token)
            result = search_memory_semantic(query, cfg)
            send_telegram(chat_id, result, token)
            log(f"[CMD] /buscar '{query}' — {len(result)} chars retornados")
        else:
            send_telegram(chat_id, "Use: /buscar <termo>\nExemplo: /buscar decisão campanha", token)

    elif cmd == "/contexto":
        # Lista arquivos injetados no contexto de sessão com tamanho e estimativa de tokens
        context_files: list[tuple[str, Path]] = [
            ("CORE.md", BASE_DIR / "CORE.md"),
            ("USER.md", BASE_DIR / "USER.md"),
            ("BEHAVIOR.md", BASE_DIR / "BEHAVIOR.md"),
            ("TOOLS.md", BASE_DIR / "TOOLS.md"),
            ("MEMORY.md", MEMORY_FILE),
            ("HEARTBEAT.md", HEARTBEAT_FILE),
            ("BOOTSTRAP.md", BOOTSTRAP_FILE),
        ]

        lines = ["Arquivos no contexto de sessao:\n"]
        total_chars = 0
        for label, path in context_files:
            if not path.exists():
                continue
            try:
                size_bytes = path.stat().st_size
                size_kb = size_bytes / 1024
                # Estimativa: ~4 chars por token
                chars = path.read_text(encoding="utf-8", errors="ignore").__len__()
                tokens_est = chars // 4
                total_chars += chars
                lines.append(f"- {label}: {size_kb:.1f}KB ~{tokens_est}tok")
            except Exception:
                lines.append(f"- {label}: erro ao ler")

        # Notas de sessao recentes
        note_chars = 0
        if MEMORY_DIR.exists():
            recent_notes = sorted(
                [f for f in MEMORY_DIR.glob("[0-9]*.md") if not f.name.startswith("conv-")],
                reverse=True
            )[:14]
            for f in recent_notes:
                try:
                    note_chars += len(f.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
            if note_chars:
                lines.append(f"- notas/sessoes (ate 7 dias): {note_chars/1024:.1f}KB ~{note_chars//4}tok")
                total_chars += note_chars

        # Conv-logs recentes
        conv_chars = 0
        if MEMORY_DIR.exists():
            for f in sorted(MEMORY_DIR.glob("conv-[0-9]*.md"), reverse=True)[:3]:
                try:
                    conv_chars += len(f.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    pass
            if conv_chars:
                capped = min(conv_chars, 6000)
                lines.append(f"- conv-logs (3 dias, cap 6k): ~{capped//4}tok")
                total_chars += capped

        total_tokens = total_chars // 4
        lines.append(f"\nTotal estimado: ~{total_tokens} tokens")
        lines.append(f"Bootstrap: {'ATIVO' if is_bootstrap_mode() else 'concluido'}")
        lines.append(f"Contexto injetado nesta sessao: {'sim' if _context_injected_for_session == state.get('session_id') else 'nao'}")

        send_telegram(chat_id, "\n".join(lines), token)
        log("[CMD] /contexto exibido")

    else:
        send_telegram(chat_id, (
            "Comandos:\n"
            "/status — info da sessão\n"
            "/nova — nova sessão (salva memória)\n"
            "/contexto — tamanho dos arquivos no contexto\n"
            "/modelo — ver modelo atual\n"
            "/opus /sonnet /haiku — trocar modelo\n"
            "/memoria — ver memórias salvas\n"
            "/buscar <termo> — buscar nas memórias\n"
            "/lembretes — ver agendamentos\n"
            "/intervalo <min> — intervalo de avisos (0 = desligar)\n"
            "/configurar — atualizar configuração\n"
            "/bg <tarefa> — executar em background"
        ), token)


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------
def cleanup_temp_files(max_age_hours: int = 24) -> None:
    """Remove arquivos temporários e marcadores .summarized antigos."""
    cutoff = time.time() - (max_age_hours * 3600)
    cleaned = 0
    for temp_dir in [AUDIO_TEMP_DIR, FILES_TEMP_DIR]:
        if not temp_dir.exists():
            continue
        for f in temp_dir.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
                    cleaned += 1
            except Exception:
                pass
    # Remove marcadores .summarized com mais de 7 dias
    if MEMORY_DIR.exists():
        summarized_cutoff = time.time() - (7 * 24 * 3600)
        for f in MEMORY_DIR.glob("*.summarized"):
            try:
                if f.stat().st_mtime < summarized_cutoff:
                    f.unlink()
                    cleaned += 1
            except Exception:
                pass
    if cleaned:
        log(f"[CLEANUP] {cleaned} arquivos temporários removidos")


def run() -> None:
    log("=== Claude Terminal (Telegram) iniciado ===")

    cfg = load_config()
    validate_config(cfg)
    state = load_state()
    token = cfg["telegram_token"]

    # Signal handlers para shutdown gracioso
    def _graceful_shutdown(signum, frame):
        log(f"[SHUTDOWN] Sinal {signum} recebido — memory flush antes de sair...")
        current_state = load_state()
        _flush_memory_before_reset(current_state.get("session_id"), cfg, label="SIGTERM")
        log("[SHUTDOWN] Encerrado.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    # Se há log de conversa não resumido de ontem, salva agora
    yesterday = datetime.now() - timedelta(days=1)
    yesterday_log = _conv_log_path(yesterday)
    yesterday_summary = MEMORY_DIR / f"conv-{yesterday.strftime('%Y-%m-%d')}.summarized"
    if yesterday_log.exists() and not yesterday_summary.exists():
        log("[INIT] Resumindo log de ontem não salvo...")
        def _bg_save_yesterday():
            try:
                save_session_to_memory(None, cfg)
                yesterday_summary.touch()
                log("[INIT] Log de ontem resumido com sucesso")
            except Exception as e:
                log(f"[INIT] Erro ao resumir log de ontem: {e}")
        threading.Thread(target=_bg_save_yesterday, daemon=True).start()

    # Descarta updates antigos na primeira execução — exceto quando ainda não há
    # chat_id registrado: nesse caso os updates pendentes contêm a primeira mensagem
    # do usuário (que registra o chat_id E deve ser processada normalmente).
    if state.get("last_update_id") is None:
        if cfg.get("telegram_chat_id"):
            updates = get_updates(token, offset=None)
            if updates:
                state["last_update_id"] = updates[-1]["update_id"]
                save_state(state)
                log(f"[INIT] {len(updates)} updates antigos descartados")
            else:
                state["last_update_id"] = 0
                save_state(state)
        else:
            # Sem chat_id: não descarta nada — a primeira mensagem registra o chat_id
            # e deve ser processada normalmente
            state["last_update_id"] = 0
            save_state(state)
        log("[INIT] Pronto para receber mensagens")

    authorized_chat = cfg.get("telegram_chat_id")
    log(f"[INIT] Chat autorizado: {authorized_chat or 'aguardando primeira mensagem'}")

    # Garante que diretórios existem
    MEMORY_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)
    FILES_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Limpeza de temporários antigos (>24h)
    cleanup_temp_files()

    # Pré-aquece sessão Claude
    state = prewarm_session(cfg, state)

    # Heartbeat NÃO dispara no startup — espera o intervalo completo
    global _last_heartbeat_at, _last_heartbeat_notification
    _last_heartbeat_at = time.time()
    # Restaura última notificação do state para evitar duplicação pós-restart
    _last_heartbeat_notification = state.get("last_heartbeat_notification", "")

    while True:
        try:
            state = load_state()
            cfg = load_config()
            token = cfg["telegram_token"]
            authorized_chat = cfg.get("telegram_chat_id")

            # Usa modelo do state se disponível (troca via /opus etc)
            if state.get("claude_model"):
                cfg["claude_model"] = state["claude_model"]

            # Verifica timeout de sessão a cada ciclo
            state = check_session_timeout(state, cfg)

            # Verifica lembretes agendados
            try:
                check_reminders(cfg, state.get("session_id"))
            except Exception as e:
                log(f"[LEMBRETE] Erro: {e}")

            # Heartbeat proativo
            if should_run_heartbeat(cfg) and state.get("session_id"):
                try:
                    run_heartbeat(cfg, state)
                except Exception as e:
                    log(f"[HEARTBEAT] Erro: {e}")

            last_uid = state.get("last_update_id")
            offset = last_uid + 1 if last_uid is not None else None
            updates = get_updates(token, offset=offset)

            for update in updates:
                update_id = update["update_id"]
                state["last_update_id"] = update_id
                save_state(state)

                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]

                # Registra chat_id na primeira mensagem
                if authorized_chat is None:
                    cfg["telegram_chat_id"] = chat_id
                    tmp = CONFIG_FILE.with_suffix(".tmp")
                    tmp.write_text(json.dumps(cfg, indent=2))
                    tmp.replace(CONFIG_FILE)
                    authorized_chat = chat_id
                    log(f"[INIT] Chat autorizado registrado: {chat_id}")

                if chat_id != authorized_chat:
                    log(f"[AVISO] Mensagem ignorada (chat {chat_id} não autorizado)")
                    continue

                state = load_state()

                text = msg.get("text", "").strip()
                caption = msg.get("caption", "").strip()
                voice = msg.get("voice") or msg.get("audio")
                photo = msg.get("photo")  # Lista de resoluções
                document = msg.get("document")  # Arquivos (PDF, DOCX, etc)
                sticker = msg.get("sticker")
                location = msg.get("location")
                contact = msg.get("contact")

                tipo = "[texto]"
                if voice: tipo = "[áudio]"
                elif photo: tipo = "[imagem]"
                elif document: tipo = f"[arquivo: {document.get('file_name', '?')}]"
                elif sticker: tipo = f"[sticker: {sticker.get('emoji', '?')}]"
                elif location: tipo = "[localização]"
                elif contact: tipo = f"[contato: {contact.get('first_name', '?')}]"
                log(f"[NOVA] update_id={update_id} | {text[:60] or caption[:60] or tipo}")

                # Contexto extra: reply e forward
                extra_context = _build_message_context(msg)

                try:
                    if text.startswith("/"):
                        handle_command(text, chat_id, state, cfg)
                    elif voice:
                        handle_audio(voice["file_id"], chat_id, state, cfg,
                                     extra_context=extra_context)
                    elif photo:
                        handle_photo(photo, caption or None, chat_id, state, cfg,
                                     extra_context=extra_context)
                    elif document:
                        handle_file(
                            document["file_id"],
                            document.get("file_name", "documento"),
                            document.get("mime_type", "application/octet-stream"),
                            caption or None, chat_id, state, cfg,
                            extra_context=extra_context,
                        )
                    elif sticker:
                        handle_sticker(sticker, chat_id, state, cfg)
                    elif location:
                        handle_location(location, chat_id, state, cfg)
                    elif contact:
                        handle_contact(contact, chat_id, state, cfg)
                    elif text:
                        if extra_context:
                            text = f"{extra_context}\n\n{text}"
                        handle_text(text, chat_id, state, cfg)
                    elif msg.get("video") or msg.get("video_note") or msg.get("animation"):
                        _safe_send(chat_id, "Video ainda nao e suportado. Envia como texto ou audio.", token)
                except Exception as e:
                    log(f"[ERRO] Handler crashou: {e}")
                    _safe_send(chat_id, "❌ Erro interno. Tente novamente.", token)

                state = load_state()

        except KeyboardInterrupt:
            log("=== Daemon encerrado ===")
            sys.exit(0)
        except Exception as e:
            log(f"[ERRO] Loop principal: {e}")

        time.sleep(cfg.get("polling_interval_seconds", 2))


if __name__ == "__main__":
    run()
