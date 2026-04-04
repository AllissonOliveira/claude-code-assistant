# HEARTBEAT.md — Verificação Proativa

Este arquivo define o que verificar, como julgar urgência e como responder nos heartbeats automáticos.
Você pode e deve atualizar este arquivo quando aprender o que me interessa ou não interessa nos avisos.

---

## O que verificar

### 1. Google Calendar
- Eventos começando nas próximas 60 minutos
- SE o evento já começou há mais de 15 minutos: não avise (já passou)
- SE o evento é rotineiro e recorrente sem nada especial: pode omitir se achar irrelevante

### 2. Gmail
- Emails recebidos HOJE que requerem ação do usuário HOJE
- "Urgente" = cliente esperando resposta, prazo próximo, problema que trava algo, pagamento/cobrança
- Emails informativos, newsletters, notificações automáticas: ignore
- Emails de dias anteriores: ignore (já foram processados ou não são urgentes)

### 3. Meta Ads (quando relevante — não verificar todo heartbeat, só se algo mudar)
- Campanha com ROAS caindo mais de 20% em relação à média dos 7 dias anteriores
- Gasto diário acima de 150% do budget diário esperado
- Campanha pausada inesperadamente (não por agendamento)
- CPA acima de 2x o target configurado

---

## Critério para enviar notificação

A informação precisa ser:
- (a) **nova** — não foi enviada no heartbeat anterior
- (b) **time-sensitive** — precisa de ação hoje ou nas próximas horas

Se não atender os dois critérios: responda APENAS `HEARTBEAT_OK`

---

## Formato quando há algo relevante

- Máximo 3 linhas
- Sem introduções ("Olá!", "Bom dia!", "Verificação concluída...")
- Direto ao ponto: o que é, quando é, o que precisa fazer
- Exemplos bons:
  - "Reunião com Bruno em 40 min (10h00)"
  - "Email de Ana Beatriz: cliente bloqueado, aguarda resposta"
  - "Campanha Verão: ROAS caiu 28% hoje vs. semana passada"

---

## Palavra-chave de silêncio

Quando não há nada relevante: responda APENAS a palavra `HEARTBEAT_OK` (sem mais nada).

---

## Aprendizados (atualize conforme necessário)

- [espaço reservado — atualize quando aprender o que interessa ou não ao usuário]
