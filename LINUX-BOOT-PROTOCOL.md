# Linux 发行版内核安装接口

发行版安装文件和配置，kShimC 只读加载。更新内核无需重打包 boot.img。

## 分区与目录

在 `boot/kshim-ext4.config` 配置：PARTUUID 非空时按它查找，留空时按 GPT PARTLABEL 查找，不自动回退。

```ini
CONFIG_KSHIM_BOOT_PARTUUID=""
CONFIG_KSHIM_BOOT_PARTLABEL="ARMADA_BOOT"
```

目标必须唯一，使用干净、受支持的 ext4。PARTLABEL/PARTUUID 不等于文件系统 LABEL/UUID。

路径相对分区根目录；挂载为 `/boot` 时位于 `/boot/kshim/`：

```text
kshim/boot.conf
kshim/systems/distro/entries.conf
kshim/systems/distro/versions/kernel-v1/manifest.conf
kshim/systems/distro/versions/kernel-v1/{Image,board.dtb,initramfs.img}
```

`distro`、`kernel-v1` 分别为系统和版本 ID。载荷路径由 manifest 指定，相对版本目录；禁用软链接、绝对路径、`.`、`..`。路径用可打印 ASCII，不含反斜杠、冒号、空组件。

## 配置

UTF-8、无 BOM、LF 换行、`key=value`，不加引号、排版空格或未知键。支持空行及行首 `#` 注释；禁用重复键、空值、行尾注释、变量、CRLF、Tab。每文件限 8192 字节。

ID 最多 63 字节，匹配 `[A-Za-z0-9_-][A-Za-z0-9_.-]*`；不用 `none`、`current`、`previous` 作 ID。

### boot.conf

```ini
format=1
systems=distro
default=android
timeout_ms=8000
```

`systems` 为逗号分隔的 1～4 个系统 ID。`default` 支持 `android`、`系统/current`、`系统/previous`、`系统/版本ID`。`timeout_ms` 为 `0..600000`，0 表示手选。

仅控制外置菜单；`android` 表示返回一级菜单，其默认项由 boot.img 决定。

### entries.conf

```ini
format=2
current=kernel-v1
previous=none
versions=kernel-v1
```

`versions` 按顺序列出不同版本，须包含 current 和非 none 的 previous；两者不能相同。
菜单按需分页，支持从任意页启动，并能直接打开默认版本所在的页。`entries.conf`
仍受 8192 字节的配置文件大小限制，发布也受启动分区剩余空间限制。
支持分页的加载器须在发布第 9 个可见版本前部署。旧加载器无法读取超过 8 项的列表。

### manifest.conf

以下 `<bytes>`、`<sha256>` 和根 UUID 必须替换为实际值：

```ini
format=1
system_id=distro
title=Example Linux
boot_id=kernel-v1
kernel_release=6.x-example
device=oneplus,opd2413
image=Image
image_size=<bytes>
image_sha256=<sha256>
dtb=board.dtb
dtb_size=<bytes>
dtb_sha256=<sha256>
initrd=initramfs.img
initrd_size=<bytes>
initrd_sha256=<sha256>
cmdline=root=UUID=<root-uuid> rw
```

system_id、boot_id 匹配目录名；title/kernel_release 限 95/127 字节。大小填最终文件的十进制字节数，摘要填 64 位小写十六进制 SHA-256。

无需外置 initramfs 时写 `initrd=none`，并删除 initrd_size、initrd_sha256 两行。

cmdline 为完整单行参数，限 4095 字节，替换 DT bootargs；自行提供 root、rootflags、ostree 等。内核、模块、initramfs 和根部署须配套。

## 载荷限制

- 内核为未压缩、小端 ARM64 Image；头部 image_size 非零，text_offset 小于 2 MiB 且按 64 KiB 对齐。
- DTB 为已应用 overlay 的独立完整文件，根 compatible 含 `oneplus,opd2413`、`qcom,sm8750`。
- 单文件最多 128 MiB，DTB 最多 1 MiB。超过 256 KiB 的 DTB 需要 v15 或更新的加载器，旧版仍限制为 256 KiB。`max(Image文件长度, 头部image_size) + DTB + initramfs` 最多 256 MiB；manifest 的 image_size 填文件长度。运行时另有 1.25 MiB 输出缓冲供设备树修改和内核交接使用。
- ext4 特性限制见 [读取器](boot/vendor/nh-ext4/NhExt4.c)。

## 安装、更新与删除

1. 核对分区，持有系统锁 `kshim/systems/<ID>/.update.lock`；每次更新使用新 boot_id。
2. 在同分区临时目录准备载荷及 manifest，核对摘要，fsync 文件和目录，原子重命名为版本目录。
3. 最后原子替换 entries.conf 并同步父目录：新版本设 current，原 current 设 previous，保留其他版本。
4. 首次安装再加入 boot.conf；持有全局锁 `kshim/.config.lock` 完成读取、合并和写入，保留其他系统配置。两种锁均用 flock。

保留旧版模块和根部署。删除前先移除选择器、版本列表及全局默认引用；八条上限只计可见条目。无自动回退，手选不写回。

参考发布工具：[tools/boot_files.py](tools/boot_files.py)，自动生成 manifest、原子更新选择器。发布后同步，确保文件系统干净。
