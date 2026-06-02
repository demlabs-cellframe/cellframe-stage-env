# Top-level CMakeLists for the cf-tools Docker image build.
#
# Builds cf-cert-generator + dap-cert + dap-gdb-tool against an in-tree
# dap-sdk via a single CMake configuration, so all link dependencies are
# resolved by CMake's target graph (no manual .o / .a post-processing).
#
# Dockerfile.tools COPY's this file to /src/CMakeLists.txt and runs
# `cmake /src` once; the SDK and tool sources are arranged under /src/
# by the preceding COPY layers.
#
# Standalone-safe: depends only on stage-env's own src/certs and src/gdb,
# plus whichever dap-sdk / cellframe-sdk the operator wired in.

cmake_minimum_required(VERSION 3.12)
project(cf_tools_root C)

set(BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(BUILD_STATIC ON  CACHE BOOL "" FORCE)
set(BUILD_DAP_SDK_TESTS OFF CACHE BOOL "" FORCE)
set(INSTALL_DAP_SDK OFF CACHE BOOL "" FORCE)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_subdirectory(dap-sdk dap-sdk-build)

# cert-generator / gdb-tool CMakeLists historically link against the
# file-name `dap-sdk` (resolved through link_directories). Expose the
# SDK's CMake target under that name so transitive include dirs and
# OBJECT-library deps flow in automatically.
if(TARGET dap_sdk AND NOT TARGET dap-sdk)
    add_library(dap-sdk ALIAS dap_sdk)
endif()

# Hand the tool subprojects explicit source/build paths — their own
# defaults assume a standalone repo layout that doesn't apply here.
set(DAP_SDK_SRC       "${CMAKE_CURRENT_SOURCE_DIR}/dap-sdk"
    CACHE PATH "" FORCE)
set(DAP_SDK_BUILD     "${CMAKE_CURRENT_BINARY_DIR}/dap-sdk-build"
    CACHE PATH "" FORCE)
set(CELLFRAME_SDK_SRC "${CMAKE_CURRENT_SOURCE_DIR}/cellframe-sdk"
    CACHE PATH "" FORCE)

if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/cert-generator/CMakeLists.txt)
    add_subdirectory(cert-generator)
endif()
if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/gdb-tool/CMakeLists.txt)
    add_subdirectory(gdb-tool)
endif()
