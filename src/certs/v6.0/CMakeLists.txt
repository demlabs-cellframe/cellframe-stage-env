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

# SDK 5.x has flat structure: core/include/, crypto/include/, etc.
# SDK 6.x has module structure: module/core/include/, etc.
# Support both by globbing both patterns

# Try flat structure first (5.x)
file(GLOB DAP_SDK_FLAT_INCLUDES LIST_DIRECTORIES true "${DAP_SDK_SRC}/*/include")
# Also try module structure (6.x)
file(GLOB DAP_SDK_MODULE_INCLUDES LIST_DIRECTORIES true "${DAP_SDK_SRC}/module/*/include")

set(DAP_SDK_INCLUDE_DIRS ${DAP_SDK_FLAT_INCLUDES} ${DAP_SDK_MODULE_INCLUDES})

# Pick up cellframe-sdk module includes if available
set(CF_SDK_INCLUDE_DIRS "")
if(EXISTS "${CELLFRAME_SDK_SRC}/modules")
    file(GLOB_RECURSE CF_SDK_INCLUDE_DIRS LIST_DIRECTORIES true "${CELLFRAME_SDK_SRC}/modules/*/include")
endif()

# SDK 5.x build paths
include_directories(
    ${DAP_SDK_INCLUDE_DIRS}
    ${CF_SDK_INCLUDE_DIRS}
    ${DAP_SDK_SRC}/core/src
    ${DAP_SDK_SRC}/core/src/unix
    ${DAP_SDK_BUILD}/core
    ${DAP_SDK_BUILD}/core/json-c
    # json-c source headers (needed for arraylist.h, etc. referenced by build dir json.h)
    ${DAP_SDK_SRC}/3rdparty/json-c
    # uthash headers (needed for utlist.h)
    ${DAP_SDK_SRC}/3rdparty/uthash/src
    # SDK 6.x fallback paths
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

# Link directories - search both SDK build and cellframe-sdk build
link_directories(
    ${DAP_SDK_BUILD}
    ${DAP_SDK_BUILD}/../cellframe-sdk
    ${DAP_SDK_BUILD}/core/json-c
    ${DAP_SDK_BUILD}/3rdparty/libmdbx
    ${DAP_SDK_BUILD}/crypto/XKCP/xkcp_build_src/bin
    ${DAP_SDK_BUILD}/plugin
    ${DAP_SDK_BUILD}/net/app-cli
)

# Compile cellframe-sdk common module sources when available (needed for
# dap_chain_addr_fill_from_key, dap_chain_addr_to_str, etc.)
set(CF_COMMON_SOURCES "")
if(EXISTS "${CELLFRAME_SDK_SRC}/modules/common/dap_chain_common.c")
    list(APPEND CF_COMMON_SOURCES "${CELLFRAME_SDK_SRC}/modules/common/dap_chain_common.c")
    message(STATUS "Using cellframe-sdk common module: ${CELLFRAME_SDK_SRC}/modules/common/dap_chain_common.c")
endif()

# Collect all DAP SDK static libraries
file(GLOB DAP_SDK_LIBS "${DAP_SDK_BUILD}/*/libdap_*.a"
                       "${DAP_SDK_BUILD}/*/*/libdap_*.a"
                       "${DAP_SDK_BUILD}/*/*/*/libdap_*.a"
                       "${DAP_SDK_BUILD}/*/*/*/*/libdap_*.a"
                       "${DAP_SDK_BUILD}/3rdparty/*/*.a"
                       "${DAP_SDK_BUILD}/crypto/XKCP/xkcp_build_src/bin/*.a")

# Specific libraries that need to be linked
set(DAP_JSON_C_LIB "${DAP_SDK_BUILD}/core/json-c/libdap_json-c.a")
if(NOT EXISTS ${DAP_JSON_C_LIB})
    set(DAP_JSON_C_LIB "${DAP_SDK_BUILD}/dap-sdk/core/json-c/libdap_json-c.a")
endif()

set(MDBX_LIB "${DAP_SDK_BUILD}/3rdparty/libmdbx/libmdbx.a")
if(NOT EXISTS ${MDBX_LIB})
    set(MDBX_LIB "${DAP_SDK_BUILD}/dap-sdk/3rdparty/libmdbx/libmdbx.a")
endif()

# XKCP library (for Keccak/SHA3 functions)
set(XKCP_LIB "${DAP_SDK_BUILD}/crypto/XKCP/xkcp_build_src/bin/libdap-XKCP-plainc-native.a")
if(NOT EXISTS ${XKCP_LIB})
    set(XKCP_LIB "${DAP_SDK_BUILD}/dap-sdk/crypto/XKCP/xkcp_build_src/bin/libdap-XKCP-plainc-native.a")
endif()

# Kyber library
set(KYBER_LIB "${DAP_SDK_BUILD}/crypto/src/Kyber/crypto_kem/kyber512/optimized/libdap_crypto_kyber512.a")
if(NOT EXISTS ${KYBER_LIB})
    set(KYBER_LIB "${DAP_SDK_BUILD}/dap-sdk/crypto/src/Kyber/crypto_kem/kyber512/optimized/libdap_crypto_kyber512.a")
endif()

# Collect cellframe-sdk library
set(CELLFRAME_SDK_LIB "${DAP_SDK_BUILD}/../cellframe-sdk/libcellframe-sdk.a")
if(NOT EXISTS ${CELLFRAME_SDK_LIB})
    file(GLOB CELLFRAME_SDK_LIB_GLOB "${DAP_SDK_BUILD}/../cellframe-sdk/*.a")
    if(CELLFRAME_SDK_LIB_GLOB)
        list(GET CELLFRAME_SDK_LIB_GLOB 0 CELLFRAME_SDK_LIB)
    endif()
endif()

message(STATUS "DAP SDK Libraries found: ${DAP_SDK_LIBS}")
message(STATUS "Cellframe SDK Library: ${CELLFRAME_SDK_LIB}")

# === cf-cert-generator ===
add_executable(cf-cert-generator cert-generator.c ${CF_COMMON_SOURCES})

if(CELLFRAME_SDK_LIB AND EXISTS ${CELLFRAME_SDK_LIB})
    target_link_libraries(cf-cert-generator
        -Wl,--whole-archive
        ${CELLFRAME_SDK_LIB}
        -Wl,--no-whole-archive
        ${DAP_SDK_LIBS}
        ${DAP_JSON_C_LIB}
        ${MDBX_LIB}
        ${XKCP_LIB}
        ${KYBER_LIB}
        pthread
        m
        ssl
        crypto
        dl
    )
else()
    target_link_libraries(cf-cert-generator
        ${DAP_SDK_LIBS}
        ${DAP_JSON_C_LIB}
        ${MDBX_LIB}
        ${XKCP_LIB}
        ${KYBER_LIB}
        pthread
        m
        ssl
        crypto
        dl
    )
endif()

# === dap-cert (simple utility) ===
add_executable(dap-cert dap-cert.c ${CF_COMMON_SOURCES})

if(CELLFRAME_SDK_LIB AND EXISTS ${CELLFRAME_SDK_LIB})
    target_link_libraries(dap-cert
        -Wl,--whole-archive
        ${CELLFRAME_SDK_LIB}
        -Wl,--no-whole-archive
        ${DAP_SDK_LIBS}
        ${DAP_JSON_C_LIB}
        ${MDBX_LIB}
        ${XKCP_LIB}
        ${KYBER_LIB}
        pthread
        m
        ssl
        crypto
        dl
    )
else()
    target_link_libraries(dap-cert
        ${DAP_SDK_LIBS}
        ${DAP_JSON_C_LIB}
        ${MDBX_LIB}
        ${XKCP_LIB}
        ${KYBER_LIB}
        pthread
        m
        ssl
        crypto
        dl
    )
endif()
