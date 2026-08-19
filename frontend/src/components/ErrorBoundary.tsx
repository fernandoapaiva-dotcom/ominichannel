import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught React Error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '30px',
          backgroundColor: '#180e15',
          color: '#f87171',
          height: '100vh',
          width: '100vw',
          overflowY: 'auto',
          fontFamily: 'monospace',
          boxSizing: 'border-box'
        }}>
          <h1 style={{ fontSize: '22px', marginBottom: '16px', color: '#ef4444' }}>
            ⚠️ Ocorreu um Erro de Renderização no React
          </h1>
          <p style={{ color: '#fff', fontSize: '14px', marginBottom: '12px' }}>
            <strong>Erro:</strong> {this.state.error?.toString()}
          </p>
          <pre style={{
            backgroundColor: '#000',
            padding: '16px',
            borderRadius: '8px',
            overflowX: 'auto',
            fontSize: '12px',
            color: '#fca5a5'
          }}>
            {this.state.errorInfo?.componentStack || this.state.error?.stack}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: '20px',
              padding: '10px 20px',
              backgroundColor: '#ef4444',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontWeight: 'bold'
            }}
          >
            Recarregar Aplicação (F5)
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
