cmake_minimum_required(VERSION 3.16)

if(DEFINED ENV{VCPKG_ROOT} AND NOT DEFINED CMAKE_TOOLCHAIN_FILE)
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
        CACHE STRING "")
endif()

project(watcher_tools CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(OpenCV REQUIRED)

add_executable(img_send_test img_send_test.cpp)

target_include_directories(img_send_test PRIVATE ${OpenCV_INCLUDE_DIRS})
target_link_libraries(img_send_test PRIVATE ${OpenCV_LIBS})

if(WIN32)
    target_link_libraries(img_send_test PRIVATE ws2_32)
endif()
