# T01：隔离环境与 i686-elf 工具链

任务：T01

分支：`feature/T01-environment-toolchain`

状态：**T01 验收通过，待合并**

## 实现摘要

- 固定 Ubuntu WSL、容器 base、Binutils 2.42 和 GCC 13.2.0 的 URL/digest/SHA-256；私有构建 `i686-elf` GCC、ld 和 libgcc。
- 提供 WSL create/enter/backup/destroy、bootstrap/with-env/verify 以及 rootless OCI create/run/destroy 的有界生命周期。
- 使用路径 ownership、reparse/symlink、进程锁、intent/state、镜像 ID/标签和专用 storage 防止越界创建、恢复与清理。
- 代码和 Git 始终位于 Windows 权威工作树；WSL 只运行 Linux 构建与测试。

## 正式 WSL 与工具链证据

正式 `MiniOrangeOS-Dev` 前两次 bootstrap 分别安全失败于官方 `/etc/os-release` symlink 兼容和 T00 root-owned `.local/share` 中间目录，均发生在 apt/工具链写入前；相应 trust/ownership 规则与回归测试修复后，第三次执行约 **6 分 15 秒**，输出 `system_status=complete`、`toolchain_status=built`。紧接第二次执行约 **5 秒**，apt 变更为 0，输出 `toolchain_status=up-to-date`，10 项稳定产物无差异。

安装 prefix 为 `/home/minios/.local/share/miniorangeos-dev/toolchain`；marker 指纹为 `07a384a549e114bdd2e990d042c9ac143fc1e9a0dbc60190e4acbd4be4c4cea5`。实测 GCC 13.2.0、GNU ld 2.42、`i686-elf` dumpmachine、prefix 内 libgcc 与 ELF32 i386 freestanding 编译均 PASS。固定来源详见 `docs/provenance.md`。

最终 WSL 身份加固合入后，正式发行版因尚无可信 identity，`verify.sh` 先按预期返回 FAIL。随后从 Windows 权威工作树执行唯一受审迁移入口：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\environment\wsl\create.ps1 -DistroName MiniOrangeOS-Dev -AuthorizedRoot D:\ApplicationData\MiniOrangeOS -SkipBootstrap
```

迁移只在精确 Lxss 名称、BasePath、非 reparse 目录和 `Version=2` 校验后 provision/validate identity；没有运行 apt 或工具链。迁移后 `verify.sh` PASS，`/etc/miniorangeos/instance.identity` 为 `root:root`、mode `0644`、170 bytes。`apt-packages.lock` SHA-256 仍为 `baddb44eda2d5c4adece0db1e71f4555d43c3c42a941010783676019ca117539`，`state/toolchain.env` SHA-256 仍为 `2196f0f32d8d58a66ad64b0b12cfd8c4c4f52ffaa7e8515954ad7da66693b1d9`，`/var/lib/dpkg/status` mtime 仍为 `1783943414`，证明迁移未触发 apt/dpkg 或工具链重建。报告不记录 Lxss registration GUID。

## 最终全分支审查

独立审查最初提出 6 个 Important，全部完成修复和复审：

- stale/运行中项目容器、stop 后 auto-remove 与 `ready` image/builder 漂移均可安全收敛，foreign replacement fail closed；
- `enter.ps1 -Command` 以单字符串 `bash -lc` 执行并保留参数边界；
- source manifest v2 绑定完整树、源码根 mode 与 hardlink 等价组，漂移在 `configure` 前拒绝；
- lifecycle 强制 Lxss `Version=2`，WSL 使用 root-owned identity，Podman/Docker 使用真实 OCI runtime 事实；
- package-state 由 `openat`/`O_NOFOLLOW`/`O_CLOEXEC` helper 锚定写入，锁不泄漏给 apt/dpkg 子树；
- handled signal 与真实 `SIGKILL` residue 均有恢复回归，未知、foreign、writable 或 hardlink residue 在 apt 前拒绝。

各最终复审均为 Approved，Critical 0、Important 0。`destroy.ps1` 默认 preview、`-Apply` 加精确确认名才注销的语义未改变。

## 备份与 WSL 清理证据

正式发行版备份：

- 路径：`D:\ApplicationData\MiniOrangeOS\exports\MiniOrangeOS-Dev-20260713-221120.tar`
- 大小：`6,179,215,360 bytes`
- SHA-256：`32adf0d27f6fe5be6ab818641c5b5c91d657ab35506dc86ae3f17bcb781e2a3b`

空发行版 `MiniOrangeOS-Dev-Test-Empty` 的 destroy preview 后发行版和目录仍存在；带 `-Apply` 和精确确认名后只删除目标。最终正式 `MiniOrangeOS-Dev` 与 `docker-desktop` 均保留。

## rootless Podman 证据

独立 `MiniOrangeOS-Dev-Test-ContainerHost`：Ubuntu 24.04.4 WSL2、rootless Podman 4.9.3、overlay/crun；固定 base digest 为 `sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54`。

| 操作 | 真实结果 |
|---|---|
| 首次 `create.sh` | `42m48s`，exit 0，state ready |
| 第二次 `create.sh` | `2.951s`，`container_status=up-to-date`，镜像 ID 不变 |
| `run.sh ./environment/verify.sh` | `3.645s`，`result=PASS` |
| `destroy.sh --all` | `2.002s`，项目 image/storage/state 清除 |

集成暴露并修复三个真实缺陷：过长 runroot、错误的 `image rmi` 子命令、普通 `rm -rf` 无法清理 rootless overlay 的 subuid 文件。最终默认 Podman images/containers/volumes 均为 `[]` 且未变化；测试发行版 preview 后仍在，精确 apply 后已注销并删除授权目录。

## 风险与边界

- `/mnt/d` 的大型 context、并行/增量性能和 Linux 权限/大小写语义弱于 ext4；昂贵容器层放在 WSL ext4，后续持续测试。
- Windows 已预存项目外 `D:\ProgramFiles\GreenSoftware\development-tools\mingw64\bin\gdb.exe`；未删除或修改它，项目只拒绝权威工作树或授权环境根造成的 PATH 污染。
- 容器宿主内核是 Microsoft WSL2，不是原生 Linux；原生内核差异由后续 Linux CI 验证。
- 完整外部日志保存在授权环境根；仓库只提交事实摘要，避免提交 4–7 GiB 工具链、VHDX 或备份产物。

## 结论

固定来源、正式 WSL 构建与幂等、identity-only 迁移、备份、空发行版定向销毁、rootless Podman create/run/destroy、最终安全审查闭环和无全局污染均有真实证据。当前状态为 **T01 验收通过，待合并**；合并、merge SHA 与分支清理由 Task 9 完成后回填。
