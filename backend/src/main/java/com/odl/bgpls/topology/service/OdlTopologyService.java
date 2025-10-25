package com.odl.bgpls.topology.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.odl.bgpls.topology.config.OdlConfig;
import com.odl.bgpls.topology.model.Link;
import com.odl.bgpls.topology.model.Node;
import com.odl.bgpls.topology.model.TopologyResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.util.*;

@Service
@Slf4j
public class OdlTopologyService {

    private final WebClient odlWebClient;
    private final OdlConfig odlConfig;
    private final ObjectMapper objectMapper;

    public OdlTopologyService(WebClient odlWebClient, OdlConfig odlConfig) {
        this.odlWebClient = odlWebClient;
        this.odlConfig = odlConfig;
        this.objectMapper = new ObjectMapper();
    }

    /**
     * Fetch topology data from OpenDaylight
     */
    public Mono<TopologyResponse> getTopology() {
        String topologyPath = odlConfig.getBgplsTopologyPath() + odlConfig.getTopologyId();

        log.info("Fetching topology from ODL: {}", topologyPath);

        return odlWebClient.get()
                .uri(topologyPath)
                .retrieve()
                .bodyToMono(String.class)
                .map(this::parseTopologyData)
                .doOnError(error -> log.error("Error fetching topology from ODL: {}", error.getMessage()))
                .onErrorReturn(createEmptyTopology());
    }

    /**
     * Parse ODL topology JSON response
     */
    private TopologyResponse parseTopologyData(String jsonResponse) {
        try {
            JsonNode root = objectMapper.readTree(jsonResponse);
            JsonNode topology = root.path("topology").get(0);

            List<Node> nodes = parseNodes(topology.path("node"));
            List<Link> links = parseLinks(topology.path("link"));

            return TopologyResponse.builder()
                    .topologyId(odlConfig.getTopologyId())
                    .nodes(nodes)
                    .links(links)
                    .timestamp(System.currentTimeMillis())
                    .build();

        } catch (Exception e) {
            log.error("Error parsing topology data: {}", e.getMessage(), e);
            return createEmptyTopology();
        }
    }

    /**
     * Parse nodes from ODL response
     */
    private List<Node> parseNodes(JsonNode nodesJson) {
        List<Node> nodes = new ArrayList<>();

        if (nodesJson.isArray()) {
            for (JsonNode nodeJson : nodesJson) {
                try {
                    String nodeId = nodeJson.path("node-id").asText();
                    JsonNode bgplsNode = nodeJson.path("l3-unicast-igp-topology:igp-node-attributes");

                    Node.NodeBuilder builder = Node.builder()
                            .id(nodeId)
                            .nodeId(nodeId)
                            .name(extractNodeName(nodeId));

                    // Extract router ID
                    if (bgplsNode.has("router-id")) {
                        String routerId = bgplsNode.path("router-id").asText();
                        builder.routerId(routerId);
                        builder.igpRouterId(routerId);
                    }

                    // Extract AS number
                    JsonNode prefix = nodeJson.path("bgpls-node").path("prefix-descriptors");
                    if (prefix.has("originating-as")) {
                        builder.asNumber(prefix.path("originating-as").asLong());
                    }

                    // Additional attributes
                    Map<String, Object> attributes = new HashMap<>();
                    if (bgplsNode.has("name")) {
                        attributes.put("name", bgplsNode.path("name").asText());
                    }
                    if (!attributes.isEmpty()) {
                        builder.attributes(attributes);
                    }

                    builder.type("router");
                    nodes.add(builder.build());

                } catch (Exception e) {
                    log.warn("Error parsing node: {}", e.getMessage());
                }
            }
        }

        log.info("Parsed {} nodes", nodes.size());
        return nodes;
    }

    /**
     * Parse links from ODL response
     */
    private List<Link> parseLinks(JsonNode linksJson) {
        List<Link> links = new ArrayList<>();

        if (linksJson.isArray()) {
            for (JsonNode linkJson : linksJson) {
                try {
                    String linkId = linkJson.path("link-id").asText();
                    String source = linkJson.path("source").path("source-node").asText();
                    String target = linkJson.path("destination").path("dest-node").asText();

                    Link.LinkBuilder builder = Link.builder()
                            .id(linkId)
                            .linkId(linkId)
                            .source(source)
                            .target(target)
                            .sourceNodeId(source)
                            .targetNodeId(target);

                    // Extract link attributes
                    JsonNode linkAttrs = linkJson.path("l3-unicast-igp-topology:igp-link-attributes");
                    if (linkAttrs.has("metric")) {
                        builder.metric(linkAttrs.path("metric").asLong());
                    }

                    // Extract bandwidth if available
                    if (linkAttrs.has("max-link-bandwidth")) {
                        builder.bandwidth(linkAttrs.path("max-link-bandwidth").asLong());
                    }

                    // Additional attributes
                    Map<String, Object> attributes = new HashMap<>();
                    if (linkAttrs.has("te-metric")) {
                        attributes.put("teMetric", linkAttrs.path("te-metric").asLong());
                    }
                    if (linkAttrs.has("admin-group")) {
                        attributes.put("adminGroup", linkAttrs.path("admin-group").asText());
                    }
                    if (!attributes.isEmpty()) {
                        builder.attributes(attributes);
                    }

                    builder.linkType("bidirectional");
                    links.add(builder.build());

                } catch (Exception e) {
                    log.warn("Error parsing link: {}", e.getMessage());
                }
            }
        }

        log.info("Parsed {} links", links.size());
        return links;
    }

    /**
     * Extract readable node name from node ID
     */
    private String extractNodeName(String nodeId) {
        if (nodeId != null && nodeId.contains("router-id=")) {
            String[] parts = nodeId.split("router-id=");
            if (parts.length > 1) {
                return "Router-" + parts[1].replace("/", "");
            }
        }
        return nodeId;
    }

    /**
     * Create empty topology response
     */
    private TopologyResponse createEmptyTopology() {
        return TopologyResponse.builder()
                .topologyId(odlConfig.getTopologyId())
                .nodes(Collections.emptyList())
                .links(Collections.emptyList())
                .timestamp(System.currentTimeMillis())
                .build();
    }

    /**
     * Get available topologies from ODL
     */
    public Mono<List<String>> getAvailableTopologies() {
        return odlWebClient.get()
                .uri(odlConfig.getNetworkTopologyPath())
                .retrieve()
                .bodyToMono(String.class)
                .map(this::extractTopologyIds)
                .doOnError(error -> log.error("Error fetching topologies: {}", error.getMessage()))
                .onErrorReturn(Collections.emptyList());
    }

    /**
     * Extract topology IDs from response
     */
    private List<String> extractTopologyIds(String jsonResponse) {
        try {
            List<String> topologyIds = new ArrayList<>();
            JsonNode root = objectMapper.readTree(jsonResponse);
            JsonNode topologies = root.path("network-topology").path("topology");

            if (topologies.isArray()) {
                for (JsonNode topology : topologies) {
                    String topologyId = topology.path("topology-id").asText();
                    if (!topologyId.isEmpty()) {
                        topologyIds.add(topologyId);
                    }
                }
            }

            return topologyIds;
        } catch (Exception e) {
            log.error("Error parsing topology IDs: {}", e.getMessage());
            return Collections.emptyList();
        }
    }
}
