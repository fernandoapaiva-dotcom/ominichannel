import React, { useEffect, useMemo, useState } from 'react';
import { Sparkles, Check, Copy, Link2 } from 'lucide-react';
import { api, Empresa, ItemNota, SoftsystemProduto } from './comprasApi';
import { Aviso, Botao, Campo, Chip, Modal, input } from './ui';
import { ProdutoVinculoModal } from './ProdutoVinculoModal';

// Etapa 2 da entrada de nota (15/10/2026): produto que ainda não existe na loja. A IA SUGERE o
// cadastro no padrão da casa (descrição, grupo/subgrupos N1-N3, marca, unidade, NCM, referência)
// a partir do produto MODELO e de descrições reais do mesmo subgrupo; a pessoa CONFIRMA. O produto
// é criado no Softsystem no lançamento da nota, copiando a tributação e as margens do modelo.

interface No { codigo: number; nome: string; subgrupos?: No[]; nivel2?: No[]; nivel3?: No[] }
interface Arvore { grupos: No[]; marcas: { codigo: number; nome: string }[] }

interface Cadastro {
  modelo_codigo: number | null;
  descricao: string;
  codgrupo: number | null;
  codsubgrupo: number | null;
  codsubgruponivel2: number | null;
  codsubgruponivel3: number | null;
  codmarca: number | null;
  marca_nova: string | null;
  unidade: string;
  ncm: string;
  cest: string;
  ean: string;
  referencia: string;
  peso: number | null;
  explicacao?: string;
  origem?: string;
  confirmado?: boolean;
  confirmado_por?: string;
}

interface Props {
  entradaId: number;
  empresa: Empresa;
  item: ItemNota & { cadastro_novo?: Cadastro | null };
  onFechar: () => void;
  onSalvo: () => void;
}

const VAZIO: Cadastro = {
  modelo_codigo: null, descricao: '', codgrupo: null, codsubgrupo: null, codsubgruponivel2: null, codsubgruponivel3: null,
  codmarca: null, marca_nova: null, unidade: 'UN', ncm: '', cest: '', ean: '', referencia: '', peso: null,
};

const sel: React.CSSProperties = { ...input, width: '100%' };
const semAcento = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase().replace(/\s+/g, ' ');

export const CadastroProdutoModal: React.FC<Props> = ({ entradaId, empresa, item, onFechar, onSalvo }) => {
  const [arvore, setArvore] = useState<Arvore | null>(null);
  const [cad, setCad] = useState<Cadastro>(() => ({
    ...VAZIO, ...(item.cadastro_novo || {}),
    modelo_codigo: item.cadastro_novo?.modelo_codigo ?? (item.produto_modelo_codigo ? Number(item.produto_modelo_codigo) : null),
  }));
  const [sugerindo, setSugerindo] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [trocarModelo, setTrocarModelo] = useState(false);
  const [modeloDesc, setModeloDesc] = useState<string>((item as any).produto_modelo_descricao || '');
  const [marcaNovaAberta, setMarcaNovaAberta] = useState(!!item.cadastro_novo?.marca_nova);

  const mudar = (m: Partial<Cadastro>) => setCad((c) => ({ ...c, ...m }));

  const sugerir = async (modelo?: number | null) => {
    setSugerindo(true);
    setErro(null);
    try {
      const r = await api<{ sugestao: Cadastro }>(`/entradas/${entradaId}/itens/${item.id}/sugerir-cadastro`, {
        method: 'POST', body: { modelo_codigo: modelo ?? cad.modelo_codigo },
      });
      const s = r.sugestao;
      setCad({ ...VAZIO, ...s, ncm: s.ncm || '', cest: s.cest || '', ean: s.ean || '', referencia: s.referencia || '', confirmado: false });
      setMarcaNovaAberta(!!s.marca_nova);
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setSugerindo(false);
    }
  };

  useEffect(() => {
    api<Arvore>(`/softsystem/arvore-cadastro?empresa=${empresa}`).then(setArvore).catch((e) => setErro(e.message));
    if (!item.cadastro_novo && cad.modelo_codigo) sugerir(cad.modelo_codigo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const grupo = useMemo(() => arvore?.grupos.find((g) => g.codigo === cad.codgrupo), [arvore, cad.codgrupo]);
  const sub = useMemo(() => grupo?.subgrupos?.find((s) => s.codigo === cad.codsubgrupo), [grupo, cad.codsubgrupo]);
  const n2 = useMemo(() => sub?.nivel2?.find((s) => s.codigo === cad.codsubgruponivel2), [sub, cad.codsubgruponivel2]);

  const escolherModelo = async (p: SoftsystemProduto, modo: 'vincular' | 'modelo') => {
    setTrocarModelo(false);
    if (modo === 'vincular') {
      // não é produto novo: é um que a loja já tem
      if (!confirm(`Vincular este item ao produto ${p.codigo} - ${p.descricao}? (não cadastra produto novo)`)) return;
      try {
        await api(`/entradas/${entradaId}/precificacao`, {
          method: 'PUT', body: { itens: [{
            item_id: item.id, softsystem_prod_codigo: String(p.codigo), softsystem_descricao: p.descricao, softsystem_grupo: p.grupo,
            softsystem_subgrupo: p.subgrupo, vinculo_metodo: 'manual', produto_modelo_codigo: null, softsystem_status: 'vinculado',
          }] },
        });
        onSalvo();
        onFechar();
      } catch (e: any) {
        setErro(e.message);
      }
      return;
    }
    setModeloDesc(p.descricao);
    mudar({ modelo_codigo: p.codigo });
    sugerir(p.codigo);
  };

  const confirmar = async () => {
    setSalvando(true);
    setErro(null);
    try {
      await api(`/entradas/${entradaId}/itens/${item.id}/cadastro-novo`, {
        method: 'PUT', body: {
          ...cad, descricao: semAcento(cad.descricao), marca_nova: marcaNovaAberta ? cad.marca_nova : null,
          codmarca: marcaNovaAberta ? null : cad.codmarca, peso: cad.peso || null,
        },
      });
      onSalvo();
      onFechar();
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setSalvando(false);
    }
  };

  if (trocarModelo) {
    return <ProdutoVinculoModal empresa={empresa} item={item} onFechar={() => setTrocarModelo(false)} onEscolher={escolherModelo} />;
  }

  const num = (v: string) => (v === '' ? null : Number(v));

  return (
    <Modal titulo="Cadastro do produto novo" onFechar={onFechar} largura={860}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '13px' }}>
        <div style={{ color: 'var(--text-muted)' }}>
          <div style={{ color: 'var(--text-main)', fontWeight: 600 }}>Na nota: {item.descricao_fornecedor}</div>
          Cód. fornecedor {item.codigo_fornecedor} · EAN {item.ean || '—'} · NCM {item.ncm || '—'} · {item.unidade}
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span>Modelo (tributação e margens copiadas dele):</span>
          {cad.modelo_codigo ? <Chip cor="#3b82f6"><Copy size={11} /> #{cad.modelo_codigo} {modeloDesc}</Chip> : <Chip cor="#ef4444">escolha um modelo</Chip>}
          <Botao variante="fantasma" icone={<Link2 size={13} />} onClick={() => setTrocarModelo(true)} style={{ padding: '4px 10px' }}>
            {cad.modelo_codigo ? 'Trocar modelo / é um produto que já existe' : 'Escolher modelo'}
          </Botao>
          <Botao variante="secundario" icone={<Sparkles size={13} />} onClick={() => sugerir()} disabled={sugerindo || !cad.modelo_codigo} style={{ padding: '4px 10px' }}>
            {sugerindo ? 'IA pensando...' : 'Sugerir de novo com IA'}
          </Botao>
        </div>

        {cad.explicacao && (
          <Aviso tipo="info"><strong>{cad.origem === 'ia' ? 'Sugestão da IA' : 'Sugestão'}:</strong> {cad.explicacao} Confira tudo antes de confirmar.</Aviso>
        )}
        {erro && <Aviso tipo="erro" onFechar={() => setErro(null)}>{erro}</Aviso>}

        <Campo rotulo="Descrição (padrão da casa)" dica='Ex.: "BICO DE CONTATO ROSCA M-6 28X8.0MM FURO 0.8MM" - o que é, tipo, medidas, aplicação'>
          <input style={{ ...input, width: '100%', fontWeight: 700 }} maxLength={150} value={cad.descricao}
            onChange={(e) => mudar({ descricao: semAcento(e.target.value) })} />
        </Campo>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px' }}>
          <Campo rotulo="Grupo">
            <select style={sel} value={cad.codgrupo ?? ''} onChange={(e) => mudar({ codgrupo: num(e.target.value), codsubgrupo: null, codsubgruponivel2: null, codsubgruponivel3: null })}>
              <option value="">—</option>
              {arvore?.grupos.map((g) => <option key={g.codigo} value={g.codigo}>{g.nome}</option>)}
            </select>
          </Campo>
          <Campo rotulo="Subgrupo (N1)">
            <select style={sel} value={cad.codsubgrupo ?? ''} onChange={(e) => mudar({ codsubgrupo: num(e.target.value), codsubgruponivel2: null, codsubgruponivel3: null })}>
              <option value="">—</option>
              {grupo?.subgrupos?.map((g) => <option key={g.codigo} value={g.codigo}>{g.nome}</option>)}
            </select>
          </Campo>
          <Campo rotulo="Subgrupo N2">
            <select style={sel} value={cad.codsubgruponivel2 ?? ''} onChange={(e) => mudar({ codsubgruponivel2: num(e.target.value), codsubgruponivel3: null })}>
              <option value="">—</option>
              {sub?.nivel2?.map((g) => <option key={g.codigo} value={g.codigo}>{g.nome}</option>)}
            </select>
          </Campo>
          <Campo rotulo="Subgrupo N3">
            <select style={sel} value={cad.codsubgruponivel3 ?? ''} onChange={(e) => mudar({ codsubgruponivel3: num(e.target.value) })}>
              <option value="">—</option>
              {n2?.nivel3?.map((g) => <option key={g.codigo} value={g.codigo}>{g.nome}</option>)}
            </select>
          </Campo>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
          <Campo rotulo="Marca">
            {marcaNovaAberta ? (
              <input style={{ ...input, width: '100%' }} placeholder="Nome da marca nova" value={cad.marca_nova || ''}
                onChange={(e) => mudar({ marca_nova: semAcento(e.target.value).slice(0, 40) })} />
            ) : (
              <select style={sel} value={cad.codmarca ?? ''} onChange={(e) => mudar({ codmarca: num(e.target.value) })}>
                <option value="">—</option>
                {arvore?.marcas.map((m) => <option key={m.codigo} value={m.codigo}>{m.nome}</option>)}
              </select>
            )}
            <button type="button" onClick={() => setMarcaNovaAberta(!marcaNovaAberta)}
              style={{ background: 'none', border: 'none', color: 'var(--accent-primary)', fontSize: '11.5px', cursor: 'pointer', padding: '3px 0' }}>
              {marcaNovaAberta ? 'escolher da lista' : 'marca não está na lista'}
            </button>
          </Campo>
          <Campo rotulo="Unidade">
            <select style={sel} value={cad.unidade} onChange={(e) => mudar({ unidade: e.target.value })}>
              {Array.from(new Set(['UN', 'PC', 'CX', 'RL', 'KG', 'M', 'PAR', 'JG', 'KIT', 'LT', cad.unidade])).map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </Campo>
          <Campo rotulo="NCM"><input style={{ ...input, width: '100%' }} value={cad.ncm} onChange={(e) => mudar({ ncm: e.target.value.replace(/\D/g, '').slice(0, 8) })} /></Campo>
          <Campo rotulo="CEST"><input style={{ ...input, width: '100%' }} value={cad.cest} onChange={(e) => mudar({ cest: e.target.value.replace(/\D/g, '').slice(0, 7) })} /></Campo>
          <Campo rotulo="EAN (código de barras)"><input style={{ ...input, width: '100%' }} value={cad.ean} onChange={(e) => mudar({ ean: e.target.value.replace(/\D/g, '').slice(0, 14) })} /></Campo>
          <Campo rotulo="Referência do fabricante"><input style={{ ...input, width: '100%' }} maxLength={40} value={cad.referencia} onChange={(e) => mudar({ referencia: e.target.value })} /></Campo>
          <Campo rotulo="Peso (kg)"><input style={{ ...input, width: '100%' }} inputMode="decimal" value={cad.peso ?? ''} onChange={(e) => mudar({ peso: e.target.value === '' ? null : Number(e.target.value.replace(',', '.')) || null })} /></Campo>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
            {item.cadastro_novo?.confirmado ? `Confirmado por ${item.cadastro_novo.confirmado_por}. ` : ''}
            O produto é criado no Softsystem quando a nota for lançada.
          </span>
          <div style={{ display: 'flex', gap: '8px' }}>
            <Botao variante="fantasma" onClick={onFechar}>Cancelar</Botao>
            <Botao icone={<Check size={14} />} onClick={confirmar} disabled={salvando || sugerindo || !cad.modelo_codigo}>
              {salvando ? 'Salvando...' : 'Confirmar cadastro'}
            </Botao>
          </div>
        </div>
      </div>
    </Modal>
  );
};
