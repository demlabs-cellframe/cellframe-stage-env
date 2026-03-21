# GDB Tool for Cellframe Node E2E Testing
# Direct B-tree access via dap-sdk (no cellframe-sdk dependency)
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

add_executable(dap-gdb-tool dap-gdb-tool.c)

target_include_directories(dap-gdb-tool PRIVATE
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
    ${DAP_SDK_SRC}/module/global-db/include
)

target_link_directories(dap-gdb-tool PRIVATE ${DAP_SDK_BUILD})
target_link_libraries(dap-gdb-tool PRIVATE dap-sdk pthread m)
