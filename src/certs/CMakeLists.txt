# Certificate Tools for Cellframe Node E2E Testing
cmake_minimum_required(VERSION 3.10)
project(CellframeCertTools C)

if(NOT DEFINED DAP_SDK_SRC)
    set(DAP_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../../lib/dap-sdk")
endif()

if(NOT DEFINED DAP_SDK_BUILD)
    set(DAP_SDK_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../../../../build/lib/dap-sdk")
endif()

message(STATUS "DAP SDK Source: ${DAP_SDK_SRC}")
message(STATUS "DAP SDK Build: ${DAP_SDK_BUILD}")

add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

# === cf-cert-generator (dap-sdk only, no cellframe-sdk dependency) ===
add_executable(cf-cert-generator cert-generator.c)

target_include_directories(cf-cert-generator PRIVATE
    ${DAP_SDK_SRC}
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
    ${DAP_SDK_SRC}/module/cluster/include
)

target_link_directories(cf-cert-generator PRIVATE ${DAP_SDK_BUILD})
target_link_libraries(cf-cert-generator PRIVATE dap-sdk pthread m)

# === dap-cert (needs cellframe-sdk — built separately when SDK is available) ===
if(DEFINED CELLFRAME_SDK_BUILD AND DEFINED CELLFRAME_SDK_SRC)
    add_executable(dap-cert dap-cert.c)

    target_include_directories(dap-cert PRIVATE
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
        ${DAP_SDK_SRC}/module/net/stream/stream/include
        ${DAP_SDK_SRC}/module/cluster/include
        ${CELLFRAME_SDK_SRC}/modules/common/include
    )

    target_link_directories(dap-cert PRIVATE ${CELLFRAME_SDK_BUILD} ${DAP_SDK_BUILD})
    target_link_libraries(dap-cert PRIVATE cellframe_sdk dap-sdk pthread m)
endif()
