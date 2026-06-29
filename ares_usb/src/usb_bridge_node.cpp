#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/float32_multi_array.hpp"

#include "ares_protocol.hpp" // 来自 ares_comm/ARES_bulk_library
#include "ares_usb_comm/helpers.hpp"

#include <vector>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <algorithm>
#include <cctype>
#include <chrono>
#include <atomic>
#include <condition_variable>
#include <thread>
#include <mutex>
#include <memory>

using namespace std::chrono_literals;

namespace ares_usb_comm
{
/**
 * @class UsbPassthroughNode
 * @brief ROS2 节点：动态透传节点。修复了 USB 底层阻塞导致的断连问题。
 */
class UsbPassthroughNode : public rclcpp::Node
{
public:
    UsbPassthroughNode() : Node("usb_passthrough_node")
    {
        RCLCPP_INFO(this->get_logger(), "UsbPassthroughNode starting...");

        add_board(0x0001);
        add_board(0x0002);

        // 定时器 1: 动态发现下发 (TX) 话题 (1Hz)
        topic_discovery_timer_ = this->create_wall_timer(
            1s, std::bind(&UsbPassthroughNode::discover_passthrough_topics, this));

        // 定时器 2: 异步创建上报 (RX) 通道 (10Hz)，剥离高耗时操作
        pub_creation_timer_ = this->create_wall_timer(
            100ms, std::bind(&UsbPassthroughNode::create_pending_publishers, this));

        diagnostics_timer_ = this->create_wall_timer(
            1s, std::bind(&UsbPassthroughNode::report_diagnostics, this));
            
        RCLCPP_INFO(this->get_logger(), "Passthrough bridge initialized. Waiting for topics 't0x...' or USB data...");
    }

    ~UsbPassthroughNode() override
    {
        RCLCPP_INFO(this->get_logger(), "Disconnecting USB devices...");
        for (auto& board : boards_) {
            board->stop_tx();
        }
        for (auto& board : boards_) {
            board->protocol.disconnect();
        }
    }

private:
    struct BoardRoute
    {
        struct PendingFrame
        {
            std::vector<uint8_t> payload;
        };

        explicit BoardRoute(uint16_t usb_pid, rclcpp::Logger node_logger)
            : pid(usb_pid), protocol(usb_pid), logger(node_logger)
        {
        }

        void start_tx()
        {
            tx_thread = std::thread([this]() {
                auto next_connect_attempt = std::chrono::steady_clock::now();
                while (true) {
                    std::unordered_map<uint16_t, PendingFrame> local_frames;
                    {
                        std::unique_lock<std::mutex> lock(tx_mutex);
                        tx_cv.wait(lock, [this]() {
                            return stopping || !pending_frames.empty();
                        });
                        if (stopping) {
                            return;
                        }
                        local_frames.swap(pending_frames);
                    }

                    for (auto& [data_id, frame] : local_frames) {
                        if (!protocol.is_connected() &&
                            !protocol.manages_reconnect()) {
                            const auto now = std::chrono::steady_clock::now();
                            if (now >= next_connect_attempt) {
                                protocol.connect();
                                next_connect_attempt = now + std::chrono::seconds(1);
                            }
                        }
                        if (protocol.send_sync(
                                data_id, frame.payload.data(), frame.payload.size())) {
                            ++tx_success;
                        } else {
                            ++tx_failure;
                        }
                    }
                }
            });
        }

        void enqueue(uint16_t data_id, const std::vector<uint8_t>& payload)
        {
            {
                std::lock_guard<std::mutex> lock(tx_mutex);
                pending_frames[data_id].payload = payload;
            }
            tx_cv.notify_one();
        }

        void stop_tx()
        {
            {
                std::lock_guard<std::mutex> lock(tx_mutex);
                stopping = true;
            }
            tx_cv.notify_one();
            if (tx_thread.joinable()) {
                tx_thread.join();
            }
        }

        uint16_t pid;
        ares::Protocol protocol;
        rclcpp::Logger logger;
        std::mutex tx_mutex;
        std::condition_variable tx_cv;
        std::unordered_map<uint16_t, PendingFrame> pending_frames;
        std::thread tx_thread;
        bool stopping{false};
        std::atomic<uint64_t> tx_success{0};
        std::atomic<uint64_t> tx_failure{0};
        uint64_t last_tx_success{0};
        uint64_t last_tx_failure{0};
        uint64_t last_heartbeat_success{0};
        uint64_t last_heartbeat_failure{0};
    };

    void add_board(uint16_t pid)
    {
        auto board = std::make_unique<BoardRoute>(pid, this->get_logger());
        BoardRoute *board_ptr = board.get();

        board_ptr->protocol.register_sync_callback(
            [this](uint16_t data_id, const uint8_t *data, size_t len) {
                handle_passthrough_rx(data_id, data, len);
            });

        if (!board_ptr->protocol.connect()) {
            RCLCPP_ERROR(
                this->get_logger(),
                "Failed to connect USB device PID=0x%04X, node will keep running but this board is inactive.",
                pid);
        } else {
            RCLCPP_INFO(
                this->get_logger(),
                "USB broadcast target ready: PID=0x%04X.",
                pid);
        }

        board_ptr->start_tx();
        boards_.push_back(std::move(board));
    }

    // ---------------- 动态透传功能 (ROS2 -> 下位机 TX) ------------------------
    void discover_passthrough_topics()
    {
        auto topic_names_and_types = this->get_topic_names_and_types();
        
        for (const auto& [topic_name, types] : topic_names_and_types)
        {
            std::string clean_name = topic_name;
            if (!clean_name.empty() && clean_name[0] == '/') {
                clean_name = clean_name.substr(1);
            }

            if (clean_name.length() > 3 && clean_name.substr(0, 3) == "t0x")
            {
                size_t underscore_pos = clean_name.find('_', 3);
                std::string hex_str = (underscore_pos != std::string::npos) ? clean_name.substr(3, underscore_pos - 3) : clean_name.substr(3);

                bool is_hex = !hex_str.empty() && std::all_of(hex_str.begin(), hex_str.end(), ::isxdigit);
                if (!is_hex) continue;

                bool is_valid_type = false;
                for (const auto& type : types) {
                    if (type == "std_msgs/msg/Float32MultiArray") {
                        is_valid_type = true;
                        break;
                    }
                }
                if (!is_valid_type) continue;

                if (passthrough_subs_.find(clean_name) == passthrough_subs_.end())
                {
                    uint16_t data_id = static_cast<uint16_t>(std::stoul(hex_str, nullptr, 16));
                    auto sub = this->create_subscription<std_msgs::msg::Float32MultiArray>(
                        topic_name, 10,
                        [this, data_id, topic_name](const std_msgs::msg::Float32MultiArray::SharedPtr msg) {
                            this->passthrough_tx_callback(data_id, topic_name, msg);
                        });
                    
                    passthrough_subs_[clean_name] = sub;
                    RCLCPP_INFO(this->get_logger(), "🔗 [TX Channel] ROS Topic: '%s' ---> DataID: 0x%04X", topic_name.c_str(), data_id);
                }
            }
        }
    }

    void passthrough_tx_callback(uint16_t id, const std::string& topic_name, const std_msgs::msg::Float32MultiArray::SharedPtr msg)
    {
        size_t float_count = msg->data.size();
        if (float_count == 0) return;

        size_t byte_len = float_count * 4;
        if (tx_known_lengths_.find(id) == tx_known_lengths_.end() || tx_known_lengths_[id] != byte_len) {
            RCLCPP_INFO(
                this->get_logger(),
                "✅ [TX Broadcast] Topic: '%s' ---> PID=0x0001,0x0002 DataID=0x%04X | %zu Bytes",
                topic_name.c_str(), id, byte_len);
            tx_known_lengths_[id] = byte_len; 
        }

        std::vector<uint8_t> payload(byte_len);
        for (size_t i = 0; i < float_count; ++i)
        {
            const uint8_t *float_bytes = reinterpret_cast<const uint8_t *>(&msg->data[i]);
            payload[i * 4 + 0] = float_bytes[0];
            payload[i * 4 + 1] = float_bytes[1];
            payload[i * 4 + 2] = float_bytes[2];
            payload[i * 4 + 3] = float_bytes[3];
        }

        for (auto& board : boards_) {
            board->enqueue(id, payload);
        }
    }

    // ---------------- 动态透传功能 (下位机 -> ROS2 RX) ------------------------
    /**
     * @brief USB 接收回调。只做数据转换和发布，绝对不执行阻塞操作 (完美复刻 UsbBridgeNode 逻辑)
     */
    void handle_passthrough_rx(uint16_t data_id, const uint8_t *data, size_t len)
    {
        if (len % 4 != 0) return;
        rclcpp::Publisher<std_msgs::msg::Float32MultiArray>::SharedPtr pub = nullptr;
        
        // 快速查找是否已经建立了该 ID 的发布通道
        {
            std::lock_guard<std::mutex> lock(pub_mutex_);
            auto it = passthrough_pubs_.find(data_id);
            if (it != passthrough_pubs_.end()) {
                pub = it->second;
            }
        }

        // 如果通道存在，直接解包并发布
        if (pub) 
        {
            size_t float_count = len / 4;
            auto msg = std_msgs::msg::Float32MultiArray();
            msg.data.resize(float_count);

            for (size_t i = 0; i < float_count; ++i)
            {
                uint32_t temp = (uint32_t)data[i * 4 + 3] << 24 |
                                (uint32_t)data[i * 4 + 2] << 16 |
                                (uint32_t)data[i * 4 + 1] << 8 |
                                (uint32_t)data[i * 4 + 0];
                msg.data[i] = *reinterpret_cast<float *>(&temp);
            }
            
            // 执行发布
            pub->publish(msg);
        } 
        else 
        {
            // 如果通道不存在，将其放入待创建名单，让 ROS 主线程去慢吞吞地创建，保护 USB 线程
            std::lock_guard<std::mutex> lock(pending_mutex_);
            pending_pubs_to_create_.insert(data_id);
        }
    }

    /**
     * @brief 异步创建发布通道。脱离了 USB 中断上下文，安全执行高耗时的 create_publisher
     */
    void create_pending_publishers()
    {
        std::unordered_set<uint16_t> local_pending;
        
        // 快速获取名单并清空
        {
            std::lock_guard<std::mutex> lock(pending_mutex_);
            if (pending_pubs_to_create_.empty()) return;
            std::swap(local_pending, pending_pubs_to_create_);
        }

        // 慢慢创建 ROS 2 Publisher
        for (uint16_t data_id : local_pending)
        {
            char topic_name_buf[32];
            snprintf(topic_name_buf, sizeof(topic_name_buf), "r0x%04X", data_id); 
            std::string clean_name = topic_name_buf; 

            std::lock_guard<std::mutex> lock(pub_mutex_);
            if (passthrough_pubs_.find(data_id) == passthrough_pubs_.end())
            {
                passthrough_pubs_[data_id] = this->create_publisher<std_msgs::msg::Float32MultiArray>(clean_name, 10);
                RCLCPP_INFO(this->get_logger(), "🔗 [RX Channel Built] ID: 0x%04X ---> Topic: '/%s'", data_id, clean_name.c_str());
            }
        }
    }

    void report_diagnostics()
    {
        for (auto& board : boards_) {
            const uint64_t tx_ok = board->tx_success.load();
            const uint64_t tx_fail = board->tx_failure.load();
            const uint64_t heartbeat_ok =
                board->protocol.heartbeat_success_count();
            const uint64_t heartbeat_fail =
                board->protocol.heartbeat_failure_count();

            RCLCPP_INFO(
                this->get_logger(),
                "USB PID=0x%04X online=%s data_ok=%lu/s data_fail=%lu/s heartbeat_ok=%lu/s heartbeat_fail=%lu/s",
                board->pid,
                board->protocol.is_connected() ? "true" : "false",
                static_cast<unsigned long>(tx_ok - board->last_tx_success),
                static_cast<unsigned long>(tx_fail - board->last_tx_failure),
                static_cast<unsigned long>(
                    heartbeat_ok - board->last_heartbeat_success),
                static_cast<unsigned long>(
                    heartbeat_fail - board->last_heartbeat_failure));

            board->last_tx_success = tx_ok;
            board->last_tx_failure = tx_fail;
            board->last_heartbeat_success = heartbeat_ok;
            board->last_heartbeat_failure = heartbeat_fail;
        }
    }

    // ---------------- 成员变量 ------------------------------------------
    std::vector<std::unique_ptr<BoardRoute>> boards_;

    rclcpp::TimerBase::SharedPtr topic_discovery_timer_; 
    rclcpp::TimerBase::SharedPtr pub_creation_timer_; 
    rclcpp::TimerBase::SharedPtr diagnostics_timer_;

    std::unordered_map<std::string, rclcpp::Subscription<std_msgs::msg::Float32MultiArray>::SharedPtr> passthrough_subs_;
    
    // 保护 Publisher 字典的锁
    std::mutex pub_mutex_;
    std::unordered_map<uint16_t, rclcpp::Publisher<std_msgs::msg::Float32MultiArray>::SharedPtr> passthrough_pubs_;

    // 记录长度的字典（用于日志去重）
    std::unordered_map<uint16_t, size_t> tx_known_lengths_;

    // 异步创建相关
    std::mutex pending_mutex_;
    std::unordered_set<uint16_t> pending_pubs_to_create_;
};

} // namespace ares_usb_comm

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);
    {
        auto node = std::make_shared<ares_usb_comm::UsbPassthroughNode>();
        rclcpp::spin(node);
    }
    rclcpp::shutdown();
    return 0;
}
