#include "watcher_sender.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <climits>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>

#if defined(_WIN32)
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#  ifndef NOMINMAX
#    define NOMINMAX
#  endif
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "ws2_32.lib")
#elif defined(__linux__) || defined(__APPLE__)
#  include <arpa/inet.h>
#  include <cerrno>
#  include <fcntl.h>
#  include <netinet/in.h>
#  include <sys/select.h>
#  include <sys/socket.h>
#  include <sys/time.h>
#  include <unistd.h>
#else
#  error "watcher_sender: unsupported platform"
#endif

// ---------------------------------------------------------------------------
// Protocol (matches ImageReceiver in watcher.py)
//
//  Header: 36 bytes, all fields little-endian
//    [0..3]   char[4]   magic    = 'W','I','M','G'
//    [4..7]   uint32    type     0=image  1=clear history
//    [8..11]  uint32    width
//   [12..15]  uint32    height
//   [16..19]  uint32    channels  1=grayscale  3=BGR  4=BGRA
//   [20..35]  char[16]  name     null-padded UTF-8; name[0]==0 means unnamed
//
//  For type 0 (image): width * height * channels bytes of raw pixel data
//  For type 1 (clear): no payload
// ---------------------------------------------------------------------------

namespace {

constexpr uint16_t PORT              = 14972;
constexpr char     HOST[]            = "127.0.0.1";
constexpr size_t   HEADER_SIZE       = 36;
constexpr size_t   NAME_SIZE         = 16;
constexpr uint32_t TYPE_IMAGE        = 0;
constexpr uint32_t TYPE_CLEAR        = 1;

constexpr size_t   MAX_QUEUE         = 16;     // oldest images dropped beyond this
constexpr int      CONNECT_TIMEOUT_MS = 500;
constexpr int      SEND_TIMEOUT_MS   = 2000;
constexpr auto     RETRY_INTERVAL    = std::chrono::seconds(1);
constexpr int      EXIT_FLUSH_MS     = 1000;   // drain time at exit, if connected

// ---------------------------------------------------------------------------
// Platform socket helpers
// ---------------------------------------------------------------------------

#if defined(_WIN32)
using socket_t = SOCKET;
constexpr socket_t INVALID_SOCK = INVALID_SOCKET;

void close_socket(socket_t s) { ::closesocket(s); }

void set_nonblocking(socket_t s, bool enable)
{
    u_long mode = enable ? 1 : 0;
    ::ioctlsocket(s, FIONBIO, &mode);
}

bool connect_pending() { return ::WSAGetLastError() == WSAEWOULDBLOCK; }

void set_send_timeout(socket_t s, int ms)
{
    DWORD tv = static_cast<DWORD>(ms);
    ::setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&tv), sizeof(tv));
}
#else   // Linux / macOS (POSIX sockets)
using socket_t = int;
constexpr socket_t INVALID_SOCK = -1;

void close_socket(socket_t s) { ::close(s); }

void set_nonblocking(socket_t s, bool enable)
{
    int flags = ::fcntl(s, F_GETFL, 0);
    ::fcntl(s, F_SETFL, enable ? (flags | O_NONBLOCK) : (flags & ~O_NONBLOCK));
}

bool connect_pending() { return errno == EINPROGRESS; }

void set_send_timeout(socket_t s, int ms)
{
    timeval tv{ms / 1000, (ms % 1000) * 1000};
    ::setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
}
#endif

#ifdef MSG_NOSIGNAL
constexpr int SEND_FLAGS = MSG_NOSIGNAL;   // Linux: no SIGPIPE on a closed peer
#else
constexpr int SEND_FLAGS = 0;
#endif

// Connect to the viewer, giving up after timeout_ms. A plain blocking
// connect to a closed localhost port can take ~2s on Windows.
socket_t connect_to_viewer(int timeout_ms)
{
    socket_t s = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCK)
        return INVALID_SOCK;

#ifdef SO_NOSIGPIPE
    int one = 1;
    ::setsockopt(s, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));   // macOS
#endif

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(PORT);
    ::inet_pton(AF_INET, HOST, &addr.sin_addr);

    set_nonblocking(s, true);
    if (::connect(s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        if (!connect_pending()) {
            close_socket(s);
            return INVALID_SOCK;
        }

        fd_set wfds, efds;
        FD_ZERO(&wfds);
        FD_ZERO(&efds);
        FD_SET(s, &wfds);
        FD_SET(s, &efds);   // Windows reports a failed connect here
        timeval tv{timeout_ms / 1000, (timeout_ms % 1000) * 1000};
#ifdef _WIN32
        int n = ::select(0, nullptr, &wfds, &efds, &tv);
#else
        int n = ::select(s + 1, nullptr, &wfds, &efds, &tv);
#endif
        int       err = 0;
        socklen_t len = sizeof(err);
        if (n <= 0 || FD_ISSET(s, &efds)
            || ::getsockopt(s, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&err), &len) != 0
            || err != 0) {
            close_socket(s);
            return INVALID_SOCK;
        }
    }
    set_nonblocking(s, false);
    set_send_timeout(s, SEND_TIMEOUT_MS);
    return s;
}

// Write exactly n bytes; returns false on failure.
bool send_all(socket_t s, const uint8_t* ptr, size_t n)
{
    while (n > 0) {
        int chunk = static_cast<int>(std::min<size_t>(n, INT_MAX));
        auto sent = ::send(s, reinterpret_cast<const char*>(ptr), chunk, SEND_FLAGS);
        if (sent <= 0)
            return false;
        ptr += sent;
        n   -= static_cast<size_t>(sent);
    }
    return true;
}

// ---------------------------------------------------------------------------
// Message encoding
// ---------------------------------------------------------------------------

struct Message {
    std::vector<uint8_t> bytes;   // header + payload, ready to send
    bool                 is_image;
};

void put_u32(uint8_t* p, uint32_t v)
{
    p[0] = static_cast<uint8_t>(v);
    p[1] = static_cast<uint8_t>(v >> 8);
    p[2] = static_cast<uint8_t>(v >> 16);
    p[3] = static_cast<uint8_t>(v >> 24);
}

void write_header(uint8_t* p, uint32_t type, uint32_t width, uint32_t height,
                  uint32_t channels, const std::string& name)
{
    std::memcpy(p, "WIMG", 4);
    put_u32(p + 4,  type);
    put_u32(p + 8,  width);
    put_u32(p + 12, height);
    put_u32(p + 16, channels);
    std::memset(p + 20, 0, NAME_SIZE);
    std::memcpy(p + 20, name.data(), std::min(name.size(), NAME_SIZE - 1));
}

// ---------------------------------------------------------------------------
// Background sender
// ---------------------------------------------------------------------------

class Worker
{
public:
    static Worker& instance()
    {
        static Worker worker;
        return worker;
    }

    void enqueue(Message msg)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stop_)
            return;
        if (queue_.size() >= MAX_QUEUE) {
            // Keep the newest images; never drop a clear command.
            auto it = std::find_if(queue_.begin(), queue_.end(),
                                   [](const Message& m) { return m.is_image; });
            if (it == queue_.end())
                return;
            queue_.erase(it);
        }
        queue_.push_back(std::move(msg));
        work_cv_.notify_one();
    }

    bool flush(int timeout_ms)
    {
        std::unique_lock<std::mutex> lock(mutex_);
        return idle_cv_.wait_for(lock, std::chrono::milliseconds(timeout_ms),
                                 [this] { return queue_.empty() && !busy_; });
    }

    bool connected() const { return connected_; }

private:
    Worker()
    {
#ifdef _WIN32
        WSADATA wsa{};
        ::WSAStartup(MAKEWORD(2, 2), &wsa);
#endif
        thread_ = std::thread(&Worker::run, this);
    }

    ~Worker()
    {
        if (connected_)
            flush(EXIT_FLUSH_MS);
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stop_ = true;
        }
        work_cv_.notify_one();
        thread_.join();
#ifdef _WIN32
        ::WSACleanup();
#endif
    }

    void run()
    {
        socket_t sock         = INVALID_SOCK;
        auto     next_attempt = std::chrono::steady_clock::now();

        std::unique_lock<std::mutex> lock(mutex_);
        while (true) {
            work_cv_.wait(lock, [this] { return stop_ || !queue_.empty(); });
            if (stop_)
                break;

            if (sock == INVALID_SOCK) {
                if (std::chrono::steady_clock::now() < next_attempt) {
                    work_cv_.wait_until(lock, next_attempt, [this] { return stop_; });
                    continue;
                }
                lock.unlock();
                sock = connect_to_viewer(CONNECT_TIMEOUT_MS);
                lock.lock();
                if (sock == INVALID_SOCK) {
                    next_attempt = std::chrono::steady_clock::now() + RETRY_INTERVAL;
                    continue;
                }
                connected_ = true;
            }

            Message msg = std::move(queue_.front());
            queue_.pop_front();
            busy_ = true;
            lock.unlock();

            bool ok = send_all(sock, msg.bytes.data(), msg.bytes.size());

            lock.lock();
            busy_ = false;
            if (!ok) {
                // Viewer closed or stalled; the message is lost. Reconnect later.
                close_socket(sock);
                sock         = INVALID_SOCK;
                connected_   = false;
                next_attempt = std::chrono::steady_clock::now() + RETRY_INTERVAL;
            }
            idle_cv_.notify_all();
        }

        if (sock != INVALID_SOCK)
            close_socket(sock);
        connected_ = false;
    }

    std::mutex              mutex_;
    std::condition_variable work_cv_;   // signals the worker thread
    std::condition_variable idle_cv_;   // signals flush()
    std::deque<Message>     queue_;
    bool                    busy_ = false;
    bool                    stop_ = false;
    std::atomic<bool>       connected_{false};
    std::thread             thread_;
};

} // namespace

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

namespace watcher {

void Sender::send(const void* data, int width, int height, int channels,
                  size_t stride, const std::string& name)
{
    if (!data || width <= 0 || height <= 0
        || (channels != 1 && channels != 3 && channels != 4))
        return;

    const size_t row_bytes = static_cast<size_t>(width) * channels;
    if (stride == 0)
        stride = row_bytes;
    if (stride < row_bytes)
        return;

    Message msg;
    msg.is_image = true;
    msg.bytes.resize(HEADER_SIZE + row_bytes * height);
    write_header(msg.bytes.data(), TYPE_IMAGE, width, height, channels, name);

    const auto* src = static_cast<const uint8_t*>(data);
    uint8_t*    dst = msg.bytes.data() + HEADER_SIZE;
    if (stride == row_bytes) {
        std::memcpy(dst, src, row_bytes * height);
    } else {
        for (int y = 0; y < height; ++y, src += stride, dst += row_bytes)
            std::memcpy(dst, src, row_bytes);
    }

    Worker::instance().enqueue(std::move(msg));
}

void Sender::clear()
{
    Message msg;
    msg.is_image = false;
    msg.bytes.resize(HEADER_SIZE);
    write_header(msg.bytes.data(), TYPE_CLEAR, 0, 0, 0, {});
    Worker::instance().enqueue(std::move(msg));
}

bool Sender::flush(int timeout_ms)
{
    return Worker::instance().flush(timeout_ms);
}

bool Sender::connected()
{
    return Worker::instance().connected();
}

} // namespace watcher
