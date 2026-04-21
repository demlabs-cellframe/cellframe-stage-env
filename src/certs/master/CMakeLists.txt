# Certificate Tools for Cellframe Node E2E Testing
# Simplified - link against cellframe_sdk shared library
cmake_minimum_required(VERSION 3.12)
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

message(STATUS "DAP SDK Source: ${DAP_SDK_SRC}")
message(STATUS "DAP SDK Build: ${DAP_SDK_BUILD}")

# Definitions
add_definitions(-DDAP_OS_UNIX -DDAP_OS_LINUX)

# Include dirs: legacy module/*/include layout and flat master layout (core/include — no module/ prefix)
file(GLOB_RECURSE DAP_SDK_INCLUDE_DIRS LIST_DIRECTORIES true "${DAP_SDK_SRC}/module/*/include")
file(GLOB _dap_flat_includes LIST_DIRECTORIES true "${DAP_SDK_SRC}/*/include")
if(_dap_flat_includes)
    list(APPEND DAP_SDK_INCLUDE_DIRS ${_dap_flat_includes})
endif()

# Pick up cellframe-sdk module includes if available
set(CF_SDK_INCLUDE_DIRS "")
if(EXISTS "${CELLFRAME_SDK_SRC}/modules")
    file(GLOB_RECURSE CF_SDK_INCLUDE_DIRS LIST_DIRECTORIES true "${CELLFRAME_SDK_SRC}/modules/*/include")
endif()

# XKCP: dap_hash.h needs generated config.h (XKCP_has_KeccakP1600) under the SDK build tree, not only source FIPS202/.
set(_XKCP_GEN_INCLUDES "")
file(GLOB_RECURSE _XKCP_CONFIG_CANDIDATES "${DAP_SDK_BUILD}/**/config.h")
foreach(_f ${_XKCP_CONFIG_CANDIDATES})
  string(FIND "${_f}" "XKCP" _is_xkcp)
  if(NOT _is_xkcp EQUAL -1)
    get_filename_component(_xkcp_inc "${_f}" DIRECTORY)
    list(APPEND _XKCP_GEN_INCLUDES "${_xkcp_inc}")
  endif()
endforeach()
if(_XKCP_GEN_INCLUDES)
  list(REMOVE_DUPLICATES _XKCP_GEN_INCLUDES)
endif()

include_directories(
    ${_XKCP_GEN_INCLUDES}
    ${DAP_SDK_INCLUDE_DIRS}
    ${CF_SDK_INCLUDE_DIRS}
    ${DAP_SDK_SRC}/3rdparty/json-c
    ${DAP_SDK_SRC}/3rdparty/uthash/src
    ${DAP_SDK_SRC}/module/core/src
    ${DAP_SDK_SRC}/module/core/src/unix
    ${DAP_SDK_BUILD}/module/core
    ${DAP_SDK_BUILD}/module/core/json-c
    ${DAP_SDK_SRC}/core/src
    ${DAP_SDK_SRC}/core/src/unix
    ${DAP_SDK_BUILD}/core
    ${DAP_SDK_BUILD}/core/json-c
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
