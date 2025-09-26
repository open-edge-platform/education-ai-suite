include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include)

add_subdirectory(zello_world)

add_executable(npu_utilization npu_utilization.cpp)
target_link_libraries(npu_utilization ze_loader)
