export interface Node {
  id: string;
  nodeId: string;
  name: string;
  type: string;
  routerId?: string;
  asNumber?: number;
  igpRouterId?: string;
  attributes?: Record<string, any>;
}

export interface Link {
  id: string;
  linkId: string;
  source: string;
  target: string;
  sourceNodeId: string;
  targetNodeId: string;
  metric?: number;
  bandwidth?: number;
  linkType?: string;
  attributes?: Record<string, any>;
}

export interface TopologyResponse {
  topologyId: string;
  nodes: Node[];
  links: Link[];
  timestamp: number;
}

export interface TopologyStats {
  nodeCount: number;
  linkCount: number;
  avgLinkMetric?: number;
  lastUpdate: string;
}
