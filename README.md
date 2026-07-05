# 重复文件检测清理工具

一个基于 Flask 的本地 Web 应用，用于快速扫描文件夹中的重复文件并提供一键清理功能。

## 功能

- **SHA-256 哈希比对**：先按文件大小分组，再计算哈希，兼顾速度与准确性
- **实时进度显示**：通过 SSE 推送扫描进度，支持暂停、继续、停止
- **三种保留规则**：自动保留名称最短/最长的文件，或手动勾选
- **密码认证**：可选的登录保护，防止局域网内未授权访问
- **桌面 GUI 启动器**：Tkinter 窗口一键启停服务，内置日志查看器
- **跨平台**：支持 Windows（EXE）、Linux（二进制）、Docker 部署

## 快速开始

```bash
cd src
pip install -r requirements.txt
python app.py
```

浏览器打开 `http://127.0.0.1:36901`，输入密码后即可使用。

## 配置

编辑 `config.yaml`：

```yaml
server:
  host: "127.0.0.1"
  port: 36901
  password: "123456"
```

也可通过环境变量 `DUPFINDER_HOST`、`DUPFINDER_PORT`、`DUPFINDER_PASSWORD` 覆盖。

# 重复文件检测清理工具

一个基于 Flask 的本地 Web 应用，用于快速扫描文件夹中的重复文件并提供一键清理功能。

## 功能

- **SHA-256 哈希比对**：先按文件大小分组，再计算哈希，兼顾速度与准确性
- **实时进度显示**：通过 SSE 推送扫描进度，支持暂停、继续、停止
- **三种保留规则**：自动保留名称最短/最长的文件，或手动勾选
- **密码认证**：可选的登录保护，防止局域网内未授权访问
- **桌面 GUI 启动器**：Tkinter 窗口一键启停服务，内置日志查看器
- **跨平台**：支持 Windows（EXE）、Linux（二进制）、Docker 部署

## 快速开始

```bash
cd src
pip install -r requirements.txt
python app.py
```

浏览器打开 `http://127.0.0.1:36901`，输入密码后即可使用。

## 配置

编辑 `src/config.yaml`：

```yaml
server:
  host: "127.0.0.1"
  port: 36901
  password: "123456"
```

也可通过环境变量 `DUPFINDER_HOST`、`DUPFINDER_PORT`、`DUPFINDER_PASSWORD` 覆盖。

## dokcer镜像名：chongya369/dedup

##docker compose快速部署

```yaml
# 重复文件检测清理工具 - Docker 快速部署
#
# 使用方式:
#   docker compose -f docker快速部署.yml up -d
#   PASSWORD=mypass WEB_PORT=8080 SCAN_DIR=/path/to/scan docker compose -f docker快速部署.yml up -d
#   docker compose -f docker快速部署.yml down
#
# 环境变量:
#   WEB_PORT  - 宿主机访问端口，默认 36901
#   PASSWORD  - 访问密码，默认 123456，留空则无需密码
#   SCAN_DIR  - 宿主机扫描目录，默认当前目录下的 scan_data

services:
  dupfinder:
    image: chongya369/dedup:0.8.0
    container_name: dupfinder
    restart: unless-stopped
    ports:
      - "${WEB_PORT:-36901}:36901"
    environment:
      DUPFINDER_HOST: 0.0.0.0
      DUPFINDER_PORT: "36901"
      DUPFINDER_PASSWORD: "${PASSWORD:-123456}"
    volumes:
      - ${your_data}:/scan
      - /home/dupfinder_logs:/app/logs

volumes:
  dupfinder_logs:
```
