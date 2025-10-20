# Certificate Tools for Cellframe Node E2E Testing
cmake_minimum_required(VERSION 3.10)

# Build cf-cert-generator - multi-node certificate batch generator
add_executable(cf-cert-generator cert-generator.c)

target_link_libraries(cf-cert-generator
    dap_crypto
    dap_core
    dap_chain_common
)

set_target_properties(cf-cert-generator PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/tools
)

# Build dap-cert - single certificate management utility
add_executable(dap-cert dap-cert.c)

target_link_libraries(dap-cert
    dap_crypto
    dap_core
    dap_chain_common
)

set_target_properties(dap-cert PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/tools
)

# Install both tools
install(TARGETS cf-cert-generator dap-cert
    RUNTIME DESTINATION testing/tools
    COMPONENT testing
)