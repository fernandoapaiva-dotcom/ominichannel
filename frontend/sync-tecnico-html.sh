#!/bin/bash
# Mantem as paginas HTML "standalone" (PWAs a parte do app principal - Portal do Tecnico,
# Lancador de Foto) apontando pros mesmos arquivos JS/CSS com hash que o build mais recente
# gerou. Necessario porque essas paginas vivem em public/ (copiadas como estao pro dist/, sem
# passar pelo processamento do Vite) mas referenciam os nomes com hash do bundle principal -
# sem isso, toda vez que o build muda o hash (sempre que qualquer coisa no frontend muda) essas
# paginas quebram (404 no JS/CSS) ate alguem lembrar de atualizar elas na mao.
#
# Rodar depois de QUALQUER `npm run build` neste projeto.
set -euo pipefail
cd "$(dirname "$0")"

JS=$(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' dist/index.html | head -1)
CSS=$(grep -o 'assets/index-[A-Za-z0-9_-]*\.css' dist/index.html | head -1)

if [ -z "$JS" ] || [ -z "$CSS" ]; then
  echo "Nao consegui achar os assets em dist/index.html - rode 'npm run build' primeiro." >&2
  exit 1
fi

for f in tecnico.html foto-os.html; do
  sed -i -E "s#assets/index-[A-Za-z0-9_-]*\.js#${JS}#; s#assets/index-[A-Za-z0-9_-]*\.css#${CSS}#" "public/$f" "dist/$f"
done

echo "tecnico.html e foto-os.html atualizados: $JS / $CSS"
