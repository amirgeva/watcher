cmake_minimum_required(VERSION 3.16)

# True when built directly, false when pulled in by another project via
# FetchContent / add_subdirectory.
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    set(WATCHER_TOP_LEVEL ON)
else()
    set(WATCHER_TOP_LEVEL OFF)
endif()

if(WATCHER_TOP_LEVEL AND DEFINED ENV{VCPKG_ROOT} AND NOT DEFINED CMAKE_TOOLCHAIN_FILE)
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
        CACHE STRING "")
endif()

project(watcher_tools CXX)

option(WATCHER_BUILD_TESTS "Build the watcher sender test programs" ${WATCHER_TOP_LEVEL})

find_package(Threads REQUIRED)

# Sender library: watcher_sender.h is the public interface; all system
# dependent code is confined to watcher_sender.cpp.
find_package(OpenCV REQUIRED COMPONENTS core)

add_library(watcher_sender STATIC watcher_sender.cpp)
add_library(watcher::sender ALIAS watcher_sender)

target_compile_features(watcher_sender PUBLIC cxx_std_11)
target_include_directories(watcher_sender PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} ${OpenCV_INCLUDE_DIRS})
target_link_libraries(watcher_sender PUBLIC opencv_core PRIVATE Threads::Threads)

if(WIN32)
    target_link_libraries(watcher_sender PRIVATE ws2_32)
endif()

if(WATCHER_BUILD_TESTS)
    find_package(OpenCV REQUIRED COMPONENTS core imgcodecs)

    add_executable(img_send_test img_send_test.cpp)

    target_compile_features(img_send_test PRIVATE cxx_std_17)
    target_include_directories(img_send_test PRIVATE ${OpenCV_INCLUDE_DIRS})
    target_link_libraries(img_send_test PRIVATE ${OpenCV_LIBS})

    if(WIN32)
        target_link_libraries(img_send_test PRIVATE ws2_32)
    endif()

    add_executable(watcher_send_test watcher_send_test.cpp)

    target_compile_features(watcher_send_test PRIVATE cxx_std_17)
    target_link_libraries(watcher_send_test PRIVATE watcher::sender ${OpenCV_LIBS})
endif()
