"""
Script de publicação para a VM do OminiChannel (192.168.15.3).
Envia os arquivos modificados dos Pedidos de Compra e Balcão,
compila o frontend na VM e reinicia o backend.
"""
import getpass, os, sys, time, urllib.request, paramiko

HOST = "192.168.15.3"
USER = "administrator"
ROOT = "/home/administrator/ominichannel"
LOCAL_REPO = r"C:\Antigravity\omini_channel"

ARQUIVOS = [
    ("backend/app/models/models.py", f"{ROOT}/backend/app/models/models.py"),
    ("backend/app/api/v1/compras.py", f"{ROOT}/backend/app/api/v1/compras.py"),
    ("backend/app/services/softsystem_compra_writer.py", f"{ROOT}/backend/app/services/softsystem_compra_writer.py"),
    ("backend/app/services/compras_pedido_service.py", f"{ROOT}/backend/app/services/compras_pedido_service.py"),
    ("frontend/src/components/compras/comprasApi.ts", f"{ROOT}/frontend/src/components/compras/comprasApi.ts"),
    ("frontend/src/components/compras/PedidosCompraPanel.tsx", f"{ROOT}/frontend/src/components/compras/PedidosCompraPanel.tsx"),
    ("frontend/src/components/ComprasPanel.tsx", f"{ROOT}/frontend/src/components/ComprasPanel.tsx"),
]

print(f"== Publicador de Atualizações - OminiChannel ==")
print(f"Destino: {USER}@{HOST}:{ROOT}")

pw = os.environ.get("VM_PASS", "").strip()
if not pw:
    try:
        pw = getpass.getpass(f"Digite a senha do {USER}@{HOST}: ").strip()
    except Exception:
        pw = input(f"Digite a senha do {USER}@{HOST}: ").strip()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
conectou = False

# Tenta com o usuário administrator e com o usuário ubuntu caso exista
for tentativa in range(3):
    try:
        c.connect(
            HOST,
            username=USER,
            password=pw,
            timeout=15,
            banner_timeout=60,
            auth_timeout=60,
            look_for_keys=False,
            allow_agent=False
        )
        conectou = True
        print("Conectado com sucesso à VM!")
        break
    except paramiko.AuthenticationException:
        print("Senha incorreta.")
        if tentativa < 2:
            pw = input(f"Tente digitar a senha novamente (tentativa {tentativa+2}/3): ").strip()
    except Exception as e:
        sys.exit(f"Falha de conexão com a VM ({HOST}): {e}")

if not conectou:
    sys.exit("!! Não foi possível autenticar com a senha informada.")


def run(cmd, timeout=600):
    i, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode(errors="replace")
    err = e.read().decode(errors="replace")
    code = o.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"Erro ({code}): {err.strip() or out.strip()}")
    return out

try:
    print("\n1. Enviando arquivos para a VM...")
    sftp = c.open_sftp()
    for rel_local, dest_remoto in ARQUIVOS:
        caminho_local = os.path.join(LOCAL_REPO, rel_local)
        print(f" -> {rel_local}")
        sftp.put(caminho_local, dest_remoto)
    sftp.close()

    print("\n2. Validando sintaxe Python no backend...")
    run(f"cd {ROOT}/backend && venv/bin/python -m py_compile app/models/models.py app/api/v1/compras.py app/services/softsystem_compra_writer.py app/services/compras_pedido_service.py")
    print("Sintaxe Python OK!")

    print("\n3. Compilando o Frontend na VM (npm run build)...")
    run(f"cd {ROOT}/frontend && npm run build", timeout=900)
    print("Frontend compilado com sucesso!")

    print("\n4. Reiniciando o backend (PM2)...")
    run("pm2 restart omini-backend --update-env")
    print("Backend reiniciado!")

    print("\n5. Testando saúde da API...")
    time.sleep(3)
    req = urllib.request.Request("http://192.168.15.3:8000/api/v1/health")
    for _ in range(12):
        try:
            res = urllib.request.urlopen(req, timeout=5).read().decode()
            print(f"Health check: {res}")
            break
        except Exception:
            time.sleep(3)

    print("\n" + "="*50)
    print("ATUALIZAÇÃO CONCLUÍDA COM SUCESSO!")
    print("No navegador, basta apertar Ctrl + F5 para recarregar com a nova aba!")
    print("="*50)

except Exception as e:
    print(f"\n!! Erro durante a publicação: {e}")
finally:
    c.close()

