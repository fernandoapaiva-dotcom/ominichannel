import React, { useEffect, useState } from 'react';
import { MapPin, Save, RefreshCw } from 'lucide-react';
import { api } from './comprasApi';
import { Aviso, Botao, card, input, td, th } from './ui';

// Etapa 3 da entrada de nota (pedidos de 15/10/2026): depois de lançar a nota no Softsystem, a
// pessoa confere o estoque REAL de cada produto e informa onde ele fica guardado. O Guardião do
// Softsystem não replica estoque nem localização entre os bancos, então a tela mostra as DUAS lojas:
// estoque real de cada uma (cada CNPJ tem o seu - vira Ajuste de Estoque no banco da própria loja;
// na hora para administrador, registrado para o administrador aplicar nos demais) e UMA localização,
// gravada em ESTOQUE.LOCALIZACAO (Localização 1) nos dois bancos.

type Loja = 'servweld' | 'centrooeste';
interface InfoLoja { estoque: number | null; localizacao: string | null; estoque_auditado: number | null }
interface ItemAuditoria {
  item_id: number;
  numero_item: number;
  codproduto: string | null;
  descricao: string;
  qtd_recebida: number;
  lojas: Record<Loja, InfoLoja>;
  localizacao: string | null;
  auditado_por: string | null;
}
interface Resposta {
  liberada: boolean;
  modo: string;
  empresa: Loja;
  lojas: { empresa: Loja; nome: string }[];
  pode_ajustar_estoque: boolean;
  erro: string | null;
  itens: ItemAuditoria[];
}

const num = (s: string) => {
  const t = (s || '').trim().replace(/\./g, '').replace(',', '.');
  return t === '' ? null : Number(t);
};
const chave = (id: number, l: Loja) => `${id}:${l}`;

export const EstoqueLocalizacao: React.FC<{ entradaId: number; onSalvo: () => void; onProximo?: () => void }> = ({ entradaId, onSalvo, onProximo }) => {
  const [dados, setDados] = useState<Resposta | null>(null);
  const [fisico, setFisico] = useState<Record<string, string>>({});
  const [local, setLocal] = useState<Record<number, string>>({});
  const [salvando, setSalvando] = useState(false);
  const [msg, setMsg] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);

  const carregar = async () => {
    try {
      const r = await api<Resposta>(`/entradas/${entradaId}/auditoria`);
      setDados(r);
      const f: Record<string, string> = {};
      const l: Record<number, string> = {};
      r.itens.forEach((i) => {
        r.lojas.forEach(({ empresa }) => {
          const a = i.lojas?.[empresa]?.estoque_auditado;
          f[chave(i.item_id, empresa)] = a != null ? String(a).replace('.', ',') : '';
        });
        l[i.item_id] = i.localizacao ?? i.lojas?.[r.empresa]?.localizacao ?? '';
      });
      setFisico(f);
      setLocal(l);
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    }
  };

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entradaId]);

  const salvar = async () => {
    if (!dados) return;
    const itens = dados.itens.filter((i) => i.codproduto).map((i) => {
      const qs = num(fisico[chave(i.item_id, 'servweld')]);
      const qc = num(fisico[chave(i.item_id, 'centrooeste')]);
      const loc = (local[i.item_id] || '').trim();
      const locAtual = i.localizacao ?? '';
      const mudouLoc = loc && (loc !== locAtual || dados.lojas.some(({ empresa }) => (i.lojas?.[empresa]?.localizacao || '') !== loc));
      return {
        item_id: i.item_id,
        estoque_servweld: qs != null && !Number.isNaN(qs) ? qs : null,
        estoque_centrooeste: qc != null && !Number.isNaN(qc) ? qc : null,
        localizacao: mudouLoc ? loc : null,
      };
    }).filter((i) => i.estoque_servweld != null || i.estoque_centrooeste != null || i.localizacao != null);
    if (!itens.length) {
      setMsg({ tipo: 'erro', texto: 'Digite o estoque contado ou a localização de pelo menos um produto.' });
      return;
    }
    const difs: string[] = [];
    dados.itens.forEach((i) => dados.lojas.forEach(({ empresa, nome }) => {
      const q = num(fisico[chave(i.item_id, empresa)]);
      const sis = i.lojas?.[empresa]?.estoque;
      if (q != null && sis != null && Math.abs(q - sis) > 0.0001) difs.push(`${nome} · ${i.codproduto} ${i.descricao.slice(0, 34)}: ${sis} -> ${q}`);
    }));
    if (difs.length && dados.pode_ajustar_estoque && !confirm(
      `${difs.length} estoque(s) diferente(s) do Softsystem. Gravar os ajustes de estoque?\n\n${difs.join('\n')}`)) return;
    setSalvando(true);
    setMsg(null);
    try {
      const r = await api<any>(`/entradas/${entradaId}/auditoria`, { method: 'POST', body: { itens } });
      setMsg({ tipo: 'ok', texto: `${r.mensagem}${onProximo ? ' Indo para 4. Fotos e site...' : ''}` });
      if (onProximo) setTimeout(onProximo, 2500);
      await carregar();
      onSalvo();
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    } finally {
      setSalvando(false);
    }
  };

  if (!dados) return <div style={{ ...card, color: 'var(--text-muted)' }}>{msg ? msg.texto : 'Carregando estoque do Softsystem...'}</div>;
  if (!dados.liberada) {
    return <Aviso tipo="info">Esta etapa abre depois que a nota for lançada no Softsystem: aqui você confere o estoque real na prateleira e informa a localização de cada produto.</Aviso>;
  }

  const inputQtd: React.CSSProperties = { ...input, width: '82px', textAlign: 'right', fontWeight: 700 };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <Aviso tipo="info">
        Confira o <strong>estoque total de cada loja</strong> (Servweld e Centro-Oeste - cada CNPJ tem o seu) e diga onde o produto fica guardado.
        A localização vai para a <strong>Localização 1</strong> do Softsystem <strong>nas duas lojas</strong>.{' '}
        {dados.pode_ajustar_estoque
          ? 'Estoque diferente do Softsystem vira um Ajuste de Estoque no banco da loja correspondente.'
          : 'Se o estoque contado for diferente, fica registrado para o administrador aplicar o ajuste.'}
        {' '}Deixe em branco a loja que você não conferiu.
        {dados.modo === 'teste' && <strong> Modo TESTE: grava só na cópia da Servweld.</strong>}
      </Aviso>
      {dados.erro && <Aviso tipo="alerta">{dados.erro}</Aviso>}
      {msg && <Aviso tipo={msg.tipo === 'ok' ? 'ok' : 'erro'} onFechar={() => setMsg(null)}>{msg.texto}</Aviso>}

      <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '860px' }}>
          <thead>
            <tr>
              <th style={th}>Produto</th>
              <th style={{ ...th, textAlign: 'right' }}>Chegou</th>
              {dados.lojas.map((l) => (
                <th key={l.empresa} style={{ ...th, textAlign: 'center' }}>{l.nome}<div style={{ fontWeight: 400, textTransform: 'none' }}>sistema → real</div></th>
              ))}
              <th style={th}><span style={{ display: 'inline-flex', gap: '4px', alignItems: 'center' }}><MapPin size={12} /> Localização (as duas lojas)</span></th>
            </tr>
          </thead>
          <tbody>
            {dados.itens.map((i) => (
              <tr key={i.item_id}>
                <td style={td}>
                  <div style={{ fontWeight: 600, color: 'var(--text-main)' }}>{i.descricao}</div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    {i.codproduto ? `Cód. ${i.codproduto}` : 'Sem produto vinculado'}{i.auditado_por && ` · conferido por ${i.auditado_por}`}
                  </div>
                </td>
                <td style={{ ...td, textAlign: 'right' }}>{i.qtd_recebida}</td>
                {dados.lojas.map(({ empresa }) => {
                  const sis = i.lojas?.[empresa]?.estoque;
                  const q = num(fisico[chave(i.item_id, empresa)]);
                  const dif = q != null && sis != null ? q - sis : 0;
                  return (
                    <td key={empresa} style={{ ...td, textAlign: 'center', background: Math.abs(dif) > 0.0001 ? 'rgba(245,158,11,0.08)' : undefined }}>
                      <span style={{ color: 'var(--text-muted)', marginRight: '6px' }}>{sis ?? '—'} →</span>
                      <input value={fisico[chave(i.item_id, empresa)] ?? ''} inputMode="decimal" placeholder="real" disabled={!i.codproduto}
                        onChange={(e) => setFisico({ ...fisico, [chave(i.item_id, empresa)]: e.target.value })} style={inputQtd} />
                      {Math.abs(dif) > 0.0001 && (
                        <div style={{ fontSize: '11px', fontWeight: 700, color: dif < 0 ? '#f87171' : '#f59e0b' }}>{dif > 0 ? `+${+dif.toFixed(3)}` : +dif.toFixed(3)}</div>
                      )}
                    </td>
                  );
                })}
                <td style={td}>
                  <input value={local[i.item_id] ?? ''} placeholder="Ex.: P.S D 03" maxLength={60} disabled={!i.codproduto}
                    onChange={(e) => setLocal({ ...local, [i.item_id]: e.target.value.toUpperCase() })}
                    style={{ ...input, width: '100%', minWidth: '150px' }} />
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '3px' }}>
                    {dados.lojas.map(({ empresa, nome }) => `${nome}: ${i.lojas?.[empresa]?.localizacao || '—'}`).join(' · ')}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <Botao variante="fantasma" icone={<RefreshCw size={14} />} onClick={carregar}>Atualizar</Botao>
        <Botao icone={<Save size={14} />} onClick={salvar} disabled={salvando}>
          {salvando ? 'Gravando no Softsystem...' : 'Gravar estoque e localização'}
        </Botao>
        {onProximo && <Botao variante="secundario" onClick={onProximo}>Próximo: 4. Fotos e site →</Botao>}
      </div>
    </div>
  );
};
