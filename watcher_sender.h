#pragma once

// ---------------------------------------------------------------------------
// watcher_sender.h — push images to a running watcher viewer.
//
//   watcher::Sender::send(mat, "name");
//
// All calls are thread safe and never block on the network: images are
// copied into a bounded queue and transmitted by a background thread over a
// single persistent connection to 127.0.0.1:14972. If the viewer is not
// running, the background thread retries periodically; while disconnected
// the queue keeps only the most recent images. Errors are silently ignored.
//
// System-specific code (sockets, threads) lives in watcher_sender.cpp, so
// this header pulls in no platform headers.
// ---------------------------------------------------------------------------

#include <cstddef>
#include <string>

#include <opencv2/core.hpp>

namespace watcher {

class Sender
{
public:
    Sender() = delete;

    // Queue an 8-bit image with 1 (gray), 3 (BGR) or 4 (BGRA) channels.
    // Non-contiguous matrices (e.g. ROIs) are supported. A non-empty name
    // (max 15 UTF-8 bytes) adds the image to the viewer's history, replacing
    // any earlier entry with the same name. Unsupported images are ignored.
    static void send(const cv::Mat& image, const std::string& name = {});

    // Queue raw 8-bit pixels. stride is the distance in bytes between the
    // starts of consecutive rows; 0 means tightly packed (width * channels).
    static void send(const void* data, int width, int height, int channels,
                     size_t stride = 0, const std::string& name = {});

    // Queue a command that clears the viewer's history.
    static void clear();

    // Wait until everything queued so far has been sent. Returns false if
    // the timeout expires first (e.g. because the viewer is not running).
    static bool flush(int timeout_ms = 1000);

    // True while a connection to the viewer is established.
    static bool connected();
};

inline void Sender::send(const cv::Mat& image, const std::string& name)
{
    if (image.empty() || image.dims != 2 || image.depth() != CV_8U)
        return;
    send(image.data, image.cols, image.rows, image.channels(), image.step[0], name);
}

} // namespace watcher
