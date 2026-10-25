#include <chrono>
#include <filesystem>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include <opencv2/imgcodecs.hpp>

#include "watcher_sender.h"

// ---------------------------------------------------------------------------
// Exercises watcher::Sender:
//   1. sends every image given on the command line, named by file stem
//   2. sends a centre ROI of the first image (non-contiguous / strided)
//   3. streams synthetic frames from two threads concurrently
// ---------------------------------------------------------------------------

static cv::Mat make_frame(int index, const cv::Scalar& background)
{
    cv::Mat frame(240, 320, CV_8UC3, background);
    const int bar_w = 20;
    const int x     = (index * 4) % (frame.cols - bar_w);
    frame(cv::Rect(x, 0, bar_w, frame.rows)).setTo(cv::Scalar(255, 255, 255));
    return frame;
}

static void stream(const std::string& name, const cv::Scalar& background, int frames)
{
    for (int i = 0; i < frames; ++i) {
        watcher::Sender::send(make_frame(i, background), name);
        std::this_thread::sleep_for(std::chrono::milliseconds(33));
    }
}

int main(int argc, char* argv[])
{
    std::vector<cv::Mat> images;
    for (int i = 1; i < argc; ++i) {
        cv::Mat img = cv::imread(argv[i], cv::IMREAD_UNCHANGED);
        if (img.empty()) {
            std::cerr << "Failed to load image: " << argv[i] << '\n';
            continue;
        }
        watcher::Sender::send(img, std::filesystem::path(argv[i]).stem().string());
        images.push_back(img);
    }

    if (!images.empty()) {
        const cv::Mat& first = images.front();
        cv::Rect roi(first.cols / 4, first.rows / 4, first.cols / 2, first.rows / 2);
        watcher::Sender::send(first(roi), "roi");
    }

    std::thread t0(stream, "anim0", cv::Scalar(128, 0, 0), 150);
    std::thread t1(stream, "anim1", cv::Scalar(0, 0, 128), 150);
    t0.join();
    t1.join();

    const bool flushed = watcher::Sender::flush(5000);
    std::cout << (flushed ? "All images sent" : "Timed out — is watcher running?") << '\n';
    return flushed ? 0 : 1;
}
