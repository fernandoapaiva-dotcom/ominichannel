# Google Drive em horário marcado (SRV-SERVWELD)

Pedido de 15/10/2026, depois de 6 quedas da VM do OminiChannel no mesmo dia: o Google Drive para
computador sincronizando `C:\Users\Administrator\My Drive` (o Z: da loja) durante o expediente fazia
a pasta de rede engasgar e travar a VM. Agora:

| Horário | O quê |
|---|---|
| 07:30 | Google Drive fecha (`drive_parar.ps1`) - arquivos continuam no disco, loja usa normal |
| 20:00 | Backup do Softsystem |
| 20:30 | Google Drive abre e sobe o dia para a nuvem (`drive_iniciar.ps1`) |
| 23:30-06:30 | Treino do RAG na VM (`backend/scripts/watch_rag_docs.py`) |

Pré-requisito: Google Drive em **"Espelhar arquivos"** (não "streaming").

Instalação: copiar os 3 arquivos para `C:\OminiVmWatchdog` e rodar `criar_tarefas.bat` como
Administrador. Log em `C:\OminiVmWatchdog\google_drive_agenda.log`. `/IT` = a tarefa roda na sessão
do Administrador (o Drive é um app de usuário: precisa da sessão aberta, como o servidor já fica).
