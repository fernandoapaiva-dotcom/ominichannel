# Vigia de Pasta - O.S. Softsystem

> ## ⛔ OBSOLETO - NÃO INSTALAR
> Este programa foi **substituído** por [`tools/os_db_watcher/`](../os_db_watcher/README.md),
> que lê os dados direto do banco Firebird e já vigia as pastas de PDF também.
>
> **Nunca rode os dois juntos.** Este aqui lê o texto de dentro do PDF (frágil) e dispara pelo
> endpoint antigo `/ingest`: com os dois ligados o cliente recebe **tudo em dobro**, e as
> mensagens saem com "O.S. #?" e PDF chamado "? - Cliente.pdf" quando o texto do PDF não
> permite achar o número da O.S. (aconteceu em produção). Se este programa já foi instalado
> em alguma estação, rode o `uninstall.bat` daqui e confirme que a entrada
> `OminichannelWatcher.vbs` sumiu das pastas de inicialização do Windows.
>
> Mantido apenas como referência histórica.

Programa que roda no computador da loja, observa as pastas onde o Softsystem salva o
PDF da Ordem de Serviço, e envia automaticamente para o sistema Ominichannel processar
(avisos ao cliente + PDF + confirmação/aprovação).

## Instalação (um clique, por estação)

Repita esses passos em **cada computador/estação** onde o Softsystem roda:

1. Copie esta pasta inteira (`os_folder_watcher`) para o computador, por exemplo em
   `C:\OminichannelWatcher\`.
2. Confira se o `config.json` já está preenchido com a chave de acesso e os caminhos
   das pastas (`Z:\O.S SOFTSYSTEM\ABERTURA` e `Z:\O.S SOFTSYSTEM\ORCAMENTO`) - se algum
   caminho for diferente nessa estação, edite o `config.json` (é só um arquivo de texto).
3. Clique com o **botão direito** em `install.bat` → **"Executar como administrador"**.
   (Se instalar sem ser administrador ainda funciona, mas só liga automaticamente para
   o usuário que instalou - com administrador, liga sozinho para **qualquer operador**
   que fizer login nessa estação, que é o caso de vocês com mais de um operador.)
4. O instalador faz tudo sozinho: verifica se tem Python (instala automaticamente se
   não tiver), cria um ambiente isolado só para este programa, instala o necessário, e
   deixa configurado para iniciar sozinho a cada login. Já inicia na hora também, sem
   precisar reiniciar o computador para testar.
5. Ao final, confira o arquivo `watcher.log` (nesta mesma pasta) - deve aparecer:
   ```
   Observando [abertura]: Z:\O.S SOFTSYSTEM\ABERTURA
   Observando [orcamento]: Z:\O.S SOFTSYSTEM\ORCAMENTO
   Vigia de pasta iniciado.
   ```

Pronto. A partir daí, sempre que alguém abrir/salvar uma O.S. no Softsystem, o PDF é
enviado automaticamente e o WhatsApp do cliente recebe os avisos certos.

## Testar

Abra ou alimente uma O.S. de teste no Softsystem normalmente - em poucos segundos deve
chegar a mensagem no WhatsApp do número de teste, e uma nova linha "OK" deve aparecer em
`watcher.log`.

## Desinstalar

Rode `uninstall.bat` na estação. Isso só desliga o início automático - os arquivos e o
ambiente Python instalado continuam aí, prontos para reinstalar (`install.bat`) quando
quiser, sem precisar baixar/instalar tudo de novo.

## Arquivos processados

Cada PDF processado é movido para uma subpasta `processados` (se deu certo) ou `erros`
(se algo falhou) dentro da própria pasta de origem - nada é apagado, então dá pra
reenviar manualmente se precisar. O log completo fica em `watcher.log`.

## Em caso de problema

- Confira `watcher.log` - toda tentativa (certa ou errada) fica registrada ali.
- **"HTTP 401"**: a chave de API (`api_key` no `config.json`) está errada.
- **"HTTP 422 - Telefone do cliente não encontrado"**: o PDF não tem o campo
  Celular/Telefone preenchido, ou o layout mudou - avise o suporte.
- **"Pasta não encontrada"**: confira se o `Z:` está mapeado nessa estação e se o
  caminho no `config.json` está certo.
- Erro de conexão: confira se a estação tem internet.
- Se quiser reinstalar do zero: rode `uninstall.bat`, apague a pasta `venv`, e rode
  `install.bat` de novo.
