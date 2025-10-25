import { useEffect, useState } from 'react';
import TopologyVisualization from './components/TopologyVisualization';
import TopologyStats from './components/TopologyStats';
import topologyService from './services/topologyService';
import { TopologyResponse, Node, Link } from './types/topology';
import './App.css';

function App() {
  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  const [backendStatus, setBackendStatus] = useState<string>('Checking...');

  const fetchTopology = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await topologyService.getTopology();
      setTopology(data);
      setBackendStatus('Connected');
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch topology';
      setError(errorMessage);
      setBackendStatus('Disconnected');
      console.error('Error fetching topology:', err);
    } finally {
      setLoading(false);
    }
  };

  const checkHealth = async () => {
    try {
      await topologyService.checkHealth();
      setBackendStatus('Connected');
    } catch (err) {
      setBackendStatus('Disconnected');
    }
  };

  useEffect(() => {
    fetchTopology();
    checkHealth();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      fetchTopology();
    }, 10000); // Refresh every 10 seconds

    return () => clearInterval(interval);
  }, [autoRefresh]);

  const handleNodeClick = (node: Node) => {
    console.log('Node clicked:', node);
    // You can add more logic here, like showing a modal with node details
  };

  const handleLinkClick = (link: Link) => {
    console.log('Link clicked:', link);
    // You can add more logic here, like showing a modal with link details
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <h1>BGP-LS Topology Viewer</h1>
          <div className="header-actions">
            <div className="status-indicator">
              <span className={`status-dot ${backendStatus === 'Connected' ? 'connected' : 'disconnected'}`}></span>
              <span className="status-text">{backendStatus}</span>
            </div>
            <label className="auto-refresh">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Auto Refresh
            </label>
            <button onClick={fetchTopology} disabled={loading} className="refresh-btn">
              {loading ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>
      </header>

      <main className="app-main">
        {error && (
          <div className="error-banner">
            <strong>Error:</strong> {error}
            <button onClick={fetchTopology} className="retry-btn">
              Retry
            </button>
          </div>
        )}

        <div className="content-grid">
          <div className="topology-section">
            {loading && !topology ? (
              <div className="loading-container">
                <div className="spinner"></div>
                <p>Loading topology...</p>
              </div>
            ) : topology ? (
              <TopologyVisualization
                topology={topology}
                onNodeClick={handleNodeClick}
                onLinkClick={handleLinkClick}
              />
            ) : (
              <div className="empty-state">
                <h3>No Topology Data</h3>
                <p>Unable to load topology. Please check your ODL connection.</p>
              </div>
            )}
          </div>

          <aside className="stats-section">
            <TopologyStats topology={topology} />
          </aside>
        </div>
      </main>
    </div>
  );
}

export default App;
