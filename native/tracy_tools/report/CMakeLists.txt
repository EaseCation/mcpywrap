cmake_minimum_required(VERSION 3.16)

# 由 build.py 复制到 Tracy 源码根目录下的 mcpy-report/ 后构建，复用 Tracy 自身的 cmake 配置
option(NO_ISA_EXTENSIONS "Disable ISA extensions" OFF)
option(NO_PARALLEL_STL "Disable parallel STL" OFF)

set(NO_STATISTICS OFF)

include(${CMAKE_CURRENT_LIST_DIR}/../cmake/version.cmake)

set(CMAKE_CXX_STANDARD 20)

project(
    mcpy-tracy-report
    LANGUAGES C CXX
    VERSION ${TRACY_VERSION_STRING}
)

include(${CMAKE_CURRENT_LIST_DIR}/../cmake/config.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/../cmake/vendor.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/../cmake/server.cmake)

add_executable(${PROJECT_NAME} src/report.cpp ${COMMON_FILES} ${SERVER_FILES})
target_link_libraries(${PROJECT_NAME} PRIVATE TracyServer)
