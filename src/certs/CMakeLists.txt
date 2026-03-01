# Certificate Tools for Cellframe Node E2E Testing
# Simplified - link against cellframe_sdk shared library
cmake_minimum_required(VERSION 3.10)
project(CellframeCertTools C)

# Allow overriding paths via command-line (for Docker builds)
if(NOT DEFINED CELLFRAME_SDK_BUILD)
    set(CELLFRAME_SDK_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk/build")
endif()

if(NOT DEFINED CELLFRAME_SDK_SRC)
    set(CELLFRAME_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk")
endif()

# Prefer root dap-sdk (cellframe-sdk's submodule may be outdated)
if(NOT DEFINED DAP_SDK_SRC)
    if(EXISTS "${CELLFRAME_SDK_SRC}/../dap-sdk/module")
        set(DAP_SDK_SRC "${CELLFRAME_SDK_SRC}/../dap-sdk")
    else()
        set(DAP_SDK_SRC "${CELLFRAME_SDK_SRC}/dap-sdk")
    endif()
endif()

message(STATUS "Cellframe SDK Build: ${CELLFRAME_SDK_BUILD}")
message(STATUS "Cellframe SDK Source: ${CELLFRAME_SDK_SRC}")
message(STATUS "DAP SDK Source: ${DAP_SDK_SRC}")

# Definitions
add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

# Include directories - comprehensive for cellframe_sdk
include_directories(
    # Core (new path under module/)
    ${DAP_SDK_SRC}/module/core/include
    ${DAP_SDK_SRC}/module/core/src
    ${DAP_SDK_SRC}/module/core/src/unix
    ${CELLFRAME_SDK_BUILD}/dap-sdk/module/core
    
    # JSON module
    ${DAP_SDK_SRC}/module/json/include
    
    # Crypto
    ${DAP_SDK_SRC}/module/crypto/include
    ${DAP_SDK_SRC}/module/crypto/src/Kyber/crypto_kem/kyber512/optimized
    
    # Hash table (replaces uthash)
    ${DAP_SDK_SRC}/module/hash/table/include
    ${DAP_SDK_SRC}/module/hash/include
    
    # Math
    ${DAP_SDK_SRC}/module/math/include
    
    # I/O
    ${DAP_SDK_SRC}/module/io/include
    
    # Net common
    ${DAP_SDK_SRC}/module/net/common/include
    
    # Chain common (for dap_chain_addr_t)
    ${CELLFRAME_SDK_SRC}/modules/common/include
)

# Link directories
link_directories(
    ${CELLFRAME_SDK_BUILD}
)

# === cf-cert-generator ===
add_executable(cf-cert-generator cert-generator.c)

target_link_libraries(cf-cert-generator
    cellframe_sdk
    pthread
    m
    ssl
    crypto
)

# === dap-cert (simple utility) ===
add_executable(dap-cert dap-cert.c)

target_link_libraries(dap-cert
    cellframe_sdk
    pthread
    m
    ssl
    crypto
)
