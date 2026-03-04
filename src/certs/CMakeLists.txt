# Certificate Tools for Cellframe Node E2E Testing
# Minimal build - only crypto dependencies, no network stack
cmake_minimum_required(VERSION 3.10)
project(CellframeCertTools C)

if(NOT DEFINED CELLFRAME_SDK_BUILD)
    set(CELLFRAME_SDK_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk/build")
endif()

if(NOT DEFINED CELLFRAME_SDK_SRC)
    set(CELLFRAME_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../../cellframe-sdk")
endif()

if(NOT DEFINED DAP_SDK_SRC)
    set(DAP_SDK_SRC "${CELLFRAME_SDK_SRC}/dap-sdk")
endif()

if(NOT DEFINED DAP_SDK_BUILD)
    set(DAP_SDK_BUILD "${CELLFRAME_SDK_BUILD}/dap-sdk")
endif()

message(STATUS "Cellframe SDK Build: ${CELLFRAME_SDK_BUILD}")
message(STATUS "Cellframe SDK Source: ${CELLFRAME_SDK_SRC}")
message(STATUS "DAP SDK Source: ${DAP_SDK_SRC}")
message(STATUS "DAP SDK Build: ${DAP_SDK_BUILD}")

include_directories(
    # dap-sdk modular layout (module/<name>/include)
    ${DAP_SDK_SRC}/module/core/include
    ${DAP_SDK_SRC}/module/core/src
    ${DAP_SDK_SRC}/module/core/src/unix
    ${DAP_SDK_BUILD}/module/core

    ${DAP_SDK_SRC}/module/crypto/include
    ${DAP_SDK_SRC}/module/crypto/src/Kyber/crypto_kem/kyber512/optimized

    ${DAP_SDK_SRC}/module/hash/include
    ${DAP_SDK_SRC}/module/hash/table/include

    ${DAP_SDK_SRC}/module/math/include
    ${DAP_SDK_SRC}/module/json/include
    ${DAP_SDK_SRC}/module/config/include
    ${DAP_SDK_SRC}/module/io/include

    ${DAP_SDK_SRC}/module/net/common/include

    # cellframe-sdk modules
    ${CELLFRAME_SDK_SRC}/modules/common/include
)

add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

link_directories(
    ${CELLFRAME_SDK_BUILD}
    ${DAP_SDK_BUILD}
)

# === cf-cert-generator ===
add_executable(cf-cert-generator cert-generator.c)

target_link_libraries(cf-cert-generator
    cellframe_sdk
    dap-sdk
    pthread
    m
)

# === dap-cert (simple utility) ===
add_executable(dap-cert dap-cert.c)

target_link_libraries(dap-cert
    cellframe_sdk
    dap-sdk
    pthread
    m
)
