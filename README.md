# Claude Code Assistant

**Transforme o Claude em um assistente pessoal de IA persistente que vive no seu Telegram.**

Ele lembra do contexto entre sessoes, usa ferramentas MCP para acessar sua agenda, email, CRM e muito mais. Roda como daemon em segundo plano no seu Mac (ou Linux).

---

## Funcionalidades

- **Memoria persistente entre sessoes**  - CORE.md + USER.md + MEMORY.md mantém o contexto vivo entre conversas
- **Identidade personalizada**  - CORE.md define como o assistente pensa e raciocina
- **Mensagens de voz via transcricao local**  - faster-whisper + ffmpeg, privado, sem nuvem
- **Integracoes MCP**  - Google Calendar, Gmail, Meta Ads, HubSpot, Notion, Supabase, Puppeteer e mais
- **Pipeline de 4 estagios**  - classificacao inteligente, reasoning gate, execucao e auto-revisao
- **Gerenciamento de sessoes** com timeout automatico e pre-aquecimento
- **Notificacoes proativas via heartbeat**  - verifica email e agenda periodicamente
- **Extracao de memoria com classificacao**  - fatos CONFIRMED e inferencias INFERRED sao separados
- **Consolidacao automatica de memoria**  - >30 notas sao automaticamente resumidas
- **Busca semantica**  - comando /buscar <termo> para acessar memória
- **Execucao de tarefas em segundo plano**  - /bg <tarefa> para trabalhos pesados
- **Troca de modelo em tempo real**  - /opus /sonnet /haiku
- **Inicio automatico como LaunchAgent** (macOS) ou servico systemd (Linux)

---

## Comeco Rapido

### Via instalador (recomendado)

```bash
git clone https://github.com/alissonoliveira/claude-code-assistant
cd claude-code-assistant
pip install -e .
claude-assistant-setup
```

O wizard `/setup` guia voce na criacao do bot no Telegram, configuracao do perfil, selecao de integracoes MCP e instalacao do servico. E a forma principal de instalacao.

### Manual (desenvolvimento)

```bash
python daemon.py
```

---

## Como Funciona  - Arquitetura

```
┌──────────┐     ┌──────────────┐     ┌──────────────────┐
│ Telegram │◄───►│   Daemon     │◄───►│   Claude CLI     │
│  (voce)  │     │  (Python)    │     │  (claude -p)     │
└──────────┘     └──────────────┘     └──────────────────┘
                       │                       │
                  ┌────┴────┐           ┌──────┴────────┐
                  │ Sistema │           │   MCP Tools   │
                  │   de    │           │               │
                  │ Memoria │           │ - Calendar    │
                  │         │           │ - Gmail       │
                  │CORE.md  │           │ - Meta Ads    │
                  │USER.md  │           │ - HubSpot     │
                  │MEMORY.md│           │ - Notion      │
                  └─────────┘           │ - Supabase    │
                                        │ - Puppeteer   │
                                        └───────────────┘
```

### Pipeline de Processamento

```
Mensagem do Usuario
        ↓
   [ Router ]
   (classifica em SIMPLE, QUESTION, TASK, DESTRUCTIVE, MEMORY_QUERY)
        ↓
[ Reasoning Gate ]
(analise previa: entendimento, dependencias, riscos, abordagem)
        ↓
  [ Execucao ]
  (chama Claude com contexto de memoria e ferramentas MCP)
        ↓
 [ Self-Review ]
 (verifica: factual, irreversivel, completo)
        ↓
  Resposta → Telegram
```

### Fluxo de Memoria

1. **Voce** envia uma mensagem (texto ou voz) para o bot no Telegram
2. O **Daemon** (processo Python em background) captura via polling da API do Telegram Bot
3. O daemon injeta contexto: CORE.md + USER.md + MEMORY.md + notas do dia
4. O daemon classifica a mensagem (SIMPLE, TASK, DESTRUCTIVE, etc)
5. Se TASK ou DESTRUCTIVE, executa Reasoning Gate (analise previa antes da acao)
6. Encaminha para o **Claude CLI** (`claude -p --resume <session_id>`)
7. Claude processa, usa **ferramentas MCP** conforme necessario
8. Resposta retorna ao Telegram
9. Se foi primeira mensagem de sessao ou checkpoint atingido, memoria é consolidada

---

## Sistema de Memoria

A memoria dá continuidade entre sessoes atraves de quatro arquivos principais:

| Arquivo | Quando é Lido | Quando é Atualizado | Proposito |
|---|---|---|---|
| **CORE.md** | Inicio de cada sessao | Manualmente pelo usuario | Identidade, personalidade, estilo de raciocinio do assistente |
| **USER.md** | Inicio de cada sessao | Automaticamente via checkpoint | Perfil do usuario: cargo, empresa, preferencias, estilo de comunicacao |
| **MEMORY.md** | Inicio de cada sessao | Automaticamente via checkpoint | Fatos e decisoes de longo prazo, lições aprendidas |
| **CLAUDE.md** | Inicio de cada sessao | Manualmente pelo usuario | Prompt de sistema, ferramentas disponiveis, regras de comportamento |

Além disso:
- **memory/YYYY-MM-DD.md**  - notas diarias capturando decisoes, tarefas, contexto
- **memory/YYYY-MM-HHMM.md**  - resumos manuais via /nova quando transição de sessao
- **Consolidacao automatica**  - quando ha >30 notas, as 10 mais antigas sao resumidas em memory/YYYY-MM-summary.md

### Checkpoint de Memoria

A cada 5 mensagens (ou ao final de sessao), o daemon:
1. Pede ao Claude para extrair informacoes novo sobre voce: contatos, preferencias, decisoes
2. Classifica cada item como CONFIRMED (dito explicitamente) ou INFERRED (deduzido)
3. Atualiza USER.md (so CONFIRMED) ou MEMORY.md (so fatos confirmados)
4. Marca INFERRED com comentario indicando confiança

---

## Comandos do Telegram

| Comando | Descricao |
|---|---|
| `/status` | Mostra sessao atual, modelo, contagem de memorias |
| `/nova` | Nova sessao (salva memoria antes) |
| `/modelo` | Mostrar modelo atual |
| `/opus` `/sonnet` `/haiku` | Trocar modelo do Claude |
| `/memory` | Listar ultimas 10 memorias salvas |
| `/buscar <termo>` | Buscar semanticamente nas memorias |
| `/bg <tarefa>` | Executar tarefa em segundo plano |
| `/intervalo` | Configurar intervalo de heartbeat |
| `/configurar` | Abrir menu de configuracao |
| `/contexto` | Injetar contexto manual na sessao |
| `/pular` | Pular ciclo de heartbeat |

**Dica:** Qualquer mensagem que nao comece com `/` é encaminhada ao Claude. Mensagens de voz sao transcritas localmente via faster-whisper.

---

## Requisitos

- **Python 3.12+**
- **Claude Code CLI**  - instalado e autenticado ([guia](https://docs.anthropic.com/en/docs/claude-cli))
- **Conta no Telegram**  - com bot criado via [@BotFather](https://t.me/BotFather)
- **Opcional:** faster-whisper para transcrição local de audio (mais rápido e privado que Whisper padrão)
- **Opcional:** ffmpeg para conversao de audio

### Instalacao de Dependencias (macOS)

```bash
# Python 3.12+
brew install python@3.12

# ffmpeg (para conversao de audio)
brew install ffmpeg

# faster-whisper (opcional mas recomendado)
pip install faster-whisper
```

### Instalacao de Dependencias (Linux)

```bash
# Python 3.12+
sudo apt-get install python3.12

# ffmpeg
sudo apt-get install ffmpeg

# faster-whisper
pip install faster-whisper
```

---

## Configuracao

Apos rodar o assistente de configuracao, seu `config.json` ficará assim:

```json
{
  "telegram_token": "SEU_TOKEN_DO_BOT",
  "telegram_chat_id": null,
  "user_name": "Seu Nome",
  "claude_model": "sonnet",
  "project_dir": ".",
  "polling_interval_seconds": 2,
  "session_timeout_hours": 3,
  "max_retry_attempts": 3,
  "retry_backoff_seconds": [5, 10, 30],
  "heartbeat_interval_minutes": 30,
  "heartbeat_times": ["09:00", "13:00", "18:00"],
  "reasoning_gate_enabled": true,
  "whisper_bin": "",
  "whisper_model": "base",
  "whisper_language": "pt",
  "timezone": "America/Sao_Paulo"
}
```

| Chave | Descricao |
|---|---|
| `telegram_token` | Token obtido via @BotFather |
| `telegram_chat_id` | Seu chat ID (detectado automaticamente) |
| `user_name` | Seu nome (usado em lembretes) |
| `claude_model` | `sonnet`, `opus` ou `haiku` |
| `session_timeout_hours` | Resetar sessao apos N horas de inatividade |
| `heartbeat_interval_minutes` | Intervalo de verificacao proativa (0 = desativado) |
| `heartbeat_times` | Horarios fixos para verificacao (ex: `["09:00", "18:00"]`) |
| `reasoning_gate_enabled` | Ativa analise previa antes de executar tarefas |
| `whisper_model` | `base` (padrao), `small`, `medium`, `large` |
| `whisper_language` | Codigo ISO 639-1 do idioma (ex: `pt`, `en`) |
| `timezone` | Fuso horario IANA (ex: `America/Sao_Paulo`) |

---

## Executando como Servico

### macOS (LaunchAgent)

```bash
# Iniciar
launchctl load ~/Library/LaunchAgents/com.user.claude-assistant.plist

# Parar
launchctl unload ~/Library/LaunchAgents/com.user.claude-assistant.plist

# Ver logs
tail -f logs/daemon.log
```

### Linux (systemd)

```bash
# Ativar e iniciar
systemctl --user enable claude-assistant.service
systemctl --user start claude-assistant.service

# Verificar status
systemctl --user status claude-assistant.service

# Ver logs
journalctl --user -u claude-assistant.service -f
```

---

## Inspiracao

Este projeto foi inspirado pela abordagem do [OpenClaw](https://github.com/openclaw/openclaw) para assistentes persistentes  - em particular a arquitetura SOUL.md/USER.md/MEMORY.md (renomeada para CORE.md/USER.md/MEMORY.md neste projeto) para dar aos agentes de IA identidade, memoria e continuidade.

---

## Licenca

[MIT](LICENSE)

---

## Contribuindo

Pull requests sao bem-vindos. Para mudancas grandes, abra uma issue primeiro.

1. Faca um fork
2. Crie sua branch (`git checkout -b feature/minha-feature`)
3. Commit (`git commit -m 'Adiciona minha feature'`)
4. Push (`git push origin feature/minha-feature`)
5. Abra um Pull Request

Atualize testes e documentacao conforme necessário.
