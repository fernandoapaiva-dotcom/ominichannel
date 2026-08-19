import React, { useState } from 'react';
import { X, QrCode, Copy, Check, Send, ShieldCheck } from 'lucide-react';

interface PixModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSendPixToChat: (pixText: string) => void;
}

// Official Central Bank of Brazil (BACEN) EMV Co BR Code Generator
function generateBacenPixPayload(cnpj: string, merchantName: string, merchantCity: string): string {
  const cleanCnpj = cnpj.replace(/\D/g, '');
  const field26 = `0014br.gov.bcb.pix01${cleanCnpj.length.toString().padStart(2, '0')}${cleanCnpj}`;
  
  // BACEN standard formatting (no accents, uppercase)
  const nameClean = merchantName.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().slice(0, 25);
  const cityClean = merchantCity.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().slice(0, 15);

  const payloadNoCrc = 
    '000201' +
    `26${field26.length.toString().padStart(2, '0')}${field26}` +
    '52040000' +
    '5303986' +
    '5802BR' +
    `59${nameClean.length.toString().padStart(2, '0')}${nameClean}` +
    `60${cityClean.length.toString().padStart(2, '0')}${cityClean}` +
    '62070503***' +
    '6304';

  // CRC16-CCITT (0xFFFF)
  let crc = 0xFFFF;
  for (let i = 0; i < payloadNoCrc.length; i++) {
    crc ^= payloadNoCrc.charCodeAt(i) << 8;
    for (let j = 0; j < 8; j++) {
      if ((crc & 0x8000) !== 0) {
        crc = ((crc << 1) ^ 0x1021) & 0xFFFF;
      } else {
        crc = (crc << 1) & 0xFFFF;
      }
    }
  }
  const crcHex = (crc & 0xFFFF).toString(16).toUpperCase().padStart(4, '0');
  return payloadNoCrc + crcHex;
}

export const PixModal: React.FC<PixModalProps> = ({
  isOpen,
  onClose,
  onSendPixToChat
}) => {
  const [copiedKey, setCopiedKey] = useState(false);
  const [copiedPayload, setCopiedPayload] = useState(false);

  const cnpjKey = "54804458000122";
  const formattedCnpj = "54.804.458/0001-22";
  const companyName = "SERVWELD SOLDA";
  const fullName = "Servweld / Servsolda Equipamentos e Serviços Ltda";
  const city = "BRASILIA";

  // Official BACEN EMV Co Pix Copia e Cola Payload
  const bacenPixPayload = generateBacenPixPayload(cnpjKey, companyName, city);

  // Generate QR Code from the official BACEN EMV Co string
  const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(bacenPixPayload)}`;

  if (!isOpen) return null;

  const handleCopyKey = () => {
    navigator.clipboard.writeText(cnpjKey);
    setCopiedKey(true);
    setTimeout(() => setCopiedKey(false), 3000);
  };

  const handleCopyPayload = () => {
    navigator.clipboard.writeText(bacenPixPayload);
    setCopiedPayload(true);
    setTimeout(() => setCopiedPayload(false), 3000);
  };

  const handleSendToChat = () => {
    const message = `💸 *DADOS PARA PAGAMENTO VIA PIX SERVWELD*\n\n` +
      `🏢 *Favorecido:* ${fullName}\n` +
      `🆔 *Chave CNPJ:* ${formattedCnpj}\n\n` +
      `📋 *PIX COPIA E COLA (Cole no App do Banco):*\n\`${bacenPixPayload}\`\n\n` +
      `📲 *QR Code para Leitura:* ${qrCodeUrl}\n\n` +
      `⚠️ *Importante:* Após a transferência, envie o comprovante neste chat para a baixa automática no setor financeiro.`;

    onSendPixToChat(message);
    onClose();
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 2000,
      padding: '16px'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '100%',
        maxWidth: '460px',
        borderRadius: 'var(--radius-lg)',
        backgroundColor: '#0b0f19',
        border: '1px solid var(--border-color)',
        overflow: 'hidden',
        boxShadow: '0 24px 48px rgba(0,0,0,0.6)'
      }}>
        {/* Header Estilo Pix */}
        <div style={{
          padding: '16px 20px',
          backgroundColor: '#111827',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justify: 'space-between',
          alignItems: 'center'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              backgroundColor: 'rgba(234, 179, 8, 0.15)',
              color: '#eab308',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <QrCode size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#fff' }}>Pagamento via Pix</h3>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Padrão Oficial Banco Central (EMV Co)</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          {/* QR Code Container com Moldura de Leitura Garantida */}
          <div style={{
            padding: '16px',
            backgroundColor: '#fff',
            borderRadius: 'var(--radius-md)',
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '8px'
          }}>
            <img
              src={qrCodeUrl}
              alt="QR Code Pix Oficial Banco Central"
              style={{ width: '200px', height: '200px', objectFit: 'contain' }}
            />
            <span style={{ fontSize: '11px', fontWeight: '700', color: '#0f172a' }}>
              ✓ QR Code Oficial Leitura Garantida em Qualquer Banco
            </span>
          </div>

          {/* Details Card */}
          <div style={{
            width: '100%',
            padding: '14px',
            backgroundColor: '#111827',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px'
          }}>
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '700' }}>
                Favorecido / Razão Social
              </div>
              <div style={{ fontSize: '13px', fontWeight: '600', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
                <ShieldCheck size={16} color="#34d399" /> {fullName}
              </div>
            </div>

            {/* Chave CNPJ */}
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '700' }}>
                Chave CNPJ
              </div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 12px',
                backgroundColor: '#1e293b',
                borderRadius: 'var(--radius-md)',
                marginTop: '4px'
              }}>
                <span style={{ fontFamily: 'monospace', fontSize: '13px', fontWeight: '700', color: 'var(--accent-primary)' }}>
                  {formattedCnpj}
                </span>
                <button
                  type="button"
                  onClick={handleCopyKey}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: copiedKey ? '#34d399' : 'var(--text-muted)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '12px',
                    fontWeight: '600'
                  }}
                >
                  {copiedKey ? <Check size={14} /> : <Copy size={14} />}
                  {copiedKey ? 'Copiado!' : 'Copiar CNPJ'}
                </button>
              </div>
            </div>

            {/* Pix Copia e Cola String */}
            <div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '700' }}>
                Pix Copia e Cola (App Bancário)
              </div>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 12px',
                backgroundColor: '#1e293b',
                borderRadius: 'var(--radius-md)',
                marginTop: '4px',
                gap: '8px'
              }}>
                <span style={{
                  fontFamily: 'monospace',
                  fontSize: '11px',
                  color: '#94a3b8',
                  maxWidth: '260px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap'
                }}>
                  {bacenPixPayload}
                </span>
                <button
                  type="button"
                  onClick={handleCopyPayload}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: copiedPayload ? '#34d399' : '#eab308',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '12px',
                    fontWeight: '700',
                    whiteSpace: 'nowrap'
                  }}
                >
                  {copiedPayload ? <Check size={14} /> : <Copy size={14} />}
                  {copiedPayload ? 'Copiado!' : 'Copiar Pix'}
                </button>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div style={{ width: '100%', display: 'flex', gap: '12px', marginTop: '4px' }}>
            <button
              type="button"
              onClick={handleCopyPayload}
              className="btn-secondary"
              style={{ flex: 1, padding: '10px' }}
            >
              <Copy size={16} /> {copiedPayload ? 'Pix Copiado!' : 'Copiar Pix Copia e Cola'}
            </button>

            <button
              type="button"
              onClick={handleSendToChat}
              className="btn-primary"
              style={{ flex: 1, padding: '10px' }}
            >
              <Send size={16} /> Enviar no Chat
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
