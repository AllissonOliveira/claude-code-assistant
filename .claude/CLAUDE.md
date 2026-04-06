# Claude Code Assistant

## Primeira Configuracao

Se `config.json` NAO existe neste diretorio, o projeto precisa ser configurado.

Informe ao usuario para rodar o instalador no terminal:

```
./install.sh
```

O script faz tudo automaticamente: instala dependencias, Claude Code CLI, pacote do bot, e abre o wizard de configuracao interativo.

IMPORTANTE: O instalador e interativo e NAO funciona dentro do Claude Code. O usuario DEVE rodar no terminal diretamente.

Alternativa para configuracao dentro do Claude Code: siga as instrucoes do arquivo `.claude/commands/setup.md` diretamente.

---

## Projeto Ja Configurado

Se `config.json` existe, o projeto esta pronto.

### Estrutura

- `daemon.py` — o daemon Telegram (self-contained, ~2700 linhas). Toda a logica do bot esta aqui.
- `config.json` — configuracao de runtime (token, modelo, intervalos). Gerado pelo wizard.
- `CORE.md` — identidade do bot e protocolo de raciocinio. Gerado pelo wizard.
- `USER.md` — perfil do usuario. Atualizado automaticamente pelo daemon.
- `BEHAVIOR.md` — regras de comportamento e correcoes. Atualizado pelo daemon.
- `MEMORY.md` — memoria de longo prazo. Atualizado pelo daemon.
- `HEARTBEAT.md` — criterios para verificacoes proativas. Gerado pelo wizard.
- `CLAUDE.md` (raiz) — instrucoes operacionais do bot. Gerado pelo wizard.

### Arquitetura

O daemon e APENAS infraestrutura: recebe mensagens do Telegram, injeta contexto, chama o Claude CLI (`claude -p --resume`), e envia respostas. Toda inteligencia (classificacao, risco, execucao) e do Claude.

### Executar

```
python daemon.py
```

Ou via LaunchAgent (macOS) / systemd (Linux), configurados pelo wizard.

### Documentacao

- `docs/ARCHITECTURE.md` — detalhes tecnicos
- `docs/USER_GUIDE.md` — guia do usuario
- `docs/MCP_INTEGRATIONS.md` — integracoes disponiveis
