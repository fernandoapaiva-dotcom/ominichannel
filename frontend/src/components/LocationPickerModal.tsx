import React, { useState } from 'react';
import { X, MapPin, Navigation, Send, Search } from 'lucide-react';
import { apiFetch } from '../services/api';

interface LocationPickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversationId: number | null;
  onLocationSent?: () => void;
}

export const LocationPickerModal: React.FC<LocationPickerModalProps> = ({
  isOpen,
  onClose,
  conversationId,
  onLocationSent
}) => {
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  const places = [
    {
      id: 'servweld_main',
      name: 'Servsolda Comercial / Servweld',
      address: 'SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226',
      lat: -15.820418,
      lng: -47.956467,
      badge: 'Principal (Localização Oficial)'
    },
    {
      id: 'servweld_tech',
      name: 'Servweld Assistência Técnica e Locação',
      address: 'SOF Sul Quadra 05 Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226',
      lat: -15.820418,
      lng: -47.956467,
      badge: 'Galpão Técnico'
    },
    {
      id: 'dom_bosco',
      name: 'Oficina Dom Bosco',
      address: 'SOF Q 5, Guará, 71215-220, DF, BR',
      lat: -15.821000,
      lng: -47.957000,
      badge: 'Ponto Próximo'
    },
    {
      id: 'decathlon',
      name: 'Decathlon Brasília EPIA Sul',
      address: 'SGV Lt 7/8 - Guará, Brasília - DF',
      lat: -15.818500,
      lng: -47.954000,
      badge: 'Ponto Próximo'
    },
    {
      id: 'casapark',
      name: 'Casa Park Shopping',
      address: 'SGCV Lote 22 - Guará, Brasília - DF',
      lat: -15.823000,
      lng: -47.953000,
      badge: 'Ponto Próximo'
    }
  ];

  const filteredPlaces = places.filter(p => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return p.name.toLowerCase().includes(q) || p.address.toLowerCase().includes(q);
  });

  if (!isOpen) return null;

  const handleSendLocation = async (place: typeof places[0]) => {
    if (!conversationId) return;

    try {
      setLoading(true);
      await apiFetch(`/conversations/${conversationId}/send-location`, {
        method: 'POST',
        body: JSON.stringify({
          name: place.name,
          address: place.address,
          latitude: place.lat,
          longitude: place.lng
        })
      });
      if (onLocationSent) onLocationSent();
      onClose();
    } catch (err: any) {
      alert(err.message || 'Erro ao enviar localização.');
    } finally {
      setLoading(false);
    }
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
        {/* Header Estilo WhatsApp */}
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
              backgroundColor: 'rgba(0, 230, 153, 0.15)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <MapPin size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#fff' }}>Enviar localização</h3>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Card de mapa nativo do WhatsApp</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        {/* Mapa Preview */}
        <div style={{
          height: '140px',
          backgroundColor: '#1e293b',
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundImage: 'radial-gradient(#334155 1px, transparent 1px)',
          backgroundSize: '16px 16px'
        }}>
          <div style={{
            position: 'absolute',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '4px'
          }}>
            <div style={{
              backgroundColor: '#ef4444',
              color: '#fff',
              padding: '6px',
              borderRadius: '50%',
              boxShadow: '0 0 16px rgba(239, 68, 68, 0.8)'
            }}>
              <MapPin size={24} />
            </div>
            <span style={{ fontSize: '11px', fontWeight: '700', backgroundColor: '#0f172a', padding: '2px 8px', borderRadius: '4px', border: '1px solid #334155', color: '#fff' }}>
              Servweld SOF Sul Guará
            </span>
          </div>

          <div style={{ position: 'absolute', bottom: '10px', right: '10px', fontSize: '10px', color: 'var(--text-muted)', backgroundColor: 'rgba(0,0,0,0.6)', padding: '2px 6px', borderRadius: '4px' }}>
            Google Maps GPS (-15.820418, -47.956467)
          </div>
        </div>

        {/* Action Button: Localização Atual */}
        <div
          onClick={() => handleSendLocation(places[0])}
          style={{
            padding: '14px 20px',
            backgroundColor: 'rgba(0, 230, 153, 0.08)',
            borderBottom: '1px solid var(--border-color)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}
        >
          <div style={{ width: '38px', height: '38px', borderRadius: '50%', border: '2px solid var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-primary)' }}>
            <Navigation size={18} />
          </div>
          <div>
            <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--accent-primary)' }}>Localização atual da loja</div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Precisão GPS de 10 metros • SOF Sul Quadra 5</div>
          </div>
        </div>

        {/* Search Input */}
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Buscar locais próximos..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px 8px 36px',
                backgroundColor: '#111827',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: '#fff',
                fontSize: '13px'
              }}
            />
          </div>
        </div>

        {/* Locais Próximos List */}
        <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
          <div style={{ padding: '8px 16px', fontSize: '11px', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
            Locais próximos
          </div>
          {filteredPlaces.map(place => (
            <div
              key={place.id}
              onClick={() => handleSendLocation(place)}
              style={{
                padding: '12px 16px',
                borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>
                  <MapPin size={16} />
                </div>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: '600', color: '#fff' }}>{place.name}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{place.address}</div>
                </div>
              </div>
              <span style={{ fontSize: '10px', color: 'var(--accent-primary)', fontWeight: '600' }}>Enviar ➔</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
