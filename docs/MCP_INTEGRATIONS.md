# Integracoes MCP

O Claude Code Assistant estende as capacidades do Claude atraves do Model Context Protocol (MCP)  - um padrao aberto para conectar modelos de IA a ferramentas e fontes de dados externas.

---

## O Que Sao MCPs?

MCP (Model Context Protocol) é um protocolo que permite ao Claude interagir com servicos externos. Cada servidor MCP expoe um conjunto de ferramentas que o Claude pode chamar durante uma conversa  - ler agenda, enviar email, consultar banco de dados, etc.

Pense nos MCPs como "plugins" para o Claude. O assistente nao apenas responde perguntas  - ele executa acoes.

---

## Como o Claude Code Os Utiliza

O Claude Code CLI tem suporte nativo a servidores MCP. Quando voce configura uma integracao MCP atraves do claude.ai (ou localmente via `.claude.json`), todas as ferramentas daquele servidor ficam automaticamente disponiveis para o Claude durante conversas.

O daemon do Claude Code Assistant passa `--add-dir <project_dir>` em toda chamada ao CLI, o que dá ao Claude acesso ao diretório do projeto e sua configuracao MCP. O Claude decide autonomamente quais ferramentas usar com base no pedido do usuario.

**Exemplos:**

- "O que tem na minha agenda hoje?" → Claude chama `gcal_list_events`
- "Rascunha uma resposta pro ultimo email do Joao" → Claude chama `gmail_search_messages`, depois `gmail_create_draft`
- "Como ta a campanha do Meta?" → Claude chama `meta_ads_get_campaigns`, depois `get_insights`
- "Encontra um horario segunda-feira pros tres" → Claude chama `gcal_find_free_slots`

---

## Integracoes Disponveis

### Google Calendar

Acesse seus eventos de agenda, encontre horarios livres, crie/atualize/delete eventos.

**Configuracao:** Conecte via [claude.ai](https://claude.ai) → Configuracoes → Integracoes → Google Calendar.

**Ferramentas disponiveis:**
- Listar eventos com opcoes de filtro por data/intervalo
- Encontrar horarios livres e slots para reunioes
- Criar, atualizar, deletar eventos
- Responder a convites de eventos
- Gerenciar lembretes

**Nota:** O Claude Code Assistant esta configurado para usar Google Calendar no heartbeat proativo  - verifica eventos proximos a cada 30 minutos.

---

### Gmail

Leia emails, pesquise mensagens, crie rascunhos.

**Configuracao:** Conecte via [claude.ai](https://claude.ai) → Configuracoes → Integracoes → Gmail.

**Ferramentas disponiveis:**
- Pesquisar e ler mensagens e threads
- Criar rascunhos de email
- Listar labels e filtros
- Obter informacoes do perfil
- Marcar como lido/nao lido

**Nota:** Usado no heartbeat para verificar emails urgentes nao lidos.

---

### Meta Ads

Gerencie campanhas de publicidade no Facebook/Instagram  - veja performance, crie campanhas, gerencie criativos.

**Configuracao:** Instale o servidor MCP do Meta Ads localmente:

```bash
# Siga as instrucoes no repositorio official do servidor MCP meta-ads
# Configure em ~/.claude.json ou .claude.json no nível do projeto
```

**Ferramentas disponiveis:**
- Obter campanhas, conjuntos de anuncios, anuncios e seus detalhes
- Ver insights e metricas de performance (ROAS, CPA, CTR, etc.)
- Criar e atualizar campanhas, conjuntos de anuncios e anuncios
- Pesquisar no Ads Archive, interesses, demografias e localizacoes
- Fazer upload de imagens e videos de anuncios

---

### HubSpot

Acesso ao CRM  - contatos, negocios, empresas, engajamentos, workflows.

**Configuracao:** Conecte via [claude.ai](https://claude.ai) → Configuracoes → Integracoes → HubSpot, ou instale localmente:

```bash
# Instale o servidor MCP do HubSpot
# Configure com sua chave de API
```

**Ferramentas disponiveis:**
- Pesquisar, listar, criar e atualizar objetos (contatos, negocios, empresas)
- Gerenciar associacoes entre objetos
- Criar e atualizar engajamentos (notas, ligacoes, emails)
- Listar e gerenciar propriedades e workflows
- Buscar por criterios customizados

---

### Notion

Acesse paginas, databases e documentos do Notion.

**Configuracao:** Conecte via [claude.ai](https://claude.ai) → Configuracoes → Integracoes → Notion.

**Ferramentas disponiveis:**
- Pesquisar paginas e databases
- Criar, atualizar e duplicar paginas
- Criar databases e visualizacoes (table, kanban, etc)
- Gerenciar comentarios
- Buscar conteudo de paginas

---

### Supabase

Acesso ao banco de dados  - executar queries SQL, gerenciar tabelas, deploy de edge functions.

**Configuracao:** Conecte via [claude.ai](https://claude.ai) → Configuracoes → Integracoes → Supabase.

**Ferramentas disponiveis:**
- Executar queries SQL em banco de dados
- Listar tabelas e gerenciar migrations
- Fazer deploy de edge functions
- Gerenciar branches e projetos
- Gerar tipos TypeScript

---

### Puppeteer

Automacao de navegador  - navegar em paginas, tirar screenshots, preencher formularios.

**Configuracao:** Instale o servidor MCP do Puppeteer localmente:

```bash
npm install -g @anthropic/mcp-puppeteer
```

**Ferramentas disponiveis:**
- Navegar para URLs
- Clicar, preencher, passar o mouse e selecionar elementos
- Tirar screenshots
- Executar JavaScript na pagina
- Verificar elementos e conteudo

---

### WhatsApp (via whatsapp-bridge)

Leia e envie mensagens do WhatsApp atraves de uma ponte local.

**Configuracao:** Requer servidor MCP de ponte WhatsApp local:

```bash
# Instale e configure o servidor MCP whatsapp-bridge
# Autentique com sua conta do WhatsApp via QR code
```

**Ferramentas disponiveis:**
- Listar chats e mensagens
- Enviar mensagens de texto, audio e arquivos
- Pesquisar contatos
- Obter contexto de chats e mensagens
- Baixar midia (fotos, videos, documentos)

---

## Como Adicionar MCPs

### Via claude.ai (hospedados na nuvem)

1. Vá para [claude.ai](https://claude.ai) → Configuracoes → Integracoes
2. Procure pela integracao desejada
3. Conecte e autorize o acesso
4. As ferramentas ficam disponiveis automaticamente no Claude Code CLI

### Servidores MCP Locais

1. Instale o pacote do servidor MCP (geralmente via npm ou pip):

```bash
npm install -g @example/mcp-server
```

2. Adicione a configuracao em `~/.claude.json` ou `.claude.json` no nível do projeto:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "@example/mcp-server"],
      "env": {
        "API_KEY": "sua-chave-api-aqui"
      }
    }
  }
}
```

3. Reinicie o daemon do Claude Code Assistant:

```bash
# Se usando LaunchAgent (macOS)
launchctl unload ~/Library/LaunchAgents/com.user.claude-assistant.plist
launchctl load ~/Library/LaunchAgents/com.user.claude-assistant.plist

# Se usando systemd (Linux)
systemctl --user restart claude-assistant.service

# Se executando manualmente
# Simplesmente reinicie python daemon.py
```

4. O Claude agora tem acesso a todas as ferramentas do novo servidor

### Construindo um Servidor MCP Customizado

Se voce precisa que o Claude acesse um servico que nao tem servidor MCP existente, construa um:

```bash
npm create @anthropic/mcp-server my-custom-server
```

Depois siga os passos acima para integrar ao seu projeto.

A especificacao completa do MCP está em [modelcontextprotocol.io](https://modelcontextprotocol.io).

---

## Priorizacao de Integracoes

### Essencial (comecam aqui)

- **Google Calendar**  - agenda (heartbeat usa isso)
- **Gmail**  - emails (heartbeat usa isso)

### Recomendado

- **Notion**  - documentacoes e databases
- **Puppeteer**  - automacao de navegador

### Opcional (case-specific)

- **Meta Ads**  - se trabalha com publicidade
- **HubSpot**  - se usa CRM
- **Supabase**  - se precisa banco de dados
- **WhatsApp**  - se integra com WhatsApp

---

## Troubleshooting

### "Ferramenta nao disponivel"

**Causa:** MCP nao esta registrado ou configuracao está incorreta.

**Solucao:**
1. Verifique se MCP está listado em claude.ai ou ~/.claude.json
2. Reinicie o daemon: `systemctl --user restart claude-assistant.service`
3. Teste manualmente: `claude -p "use a ferramenta X" --add-dir .`

### "Autenticacao falhou"

**Causa:** Chave de API expirou ou permissoes insuficientes.

**Solucao:**
1. Reconecte via claude.ai ou atualize API key em ~/.claude.json
2. Verifique permissoes do servico (ex: Gmail precisa "enviar emails")
3. Reinicie daemon

### "Timeout ao chamar ferramenta"

**Causa:** Servico externo fora ou lento.

**Solucao:**
1. Verifique status do servico
2. Aumentar timeout (se configuravel)
3. Usar ferramenta alternativa se disponivel
