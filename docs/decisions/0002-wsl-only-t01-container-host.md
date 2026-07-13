# ADR-0002：T01 容器集成只在独立 WSL2 宿主执行

## 状态

已接受，2026-07-13。

## 背景

用户要求代码保留在 Windows 权威工作树，Linux 测试只在 WSL 中执行。T01 又必须真实验证 Ubuntu 24.04 rootless 容器，而不能把未运行的原生 Linux 环境写成 PASS。

## 决策

- 创建独立 `MiniOrangeOS-Dev-Test-ContainerHost`，使用 Ubuntu 24.04.4 WSL2 和 rootless Podman 4.9.3。
- 该发行版不复用正式 `MiniOrangeOS-Dev` 的工具链状态；项目 graphroot 放在发行版 ext4，`/mnt/d` 只提供只读构建 context。
- Windows Git 仍是唯一 Git；WSL 内不运行 Git。
- 验收后通过 WSL lifecycle preview 与精确确认定向注销测试发行版。
- 报告明确写明 Microsoft WSL2 内核边界，不将结果表述为原生 Linux 内核验证。

## 结果

固定基础镜像 create、幂等 create、`verify.sh`、失败恢复、镜像与专用 storage 清理均通过；默认 Podman 资源不变，正式 WSL 和 `docker-desktop` 保留。

## 代价与后续

已验证内核为 `6.6.87.2-microsoft-standard-WSL2`。namespace、cgroup、overlay、OCI runtime 与性能在原生 Linux 可能不同；后续 Linux CI 必须在原生 Linux 内核重新运行容器和构建测试。在此之前，T01 的证据范围仅为 Ubuntu 24.04 WSL2。
