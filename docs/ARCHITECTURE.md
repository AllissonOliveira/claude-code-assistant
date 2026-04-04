# Arquitetura

Este documento descreve como o Claude Code Assistant funciona internamente.

---

## Visao Geral

O Claude Code Assistant é um daemon Python que faz a ponte entre o Telegram e o Claude Code CLI. Ele executa um loop de polling continuo na API do Telegram, processa mensagens atraves de um pipeline de 4 estagios (Router, Reasoning Gate, Execucao, Self-Review), mantendo memoria persistente entre sessoes.

```
Usuario (Telegram) → Daemon (Python) → Classificacao → Reasoning Gate
                                             ↓
                                        Execucao
                                       (Claude CLI)
                                             ↓
                                       Self-Review
                                             ↓
                                      Resposta
```

---

## Pipeline de Processamento de Mensagens

### 1. Router (Classificacao)

Toda mensagem recebida é classificada em um de cinco tipos:

```python
class MessageType(Enum):
    SIMPLE = "simple"         # Respostas rapidas (oi, obrigado, etc)
    QUESTION = "question"     # Perguntas abertas
    TASK = "task"             # Pedidos de acao (agenda, cria, analisa, etc)
    DESTRUCTIVE = "destructive"  # Acoes irreversiveis (envia, deleta, etc)
    MEMORY_QUERY = "memory_query" # Busca semantica (/buscar)
```

A classificacao é feita via regex patterns rapidos em `daemon.py`:

- `SIMPLE`: matches contra patterns como "ok", "boa", "valeu"
- `DESTRUCTIVE`: detecta "envia", "deleta", "apaga", "sobrescreve"
- `TASK`: detecta "agenda", "cria", "faz", "analisa", "verifica"
- `MEMORY_QUERY`: inicia com `/buscar`
- `QUESTION`: qualquer coisa que nao caia nas categorias acima

### 2. Reasoning Gate

Mensagens classificadas como `TASK` ou `DESTRUCTIVE` passam por um Reasoning Gate antes de serem executadas.

O gate executa uma analise previa que monta um "scratchpad" contendo:

```
ENTENDIMENTO: O que está sendo pedido, em uma frase.
DEPENDENCIAS: Que informações ou ferramentas são necessárias?
RISCOS: Algo pode dar errado? Sim/Não. Se sim, o que?
ABORDAGEM: Como resolver? Passos concretos.
CONFIANCA: Alta / Media / Baixa. Por que?
```

Se a confianca for **Baixa**, o gate responde com `CLARIFY: <pergunta precisa>` e a mensagem nao é executada. Caso contrario (`Alta` ou `Media`), termina com `PROCEED` e segue para Execucao.

Este mecanismo evita erros catastrophicos: deletar algo sem entender totalmente, enviar mensagem ao destino errado, etc.

### 3. Execucao

A mensagem é encaminhada para o **Claude CLI** via subprocess:

```bash
claude -p "<prompt>" --output-format json --add-dir <project_dir> \
  --model <model> [--resume <session_id>]
```

#### Injecao de Contexto

Quando uma sessao é nova (sem `session_id` ainda), o daemon monta um bloco de contexto:

1. **CORE.md**  - identidade, personalidade, estilo de raciocinio
2. **USER.md**  - perfil do usuario, preferencias, estilo de comunicacao
3. **MEMORY.md**  - fatos e decisoes de longo prazo
4. **memory/YYYY-MM-DD.md**  - notas do dia (se existirem)
5. **memory/YYYY-MM-DD.md (ontem)**  - notas do dia anterior (se existirem)
6. **[Turn Context]**  - informacoes especificas do turno atual (data/hora, lembretes pendentes, regras de comportamento)

Esse contexto é encapsulado em marcadores `[SESSION CONTEXT] ... [END CONTEXT]`. As instrucoes no CLAUDE.md dizem ao Claude para pular releitura de arquivos quando encontra esses marcadores.

#### Variáveis de Ambiente

A variavel `ANTHROPIC_API_KEY` é **explicitamente removida** do processo filho Claude. Isso evita conflitos com a autenticacao propria do Claude Code, que usa o mesmo arquivo de credenciais.

#### Retry com Backoff Exponencial

Se o Claude falhar (timeout, erro de API), o daemon retenta com backoff:

```python
retry_backoff_seconds: [5, 10, 30]  # 5s, 10s, 30s
```

Também detecta rate limits analisando stderr e respostas JSON de erro, com mensagens amigáveis para o usuario.

### 4. Self-Review

Antes de enviar a resposta, ela passa por uma auto-revisao que verifica:

1. **FACTUAL**  - há afirmacao sem certeza de que é verdadeira?
2. **IRREVERSIVEL**  - instrui acao que nao pode ser desfeita sem confirmacao explicita?
3. **COMPLETO**  - falta informacao que o usuario precisaria?

Se tudo está OK, responde `APPROVED` e a mensagem é enviada. Caso contrario, responde `REVISE: <problema>` e o ciclo volta para Claude corrigir.

---

## Como as Sessoes Funcionam

Sessoes fornecem continuidade conversacional dentro de uma unica janela de contexto do Claude.

### Ciclo de Vida

1. **Pre-aquecimento**  - Na inicializacao do daemon, se nao existir sessao, uma é criada com um prompt minimo para tornar a primeira mensagem real mais rapida.

2. **Retomada**  - Mensagens subsequentes usam `claude -p --resume <session_id>` para continuar a mesma conversa.

3. **Timeout**  - Se nao houver atividade por `session_timeout_hours` (padrao: 3), a sessao é arquivada em `sessions/` e resetada.

4. **Reset Manual**  - O comando `/nova` salva a memoria da sessao, arquiva, e inicia uma nova.

### Invocacao do Claude CLI

```bash
claude -p "<prompt>" --output-format json --add-dir <project_dir> --model <model> [--resume <session_id>]
```

**Detalhes importantes:**

- `--add-dir` dá ao Claude acesso ao diretório do projeto (CORE.md, USER.md, MEMORY.md, etc)
- `--output-format json` retorna saída estruturada com `session_id` para retomada
- `ANTHROPIC_API_KEY` é explicitamente removida do processo filho
- Lógica de retry com backoff exponencial trata falhas transitórias
- Detecção de rate limit analisa stderr e respostas JSON

---

## Sistema de Memoria

A memoria é o grande diferencial  - ela dá ao Claude continuidade entre sessoes e aprendizado sobre o usuario.

### Arquivos de Memoria

| Arquivo | Atualizado Por | Leitura | Proposito |
|---|---|---|---|
| **CORE.md** | Usuario (manual) | Cada sessao | Identidade, personalidade, estilo de raciocinio do assistente |
| **USER.md** | Claude (checkpoint) | Cada sessao | Perfil do usuario, preferencias, contexto, responsabilidades |
| **MEMORY.md** | Claude (checkpoint) | Cada sessao | Fatos de longo prazo, decisoes importantes, licoes aprendidas |
| **CLAUDE.md** | Usuario (manual) | Cada sessao | Prompt de sistema, ferramentas, protocolo de resposta |
| **memory/YYYY-MM-DD.md** | Claude (auto) | Proxima sessao | Resumo diario das conversas |
| **memory/YYYY-MM-HHMM.md** | Claude (manual) | Proxima sessao | Resumo de sessao salvo via /nova |

### Checkpoint de Memoria

A cada 5 mensagens (ou ao final de sessao), o daemon:

1. Extrai informacoes novas sobre o usuario: **contatos** (telefones, emails), **preferencias** (regras de comportamento), **decisoes** (fatos importantes), **tarefas pendentes** (com datas).

2. Classifica cada item como:
   - `CONFIRMED`  - o usuario disse explicitamente, sem ambiguidade
   - `INFERRED`  - voce deduziu a partir do contexto. Pode estar errado.

3. Persiste em arquivos:
   - USER.md recebe **contatos CONFIRMED** e **preferencias CONFIRMED**
   - MEMORY.md recebe **decisoes CONFIRMED** e **fatos confirmados**
   - INFERRED é marcado com comentario indicando confiança ("pode estar errado")

### Consolidacao Automatica de Memoria

Quando há >30 notas em `memory/`, o daemon:

1. Identifica as 10 notas mais antigas
2. Combina em um bloco coeso
3. Chama o Claude para resumir em `memory/YYYY-MM-summary.md`
4. Deleta as notas originais

Isso mantém a pasta de memoria organizada e evita contexto duplicado.

### Post-Compaction Refresh

Apos consolidacao, o daemon re-injeta "standing orders" (preferencias recorrentes) no inicio da proxima sessao, garantindo que o Claude continue seguindo as mesmas regras.

---

## Como o Heartbeat Funciona

O recurso de heartbeat proativo verifica periodicamente se há algo que o usuario precisa saber.

### Fluxo

1. A cada `heartbeat_interval_minutes` (padrao: 30), o daemon envia um prompt especial para o Claude
2. O prompt inclui context turn com data/hora atual
3. Claude verifica emails urgentes nao lidos no Gmail e eventos proximos no Google Calendar (usando ferramentas MCP)
4. Se algo precisa atencao, Claude envia uma notificacao para o Telegram
5. Se nada relevante, Claude responde com `HEARTBEAT_OK` e daemon continua silenciosamente

### Restricoes

- Heartbeat so roda quando há sessao ativa
- Desative setando `heartbeat_interval_minutes` como 0
- Mensagens de heartbeat sao marcadas com prefixo `[HEARTBEAT]` para o usuario diferenciar

---

## Como a Transcricao de Audio Funciona

1. **Telegram envia áudio**  - arquivo `.ogg` via API Bot
2. **Daemon baixa**  - via API `getFile` do Telegram para `audio/temp/`
3. **Converte via ffmpeg**  - `ffmpeg -i input.ogg -ar 16000 -ac 1 output.wav`
4. **Transcreve com faster-whisper**  - subprocess: `from faster_whisper import WhisperModel`
5. **Fallback para Whisper CLI**  - se faster-whisper falhar: `whisper <arquivo> --model <modelo> --language pt --output_format txt`
6. **Encaminha texto**  - resultado é passado para `handle_text()` normalmente
7. **Limpa temporários**  - deleta áudio e transcrição apos processamento

### Vantagens de faster-whisper

- **5-10x mais rápido** que Whisper original
- **Roda no CPU** (nao precisa GPU)
- **Detecta idioma automaticamente**
- **Saída estruturada** (timestamps, confianca)

**Modelo padrão:** `base` (74MB). Opcoes: `base`, `small` (244MB), `medium` (1.4GB), `large` (2.9GB).

---

## Como a Busca Semantica Funciona (/buscar)

O comando `/buscar <termo>` permite encontrar informacoes na memoria sem precisar lembrar de datas ou palavras exatas.

### Fluxo

1. Usuario digita `/buscar decisao campanha`
2. Daemon coleta ultimas 7 dias de notas em `memory/YYYY-MM-DD.md`
3. Se houver matches textuais (contendo "decisao" ou "campanha"), retorna com contexto
4. Caso contrario, passa todos os textos para Claude avaliar
5. Claude usa "semantic search"  - entende o significado, nao só palavras-chave
6. Retorna trechos relevantes com contexto

Este mecanismo é mais poderoso que regex porque entende **significado**, nao apenas **palavras**.

---

## Estrutura de Arquivos

```
claude-code-assistant/
├── daemon.py                    # Ponto de entrada standalone (~2700 linhas)
├── claude_assistant/            # Wrapper para entry point do pacote
│   ├── __init__.py
│   └── daemon.py                # Delega para daemon.py da raiz
├── setup_wizard/                # Configuracao interativa
│   ├── wizard.py                # Orquestrador principal (4 etapas)
│   ├── profile_builder.py       # Coleta perfil via documento ou perguntas
│   ├── mcp_installer.py         # Selecao e instalacao de MCPs
│   ├── telegram_guide.py        # Guia de criacao do bot no Telegram
│   ├── service_installer.py     # LaunchAgent (macOS) / systemd (Linux)
│   └── templates/
│       ├── __init__.py          # Templates dos .md gerados
│       ├── BOOTSTRAP.md
│       ├── HEARTBEAT.md
│       └── PROFILE_TEMPLATE.md
├── config.json                  # Configuracao runtime (gitignored)
├── config.example.json          # Exemplo (commitado)
├── state.json                   # Estado da sessao (gitignored)
├── CORE.md                      # Identidade do assistente (gitignored)
├── USER.md                      # Perfil do usuario (gitignored)
├── MEMORY.md                    # Memoria de longo prazo (gitignored)
├── CLAUDE.md                    # Prompt de sistema (gitignored)
├── BEHAVIOR.md                  # Regras de comportamento (gitignored)
├── memory/                      # Notas diarias (gitignored)
├── sessions/                    # Metadados de sessoes arquivadas (gitignored)
├── audio/temp/                  # Arquivos temporários (gitignored)
├── logs/                        # Logs do daemon (gitignored)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── MCP_INTEGRATIONS.md
│   └── examples/
│       ├── CLAUDE.md
│       ├── CORE.md
│       └── USER.md
└── LICENSE (MIT)
```

---

## Seguranca de Threads

O daemon usa threading para paralelismo sem bloqueio:

- **Indicadores de digitacao**  - threads em background enviam acao "typing" a cada 4 segundos enquanto Claude processa
- **Tarefas em background** (`/bg`)  - rodam em daemon threads, nao bloqueiam a loop principal
- **Persistencia de estado**  - protegida por `threading.Lock` com escrita atomica de arquivos (escreve em `.tmp`, depois renomeia)

O estado é recarregado do disco a cada ciclo do loop, entao threads em background que modificam estado nao causam conflitos.

---

## Padroes de Qualidade

### Feito certo na primeira vez

O assistente segue uma filosofia "feito certo na primeira vez":

1. **Reasoning Gate**  - analise previa antes de acoes irreversiveis
2. **Self-Review**  - verificacao de factualidade, reversibilidade, completude
3. **Memoria CONFIRMED/INFERRED**  - separa fatos confirmados de suposicoes
4. **Confirmacao de acao**  - antes de deletar, enviar, sobrescrever

Esta abordagem reduz erros e rebuild de contexto.

---

## Fluxo Completo de Exemplo

**Cenário:** Usuario envia "/bg analisa as ultimas 3 campanhas de Meta Ads"

1. **Router**  - classifica como `TASK` (acao pesada)
2. **Turn Context**  - injeta data/hora, lembretes pendentes, BEHAVIOR.md
3. **Reasoning Gate**  - analisa: precisa de ferramentas Meta Ads MCP, vai demorar, sem risco. Resultado: `PROCEED`
4. **Execucao (thread bg)**  - chama Claude com contexto + ferramentas MCP
5. Claude acessa Meta Ads MCP, puxa insights das 3 campanhas, analisa
6. **Self-Review**  - valida se dados estao corretos, resposta é completa
7. **Resultado**  - envia mensagem para Telegram com analise
8. **Checkpoint**  - se >30 min ou >5 mensagens passaram, salva memoria
