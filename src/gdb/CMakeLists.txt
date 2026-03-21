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

# Detect SDK version by checking for dap_sdk.h (unified init, present in 6.0+)
# AND dap_global_db_btree.h (btree cursor API, only in custom builds)
if(NOT EXISTS "${DAP_SDK_SRC}/dap_sdk.h")
    message(STATUS "No dap_sdk.h — legacy SDK detected")
    set(DAP_SDK_PRE_6 ON)
elseif(EXISTS "${DAP_SDK_SRC}/global-db/include/dap_global_db_btree.h")
    message(STATUS "Detected dap_global_db_btree.h — btree API")
    set(DAP_SDK_PRE_6 ON)
else()
    message(STATUS "Detected DAP SDK 6+ (driver API)")
    set(DAP_SDK_PRE_6 OFF)
endif()

add_executable(dap-gdb-tool dap-gdb-tool.c)

if(DAP_SDK_PRE_6)
    target_compile_definitions(dap-gdb-tool PRIVATE DAP_SDK_PRE_6)
endif()

# Include paths — common core + version-specific
target_include_directories(dap-gdb-tool PRIVATE
    ${DAP_SDK_SRC}
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
    ${DAP_SDK_SRC}/global-db/include
)

# 6.x needs net/stream headers for dap_global_db_driver.h -> dap_stream_cluster.h
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
