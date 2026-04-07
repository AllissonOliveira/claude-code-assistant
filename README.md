# Claude Code Assistant

**Transforme o Claude em um assistente pessoal de IA persistente que vive no seu Telegram.**

Ele lembra do contexto entre sessoes, usa ferramentas MCP para acessar sua agenda, email, WhatsApp, CRM e muito mais. Roda como daemon em segundo plano no seu Mac (ou Linux).

---

## Funcionalidades

- **Memoria persistente entre sessoes** - CORE.md + USER.md + MEMORY.md mantem o contexto vivo entre conversas
- **Identidade personalizada** - CORE.md define como o assistente pensa e raciocina
- **Toda inteligencia no Claude** - o daemon e infraestrutura, o Claude decide tudo (classificacao, risco, confirmacao, execucao)
- **Mensagens de voz via transcricao local** - faster-whisper + ffmpeg, privado, sem nuvem
- **Integracoes MCP** - Google Calendar, Gmail, WhatsApp, HubSpot, Notion, Puppeteer e mais
- **Gerenciamento de sessoes** com timeout automatico e pre-aquecimento
- **Briefing matinal** - resumo completo do dia (agenda, emails, pendencias) no primeiro aviso
- **Notificacoes proativas via heartbeat** - verifica email e agenda periodicamente
- **Extracao de memoria com classificacao** - fatos CONFIRMED e inferencias INFERRED sao separados
- **Deteccao de padroes de comportamento** - o bot aprende horarios, temas e estilo do usuario
- **Correcoes persistentes** - quando voce corrige o bot, ele salva a regra e nao repete o erro
- **Consolidacao automatica de memoria** - notas e MEMORY.md sao comprimidos quando crescem
- **Configuracao por linguagem natural** - "muda pro opus", "desliga os avisos" direto no chat
- **Busca semantica** - /buscar para acessar memoria
- **Execucao de tarefas em segundo plano** - /bg para trabalhos pesados
- **Troca de modelo em tempo real** - por comando ou linguagem natural
- **Inicio automatico como LaunchAgent** (macOS) ou servico systemd (Linux)

---

## Comeco Rapido

### Via instalador (recomendado)

```bash
git clone https://github.com/AllissonOliveira/claude-code-assistant
cd claude-code-assistant
./install.sh
```

O instalador faz tudo automaticamente:
1. Instala dependencias (Python, Node, Go, uv, ffmpeg)
2. Instala e configura o Claude Code CLI
3. Configura seu perfil e preferencias
4. Cria o bot no Telegram
5. Instala todas as integracoes MCP (WhatsApp, Calendar, Gmail, etc.)
6. Instala como servico do sistema

### Manual (desenvolvimento)

```bash
pip install -e .
python daemon.py
```

---

## Como Funciona

```
┌──────────┐     ┌──────────────┐     ┌──────────────────┐
│ Telegram │◄───►│   Daemon     │◄───►│   Claude CLI     │
│  (voce)  │     │ (infraestr.) │     │  (inteligencia)  │
└──────────┘     └──────────────┘     └──────────────────┘
                       │                       │
                  ┌────┴────┐           ┌──────┴────────┐
                  │ Sistema │           │   MCP Tools   │
                  │   de    │           │               │
                  │ Memoria │           │ - Calendar    │
                  │         │           │ - Gmail       │
                  │CORE.md  │           │ - WhatsApp    │
                  │USER.md  │           │ - HubSpot     │
                  │MEMORY.md│           │ - Notion      │
                  └─────────┘           │ - Puppeteer   │
                                        └───────────────┘
```

### Principio Arquitetural

O daemon e APENAS infraestrutura: recebe mensagens, injeta contexto, envia respostas, salva memoria. Toda decisao inteligente e do Claude: classificacao, analise de risco, confirmacao, execucao e revisao acontecem internamente no raciocinio do Claude.

### Fluxo de Processamento

```
Mensagem do Usuario (texto, voz, foto, documento)
        ↓
  [ Daemon recebe ]
  (polling Telegram, transcricao de audio se necessario)
        ↓
  [ Contexto injetado ]
  (CORE.md + CLAUDE.md + USER.md + BEHAVIOR.md + MEMORY.md
   + notas recentes + conv-log + data/hora + lembretes)
        ↓
  [ Claude processa ]
  (classifica, analisa risco, confirma se necessario,
   executa com ferramentas MCP, revisa antes de responder)
        ↓
  [ Daemon entrega ]
  (envia resposta ao Telegram, registra no conv-log)
        ↓
  [ Checkpoint de memoria ]
  (a cada 5 mensagens, extrai fatos e padroes)
```

---

## Sistema de Memoria

| Arquivo | Quando e Lido | Quando e Atualizado | Proposito |
|---|---|---|---|
| **CORE.md** | Inicio de cada sessao | Manualmente pelo usuario | Identidade, personalidade, protocolo de raciocinio |
| **CLAUDE.md** | Inicio de cada sessao | Manualmente pelo usuario | Regras operacionais (Calendar, lembretes, config) |
| **USER.md** | Inicio de cada sessao | Automaticamente via checkpoint | Perfil do usuario: cargo, contatos, preferencias |
| **BEHAVIOR.md** | Inicio de cada sessao + heartbeat | Automaticamente quando usuario corrige o bot | Regras de comportamento e correcoes |
| **MEMORY.md** | Inicio de cada sessao | Automaticamente via checkpoint | Fatos, decisoes, padroes, pendencias |

Alem disso:
- **memory/YYYY-MM-DD.md** - notas diarias capturando decisoes, tarefas, contexto
- **memory/conv-YYYY-MM-DD.md** - log bruto de conversas
- **Consolidacao automatica** - MEMORY.md e comprimido quando passa de 15KB, notas antigas sao resumidas quando passam de 30 arquivos

### Checkpoint de Memoria

A cada 5 mensagens (ou ao final de sessao), o daemon:
1. Pede ao Claude para extrair informacoes novas: contatos, preferencias, decisoes, padroes, tarefas
2. Classifica cada item como CONFIRMED (dito explicitamente) ou INFERRED (deduzido)
3. Atualiza USER.md (contatos e preferencias) e MEMORY.md (decisoes, padroes, pendencias)
4. Marca no conv-log ate onde processou para nao duplicar

### Correcoes Automaticas

Quando voce corrige o bot ("errado", "nao era isso", "para de fazer X"), o daemon detecta e salva a correcao em BEHAVIOR.md com a regra e o contexto. O bot nao repete o erro.

---

## Comandos do Telegram

| Comando | Descricao |
|---|---|
| `/status` | Mostra sessao atual, modelo, contagem de memorias |
| `/nova` | Nova sessao (salva memoria antes) |
| `/modelo` | Mostrar modelo atual |
| `/opus` `/sonnet` `/haiku` | Trocar modelo do Claude |
| `/memory` | Listar ultimas memorias salvas |
| `/buscar <termo>` | Buscar semanticamente nas memorias |
| `/bg <tarefa>` | Executar tarefa em segundo plano |
| `/intervalo` | Configurar intervalo de heartbeat |
| `/configurar` | Abrir menu de configuracao |

**Dica:** Voce tambem pode mudar configuracoes por linguagem natural: "muda pro opus", "desliga os avisos proativos", "muda o heartbeat pra 1 hora".

Para um guia completo de uso, veja [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

---

## Requisitos

- **Python 3.12+**
- **Claude Code CLI** - instalado e autenticado ([guia](https://docs.anthropic.com/en/docs/claude-cli))
- **Conta no Telegram** - com bot criado via [@BotFather](https://t.me/BotFather)
- **Opcional:** faster-whisper para transcricao local de audio
- **Opcional:** ffmpeg para conversao de audio

### Instalacao de Dependencias (macOS)

```bash
brew install python@3.12
brew install ffmpeg
pip install faster-whisper
```

### Instalacao de Dependencias (Linux)

```bash
sudo apt-get install python3.12
sudo apt-get install ffmpeg
pip install faster-whisper
```

---

## Configuracao

Apos rodar o assistente de configuracao, seu `config.json` ficara assim:

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
systemctl --user enable claude-assistant.service
systemctl --user start claude-assistant.service
systemctl --user status claude-assistant.service
journalctl --user -u claude-assistant.service -f
```

---

## Seguranca

Este projeto acessa dados pessoais e credenciais sensiveis. Algumas precaucoes:

- **config.json** contem seu token Telegram. O wizard configura permissoes restritas (0o600), mas verifique: `chmod 600 config.json`
- **MEMORY.md e USER.md** contem dados pessoais (contatos, preferencias, decisoes). Sao protegidos pelo `.gitignore` e nunca vao pro GitHub
- **Use Full Disk Encryption**: FileVault (macOS) ou LUKS (Linux)
- **Nao execute em servidores compartilhados**: o bot tem acesso a emails, agenda e mensagens
- **Token do Telegram**: se vazar, revogue imediatamente via @BotFather e gere um novo

---

## Documentacao

- [Guia do Usuario](docs/USER_GUIDE.md) - como usar o bot no dia a dia
- [Arquitetura](docs/ARCHITECTURE.md) - detalhes tecnicos
- [Integracoes MCP](docs/MCP_INTEGRATIONS.md) - servicos disponiveis

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
