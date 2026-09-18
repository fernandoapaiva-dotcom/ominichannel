# Vigia de Banco - Softsystem (Firebird)

Programa que roda no computador da loja, consulta **só leitura** o banco Firebird do
Softsystem (Servweld e Centro-Oeste) a cada 20 segundos, detecta eventos novos na aba
"Eventos" de qualquer O.S., e envia os dados automaticamente para o sistema Ominichannel
disparar as mensagens certas pro cliente no WhatsApp - sem precisar ler PDF nenhum.

**Este vigia nunca escreve nada no banco do Softsystem** - todas as consultas usam
transação explicitamente somente-leitura.

## O que cada tipo de evento dispara

| Evento no Softsystem              | O que acontece no WhatsApp do cliente |
|------------------------------------|----------------------------------------|
| ENTRADA                            | Avisos da natureza da O.S. (orçamento/garantia/locação) + PDF, após confirmação |
| ORC ENV/ AGUARD APROVACAO          | Envia o PDF do orçamento + pergunta de aprovação |
| ORC ENV/ APROVADO / N APROV        | Avisa o grupo "SERV - Solicitação de O.S." e o técnico responsável |
| Avaliação, Execução, Aguard. Retirada, Finalizada, Aguard. Peça, Sem Conserto, Não Autorizada, Sem Defeito, Desmch/Sucateado | Aviso simples de progresso (texto editável na tela de Automações do sistema) |

## Instalação (um clique, por estação)

1. Copie esta pasta inteira (`os_db_watcher`) para o computador, por exemplo em
   `C:\OminichannelDbWatcher\`.
2. Confira o `config.json` - já vem com a chave de API, os caminhos do Firebird e o
   usuário/senha. Só ajuste se algo for diferente nessa estação.
3. Clique com o **botão direito** em `install.bat` → **"Executar como administrador"**.
4. O instalador cuida do resto sozinho (Python, dependências, início automático).
5. Confira `db_watcher.log` - deve aparecer "Vigia de banco iniciado."

## Importante: primeira execução

Na primeira vez que roda em cada estação, o vigia **não processa nada do passado** - ele
marca a data/hora atual como ponto de partida e só reage a eventos *novos* a partir daí.
Isso evita mandar mensagem retroativa pra centenas de O.S. antigas.

## Testar

Abra uma O.S. de teste no Softsystem (ou mude o "Tipo de Evento" de uma existente) - em
poucos segundos (até 20s do ciclo + o tempo de digitação simulada) deve chegar a mensagem
no WhatsApp do cliente, e uma linha "OK" deve aparecer em `db_watcher.log`.

## Desinstalar

Rode `uninstall.bat`. Isso só desliga o início automático - o ambiente Python instalado
continua pronto pra quando quiser ligar de novo.

## Em caso de problema

- Confira `db_watcher.log` - toda tentativa fica registrada ali.
- **Erro de conexão com o banco**: confira se `192.168.15.16` está acessível dessa estação
  e se usuário/senha no `config.json` estão certos.
- **"HTTP 401"**: a chave de API está errada.
- Se um evento falhar ao enviar, o vigia tenta de novo no próximo ciclo (não perde nada) -
  mas também não avança para os próximos eventos até esse specific resolver, então um erro
  persistente trava a fila. Fique de olho no log se um "FALHA" aparecer repetidamente.
- O arquivo `state.json` guarda até onde o vigia já processou - apague-o (com o vigia
  parado) se precisar reprocessar tudo de novo a partir de agora.
