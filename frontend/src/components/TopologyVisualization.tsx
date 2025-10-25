import { useEffect, useRef, useState } from 'react';
import cytoscape, { Core, EdgeDefinition, NodeDefinition } from 'cytoscape';
import { TopologyResponse, Node, Link } from '../types/topology';
import '../styles/TopologyVisualization.css';

interface TopologyVisualizationProps {
  topology: TopologyResponse | null;
  onNodeClick?: (node: Node) => void;
  onLinkClick?: (link: Link) => void;
}

const TopologyVisualization: React.FC<TopologyVisualizationProps> = ({
  topology,
  onNodeClick,
  onLinkClick,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [selectedElement, setSelectedElement] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Initialize Cytoscape
    cyRef.current = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#4A90E2',
            'label': 'data(label)',
            'color': '#fff',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': '12px',
            'width': '60px',
            'height': '60px',
            'border-width': '2px',
            'border-color': '#2E5C8A',
            'text-outline-color': '#000',
            'text-outline-width': '1px',
          },
        },
        {
          selector: 'node:selected',
          style: {
            'background-color': '#FF6B6B',
            'border-color': '#C92A2A',
            'border-width': '3px',
          },
        },
        {
          selector: 'edge',
          style: {
            'width': 3,
            'line-color': '#888',
            'target-arrow-color': '#888',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'label': 'data(label)',
            'font-size': '10px',
            'text-rotation': 'autorotate',
            'text-background-color': '#fff',
            'text-background-opacity': 0.8,
            'text-background-padding': '3px',
          },
        },
        {
          selector: 'edge:selected',
          style: {
            'line-color': '#FF6B6B',
            'target-arrow-color': '#FF6B6B',
            'width': 5,
          },
        },
      ],
      layout: {
        name: 'cose',
        idealEdgeLength: 100,
        nodeOverlap: 20,
        refresh: 20,
        fit: true,
        padding: 30,
        randomize: false,
        componentSpacing: 100,
        nodeRepulsion: 400000,
        edgeElasticity: 100,
        nestingFactor: 5,
        gravity: 80,
        numIter: 1000,
        initialTemp: 200,
        coolingFactor: 0.95,
        minTemp: 1.0,
      },
      minZoom: 0.3,
      maxZoom: 3,
    });

    // Add event listeners
    cyRef.current.on('tap', 'node', (evt) => {
      const node = evt.target;
      const nodeData = node.data() as Node;
      setSelectedElement(nodeData.id);
      onNodeClick?.(nodeData);
    });

    cyRef.current.on('tap', 'edge', (evt) => {
      const edge = evt.target;
      const edgeData = edge.data() as Link;
      setSelectedElement(edgeData.id);
      onLinkClick?.(edgeData);
    });

    // Cleanup
    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
      }
    };
  }, [onNodeClick, onLinkClick]);

  useEffect(() => {
    if (!cyRef.current || !topology) return;

    // Convert topology data to Cytoscape format
    const elements: (NodeDefinition | EdgeDefinition)[] = [];

    // Add nodes
    topology.nodes.forEach((node) => {
      elements.push({
        data: {
          id: node.id,
          label: node.name || node.nodeId,
          ...node,
        },
      });
    });

    // Add edges
    topology.links.forEach((link) => {
      const label = link.metric ? `${link.metric}` : '';
      elements.push({
        data: {
          id: link.id,
          source: link.source,
          target: link.target,
          label: label,
          ...link,
        },
      });
    });

    // Update graph
    cyRef.current.elements().remove();
    cyRef.current.add(elements);

    // Run layout
    const layout = cyRef.current.layout({
      name: 'cose',
      idealEdgeLength: 100,
      nodeOverlap: 20,
      refresh: 20,
      fit: true,
      padding: 30,
      randomize: false,
      componentSpacing: 100,
      nodeRepulsion: 400000,
      edgeElasticity: 100,
      nestingFactor: 5,
      gravity: 80,
      numIter: 1000,
      initialTemp: 200,
      coolingFactor: 0.95,
      minTemp: 1.0,
    });

    layout.run();
  }, [topology]);

  const handleFit = () => {
    cyRef.current?.fit(undefined, 50);
  };

  const handleCenter = () => {
    cyRef.current?.center();
  };

  const handleReset = () => {
    cyRef.current?.reset();
  };

  return (
    <div className="topology-container">
      <div className="topology-controls">
        <button onClick={handleFit} className="control-btn">
          Fit
        </button>
        <button onClick={handleCenter} className="control-btn">
          Center
        </button>
        <button onClick={handleReset} className="control-btn">
          Reset
        </button>
      </div>
      <div ref={containerRef} className="topology-canvas" />
      {selectedElement && (
        <div className="selection-info">
          Selected: {selectedElement}
        </div>
      )}
    </div>
  );
};

export default TopologyVisualization;
