import { TopologyResponse, TopologyStats as Stats } from '../types/topology';
import '../styles/TopologyStats.css';

interface TopologyStatsProps {
  topology: TopologyResponse | null;
}

const TopologyStats: React.FC<TopologyStatsProps> = ({ topology }) => {
  if (!topology) {
    return (
      <div className="stats-container">
        <div className="stats-card">
          <h3>No Topology Data</h3>
          <p>Waiting for topology data...</p>
        </div>
      </div>
    );
  }

  const calculateStats = (): Stats => {
    const avgMetric = topology.links.length > 0
      ? topology.links
          .filter(link => link.metric !== undefined)
          .reduce((sum, link) => sum + (link.metric || 0), 0) /
        topology.links.filter(link => link.metric !== undefined).length
      : undefined;

    return {
      nodeCount: topology.nodes.length,
      linkCount: topology.links.length,
      avgLinkMetric: avgMetric ? Math.round(avgMetric) : undefined,
      lastUpdate: new Date(topology.timestamp).toLocaleString(),
    };
  };

  const stats = calculateStats();

  return (
    <div className="stats-container">
      <div className="stats-header">
        <h2>Topology Statistics</h2>
        <span className="topology-id">{topology.topologyId}</span>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Nodes</div>
          <div className="stat-value">{stats.nodeCount}</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Links</div>
          <div className="stat-value">{stats.linkCount}</div>
        </div>

        {stats.avgLinkMetric !== undefined && (
          <div className="stat-card">
            <div className="stat-label">Avg. Metric</div>
            <div className="stat-value">{stats.avgLinkMetric}</div>
          </div>
        )}

        <div className="stat-card full-width">
          <div className="stat-label">Last Update</div>
          <div className="stat-value-small">{stats.lastUpdate}</div>
        </div>
      </div>

      {topology.nodes.length > 0 && (
        <div className="nodes-list">
          <h3>Network Nodes</h3>
          <div className="nodes-scroll">
            {topology.nodes.map((node) => (
              <div key={node.id} className="node-item">
                <div className="node-name">{node.name}</div>
                <div className="node-details">
                  {node.routerId && (
                    <span className="node-detail">Router ID: {node.routerId}</span>
                  )}
                  {node.asNumber && (
                    <span className="node-detail">AS: {node.asNumber}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default TopologyStats;
