#!/bin/bash
# Ajustes DENTRO da VM do OminiChannel apos o travamento de 12/10/2026.
# Rodar dentro da VM:  sudo bash harden_guest.sh
#
# NAO liga kernel.softlockup_panic nem kernel.hung_task_panic: a investigacao de 12/10 mostrou
# 400+ "soft lockup" POR BOOT ha dias (vCPU sem ser escalonada pelo hospedeiro - VirtualBox em
# modo NEM sobre o Hyper-V, com 3 nucleos fisicos divididos entre o Windows e 2 VMs). Com panic
# ligado a VM reiniciaria varias vezes por hora. Quem reinicia a VM quando ela para de responder
# DE VERDADE e o vigia externo (vm_watchdog.ps1, no SRV-SERVWELD).
#
# 1. Kernel panic real -> reinicia sozinho em 10s.
# 2. Montagens CIFS do \\192.168.15.16 com nofail: a VM liga mesmo com o servidor fora do ar
#    (sem cair em modo de emergencia). Elas ja sao "soft" (padrao do kernel).
set -euo pipefail

printf '# Kernel panic real -> reinicia sozinho em 10s (12/10/2026)\nkernel.panic = 10\n' > /etc/sysctl.d/99-omini-panic.conf
sysctl -p /etc/sysctl.d/99-omini-panic.conf

if grep -E '[[:space:]]cifs[[:space:]]' /etc/fstab | grep -qv nofail; then
    cp -a /etc/fstab "/etc/fstab.bak-$(date +%Y%m%d%H%M)"
    sed -i -E '/[[:space:]]cifs[[:space:]]/{/nofail/!s/,_netdev/,_netdev,nofail,x-systemd.mount-timeout=30/}' /etc/fstab
    systemctl daemon-reload
fi
echo "== CIFS no /etc/fstab =="
grep -E '[[:space:]]cifs[[:space:]]' /etc/fstab || true
findmnt --verify --tab-file /etc/fstab | tail -2
