#!/bin/bash
#
# XAgent 后端服务运维脚本
#
# 用法:
#   ./xagent-server.sh start     # 启动服务
#   ./xagent-server.sh stop      # 停止服务
#   ./xagent-server.sh restart   # 重启服务
#   ./xagent-server.sh status    # 查看服务状态
#   ./xagent-server.sh log       # 查看实时日志
#

set -e

# ==============================================================================
# 配置项
# ==============================================================================

# 服务名称
SERVICE_NAME="xagent-backend"

# 项目根目录（脚本所在目录的父目录）
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Python 虚拟环境路径
VENV_DIR="${PROJECT_DIR}/.venv"

# 服务配置
HOST="${XAGENT_HOST:-0.0.0.0}"
PORT="${XAGENT_PORT:-8000}"
WORKERS="${XAGENT_WORKERS:-1}"

# 日志配置
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/server.log"
PID_FILE="${LOG_DIR}/server.pid"

# 启动命令
APP_MODULE="xagent.web.app:app"
PYTHONPATH="${PROJECT_DIR}/src"

# ==============================================================================
# 颜色输出
# ==============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ==============================================================================
# 工具函数
# ==============================================================================

# 检查虚拟环境是否存在
check_venv() {
    if [[ ! -d "${VENV_DIR}" ]]; then
        log_error "虚拟环境不存在: ${VENV_DIR}"
        log_info "请先创建虚拟环境: python -m venv .venv"
        exit 1
    fi
}

# 获取 Python 解释器路径
get_python() {
    if [[ -f "${VENV_DIR}/bin/python" ]]; then
        echo "${VENV_DIR}/bin/python"
    elif [[ -f "${VENV_DIR}/Scripts/python.exe" ]]; then
        echo "${VENV_DIR}/Scripts/python.exe"
    else
        log_error "找不到虚拟环境中的 Python 解释器"
        exit 1
    fi
}

# 检查服务是否正在运行
check_running() {
    if [[ -f "${PID_FILE}" ]]; then
        local pid=$(cat "${PID_FILE}")
        if ps -p "${pid}" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# 获取服务 PID
get_pid() {
    if [[ -f "${PID_FILE}" ]]; then
        cat "${PID_FILE}"
    else
        echo ""
    fi
}

# ==============================================================================
# 命令函数
# ==============================================================================

cmd_start() {
    log_info "正在启动 ${SERVICE_NAME} 服务..."

    # 检查是否已在运行
    if check_running; then
        log_warn "服务已经在运行中 (PID: $(get_pid))"
        exit 0
    fi

    # 检查虚拟环境
    check_venv

    # 创建日志目录
    mkdir -p "${LOG_DIR}"

    local python=$(get_python)
    log_info "使用 Python: ${python}"
    log_info "服务地址: http://${HOST}:${PORT}"
    log_info "日志文件: ${LOG_FILE}"

    # 设置环境变量并启动服务
    export PYTHONPATH="${PYTHONPATH}"
    export XAGENT_LOG_LEVEL="${XAGENT_LOG_LEVEL:-INFO}"

    # 使用 nohup 后台运行
    nohup "${python}" -m uvicorn \
        "${APP_MODULE}" \
        --host "${HOST}" \
        --port "${PORT}" \
        --workers "${WORKERS}" \
        >> "${LOG_FILE}" 2>&1 &

    local pid=$!
    echo "${pid}" > "${PID_FILE}"

    # 等待服务启动
    log_info "等待服务启动..."
    sleep 2

    if ps -p "${pid}" > /dev/null 2>&1; then
        log_success "服务启动成功 (PID: ${pid})"
        log_info "访问地址: http://${HOST}:${PORT}"
        log_info "健康检查: http://${HOST}:${PORT}/health"
    else
        log_error "服务启动失败，请查看日志: ${LOG_FILE}"
        rm -f "${PID_FILE}"
        exit 1
    fi
}

cmd_stop() {
    log_info "正在停止 ${SERVICE_NAME} 服务..."

    if ! check_running; then
        log_warn "服务未在运行"
        rm -f "${PID_FILE}"
        exit 0
    fi

    local pid=$(get_pid)
    log_info "正在终止进程 (PID: ${pid})..."

    # 先尝试优雅终止
    kill -TERM "${pid}" 2>/dev/null || true

    # 等待进程结束
    local count=0
    while ps -p "${pid}" > /dev/null 2>&1 && [[ ${count} -lt 10 ]]; do
        sleep 1
        count=$((count + 1))
    done

    # 如果还在运行，强制终止
    if ps -p "${pid}" > /dev/null 2>&1; then
        log_warn "进程未响应，强制终止..."
        kill -KILL "${pid}" 2>/dev/null || true
        sleep 1
    fi

    if ps -p "${pid}" > /dev/null 2>&1; then
        log_error "无法停止服务 (PID: ${pid})"
        exit 1
    else
        log_success "服务已停止"
        rm -f "${PID_FILE}"
    fi
}

cmd_restart() {
    log_info "正在重启 ${SERVICE_NAME} 服务..."
    cmd_stop
    sleep 2
    cmd_start
}

cmd_status() {
    if check_running; then
        local pid=$(get_pid)
        log_success "服务正在运行 (PID: ${pid})"
        log_info "访问地址: http://${HOST}:${PORT}"
        log_info "日志文件: ${LOG_FILE}"

        # 显示进程信息
        ps -p "${pid}" -o pid,ppid,cmd,etime 2>/dev/null || true
    else
        log_warn "服务未在运行"
        if [[ -f "${PID_FILE}" ]]; then
            log_info "发现残留的 PID 文件: ${PID_FILE}"
        fi
    fi
}

cmd_log() {
    if [[ ! -f "${LOG_FILE}" ]]; then
        log_error "日志文件不存在: ${LOG_FILE}"
        exit 1
    fi

    log_info "正在查看日志 (按 Ctrl+C 退出)..."
    tail -f "${LOG_FILE}"
}

cmd_health() {
    local url="http://${HOST}:${PORT}/health"
    log_info "检查服务健康状态: ${url}"

    if curl -s "${url}" > /dev/null 2>&1; then
        local response=$(curl -s "${url}" 2>/dev/null)
        log_success "服务健康: ${response}"
    else
        log_error "服务未响应或健康检查失败"
        exit 1
    fi
}

# ==============================================================================
# 帮助信息
# ==============================================================================

show_help() {
    cat << EOF
XAgent 后端服务运维脚本

用法:
    $0 <command>

命令:
    start       启动服务
    stop        停止服务
    restart     重启服务
    status      查看服务状态
    log         查看实时日志
    health      检查服务健康状态
    help        显示帮助信息

环境变量:
    XAGENT_HOST         服务监听地址 (默认: 0.0.0.0)
    XAGENT_PORT         服务监听端口 (默认: 8000)
    XAGENT_WORKERS      工作进程数 (默认: 1)
    XAGENT_LOG_LEVEL    日志级别 (默认: INFO)

示例:
    # 启动服务
    ./scripts/xagent-server.sh start

    # 指定端口启动
    XAGENT_PORT=8080 ./scripts/xagent-server.sh start

    # 查看状态
    ./scripts/xagent-server.sh status

    # 查看日志
    ./scripts/xagent-server.sh log

EOF
}

# ==============================================================================
# 主入口
# ==============================================================================

main() {
    local command="${1:-help}"

    case "${command}" in
        start)
            cmd_start
            ;;
        stop)
            cmd_stop
            ;;
        restart)
            cmd_restart
            ;;
        status)
            cmd_status
            ;;
        log)
            cmd_log
            ;;
        health)
            cmd_health
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "未知命令: ${command}"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
