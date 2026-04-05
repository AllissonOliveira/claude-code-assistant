# Guia do Usuario

## Como conversar com o bot

Fale naturalmente. O bot entende portugues e responde como um assistente pessoal competente.

Exemplos:
- "Ve minha agenda de amanha"
- "Manda email pro Joao sobre o projeto"
- "Me lembra sexta as 9h de enviar o relatorio"
- "O que tinha nos emails de hoje?"
- "Marca reuniao com a equipe pra segunda 14h"

Nao precisa de comandos especiais. So mande mensagem como faria com uma pessoa.

---

## Mensagens de voz

Mande audio no Telegram e o bot transcreve automaticamente usando Whisper (local, sem nuvem). A transcricao vira texto e e processada normalmente.

---

## Lembretes

Peca naturalmente:
- "Me lembra amanha as 9h de ligar pro cliente"
- "Agenda lembrete pra sexta: revisar proposta"
- "Daqui 2 horas me avisa sobre a reuniao"

O bot confirma o agendamento com data, hora e resumo.

Para ver lembretes pendentes: `/memory`
Para buscar algo especifico: `/buscar <termo>`

---

## Mudando configuracoes

Fale naturalmente no chat:
- "Muda pro opus" ou "Usa o modelo haiku"
- "Desliga os avisos proativos"
- "Muda o intervalo do heartbeat pra 1 hora"

Tambem funciona via comandos:
- `/opus`, `/sonnet`, `/haiku` - trocar modelo
- `/intervalo` - configurar avisos proativos
- `/configurar` - menu de configuracoes

---

## Avisos proativos (Heartbeat)

O bot verifica periodicamente sua agenda e emails e avisa se tiver algo importante. Por padrao, verifica a cada 30 minutos entre 8h e 23h.

**Briefing matinal:** o primeiro aviso do dia (antes das 10h) inclui sua agenda completa, emails pendentes e lembretes do dia.

Para ajustar ou desligar:
- "Desliga os avisos" - para de enviar
- "So me avisa de manha e no fim do dia" - muda horarios
- `/intervalo` - menu de configuracao

---

## Comandos disponiveis

| Comando | O que faz |
|---|---|
| `/status` | Mostra estado da sessao, modelo, memorias |
| `/nova` | Inicia nova sessao (salva memoria antes) |
| `/modelo` | Mostra modelo atual |
| `/opus` `/sonnet` `/haiku` | Troca modelo do Claude |
| `/memory` | Lista ultimas memorias salvas |
| `/buscar <termo>` | Busca nas memorias |
| `/bg <tarefa>` | Executa tarefa em segundo plano |
| `/intervalo` | Configura avisos proativos |
| `/configurar` | Menu de configuracoes |
| `/contexto` | Mostra contexto da sessao |

---

## Como o bot lembra das coisas

O bot salva automaticamente:
- **Contatos** mencionados (nome, telefone, email)
- **Preferencias** que voce confirma ("gosto de respostas curtas")
- **Decisoes** importantes ("escolhemos o fornecedor X")
- **Padroes** de comportamento (horarios, temas recorrentes)
- **Tarefas pendentes** sem data ("preciso ligar pro Joao")

A cada 5 mensagens, o bot faz um checkpoint de memoria. Quando a sessao expira (3h sem uso), salva um resumo completo.

---

## Quando o bot pede confirmacao

O bot executa direto quando o pedido e claro e sem risco. Pede confirmacao quando:
- A acao e irreversivel (enviar email, deletar algo)
- Envolve outra pessoa (marcar reuniao, enviar mensagem)
- Ha ambiguidade real no pedido

---

## Corrigindo o bot

Se o bot errar, fale diretamente:
- "Errado, nao era isso"
- "Nao e assim que eu quero"
- "Para de fazer X"

O bot salva a correcao e nao repete o erro.

---

## FAQ

**Por que o bot manda mensagens sozinho?**
Sao avisos proativos (heartbeat) verificando agenda e emails. Desative com "desliga os avisos".

**Por que o bot esqueceu algo?**
A memoria e salva a cada 5 mensagens. Se o daemon caiu antes do checkpoint, informacoes recentes podem ser perdidas. Use `/buscar` para procurar nas memorias.

**Como saber qual modelo esta usando?**
Mande `/modelo` ou pergunte "qual modelo voce esta usando?".

**Posso mudar o modelo no meio da conversa?**
Sim. "Muda pro opus" ou `/opus`. A mudanca aplica na proxima mensagem.
