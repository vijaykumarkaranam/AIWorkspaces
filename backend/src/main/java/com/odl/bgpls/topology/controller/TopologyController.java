package com.odl.bgpls.topology.controller;

import com.odl.bgpls.topology.model.TopologyResponse;
import com.odl.bgpls.topology.service.OdlTopologyService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/topology")
@RequiredArgsConstructor
@Slf4j
public class TopologyController {

    private final OdlTopologyService topologyService;

    /**
     * Get current BGP-LS topology
     */
    @GetMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ResponseEntity<TopologyResponse>> getTopology() {
        log.info("GET /api/topology - Fetching topology");

        return topologyService.getTopology()
                .map(ResponseEntity::ok)
                .defaultIfEmpty(ResponseEntity.notFound().build());
    }

    /**
     * Get available topologies from ODL
     */
    @GetMapping(value = "/list", produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ResponseEntity<List<String>>> getAvailableTopologies() {
        log.info("GET /api/topology/list - Fetching available topologies");

        return topologyService.getAvailableTopologies()
                .map(ResponseEntity::ok)
                .defaultIfEmpty(ResponseEntity.ok(List.of()));
    }

    /**
     * Health check endpoint
     */
    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        return ResponseEntity.ok(Map.of(
                "status", "UP",
                "service", "BGP-LS Topology Backend",
                "timestamp", String.valueOf(System.currentTimeMillis())
        ));
    }
}
