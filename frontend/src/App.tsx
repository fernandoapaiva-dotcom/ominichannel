import React, { useState, useEffect } from 'react';
import { User } from './types';
import { apiFetch } from './services/api';
import { Login } from './pages/Login';
import { Dashboard } from './pages/Dashboard';
import { AudioProvider } from './context/AudioContext';

export const App: React.FC = () => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = async () => {
    const token = localStorage.getItem('token');
    if (!token) {
      setLoading(false);
      return;
    }

    try {
      const userData = await apiFetch('/auth/me');
      setUser(userData);
    } catch (err) {
      localStorage.removeItem('token');
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('token');
    setUser(null);
  };

  if (loading) {
    return (
      <div style={{
        height: '100vh',
        width: '100vw',
        backgroundColor: 'var(--bg-primary)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--accent-primary)',
        fontFamily: 'var(--font-heading)',
        fontSize: '18px'
      }}>
        Carregando OminiChannel...
      </div>
    );
  }

  if (!user) {
    return <Login onLoginSuccess={checkAuth} />;
  }

  return (
    <AudioProvider>
      <Dashboard user={user} onLogout={handleLogout} />
    </AudioProvider>
  );
};

export default App;
