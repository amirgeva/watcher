# Integrating the watcher sender

How to send images to watcher from your own CMake project. You change your CMake files once, and after that your code needs only an `#include`.

## Requirements

- CMake 3.16+
- C++11 or later
- OpenCV must be findable by your build (vcpkg, a system package, or `OpenCV_DIR`)

## 1. Edit your `CMakeLists.txt`

Add this once, after `project(...)`:

```cmake
include(FetchContent)
FetchContent_Declare(watcher
    GIT_REPOSITORY https://github.com/amirgeva/watcher.git
    GIT_TAG        main)
FetchContent_MakeAvailable(watcher)
```

Then link the sender into every target that sends images:

```cmake
target_link_libraries(my_app PRIVATE watcher::sender)
```

That is all. Linking the target brings in the include path, OpenCV core, threads and (on Windows) `ws2_32`. Only the sender library is built; watcher's own test programs are skipped.

## 2. Use it in your code

```cpp
#include "watcher_sender.h"

watcher::Sender::send(image);            // cv::Mat: 8-bit, 1/3/4 channels (gray/BGR/BGRA)
watcher::Sender::send(image, "name");    // named: replaces the history entry with that name
```

The calls are thread safe and never block. If watcher isn't running, the images are dropped silently.

## Optional

- **Pin a version:** set `GIT_TAG` to a tag or commit hash instead of `main`.
- **Use a local checkout instead of downloading:** configure with
  `-DFETCHCONTENT_SOURCE_DIR_WATCHER=/path/to/watcher`.
