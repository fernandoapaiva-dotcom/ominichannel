# Vigia do Softsystem (banco Firebird + pastas de PDF)

Programa que roda no computador da loja e liga o **Softsystem** ao **Ominichannel**.
Ele é o único programa que precisa ficar instalado na loja - dispara sozinho os avisos
de WhatsApp para o cliente sempre que uma O.S. é aberta ou muda de estágio.

Faz duas coisas ao mesmo tempo, no mesmo processo:

1. **Vigia o banco** - consulta o Firebird do Softsystem (Servweld e Centro-Oeste) a cada
   20 segundos, **somente leitura**, procurando eventos novos na aba "Eventos" de qualquer
   O.S.. É o gatilho principal: o aviso ao cliente sai assim que o evento é salvo, sem
   esperar PDF nenhum.
2. **Vigia as pastas de PDF** (`ABERTURA` e `ORCAMENTO`) - quando um PDF novo aparece, pega
   o número da O.S. pelo **nome do arquivo** (`1934.pdf` -> O.S. 1934), consulta o banco
   pelos dados certos (cliente, telefone, equipamento) e entrega o PDF. Não lê texto de
   dentro do PDF.

**Nunca escreve nada no banco do Softsystem** - toda consulta usa transação explicitamente
somente-leitura e conexão sem disparar triggers do banco.

> Este programa **substitui** o antigo `tools/os_folder_watcher/`. Nunca rode os dois ao
> mesmo tempo (ver "Em caso de problema").

## O que cada evento dispara

| Evento no Softsystem              | O que acontece no WhatsApp do cliente |
|------------------------------------|----------------------------------------|
| ENTRADA                            | Saudação + recebimento do equipamento (com nº da O.S.) + termos do tipo da O.S. + pedido de confirmação. Depois do "Sim", chega o PDF |
| ORC ENV/ AGUARD APROVACAO          | Aviso de orçamento pronto (+ PDF, se já estiver na pasta) + pergunta de aprovação |
| ORC ENV/ APROVADO / N APROV        | Avisa o grupo "SERV - Solicitação de O.S." e o técnico responsável (nada pro cliente) |
| Avaliação, Execução, Finalizada, Desmch/Sucateado | Aviso de progresso citando o **equipamento** (marca, modelo, descrição) e o **nº da O.S.** (a Finalizada cita também o tipo da O.S.) |
| Aguard. Retirada | O texto **se adapta ao evento anterior** da O.S.: serviço concluído, reparo não autorizado, sem defeito ou sem conserto |
| Sem Conserto | Aviso fixo de "não possui conserto viável" + o **motivo**, escrito pela IA a partir da observação do técnico no Softsystem (ver abaixo) |
| Aguard. Peça, Não Autorizada, Sem Defeito | Aviso simples de progresso |

Tipos de O.S. com mensagem própria na abertura: Orçamento, Garantia de Loja, Garantia de
Fábrica, Locação de Equipamento e Visita Técnica (textos editáveis na tela de Automações).

> Os **avisos de progresso** (tabela acima) ainda **não** aparecem na tela de Automações -
> hoje só mudam no código (`eventos_os` em `backend/app/services/automation_service.py`),
> e valem igualmente para todos os tipos de O.S.

### Sem Conserto: como a observação é usada

A observação do técnico no Softsystem é um diário interno (tem CPF de terceiros, nomes,
"informado ao cliente"...), então **nunca vai crua para o cliente**: números longos são
removidos, só vira motivo se houver conteúdo técnico, a IA escreve apenas o motivo (a frase
"não possui conserto viável" é fixa) e qualquer resposta suspeita cai na mensagem genérica,
sem motivo. **Depende de a chave do Gemini estar válida** nas configurações; sem ela, sai
sempre a mensagem genérica.

### Para quem o aviso vai: campo "Contato" da O.S.

Se o campo **Contato** da O.S. (o retângulo no topo da tela da O.S.) tiver um **celular**, o aviso vai para ele
e a mensagem chama a pessoa pelo nome ("Olá, Andre!") - útil quando o cliente é uma empresa/CNPJ e quem
responde por ela é um responsável. O campo é texto livre, então o vigia entende formatos como
`ANDRE 33191133 / 996463103`, `61 984276819 - ROSANGELA` ou `PEDRO 9975-3596`: pega o primeiro celular
(número fixo é ignorado - não recebe WhatsApp; 8 dígitos começando em 9 ganham o 9 extra) e o que sobrar
de letras vira o nome. **Sem celular no Contato** (vazio, só nome, só fixo), o aviso segue como antes:
celular/fone do cadastro do cliente, com o nome do cadastro. Para o Contato valer, digite o celular
dele no campo.

### Quadro de técnicos (aba "Técnicos" do Ominichannel)

O vigia também alimenta o **Quadro de Técnicos**: uma linha por técnico (campo "Técnico 1" da O.S.), uma coluna por estágio
(Entrada, Avaliação, Orçamento enviado, Aprovado, Execução, Aguardando peça, Aguardando retirada, Sem reparo), com a data de
entrada de cada O.S. Na primeira execução ele envia os **últimos ~3 meses** das duas empresas; depois manda só o que mudou
(O.S. alterada ou com evento novo), e o quadro se atualiza sozinho. Regras: **finalizadas não aparecem no quadro** (ficam só na
auditoria, no detalhe do técnico, exclusivo de administradores) e **O.S. com condição de pagamento preenchida** (já efetivadas)
não entram. Sempre somente leitura no Softsystem. Há também o **Modo TV** (tela cheia, para a oficina).

## Regras que o operador precisa seguir

- **PDF de Abertura de OS** (relatório "Ordem de Serviço - Abertura de OS") -> salvar na
  pasta **ABERTURA**.
- **PDF de Orçamento** (relatório "Ordem de Serviço", com a O.S. já alimentada) -> salvar na
  pasta **ORCAMENTO**.
- O nome do arquivo é **só o número da O.S.** (`1936.pdf`).
- A ordem não importa: o aviso sai pelo evento, e o PDF, se aparecer depois, é entregue como
  complemento (sem repetir os textos). Mas PDF na pasta errada não é reconhecido.

## Como o sistema evita bagunçar a conversa do cliente

- **Nunca manda a mesma coisa duas vezes** pra mesma O.S. Excluir e recriar o mesmo evento
  no Softsystem **não** gera novo aviso - é proposital (protege o cliente de notificação
  repetida se alguém mexer no evento por engano).
- **Vários equipamentos de uma vez**: cada equipamento é uma O.S. separada no Softsystem. A
  primeira O.S. do atendimento dispara a sequência completa na hora; as seguintes do mesmo
  cliente (até 2 minutos de intervalo entre uma e outra - o prazo reinicia a cada nova O.S.)
  só acrescentam uma linha do novo equipamento, sem repetir saudação nem o pedido de
  confirmação. Um único "Sim" do cliente libera os PDFs de todas.
- O cliente pode responder em texto livre ("ok", "pode mandar"...) - o "Sim" não precisa
  ser exato (interpretado por palavras-chave, e por IA quando a resposta for ambígua e o
  Gemini estiver configurado no tenant).
- O PDF sempre é enviado com o nome `<nº da O.S.> - <cliente>.pdf`.
- Este fluxo só atua na instância **Assistência Técnica** - nunca em Vendas/Financeiro.

## Instalação (um clique, por estação)

1. Copie esta pasta inteira (`os_db_watcher`) para o computador, por exemplo em
   `C:\OminichannelDbWatcher\`.
2. Confira o `config.json` (crie a partir do `config.example.json`): chave de API do
   Ominichannel, caminhos do banco Firebird (usuário/senha) e as duas pastas de PDF.
3. Clique com o **botão direito** em `install.bat` -> **"Executar como administrador"**.
   Sem administrador funciona, mas só liga sozinho para o usuário que instalou; com
   administrador liga para **qualquer operador** que fizer login na estação.
4. O instalador faz tudo: instala o Python se faltar, cria ambiente isolado, instala as
   dependências e registra o início automático. Já inicia na hora.
5. Confira `db_watcher.log` - deve aparecer:
   ```
   Vigia de banco iniciado. Consultando a cada 20s.
   [vigia de pasta] Observando [abertura]: ...\ABERTURA
   [vigia de pasta] Observando [orcamento]: ...\ORCAMENTO
   ```

### Importante: precisa estar ligado

O vigia só funciona enquanto o computador está ligado e alguém já fez login. Se o PC ficar
desligado, **nada se perde**: ao ligar, ele retoma de onde parou (`state.json`) e dispara o
que ficou pendente. Só o aviso ao cliente atrasa até lá.

Se instalado, ele inicia sozinho a cada login. Iniciar "na mão" (`python db_watcher.py`)
só vale durante o teste - **não sobrevive a uma reinicialização**.

### Primeira execução

Na primeira vez em cada estação ele **não processa o passado** - marca a data/hora atual e
só reage a eventos novos dali em diante (evita mandar mensagem retroativa pra centenas de
O.S. antigas).

## Testar

Abra uma O.S. de teste no Softsystem (ou mude o "Tipo de Evento" de uma existente que
nunca foi avisada) - em até ~20s deve chegar a mensagem no WhatsApp do cliente e uma
linha "OK" aparecer em `db_watcher.log`.

## Desinstalar

Rode `uninstall.bat`. Só desliga o início automático e para o processo - o ambiente Python
continua pronto para reinstalar.

## Em caso de problema

- Confira `db_watcher.log` - toda tentativa fica registrada.
- **Nada chegou depois de ligar o PC**: veja se o processo está rodando
  (`Get-CimInstance Win32_Process | ? CommandLine -like '*db_watcher.py*'`). Se não estiver,
  o início automático não foi instalado para esse usuário - rode `install.bat` como
  administrador.
- **Mensagem duplicada ou "O.S. #?" / arquivo "? - Cliente.pdf"**: o vigia **antigo**
  (`os_folder_watcher`) está rodando junto. Pare o processo e apague a entrada
  `OminichannelWatcher.vbs` das pastas de inicialização do Windows
  (`C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp` e a do usuário).
- **Editei o evento e não chegou nada**: se a O.S. já foi avisada antes, é o comportamento
  esperado (ver "Como o sistema evita bagunçar a conversa"). Para testes repetidos use
  uma O.S. nova.
- **O PDF não chegou**: confira se está na pasta certa (Abertura x Orçamento) e se o nome é
  só o número da O.S.. PDF que falha na entrega vai para a subpasta `erros`; os entregues
  vão para `processados` (nada é apagado).
- **Erro de conexão com o banco**: confira se `192.168.15.16` está acessível dessa estação e
  se usuário/senha no `config.json` estão certos.
- **"HTTP 401"**: a chave de API está errada.
- Se um evento falhar ao enviar, o vigia tenta de novo no próximo ciclo sem pular nada -
  mas um erro persistente trava a fila. Fique de olho no log se "FALHA" repetir.
- `state.json` guarda até onde já foi processado - apague-o (com o vigia parado) só se
  quiser recomeçar a partir de agora.
