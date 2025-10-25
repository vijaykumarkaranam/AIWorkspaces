package com.odl.bgpls.topology;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class BgplsTopologyApplication {

    public static void main(String[] args) {
        SpringApplication.run(BgplsTopologyApplication.class, args);
    }
}
