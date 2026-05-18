# Certificate Tools for Cellframe Node E2E Testing
# Simplified - link against cellframe_sdk shared library
cmake_minimum_required(VERSION 3.10)
project(CellframeCertTools C)

# Allow overriding paths via command-line (for Docker builds)
if(NOT DEFINED DAP_SDK_SRC)
    set(DAP_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../../dap-sdk")
endif()

if(NOT DEFINED DAP_SDK_BUILD)
    set(DAP_SDK_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../../../../build")
endif()

if(NOT DEFINED CELLFRAME_SDK_SRC)
    set(CELLFRAME_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk")
endif()

message(STATUS "Cellframe SDK Build: ${CELLFRAME_SDK_BUILD}")
message(STATUS "Cellframe SDK Source: ${CELLFRAME_SDK_SRC}")
message(STATUS "DAP SDK Source: ${DAP_SDK_SRC}")
message(STATUS "DAP SDK Build: ${DAP_SDK_BUILD}")

# Definitions
add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

# Auto-discover all include directories from dap-sdk modules
file(GLOB_RECURSE DAP_SDK_INCLUDE_DIRS LIST_DIRECTORIES true "${DAP_SDK_SRC}/module/*/include")

# Pick up cellframe-sdk module includes if available
set(CF_SDK_INCLUDE_DIRS "")
if(EXISTS "${CELLFRAME_SDK_SRC}/modules")
    file(GLOB_RECURSE CF_SDK_INCLUDE_DIRS LIST_DIRECTORIES true "${CELLFRAME_SDK_SRC}/modules/*/include")
endif()

include_directories(
    ${DAP_SDK_INCLUDE_DIRS}
    ${CF_SDK_INCLUDE_DIRS}
    ${DAP_SDK_SRC}/module/core/src
    ${DAP_SDK_SRC}/module/core/src/unix
    ${DAP_SDK_BUILD}/module/core
    ${DAP_SDK_BUILD}/module/core/json-c
    ${CELLFRAME_SDK_BUILD}/dap-sdk/module/core
    ${DAP_SDK_SRC}/module/json/include
    ${DAP_SDK_SRC}/module/crypto/include
    ${DAP_SDK_SRC}/module/crypto/src/Kyber/crypto_kem/kyber512/optimized
    ${DAP_SDK_SRC}/module/hash/table/include
    ${DAP_SDK_SRC}/module/hash/include
    ${DAP_SDK_SRC}/module/math/include
    ${DAP_SDK_SRC}/module/io/include
    ${DAP_SDK_SRC}/module/net/common/include
    ${CELLFRAME_SDK_SRC}/modules/common/include
)

# Link directories
link_directories(
    ${DAP_SDK_BUILD}
)

# Compile cellframe-sdk common module sources when available (needed for
# dap_chain_addr_fill_from_key, dap_chain_addr_to_str, etc.)
set(CF_COMMON_SOURCES "")
if(EXISTS "${CELLFRAME_SDK_SRC}/modules/common/dap_chain_common.c")
    list(APPEND CF_COMMON_SOURCES "${CELLFRAME_SDK_SRC}/modules/common/dap_chain_common.c")
    message(STATUS "Using cellframe-sdk common module: ${CELLFRAME_SDK_SRC}/modules/common/dap_chain_common.c")
endif()

# === cf-cert-generator ===
add_executable(cf-cert-generator cert-generator.c ${CF_COMMON_SOURCES})

target_link_libraries(cf-cert-generator
    dap-sdk
    dap-sdk
    pthread
    m
    ssl
    crypto
)

# === dap-cert (simple utility) ===
add_executable(dap-cert dap-cert.c ${CF_COMMON_SOURCES})

target_link_libraries(dap-cert
    dap-sdk
    dap-sdk
    pthread
    m
    ssl
    crypto
)
