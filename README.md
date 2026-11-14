# OnePlus Pad 2 Pro kShimC

面向 OnePlus Pad 2 Pro（OPD2413）的启动菜单实现。boot.img 保留 Android 内核，附加 kShimC 和启动清单；Linux 内核、DTB、initramfs 从独立 ext4 启动分区加载，避免多套 Linux 载荷占满 boot.img。

本项目提供 kShimC、构建与镜像打包工具，以及外置启动文件协议。kShimC 本身只读访问启动文件；Linux 文件、配套模块及配置由发行版安装器维护。

## 功能

- 选择原厂 Android，或进入 Linux 系统和内核菜单。
- 最多 4 个 Linux 系统，启动版本支持分页，按需加载选中的一套文件。
- 检查载荷长度与 SHA-256，支持 current/previous 和固定版本选择。
- Atlas 分页菜单，提供中英文、启动延迟、设备信息及电源/高级启动入口；音量键选择，电源键确认。
- 当前 ext4 构建使用 8 MiB 运行体槽。语言和延迟不跨重启保存，未实现启动失败自动回退或独立充电界面。

发行版安装内核、更新 initramfs、管理版本和卸载时，请遵循 [Linux 发行版内核安装接口](LINUX-BOOT-PROTOCOL.md)。其中包含完整目录约定、配置字段、兼容性要求和原子发布流程。

## 使用范围

当前运行时针对 OPD2413 的显示、按键和 UFS 硬件。其他设备需要对应的硬件适配，不能仅替换分区名称或 DTB 就认为兼容。

外置启动源要求 GPT 分区和干净、受支持的 ext4 文件系统。当前不支持从 Btrfs、F2FS、加密分区直接加载这些启动文件，不回放 ext4 日志或修复分区。Linux 根文件系统可以采用其他格式，由其内核和 initramfs 负责挂载。

## 编译前选择启动分区

修改 [boot/kshim-ext4.config](boot/kshim-ext4.config)。

按 GPT 分区名查找：

```ini
CONFIG_KSHIM_BOOT_PARTUUID=""
CONFIG_KSHIM_BOOT_PARTLABEL="ARMADA_BOOT"
```

或指定实际 PARTUUID：

```ini
CONFIG_KSHIM_BOOT_PARTUUID="01234567-89ab-4cde-8f01-23456789abcd"
CONFIG_KSHIM_BOOT_PARTLABEL="ARMADA_BOOT"
```

上面的 UUID 仅为示例。PARTUUID 非空时只按它查找，留空时才按 GPT 分区名查找，不会自动回退。目标必须唯一；GPT 分区名与 ext4 文件系统 LABEL 不同。运行时不依赖 `/dev/sdX` 编号。

## 构建运行体

在仓库根目录执行。构建脚本需要 Docker，以及 [inputs/toolchain.json](inputs/toolchain.json) 中指定的工具链镜像；源码依赖已包含在 `boot/vendor/`，无需在线初始化子模块。如使用工具链归档，先将其导入 Docker；归档位置和摘要也记录在该配置中。

```sh
python3 tools/build_boot_tools.py --mode ext4 --out _build/ext4-tools
```

主要产物：

```text
_build/ext4-tools/kshim/kShimC.bin
_build/ext4-tools/packer/MultiBootKernelPatcher
_build/ext4-tools/result.json
```

修改配置或源码后，复用已有输出目录时增加 `--resume`；首次构建使用新目录。

当前 ext4 模式将运行体填充到 8 MiB。这个范围包含代码、静态数据、BSS、页表、堆和栈，链接时检查是否超限；增加槽容量不会自动扩大 LVGL 缓冲或堆。打包检查器校验运行体长度、ARM64 Image 头和启动清单中的大小是否一致，也兼容带明确槽大小记录的旧 4 MiB ext4 构建报告。

当前 Pad 2 Pro ext4 配置的容量预算如下（v15 起）：

| 项目 | 容量 |
| --- | --- |
| 输入 DTB | 最多 1 MiB |
| 外置 Linux 的 DTB 修改/交接缓冲 | 1.25 MiB |
| LVGL 绘制缓冲 | 两个各 434176 字节，在 3392 像素宽、32 位色下各容纳 32 行 |
| LVGL 堆 | 1 MiB，配置项 `CONFIG_KSHIM_LVGL_HEAP_BYTES` |
| Atlas 字形缓存 | 64/44/28 像素字号分别缓存 16/28/32 个字形 |
| 通用 libc 堆 | 256 KiB，CMake 参数 `KSHIM_HEAP_SIZE=0x40000` |

DTB 发布工具和运行时上限同步为 1 MiB；超过 256 KiB 的 DTB 需使用 v15 或更新加载器。单文件 128 MiB、总载荷 256 MiB 等其他限制维持原值。历史复现模式继续显式使用原 4 MiB 槽和 64 KiB 通用堆。

## 生成 boot.img

准备本设备原厂 Android boot.img，然后执行：

```sh
python3 tools/build_external_boot.py \
  --boot-tools _build/ext4-tools \
  --stock-boot /path/to/stock-android-boot.img \
  --out _build/boot
```

输出为 `_build/boot/boot.img`，输出目录必须是新目录。当前打包入口要求 Android boot header v4、空 ramdisk、无 boot signature 的原始镜像，以及受支持的未压缩 ARM64 内核。它会修改内核入口与少量头部字段，附加 kShimC 和 manifest，更新 boot 头长度、诊断字段、对齐填充及 AVB 摘要元数据。输出采用未签名模式，需要已解锁的 bootloader。

最终布局为：

```text
boot 头 → Android 内核 → 对齐填充 → kShimC → manifest → 填充及 AVB 元数据
```

正常外置 Linux 模式不把 Linux Image、DTB 或 initramfs 放入 boot.img。打包器只生成电脑上的文件，不自动启动或刷写设备，也不修改 init_boot、vendor_boot 或分区表。

需要专门的 Linux 内存回退镜像时，可额外传入完整配套的 `--debug-image`、`--debug-dtb` 和 `--debug-initrd`；此模式以内存 Linux 载荷替换 Android 基底，不用于保留 Android 的正常布局。

## 准备 Linux 启动文件

目标分区根目录的最小结构为：

```text
kshim/
├── boot.conf
└── systems/
    └── distro/
        ├── entries.conf
        └── versions/
            └── kernel-v1/
                ├── manifest.conf
                ├── Image
                ├── board.dtb
                └── initramfs.img
```

若该分区在 Linux 中挂载为 `/boot`，以上文件位于 `/boot/kshim/`。文件路径相对于分区根目录，不能增加多余的 `boot/` 层，也不能使用软链接。`manifest.conf` 必须包含实际大小、SHA-256 和完整内核启动参数，不能只复制三个文件而省略配置。

目录和各字段的完整规范见 [Linux 发行版内核安装接口](LINUX-BOOT-PROTOCOL.md)。该文档也提供可选发布工具 `tools/boot_files.py` 的离线用法；正常内核更新只需发布外置文件，不需重新打包 boot.img。内核模块、initramfs 和根系统部署必须匹配。

## 启动和菜单

先使用临时启动检查目标设备：

```sh
fastboot boot _build/boot/boot.img
```

选择 Android 可继续原厂内核启动路径；选择 `Linux (ext4 /boot)` 后，依次选择系统和内核。内核主行显示 release、`[boot_id]` 和 current/previous 标记。返回项只返回上一级菜单，不代表启动 Android；Android 从一级菜单选择。

分区内 `kshim/boot.conf` 的默认项和超时只控制外置 Linux 菜单，一级菜单的初始默认项与超时来自 boot.img 内的 manifest。菜单手选不会写回 current/previous。更换机型、固件或运行体布局后，都应重新验证 Android、Linux 和菜单返回路径。

## 发行版管理工具

`tools/boot_files.py` 提供以下命令，可选用或作为自行实现的参考：

| 命令 | 功能 |
| --- | --- |
| `publish` | 发布独立新版本，设为 current，保留旧条目 |
| `configure` | 显式管理共享系统列表、外置默认项和超时 |
| `list` | 只读查看某系统的版本 |
| `select` | 更改该系统的 current |
| `rollback` | 交换 current/previous |
| `menu` | 重排、显示或隐藏版本，不删除载荷 |

发行版负责在更新前准备好 Image、DTB、最终 initramfs 和模块，再原子切换配置；不要原地覆盖已公开版本。隐藏或保留旧内核时，也需保留其匹配的模块与根部署。

## 主机检查

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/build_host_checks.py --out _build/host-checks --sanitize
```

可使用生成的检查器验证普通离线 ext4 镜像中的配置和载荷：

```sh
_build/host-checks/check-boot-files /path/to/offline-ext4.img 4096
```

`4096` 是模拟块设备的逻辑扇区字节数，模拟 512 字节扇区时改为 `512`。主机检查不能替代设备上的硬件初始化和内核交接验证。

## 源码与许可证

- `boot/vendor/kshim/`：kShimC 运行时及其依赖；本机基础实现来自 armadaos-freedom，Atlas 界面参考 [tc1911/kShimC4sheng](https://github.com/tc1911/kShimC4sheng)。
- `boot/vendor/packer/`：内核入口补丁和 manifest 打包器。
- `boot/vendor/nh-ext4/`：外置文件读取库，来源与文件级许可见其目录内记录。
- `tools/`：构建、打包、主机检查和可选文件发布工具。
- `tests/`：主机回归检查。

分发时保留仓库及各第三方组件的许可证、版权和来源记录。各部分许可分别见 [LICENSE](LICENSE)、[kShimC LICENSE](boot/vendor/kshim/LICENSE) 及相应第三方目录。
