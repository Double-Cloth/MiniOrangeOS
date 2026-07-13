# T01 隔离环境生命周期和交叉工具链实施计划

> 执行方式：Subagent-Driven Development。每个 Task 使用新的实现代理，提交后由独立审查代理检查；Critical/Important 必须修复并复审。

目标：实现可重复、可审计、可备份、可定向删除的 `MiniOrangeOS-Dev` 与真实 Ubuntu 容器环境，并从固定源码构建 `i686-elf` Binutils/GCC。

设计依据：`docs/superpowers/specs/2026-07-13-t01-environment-toolchain-design.md`

分支：`feature/T01-environment-toolchain`

## 全局约束

- 文件修改与 Git 只在 Windows 权威工作树执行；WSL 和容器内禁止运行 Git。
- 所有脚本、测试和文档使用 UTF-8/LF；Shell 使用 `set -euo pipefail`。
- 不修改 Windows PATH、注册表、全局 Git、Linux Shell 启动文件或宿主 `/usr/local`。
- 不自动安装 Podman/Docker，不执行任何全局 prune。
- 所有删除前验证解析后的绝对路径和精确资源名；默认只预览。
- 下载必须先校验 SHA-256，再解包或构建。
- 不声称未运行的 WSL、容器、备份或删除测试为 PASS。

---

## Task 1：建立 T01 RED 契约测试

**Files:**

- Create: `tests/host/test_environment_contract.py`
- Create: `tests/host/test_environment_runtime.py`

**Tests:**

`test_environment_contract.py` 至少覆盖：

1. 12 个 T01 文件存在；
2. `environment/versions.env` 包含 WSL、容器、Binutils、GCC 的版本、URL 和 64 位小写 SHA-256；
3. Shell 脚本包含严格模式，禁止 `system prune`、`rm -rf /`、写 `/usr/local` 和修改 Shell 启动文件；
4. PowerShell 脚本只允许 `MiniOrangeOS-Dev` 或 `MiniOrangeOS-Dev-Test-*`，环境根必须在 `D:\ApplicationData\MiniOrangeOS`；
5. `destroy.ps1` 同时要求 `-Apply` 与精确 `-ConfirmName`；
6. Containerfile 固定 Ubuntu digest 和项目标签；
7. Ubuntu 删除脚本只使用项目标签与固定镜像名；
8. 文档路径与实现一致。

`test_environment_runtime.py` 使用 Python 标准库与临时目录覆盖：

1. `with-env.sh` 无命令失败；
2. 临时环境根中的假工具只在子进程 PATH 生效；
3. 环境根为 `/`、`/usr/local` 或仓库目录时失败；
4. `build_toolchain.sh --print-plan` 输出固定 target、版本和 prefix；
5. Ubuntu 后端探测在没有可用引擎时给出非零和可诊断错误。

Run in WSL:

```powershell
$script = @'
set -euo pipefail
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
python3 -m unittest \
  tests.host.test_environment_contract \
  tests.host.test_environment_runtime -v
'@
$script | wsl.exe -d MiniOrangeOS-Dev -- bash -s
```

Expected RED: 缺失 T01 文件导致断言 FAIL，不得出现导入错误或测试基础设施 ERROR。

Commit:

```text
test(environment): define T01 lifecycle contract

Refs: T01
```

---

## Task 2：实现锁文件、公共边界与临时环境注入

**Files:**

- Create: `environment/versions.env`
- Create: `environment/lib/common.sh`
- Create: `environment/with-env.sh`
- Create: `environment/verify.sh`
- Modify: `tests/host/test_environment_runtime.py` only if RED 证明测试夹具需要最小修正

**Interfaces:**

`environment/versions.env` 必须固定设计文档中的全部版本、URL 和 SHA-256，并定义：

```text
MINIOS_TARGET=i686-elf
MINIOS_WSL_DISTRO=MiniOrangeOS-Dev
MINIOS_CONTAINER_IMAGE=miniorangeos-dev:ubuntu-24.04
MINIOS_CONTAINER_LABEL=org.miniorangeos.project=MiniOrangeOS
```

`common.sh` 提供：

- 仓库根定位；
- `MINIOS_ENV_ROOT` 默认值；
- 环境根拒绝列表和绝对路径检查；
- 锁文件加载与字段存在检查；
- 原子下载和 SHA-256 校验；
- 稳定日志函数。

`with-env.sh`：

- 至少接收一个命令；
- 只为当前 `exec` 注入 `$MINIOS_ENV_ROOT/toolchain/bin` 和可选 venv/bin；
- 不写 `.bashrc`、`.profile` 或 `/etc/environment`。

`verify.sh` 先实现完整接口；工具尚未构建时必须给出明确 FAIL，而不是伪造 PASS。

Run focused tests, `bash -n` and existing 11 项 T00 回归。

Commit:

```text
feat(environment): add pinned environment contract

Refs: T01
```

---

## Task 3：实现可重复的 i686-elf 工具链构建器

**Files:**

- Create: `tools/build_toolchain.sh`
- Modify: `tests/host/test_environment_runtime.py`

**CLI:**

```text
tools/build_toolchain.sh [--print-plan] [--download-only] [--force]
```

Required behavior:

- 默认 prefix 为 `$MINIOS_ENV_ROOT/toolchain`；
- `--print-plan` 不联网、不写环境根，输出版本、target、prefix 和配置参数；
- 下载到 `$MINIOS_ENV_ROOT/downloads`，`.partial` 校验后原子改名；
- 解包到 `sources`，构建目录位于 `build`；
- Binutils 使用设计文档配置参数；
- GCC 只构建 C、`all-gcc` 和 `all-target-libgcc`；
- 完成标记必须与锁文件和实际工具自检同时匹配；
- 第二次执行输出 `toolchain_status=up-to-date` 并跳过重建；
- `--force` 只删除环境根内的目标构建目录和工具链 prefix。

TDD:

1. 先补 `--print-plan`、危险环境根、非法参数测试并观察 RED；
2. 实现最小 CLI 与边界；
3. 运行 `--download-only`，真实下载两个官方 tarball 并校验锁定 SHA-256；
4. 不在本 Task 安装系统包或声称完整构建成功。

Commit:

```text
build(toolchain): add reproducible i686-elf builder

Refs: T01
```

---

## Task 4：实现 WSL bootstrap 与生命周期脚本

**Files:**

- Create: `environment/bootstrap-inside.sh`
- Create: `environment/wsl/create.ps1`
- Create: `environment/wsl/enter.ps1`
- Create: `environment/wsl/backup.ps1`
- Create: `environment/wsl/destroy.ps1`
- Modify: `tests/host/test_environment_contract.py`
- Create: `tests/host/test_wsl_lifecycle.ps1`

**PowerShell safety contract:**

- 所有文件操作使用 `-LiteralPath`；
- 使用 `[IO.Path]::GetFullPath` 后验证位于授权根；
- 列举 WSL 名称时移除 NUL 并精确比较；
- `create.ps1` 已存在正式发行版时不导入，只验证并按参数重复 bootstrap；
- 下载使用 `.partial`、固定 SHA-256 和原子移动；
- 只 terminate/unregister 精确目标，禁止 `wsl --shutdown`；
- `destroy.ps1` 默认预览，执行要求 `-Apply -ConfirmName <exact-name>`；
- `backup.ps1` 只导出到授权 `exports`，禁止覆盖未知文件。

**Bootstrap contract:**

- `--system-only` 由 root 安装 Ubuntu 包并记录实际版本；
- `--toolchain-only` 由目标普通用户调用工具链构建器；
- 默认按两个阶段执行；非 root 且无无密码 sudo 时给出可执行提示；
- 重复执行不破坏现有工具链。

Run:

```powershell
powershell -NoProfile -File tests/host/test_wsl_lifecycle.ps1
wsl.exe -d MiniOrangeOS-Dev -- bash -n environment/bootstrap-inside.sh
```

Expected: 只执行解析、preview 和既有发行版只读检查；本 Task 不注销任何发行版。

Commit:

```text
feat(environment): add WSL lifecycle scripts

Refs: T01
```

---

## Task 5：在专用 WSL 中安装并验证工具链

**External state:** `D:\ApplicationData\MiniOrangeOS\rootfs\ext4.vhdx`

Run from PowerShell using scripts, not ad-hoc apt commands:

```powershell
powershell -NoProfile -File environment/wsl/create.ps1 -Bootstrap
```

Expected first run:

- Ubuntu 24.04 包依赖安装成功；
- Binutils/GCC tarball SHA-256 匹配；
- `i686-elf` 工具链构建到 `/home/minios/.local/share/miniorangeos-dev/toolchain`；
- `environment/verify.sh` PASS；
- `with-env.sh i686-elf-gcc --version` 与 `i686-elf-ld --version` PASS。

Immediately run the same command again.

Expected second run: 系统依赖不破坏现状，工具链报告 up-to-date，不重新下载或构建。

Also run:

```powershell
$script = @'
set -euo pipefail
cd /mnt/d/DC/program-projects/OTHER/MiniOrangeOS
./environment/verify.sh
./environment/with-env.sh i686-elf-gcc --version
./environment/with-env.sh i686-elf-ld --version
python3 -m unittest discover -s tests/host -v
'@
$script | wsl.exe -d MiniOrangeOS-Dev -- bash -s
```

This Task may create no product commit. Write full evidence to `.superpowers/sdd/t01-task-5-report.md` for review.

---

## Task 6：实现真实 Ubuntu 容器适配层

**Files:**

- Create: `environment/Containerfile`
- Create: `environment/ubuntu/lib.sh`
- Create: `environment/ubuntu/create.sh`
- Create: `environment/ubuntu/run.sh`
- Create: `environment/ubuntu/destroy.sh`
- Modify: `tests/host/test_environment_contract.py`
- Modify: `tests/host/test_environment_runtime.py`

**Containerfile:**

- `FROM ubuntu:noble-20260509.1@sha256:786a8b...`；
- OCI label 包含项目名、任务和源码版本；
- 设置 `MINIOS_CONTAINER=1`、`MINIOS_ENV_ROOT=/opt/miniorangeos-dev`；
- 复用 `bootstrap-inside.sh` 和 `build_toolchain.sh`，不维护第二套构建逻辑；
- 最终工作目录 `/workspace`，默认非特权用户。

**Backend behavior:**

- `MINIOS_CONTAINER_BACKEND` 可显式选择 `podman` 或 `docker`；
- 未指定时优先可用的 rootless Podman，其次已有 Docker；
- 只检查可用性，不自动安装或启动运行时；
- create 构建固定镜像；run 使用 `--rm` 临时容器和项目标签；destroy 默认预览，`--all` 精确删除项目资源。

TDD first with fake backend executables in a temporary PATH, then shell syntax and full host regression.

Commit:

```text
feat(environment): add Ubuntu container verification

Refs: T01
```

---

## Task 7：执行生命周期与容器集成验收

### WSL backup

Run `backup.ps1` against the formal distro; verify export exists under `D:\ApplicationData\MiniOrangeOS\exports`, is non-empty and has a SHA-256 recorded in the task report.

### WSL create/destroy drill

1. Use `MiniOrangeOS-Dev-Test-Empty` and a path below `D:\ApplicationData\MiniOrangeOS\drills`.
2. Run `create.ps1 -SkipBootstrap` with the pinned rootfs.
3. Verify Ubuntu 24.04 and the exact test name.
4. Run `destroy.ps1` without `-Apply` and prove it only previews.
5. Run with `-Apply -ConfirmName MiniOrangeOS-Dev-Test-Empty`.
6. Verify the test distro disappeared while `MiniOrangeOS-Dev` and `docker-desktop` remain.

### Container

Use an already installed backend. On this machine select Docker explicitly after the engine is available:

```bash
MINIOS_CONTAINER_BACKEND=docker ./environment/ubuntu/create.sh
MINIOS_CONTAINER_BACKEND=docker ./environment/ubuntu/run.sh ./environment/verify.sh
MINIOS_CONTAINER_BACKEND=docker ./environment/ubuntu/destroy.sh --all
```

Record before/after project-labeled resources and prove unrelated images/containers are unchanged. Restore the runtime to its prior stopped/running state when feasible.

Run all host tests again. No product commit is required unless integration reveals a defect; fixes must follow RED/GREEN and receive a separate commit.

---

## Task 8：同步文档、来源、风险、进度和任务报告

**Files:**

- Modify: `README.md`
- Modify: `environment/README.md`
- Modify: `docs/environment.md`
- Modify: `docs/testing.md`
- Modify: `docs/provenance.md`
- Modify: `docs/problems.md`
- Modify: `docs/progress.md`
- Modify: `docs/review-notes.md`
- Create: `docs/task-reports/T01-environment-toolchain.md`

Required facts:

- 真实工具版本、URL、SHA-256、安装 prefix 和环境指纹；
- WSL 首次/第二次 bootstrap 结果；
- backup 路径、大小与 SHA-256；
- test distro 的 preview/定向删除证据；
- 容器 backend、基础镜像 digest、create/run/destroy 证据；
- `/mnt/d`、构建时间、容器运行时和预存 Windows gdb 等真实风险；
- T01 状态先写“验收通过，待合并”，不得提前写已合并。

Commit:

```text
docs(t01): record environment verification

Refs: T01
```

---

## Task 9：最终验证、审查、推送和 no-ff 合并

1. 根代理亲自运行全部 Windows 静态检查、PowerShell 测试、WSL host tests、`verify.sh` 与两个交叉工具版本命令。
2. 生成 `main..HEAD` 全分支审查包，使用新的审查代理；任何 Critical/Important 阻止合并。
3. 推送 `feature/T01-environment-toolchain`。
4. 切换 `main`，`git pull --ff-only origin main`，执行：

```text
git merge --no-ff feature/T01-environment-toolchain -m "merge: complete T01 environment toolchain"
```

5. 在合并结果上重复 WSL 全部测试和 `verify.sh`。
6. 推送 `main`，回填真实 merge SHA 与完成状态，提交并再次推送。
7. 删除本地和远端已合并任务分支，确认 `main == origin/main`。

---

## 验收矩阵

| PROJECT_PLAN T01 要求 | 覆盖 Task |
|---|---|
| WSL create/enter/backup/destroy | 4、7 |
| Containerfile 和 Ubuntu 脚本 | 6、7 |
| bootstrap/with-env/verify | 2、4、5 |
| 固定版本、URL、SHA-256 | 2、3、5 |
| i686-elf Binutils/GCC | 3、5、7 |
| 重复 bootstrap | 5 |
| 真实 Ubuntu 容器 create/run/destroy | 6、7 |
| 空环境删除演练、不影响其他发行版 | 4、7 |
| 不修改全局配置和 `/usr/local` | 全局约束、2、4、6、7 |
| 文档、来源、风险、进度、心得 | 8 |
| 独立分支、审查、no-ff 合并 | 9 |
