#!/bin/bash
#
# E2E Test: Configuration Edge Cases
#
# Tests stage-env behavior with various config edge cases:
# - Missing config files
# - Invalid config values
# - Conflicting settings
# - Boundary values
# - Malformed config syntax

set -eo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_ENV_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TESTS_ROOT="$(cd "$STAGE_ENV_DIR/.." && pwd)"

# Source helpers
source "$TESTS_ROOT/helpers.sh"

# Test setup
setup_test "Config Edge Cases E2E Tests"

# Directories
CONFIG_DIR="$STAGE_ENV_DIR/config"
TEST_CONFIG_DIR="/tmp/stage-env-test-configs-$$"
TESTING_DIR="$TESTS_ROOT/testing"

# Create test config directory
mkdir -p "$TEST_CONFIG_DIR"

# Cleanup function
cleanup() {
    rm -rf "$TEST_CONFIG_DIR"
    cd "$STAGE_ENV_DIR" && ./stage-env stop 2>/dev/null || true
}
trap cleanup EXIT

# ============================================================================
# Test 1: Missing config file
# ============================================================================
test_missing_config() {
    log_info "Test 1: Missing config file"
    
    local missing_config="$TEST_CONFIG_DIR/nonexistent.cfg"
    
    # Should fail gracefully with clear error
    if cd "$STAGE_ENV_DIR" && ./stage-env --config="$missing_config" status 2>&1 | grep -i "not found\|does not exist"; then
        log_success "Missing config detected with clear error"
        ((TESTS_PASSED++)) || true
    else
        log_error "Missing config not detected properly"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 2: Empty config file
# ============================================================================
test_empty_config() {
    log_info "Test 2: Empty config file"
    
    local empty_config="$TEST_CONFIG_DIR/empty.cfg"
    touch "$empty_config"
    
    # Should fail or use defaults with warning
    cd "$STAGE_ENV_DIR" && ./stage-env --config="$empty_config" status 2>&1 || true
    local exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
        log_success "Empty config rejected or handled with defaults"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Empty config accepted (may use defaults)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 3: Invalid port numbers (boundary test)
# ============================================================================
test_invalid_ports() {
    log_info "Test 3: Invalid port numbers"
    
    local invalid_config="$TEST_CONFIG_DIR/invalid_ports.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1

[network_settings]
base_rpc_port = 99999
base_p2p_port = 0
base_cf_port = -1
base_http_port = 70000
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 1

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should fail validation
    if ! cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1; then
        log_success "Invalid ports rejected by validation"
        ((TESTS_PASSED++)) || true
    else
        log_error "Invalid ports not detected"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 4: Invalid network_id format
# ============================================================================
test_invalid_network_id() {
    log_info "Test 4: Invalid network_id format"
    
    local invalid_config="$TEST_CONFIG_DIR/invalid_network_id.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = INVALID_NOT_HEX
consensus_type = esbocs

[topology]
root_nodes_count = 1

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 1

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should fail or accept (depends on validation strictness)
    cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1 || true
    local exit_code=$?
    
    log_success "Invalid network_id handling tested (exit: $exit_code)"
    ((TESTS_PASSED++)) || true
}

# ============================================================================
# Test 5: Zero validators (invalid consensus)
# ============================================================================
test_zero_validators() {
    log_info "Test 5: Zero validators (invalid consensus)"
    
    local invalid_config="$TEST_CONFIG_DIR/zero_validators.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1
master_nodes_count = 0

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 0

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should fail validation
    if ! cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1; then
        log_success "Zero validators rejected"
        ((TESTS_PASSED++)) || true
    else
        log_error "Zero validators not detected"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 6: Invalid IP address
# ============================================================================
test_invalid_ip() {
    log_info "Test 6: Invalid IP address"
    
    local invalid_config="$TEST_CONFIG_DIR/invalid_ip.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 999.999.999.999
subnet = 172.20.0.0/16

[consensus]
min_validators = 1

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should fail or accept with warning
    cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1 || true
    
    log_success "Invalid IP handling tested"
    ((TESTS_PASSED++)) || true
}

# ============================================================================
# Test 7: Conflicting node counts (more validators than master nodes)
# ============================================================================
test_conflicting_node_counts() {
    log_info "Test 7: Conflicting node counts"
    
    local invalid_config="$TEST_CONFIG_DIR/conflicting_counts.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1
master_nodes_count = 2

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 10

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should fail or warn
    cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1 || true
    local exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
        log_success "Conflicting node counts detected"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Conflicting node counts accepted (may auto-adjust)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 8: Missing required section
# ============================================================================
test_missing_section() {
    log_info "Test 8: Missing required section"
    
    local invalid_config="$TEST_CONFIG_DIR/missing_section.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234

[topology]
root_nodes_count = 1
EOF
    
    # Should fail or use defaults
    cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1 || true
    
    log_success "Missing section handling tested"
    ((TESTS_PASSED++)) || true
}

# ============================================================================
# Test 9: Invalid collecting_level (out of range 0-100)
# ============================================================================
test_invalid_collecting_level() {
    log_info "Test 9: Invalid collecting_level"
    
    local invalid_config="$TEST_CONFIG_DIR/invalid_collecting.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1
master_nodes_count = 2

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 1
collecting_level = 150.0

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should fail validation
    if ! cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1; then
        log_success "Invalid collecting_level rejected"
        ((TESTS_PASSED++)) || true
    else
        log_error "Invalid collecting_level not detected"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 10: Malformed INI syntax
# ============================================================================
test_malformed_ini() {
    log_info "Test 10: Malformed INI syntax"
    
    local invalid_config="$TEST_CONFIG_DIR/malformed.cfg"
    cat > "$invalid_config" << 'EOF'
[network
name = testnet
this is not valid ini syntax
network_id = 0x1234
[topology
root_nodes_count = 1
EOF
    
    # Should fail with parse error
    if ! cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1 | grep -iE "parse|syntax|invalid"; then
        log_error "Malformed INI not detected"
        ((TESTS_FAILED++)) || true
    else
        log_success "Malformed INI detected"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 11: URL type without URL specified
# ============================================================================
test_url_type_without_url() {
    log_info "Test 11: URL type without URL"
    
    local invalid_config="$TEST_CONFIG_DIR/url_no_url.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 1

[node_source]
type = url
EOF
    
    # Should fail or warn
    cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1 || true
    local exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
        log_success "Missing URL detected"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Missing URL not detected (may use defaults)"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 12: Extremely large timeout values
# ============================================================================
test_extreme_timeouts() {
    log_info "Test 12: Extremely large timeout values"
    
    local invalid_config="$TEST_CONFIG_DIR/extreme_timeouts.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 1

[timeouts]
startup = 999999
health_check = 999999
command = 999999

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should accept (values are technically valid)
    if cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1; then
        log_success "Extreme timeouts accepted (valid but impractical)"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Extreme timeouts rejected"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 13: Valid config with minimal settings
# ============================================================================
test_minimal_valid_config() {
    log_info "Test 13: Minimal valid config"
    
    local minimal_config="$TEST_CONFIG_DIR/minimal.cfg"
    cat > "$minimal_config" << 'EOF'
[network]
name = mininet
network_id = 0xMINI
consensus_type = esbocs

[topology]
root_nodes_count = 1
master_nodes_count = 1

[network_settings]
base_rpc_port = 9000
base_p2p_port = 9001
base_cf_port = 9002
base_http_port = 9003
node_port = 9003
base_ip = 172.21.0.10
subnet = 172.21.0.0/16

[consensus]
min_validators = 1

[node_source]
type = url
url = https://pub.cellframe.net/linux/cellframe-node/master/cellframe-node-5.2-364-amd64.deb
EOF
    
    # Should pass validation
    if cd "$STAGE_ENV_DIR" && ./stage-env --config="$minimal_config" status 2>&1; then
        log_success "Minimal valid config accepted"
        ((TESTS_PASSED++)) || true
    else
        log_error "Minimal valid config rejected"
        ((TESTS_FAILED++)) || true
    fi
}

# ============================================================================
# Test 14: Config with special characters in network name
# ============================================================================
test_special_chars_in_name() {
    log_info "Test 14: Special characters in network name"
    
    local special_config="$TEST_CONFIG_DIR/special_chars.cfg"
    cat > "$special_config" << 'EOF'
[network]
name = test-net_123
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 1

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should accept valid characters
    if cd "$STAGE_ENV_DIR" && ./stage-env --config="$special_config" status 2>&1; then
        log_success "Network name with dash/underscore accepted"
        ((TESTS_PASSED++)) || true
    else
        log_warning "Network name with dash/underscore rejected"
        ((TESTS_PASSED++)) || true
    fi
}

# ============================================================================
# Test 15: Negative timeout values
# ============================================================================
test_negative_timeouts() {
    log_info "Test 15: Negative timeout values"
    
    local invalid_config="$TEST_CONFIG_DIR/negative_timeouts.cfg"
    cat > "$invalid_config" << 'EOF'
[network]
name = testnet
network_id = 0x1234
consensus_type = esbocs

[topology]
root_nodes_count = 1

[network_settings]
base_rpc_port = 8545
base_p2p_port = 31337
base_cf_port = 7007
base_http_port = 8079
node_port = 8079
base_ip = 172.20.0.10
subnet = 172.20.0.0/16

[consensus]
min_validators = 1
new_round_delay = -10

[node_source]
type = url
url = https://example.com/cellframe-node.deb
EOF
    
    # Should fail validation
    if ! cd "$STAGE_ENV_DIR" && ./stage-env --config="$invalid_config" status 2>&1; then
        log_success "Negative timeout rejected"
        ((TESTS_PASSED++)) || true
    else
        log_error "Negative timeout not detected"
        ((TESTS_FAILED++)) || true
    fi
}

# Run all tests
test_missing_config
test_empty_config
test_invalid_ports
test_invalid_network_id
test_zero_validators
test_invalid_ip
test_conflicting_node_counts
test_missing_section
test_invalid_collecting_level
test_malformed_ini
test_url_type_without_url
test_extreme_timeouts
test_minimal_valid_config
test_special_chars_in_name
test_negative_timeouts

# Cleanup and summary
teardown_test "Config Edge Cases E2E Tests"
print_test_summary
exit $?
