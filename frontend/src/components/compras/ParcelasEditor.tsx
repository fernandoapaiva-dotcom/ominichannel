import React, { useState } from 'react';
import { Plus, Trash2, Wand2 } from 'lucide-react';
import { brl, Parcela } from './comprasApi';
import { Botao, input, td, th } from './ui';

interface Props {
  titulo: string;
  parcelas: Parcela[];
  valorEsperado: number;
  dataBase?: string; // AAAA-MM-DD, base para gerar pela condição
  onChange: (parcelas: Parcela[]) => void;
  somenteLeitura?: boolean;
}

// Divide como o Softsystem: centavos truncados, sobra na última parcela
function gerar(valor: number, dataBase: string, condicao: string): Parcela[] {
  const dias = (condicao.match(/\d+/g) || ['0']).map(Number);
  const n = dias.length;
  const base = Math.floor((valor * 100) / n) / 100;
  const inicio = new Date(`${dataBase}T12:00:00`);
  return dias.map((d, i) => {
    const venc = new Date(inicio);
    venc.setDate(venc.getDate() + d);
    return {
      numero: String(i + 1).padStart(3, '0'),
      vencimento: venc.toISOString().slice(0, 10),
      valor: i < n - 1 ? base : Math.round((valor - base * (n - 1)) * 100) / 100,
      origem: 'condicao',
    };
  });
}

export const ParcelasEditor: React.FC<Props> = ({ titulo, parcelas, valorEsperado, dataBase, onChange, somenteLeitura }) => {
  const [condicao, setCondicao] = useState('30/60/90');
  const soma = Math.round(parcelas.reduce((a, p) => a + (Number(p.valor) || 0), 0) * 100) / 100;
  const diferenca = Math.round((valorEsperado - soma) * 100) / 100;

  const alterar = (idx: number, campo: keyof Parcela, valor: string) => {
    const novas = parcelas.map((p, i) => (i === idx ? { ...p, [campo]: campo === 'valor' ? parseFloat(valor) || 0 : valor, origem: 'manual' } : p));
    onChange(novas);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
        <strong style={{ fontSize: '14px', color: 'var(--text-main)' }}>{titulo}</strong>
        {!somenteLeitura && (
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <input style={{ ...input, width: '120px' }} value={condicao} onChange={(e) => setCondicao(e.target.value)} title="Dias após a emissão, ex: 30/60/90" />
            <Botao variante="secundario" icone={<Wand2 size={13} />}
              onClick={() => onChange(gerar(valorEsperado, dataBase || new Date().toISOString().slice(0, 10), condicao))}>
              Gerar
            </Botao>
            <Botao variante="fantasma" icone={<Plus size={13} />}
              onClick={() => onChange([...parcelas, { numero: String(parcelas.length + 1).padStart(3, '0'), vencimento: dataBase || '', valor: Math.max(diferenca, 0), origem: 'manual' }])}>
              Parcela
            </Botao>
            {parcelas.length > 0 && (
              <button
                type="button"
                onClick={() => onChange([])}
                style={{
                  padding: '4px 8px',
                  background: 'rgba(239, 68, 68, 0.1)',
                  color: '#ef4444',
                  border: '1px solid rgba(239, 68, 68, 0.2)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
                title="Limpar parcelas (usado para Remessa em Garantia, Bonificação ou Troca sem cobrança)"
              >
                Sem Cobrança / Zerar
              </button>
            )}
          </div>
        )}
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr><th style={th}>Nº</th><th style={th}>Vencimento</th><th style={th}>Valor</th><th style={th}>Origem</th>{!somenteLeitura && <th style={th}></th>}</tr>
        </thead>
        <tbody>
          {parcelas.length === 0 ? (
            <tr>
              <td colSpan={5} style={{ ...td, textAlign: 'center', padding: '16px', color: 'var(--text-muted)' }}>
                Nenhum vencimento gerado (Operação sem cobrança / Remessa). Não gerará contas a pagar.
              </td>
            </tr>
          ) : (
            parcelas.map((p, i) => (
              <tr key={i}>
                <td style={td}>{p.numero}</td>
                <td style={td}>
                  {somenteLeitura ? p.vencimento : <input type="date" style={input} value={p.vencimento} onChange={(e) => alterar(i, 'vencimento', e.target.value)} />}
                </td>
                <td style={td}>
                  {somenteLeitura ? brl(p.valor) : <input type="number" step="0.01" style={input} value={p.valor} onChange={(e) => alterar(i, 'valor', e.target.value)} />}
                </td>
                <td style={{ ...td, fontSize: '11px', color: 'var(--text-muted)' }}>{p.origem === 'xml' ? 'da nota (XML)' : p.origem === 'condicao' ? 'gerada' : 'manual'}</td>
                {!somenteLeitura && (
                  <td style={td}>
                    <Botao variante="fantasma" icone={<Trash2 size={13} />} onClick={() => onChange(parcelas.filter((_, j) => j !== i))} />
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
      <div style={{ fontSize: '12px', marginTop: '6px', color: Math.abs(diferenca) > 0.05 && parcelas.length > 0 ? '#f87171' : 'var(--text-muted)' }}>
        {parcelas.length === 0 ? (
          <span style={{ color: '#22c55e', fontWeight: 600 }}>Operação sem cobrança financeira — Contas a pagar: R$ 0,00</span>
        ) : (
          <>Soma {brl(soma)} de {brl(valorEsperado)}{Math.abs(diferenca) > 0.05 && ` — diferença de ${brl(diferenca)}`}</>
        )}
      </div>

    </div>
  );
};
