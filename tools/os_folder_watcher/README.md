# Vigia de Pasta - O.S. Softsystem

Programa que roda no computador da loja, observa as pastas onde o Softsystem salva o
PDF da Ordem de Serviço, e envia automaticamente para o sistema Ominichannel processar
(avisos ao cliente + PDF + confirmação de aprovação).

## Instalação (uma vez só)

1. Copie esta pasta inteira (`os_folder_watcher`) para o computador da loja, por exemplo
   em `C:\OminichannelWatcher\`.
2. Instale o Python 3 (se ainda não tiver): https://www.python.org/downloads/ - marque a
   opção **"Add Python to PATH"** durante a instalação.
3. Abra o Prompt de Comando (cmd) nessa pasta e rode:
   ```
   pip install watchdog requests
   ```
4. O arquivo `config.json` já vem preenchido com a chave de acesso e os caminhos das
   pastas (`Z:\O.S SOFTSYSTEM\ABERTURA` e `Z:\O.S SOFTSYSTEM\ORCAMENTO`). Só confira se
   esses caminhos estão certos no computador da loja - se o Softsystem salvar em outro
   lugar, edite o `config.json` (é só um arquivo de texto).

## Testar manualmente

No Prompt de Comando, dentro da pasta:
```
python watcher.py
```
Deixe rodando e abra/salve uma O.S. de teste no Softsystem - deve aparecer uma linha de
log dizendo "OK" e a mensagem deve chegar no WhatsApp do número de teste em poucos
segundos. Pressione Ctrl+C para parar o teste.

## Deixar rodando sempre (Tarefa Agendada do Windows)

Para não precisar abrir isso manualmente todo dia:

1. Abra o **Agendador de Tarefas** do Windows (pesquise "Agendador de Tarefas" no menu Iniciar).
2. Criar Tarefa Básica → nome "Vigia OS Softsystem".
3. Disparador: **Ao fazer logon**.
4. Ação: **Iniciar um programa**.
   - Programa/script: caminho completo do Python (ex: `C:\Users\SeuUsuario\AppData\Local\Programs\Python\Python312\python.exe`)
   - Argumentos: `watcher.py`
   - Iniciar em: caminho da pasta (ex: `C:\OminichannelWatcher`)
5. Finalizar. Reinicie o computador (ou faça logoff/logon) para testar se inicia sozinho.

## Arquivos processados

Cada PDF processado é movido para uma subpasta `processados` (se deu certo) ou `erros`
(se algo falhou) dentro da mesma pasta de origem - nada é apagado, então dá pra
reenviar manualmente se precisar. O log completo fica em `watcher.log`, nesta mesma pasta.

## Em caso de problema

- Confira o arquivo `watcher.log` - toda tentativa (certa ou errada) fica registrada ali.
- Se aparecer "HTTP 401": a chave de API (`api_key` no config.json) está errada.
- Se aparecer "HTTP 422 - Telefone do cliente não encontrado": o PDF não tem o campo
  Celular/Telefone preenchido, ou o layout mudou - avise o suporte.
- Se aparecer erro de conexão: confira se o computador da loja tem internet.
