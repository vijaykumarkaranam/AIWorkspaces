package com.odl.bgpls.topology.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties(prefix = "odl")
@Data
public class OdlConfig {

    private String baseUrl = "http://localhost:8181";
    private String username = "admin";
    private String password = "admin";
    private String topologyId = "example-linkstate-topology";

    // BGP-LS specific paths
    private String networkTopologyPath = "/restconf/data/network-topology:network-topology";
    private String bgplsTopologyPath = "/restconf/data/network-topology:network-topology/topology=";
}
