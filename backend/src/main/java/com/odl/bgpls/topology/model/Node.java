package com.odl.bgpls.topology.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class Node {
    private String id;
    private String nodeId;
    private String name;
    private String type;
    private String routerId;
    private Long asNumber;
    private String igpRouterId;
    private Map<String, Object> attributes;
}
