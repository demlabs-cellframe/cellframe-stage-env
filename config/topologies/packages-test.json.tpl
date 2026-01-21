{
  "network": {
    "name": "testnet-packages",
    "network_id": "0xABCD",
    "consensus": "esbocs",
    "native_ticker": "TPKG"
  },
  "topology": {
    "root_nodes": {
      "count": 1,
      "role": "root",
      "consensus_participation": false,
      "is_seed_node": true,
      "description": "Root node with debug tools"
    },
    "master_nodes": {
      "count": 2,
      "role": "master",
      "consensus_participation": true,
      "is_seed_node": false,
      "description": "Master nodes with validation tools"
    },
    "full_nodes": {
      "count": 1,
      "role": "full",
      "consensus_participation": false,
      "is_seed_node": false,
      "description": "Full node with monitoring"
    }
  },
  "consensus": {
    "type": "esbocs",
    "min_validators": 2,
    "new_round_delay": 30,
    "collecting_level": 10.0,
    "auth_certs_prefix": "testnet-packages.master",
    "round_start_sync_timeout": 5,
    "round_attempts_max": 2,
    "round_attempt_timeout": 5,
    "consensus_debug": true,
    "min_fee": "0.01"
  },
  "network_settings": {
    "base_rpc_port": 8545,
    "base_p2p_port": 31337,
    "base_cf_port": 7007,
    "base_http_port": 8079,
    "node_port": 8079,
    "base_ip": "172.20.0.10",
    "subnet": "172.20.0.0/16"
  },
  "build": {
    "type": "debug",
    "cellframe_version": "latest"
  },
  "additional_packages": {
    "base": [
      {
        "type": "apt",
        "packages": ["curl", "wget", "net-tools"]
      }
    ],
    "groups": {
      "root": [
        {
          "type": "apt",
          "packages": ["gdb", "strace", "valgrind"]
        },
        {
          "type": "script",
          "stage": "post_install",
          "script": "echo 'consensus-enabled = false' >> /opt/cellframe-node/etc/cellframe-node.cfg"
        }
      ],
      "master": [
        {
          "type": "apt",
          "packages": ["tcpdump", "iotop"]
        }
      ],
      "full": [
        {
          "type": "script",
          "stage": "post_install",
          "script": "echo 'full-node-mode = true' >> /opt/cellframe-node/etc/cellframe-node.cfg"
        }
      ]
    },
    "nodes": {
      "node-1": [
        {
          "type": "script",
          "stage": "post_configure",
          "script": "echo 'Root node specific setup'"
        }
      ]
    }
  }
}
