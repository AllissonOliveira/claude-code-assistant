# Claude Code Assistant

## Primeira Configuracao

Se `config.json` NAO existe neste diretorio, o projeto precisa ser configurado.

Primeiro instale as dependencias:

```
pip install -e .
```

Depois inicie a configuracao interativa usando o slash command `/setup`. Ele guia por tudo: verificacao do sistema, perfil do usuario, criacao do bot no Telegram, integracoes MCP e instalacao como servico. Siga as instrucoes do `/setup` passo a passo, fazendo uma pergunta por vez ao usuario.

Alternativa (terminal direto): o usuario pode rodar `claude-assistant-setup` no terminal fora do Claude Code.

IMPORTANTE: Nao tente criar os arquivos (CORE.md, USER.md, config.json, etc.) manualmente. O processo de configuracao gera tudo automaticamente a partir dos templates e das respostas do usuario.

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
