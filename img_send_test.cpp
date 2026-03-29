#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

#include <opencv2/imgcodecs.hpp>

#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "ws2_32.lib")
using ssize_t = int;
#else
#  include <arpa/inet.h>
#  include <netinet/in.h>
#  include <sys/socket.h>
#  include <unistd.h>
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

static constexpr uint16_t PORT    = 14972;
static constexpr char     HOST[]  = "127.0.0.1";

#pragma pack(push, 1)
struct Header {
    char     magic[4];
    uint32_t type;
    uint32_t width;
    uint32_t height;
    uint32_t channels;
    char     name[16];
};
#pragma pack(pop)

static constexpr uint32_t TYPE_IMAGE = 0;
static constexpr uint32_t TYPE_CLEAR = 1;

// Write exactly n bytes; returns false on failure.
static bool send_all(int fd, const void* buf, size_t n)
{
    const auto* ptr = static_cast<const char*>(buf);
    while (n > 0) {
        ssize_t sent = ::send(fd, ptr, static_cast<int>(n), 0);
        if (sent <= 0) return false;
        ptr += sent;
        n   -= static_cast<size_t>(sent);
    }
    return true;
}

int main(int argc, char* argv[])
{
    if (argc != 2) {
        std::cerr << "Usage: img_send_test <image_path>\n";
        return 1;
    }

    // ------------------------------------------------------------------
    // Load image with OpenCV (always BGR or grayscale)
    // ------------------------------------------------------------------
    cv::Mat img = cv::imread(argv[1], cv::IMREAD_UNCHANGED);
    if (img.empty()) {
        std::cerr << "Failed to load image: " << argv[1] << '\n';
        return 1;
    }

    // Ensure contiguous layout and uint8 depth.
    if (img.depth() != CV_8U) {
        std::cerr << "Only 8-bit images are supported.\n";
        return 1;
    }
    if (!img.isContinuous())
        img = img.clone();

    const uint32_t width    = static_cast<uint32_t>(img.cols);
    const uint32_t height   = static_cast<uint32_t>(img.rows);
    const uint32_t channels = static_cast<uint32_t>(img.channels());

    if (channels != 1 && channels != 3 && channels != 4) {
        std::cerr << "Unsupported channel count: " << channels << '\n';
        return 1;
    }

    // ------------------------------------------------------------------
    // Platform socket setup
    // ------------------------------------------------------------------
#ifdef _WIN32
    WSADATA wsa{};
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        std::cerr << "WSAStartup failed\n";
        return 1;
    }
#endif

    int sock = static_cast<int>(::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP));
    if (sock < 0) {
        std::cerr << "socket() failed\n";
        return 1;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(PORT);
    ::inet_pton(AF_INET, HOST, &addr.sin_addr);

    if (::connect(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
        std::cerr << "connect() failed — is watcher running?\n";
        return 1;
    }

    // ------------------------------------------------------------------
    // Build and send header
    // ------------------------------------------------------------------
    Header hdr{};
    std::memcpy(hdr.magic, "WIMG", 4);
    hdr.type     = TYPE_IMAGE;
    hdr.width    = width;
    hdr.height   = height;
    hdr.channels = channels;
    std::memset(hdr.name, 0, sizeof(hdr.name));

    if (!send_all(sock, &hdr, sizeof(hdr))) {
        std::cerr << "Failed to send header\n";
        return 1;
    }

    // ------------------------------------------------------------------
    // Send pixel data
    // ------------------------------------------------------------------
    const size_t payload = static_cast<size_t>(width) * height * channels;
    if (!send_all(sock, img.data, payload)) {
        std::cerr << "Failed to send pixel data\n";
        return 1;
    }

    std::cout << "Sent " << width << 'x' << height << 'x' << channels
              << " (" << payload << " bytes) to " << HOST << ':' << PORT << '\n';

#ifdef _WIN32
    ::closesocket(sock);
    WSACleanup();
#else
    ::close(sock);
#endif

    return 0;
}
