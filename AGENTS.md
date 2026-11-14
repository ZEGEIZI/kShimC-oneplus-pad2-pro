临时测试使用 fastboot boot，不使用 fastboot flash boot，避免写入 boot 分区。完成测试后固化成果使用 fastboot flash boot。
可以并行进行的测试，尽量一次性进行。已经可行的部分，尽量不要重复测试，避免耗费过多时间

## Pad 2 Pro 调试连接

- USB ACM 为只读诊断协议，可使用 `tools/collect_logs.py`；不是交互 shell。
- 优先只读核查分区及启动文件；调试镜像使用 `fastboot boot`。分区格式化、迁移及固化刷写需要先确认具体目标和验证结果。
- 当前实机测试由用户手动执行：提供带明确版本的测试镜像和 `fastboot boot` 命令，等待其反馈；不要自动重启、临时启动或刷写设备，除非用户再次明确要求代为操作。
