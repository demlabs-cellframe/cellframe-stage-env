# Certificate Tools for Cellframe Node E2E Testing
# Builds against dap-sdk 5.x or 6.x (auto-detected)
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

# DAP_HAS_SDK_INIT can be passed from Docker (based on compiled symbol check)
# Fallback: check if dap_sdk.c.o exists in build tree
if(NOT DEFINED DAP_HAS_SDK_INIT)
    file(GLOB_RECURSE _sdk_init_obj "${DAP_SDK_BUILD}/**/dap_sdk.c.o")
    if(_sdk_init_obj)
        set(DAP_HAS_SDK_INIT ON)
    else()
        set(DAP_HAS_SDK_INIT OFF)
    endif()
endif()

message(STATUS "DAP_HAS_SDK_INIT=${DAP_HAS_SDK_INIT}")

# If no unified init → legacy SDK (pre-6)
# Always use pre-6 API path — current SDK still uses the old API signatures
set(DAP_SDK_PRE_6 ON)

# === cf-cert-generator (dap-sdk only, no cellframe-sdk dependency) ===
add_executable(cf-cert-generator cert-generator.c)

if(DAP_SDK_PRE_6)
    target_compile_definitions(cf-cert-generator PRIVATE DAP_SDK_PRE_6)
endif()

# SDK 5.x: flat layout (core/, crypto/, 3rdparty/, io/)
# SDK 6.x: module/ layout (module/core/, module/crypto/, module/hash/)
# Auto-collect all XKCP include directories
file(GLOB_RECURSE XKCP_DIRS LIST_DIRECTORIES true
    ${DAP_SDK_SRC}/crypto/XKCP/lib/*)

target_include_directories(cf-cert-generator PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${DAP_SDK_SRC}
    # 5.x paths
    ${DAP_SDK_SRC}/core/include
    ${DAP_SDK_SRC}/core/src
    ${DAP_SDK_SRC}/core/src/unix
    ${DAP_SDK_BUILD}/core
    ${DAP_SDK_SRC}/crypto/include
    ${DAP_SDK_SRC}/crypto/src/Kyber/crypto_kem/kyber512/optimized
    ${XKCP_DIRS}
    ${DAP_SDK_SRC}/3rdparty/uthash/src
    ${DAP_SDK_SRC}/3rdparty/json-c
    ${DAP_SDK_BUILD}/core/json-c
    ${DAP_SDK_SRC}/io/include
    ${DAP_SDK_BUILD}/bin/.build
    ${DAP_SDK_BUILD}/bin/.build/libdap-XKCP-x8664-native.a.headers
    # 6.x paths
    ${DAP_SDK_SRC}/module/core/include
    ${DAP_SDK_SRC}/module/core/src
    ${DAP_SDK_SRC}/module/core/src/unix
    ${DAP_SDK_BUILD}/module/core
    ${DAP_SDK_SRC}/module/crypto/include
    ${DAP_SDK_SRC}/module/crypto/src/Kyber/crypto_kem/kyber512/optimized
    ${DAP_SDK_SRC}/module/hash/include
    ${DAP_SDK_SRC}/module/math/include
    ${DAP_SDK_SRC}/module/json/include
    ${DAP_SDK_SRC}/module/io/include
)

target_link_directories(cf-cert-generator PRIVATE ${DAP_SDK_BUILD})
target_link_libraries(cf-cert-generator PRIVATE dap-sdk pthread m ssl crypto)
# Link XKCP if available
find_library(XKCP_LIB NAMES dap-XKCP-x8664-native HINTS ${DAP_SDK_BUILD}/bin/.build)
if(XKCP_LIB)
    target_link_libraries(cf-cert-generator PRIVATE ${XKCP_LIB})
endif()

# === dap-cert (needs cellframe-sdk — built separately when SDK is available) ===
if(DEFINED CELLFRAME_SDK_BUILD AND DEFINED CELLFRAME_SDK_SRC)
    add_executable(dap-cert dap-cert.c)

    if(DAP_SDK_PRE_6)
        target_compile_definitions(dap-cert PRIVATE DAP_SDK_PRE_6)
    endif()

    target_include_directories(dap-cert PRIVATE
        ${DAP_SDK_SRC}/core/include
        ${DAP_SDK_SRC}/core/src
        ${DAP_SDK_SRC}/core/src/unix
        ${DAP_SDK_BUILD}/core
        ${DAP_SDK_SRC}/crypto/include
        ${DAP_SDK_SRC}/crypto/src/Kyber/crypto_kem/kyber512/optimized
        ${DAP_SDK_SRC}/3rdparty/uthash/src
        ${DAP_SDK_SRC}/3rdparty/json-c
        ${DAP_SDK_BUILD}/core/json-c
        ${DAP_SDK_SRC}/io/include
        ${DAP_SDK_SRC}/net/stream/stream/include
        ${CELLFRAME_SDK_SRC}/modules/common/include
    )

    target_link_directories(dap-cert PRIVATE ${CELLFRAME_SDK_BUILD} ${DAP_SDK_BUILD})
    target_link_libraries(dap-cert PRIVATE cellframe_sdk dap-sdk pthread m)
endif()
