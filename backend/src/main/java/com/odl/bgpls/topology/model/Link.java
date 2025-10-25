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
public class Link {
    private String id;
    private String linkId;
    private String source;
    private String target;
    private String sourceNodeId;
    private String targetNodeId;
    private Long metric;
    private Long bandwidth;
    private String linkType;
    private Map<String, Object> attributes;
}
