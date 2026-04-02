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

set(DAP_SDK_SRC "${CELLFRAME_SDK_SRC}/dap-sdk")

message(STATUS "Cellframe SDK Build: ${CELLFRAME_SDK_BUILD}")
message(STATUS "Cellframe SDK Source: ${CELLFRAME_SDK_SRC}")
message(STATUS "DAP SDK Source: ${DAP_SDK_SRC}")

# Definitions
add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

# Auto-discover all include directories from dap-sdk modules
file(GLOB_RECURSE DAP_SDK_INCLUDE_DIRS LIST_DIRECTORIES true "${DAP_SDK_SRC}/module/*/include")
# Also pick up cellframe-sdk module includes
file(GLOB_RECURSE CF_SDK_INCLUDE_DIRS LIST_DIRECTORIES true "${CELLFRAME_SDK_SRC}/modules/*/include")

include_directories(
    ${DAP_SDK_INCLUDE_DIRS}
    ${CF_SDK_INCLUDE_DIRS}
    # Platform-specific and generated headers
    ${DAP_SDK_SRC}/module/core/src
    ${DAP_SDK_SRC}/module/core/src/unix
    ${CELLFRAME_SDK_BUILD}/dap-sdk/module/core
    ${CELLFRAME_SDK_BUILD}/dap-sdk/module/core/json-c
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
