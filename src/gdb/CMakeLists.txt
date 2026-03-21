# GDB Tool for Cellframe Node E2E Testing
# Direct GDB driver access — no network stack, no event loop
cmake_minimum_required(VERSION 3.10)
project(CellframeGdbTool C)

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
    # dap-sdk core (dap_common.h, dap_time.h, dap_list.h)
    ${DAP_SDK_SRC}/core/include
    ${DAP_SDK_SRC}/core/src
    ${DAP_SDK_SRC}/core/src/unix
    ${DAP_SDK_BUILD}/core

    # dap-sdk modular layout (fallback for different SDK tree shapes)
    ${DAP_SDK_SRC}/module/core/include
    ${DAP_SDK_SRC}/module/core/src
    ${DAP_SDK_SRC}/module/core/src/unix
    ${DAP_SDK_BUILD}/module/core

    # crypto (dap_sign.h, dap_guuid.h)
    ${DAP_SDK_SRC}/crypto/include
    ${DAP_SDK_SRC}/module/crypto/include

    # hash (uthash.h)
    ${DAP_SDK_SRC}/3rdparty/uthash/src
    ${DAP_SDK_SRC}/module/hash/include
    ${DAP_SDK_SRC}/module/hash/table/include

    # json-c (json.h)
    ${DAP_SDK_SRC}/3rdparty/json-c
    ${DAP_SDK_SRC}/module/json/include

    # global-db (dap_global_db_driver.h, dap_global_db_pkt.h)
    ${DAP_SDK_SRC}/global-db/include

    # stream cluster (dap_stream_cluster.h — transitive dep of global_db_driver.h)
    ${DAP_SDK_SRC}/net/stream/stream/include
)

add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

link_directories(
    ${CELLFRAME_SDK_BUILD}
    ${DAP_SDK_BUILD}
)

add_executable(dap-gdb-tool dap-gdb-tool.c)

target_link_libraries(dap-gdb-tool
    cellframe_sdk
    dap-sdk
    pthread
    m
)
