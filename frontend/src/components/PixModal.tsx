import React, { useState } from 'react';
import { X, QrCode, Copy, Check, Send, ShieldCheck } from 'lucide-react';

interface PixModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSendPixToChat: (pixText: string) => void;
}

export const PixModal: React.FC<PixModalProps> = ({
  isOpen,
  onClose,
  onSendPixToChat
}) => {
  const [copied, setCopied] = useState(false);
  const cnpjKey = "54804458000122";
  const formattedCnpj = "54.804.458/0001-22";
  const companyName = "Servweld / Servsolda Equipamentos e Serviços Ltda";
  const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${cnpjKey}`;

  if (!isOpen) return null;

  const handleCopyKey = () => {
    navigator.clipboard.writeText(cnpjKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 3000);
  };

  const handleSendToChat = () => {
    const message = `💸 *DADOS PARA PAGAMENTO VIA PIX SERVWELD*\n\n` +
      `🏢 *Razão Social:* ${companyName}\n` +
      `🆔 *Chave Pix (CNPJ):* ${formattedCnpj}\n` +
      `🔑 *Chave para Copiar/Colar:* \`${cnpjKey}\`\n\n` +
      `📲 *QR Code para Leitura:* ${qrCodeUrl}\n\n` +
      `⚠️ *Importante:* Após realizar o pagamento, por favor envie o comprovante por aqui para validação no nosso setor financeiro.`;

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
        maxWidth: '440px',
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
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Chave CNPJ Oficial Servweld</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          {/* QR Code Container */}
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
              alt="QR Code Pix Servweld"
              style={{ width: '180px', height: '180px', objectFit: 'contain' }}
            />
            <span style={{ fontSize: '11px', fontWeight: '700', color: '#0f172a' }}>Escaneie com o app do seu Banco</span>
          </div>

          {/* Company Details Card */}
          <div style={{
            width: '100%',
            padding: '14px',
            backgroundColor: '#111827',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px'
          }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '700' }}>
              Favorecido / Razão Social
            </div>
            <div style={{ fontSize: '13px', fontWeight: '600', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <ShieldCheck size={16} color="#34d399" /> {companyName}
            </div>

            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '700', marginTop: '6px' }}>
              Chave Pix CNPJ
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              backgroundColor: '#1e293b',
              borderRadius: 'var(--radius-md)',
              border: '1px solid rgba(255,255,255,0.1)'
            }}>
              <span style={{ fontFamily: 'monospace', fontSize: '14px', fontWeight: '700', color: 'var(--accent-primary)' }}>
                {formattedCnpj}
              </span>
              <button
                type="button"
                onClick={handleCopyKey}
                style={{
                  background: 'none',
                  border: 'none',
                  color: copied ? '#34d399' : 'var(--text-muted)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  fontSize: '12px',
                  fontWeight: '600'
                }}
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
                {copied ? 'Copiado!' : 'Copiar'}
              </button>
            </div>
          </div>

          {/* Action Buttons */}
          <div style={{ width: '100%', display: 'flex', gap: '12px', marginTop: '4px' }}>
            <button
              type="button"
              onClick={handleCopyKey}
              className="btn-secondary"
              style={{ flex: 1, padding: '10px' }}
            >
              <Copy size={16} /> {copied ? 'Chave Copiada!' : 'Copiar Chave'}
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
