from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='ares_usb_bridge',
            executable='ares_usb_bridge_node',
            name='ares_usb_bridge_node',
            output='screen'
        )
    ]) 
