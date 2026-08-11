# GDB Tool for Cellframe Node E2E Testing
# Builds against dap-sdk 5.x (btree API) or 6.x (driver API)
cmake_minimum_required(VERSION 3.10)
project(CellframeGdbTool C)

if(NOT DEFINED DAP_SDK_SRC)
    set(DAP_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/../../../../lib/dap-sdk")
endif()

if(NOT DEFINED DAP_SDK_BUILD)
    set(DAP_SDK_BUILD "${CMAKE_CURRENT_SOURCE_DIR}/../../../../build/lib/dap-sdk")
endif()

message(STATUS "DAP SDK Source: ${DAP_SDK_SRC}")
message(STATUS "DAP SDK Build: ${DAP_SDK_BUILD}")

add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

# Detect which GDB API to use by checking actual headers.
# Check both flat layout (5.x: global-db/) and module layout (6.x: module/global-db/)
if(EXISTS "${DAP_SDK_SRC}/global-db/include/dap_global_db_btree.h" OR
   EXISTS "${DAP_SDK_SRC}/module/global-db/include/dap_global_db_btree.h")
    message(STATUS "GDB API: B-tree cursor (dap_global_db_btree.h)")
    set(DAP_SDK_PRE_6 ON)
elseif(EXISTS "${DAP_SDK_SRC}/global-db/include/dap_global_db_driver.h" OR
       EXISTS "${DAP_SDK_SRC}/module/global-db/include/dap_global_db_driver.h")
    message(STATUS "GDB API: Driver-level (dap_global_db_driver.h)")
    set(DAP_SDK_PRE_6 OFF)
else()
    message(FATAL_ERROR "No supported GDB API found in ${DAP_SDK_SRC}")
endif()

add_executable(dap-gdb-tool dap-gdb-tool.c)

if(DAP_SDK_PRE_6)
    target_compile_definitions(dap-gdb-tool PRIVATE DAP_SDK_PRE_6)
endif()

target_compile_definitions(dap-gdb-tool PRIVATE XKCP_has_KeccakP1600)

# Auto-collect all XKCP include directories (dirs only)
file(GLOB XKCP_HIGH_DIRS LIST_DIRECTORIES true ${DAP_SDK_SRC}/crypto/XKCP/lib/high/*)
file(GLOB XKCP_LOW_DIRS LIST_DIRECTORIES true ${DAP_SDK_SRC}/crypto/XKCP/lib/low/*)
file(GLOB XKCP_LOW_1600_DIRS LIST_DIRECTORIES true ${DAP_SDK_SRC}/crypto/XKCP/lib/low/KeccakP-1600/*)
set(XKCP_DIRS ${XKCP_HIGH_DIRS} ${XKCP_LOW_DIRS} ${XKCP_LOW_1600_DIRS}
    ${DAP_SDK_SRC}/crypto/XKCP/lib/common
    ${DAP_SDK_SRC}/crypto/XKCP/lib/low/common
    ${DAP_SDK_SRC}/crypto/XKCP/lib/high/Keccak/FIPS202
    ${DAP_SDK_SRC}/crypto/XKCP/lib/high/Keccak)

# SDK 5.x: flat layout (core/, crypto/, global-db/, net/)
# SDK 6.x: module layout (module/core/, module/crypto/, module/global-db/)
target_include_directories(dap-gdb-tool PRIVATE
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
    ${DAP_SDK_SRC}/global-db/include
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
    ${DAP_SDK_SRC}/module/global-db/include
    ${DAP_SDK_SRC}/module/cluster/include
    ${DAP_SDK_SRC}/module/net/common/include
)

# 5.x driver path needs net/stream headers (dap_global_db_driver.h → dap_stream_cluster.h)
if(NOT DAP_SDK_PRE_6)
    target_include_directories(dap-gdb-tool PRIVATE
        ${DAP_SDK_SRC}/net/stream/stream/include
        ${DAP_SDK_SRC}/net/stream/ch/include
        ${DAP_SDK_SRC}/net/link_manager/include
        ${DAP_SDK_SRC}/net/common/server/include
    )
endif()

target_link_directories(dap-gdb-tool PRIVATE ${DAP_SDK_BUILD})
target_link_libraries(dap-gdb-tool PRIVATE dap-sdk pthread m ssl crypto)
