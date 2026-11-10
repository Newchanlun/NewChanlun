# service-manager.sh —— install-*.sh 共用的服务管理器分派（#2048）。由 install 脚本 source，不单独执行。
# SERVICE_MANAGER 缺省 launchctl：本函数直接返回，调用方继续走原 launchd 分支，Mac 行为不变。
# SERVICE_MANAGER=systemd：对已预置在 ~/.config/systemd/user/ 的 newchanlun-<名>.service 执行
# enable --now / disable --now / status 后退出。单元文件由宿主部署方落盘，本脚本不生成单元。
systemd_dispatch() {
  local label="$1" action="$2" unit
  case "${SERVICE_MANAGER:-launchctl}" in
    launchctl) return 0 ;;
    systemd) ;;
    *) echo "SERVICE_MANAGER 只接受 launchctl 或 systemd，实为 ${SERVICE_MANAGER}" >&2; exit 2 ;;
  esac
  unit="newchanlun-${label#com.newchanlun.}.service"
  case "$action" in
    install)
      systemctl --user daemon-reload
      systemctl --user enable --now "${unit}"
      echo "已启用 ${unit}（systemd --user）"
      ;;
    uninstall)
      systemctl --user disable --now "${unit}" 2>/dev/null || true
      echo "已停用 ${unit}（单元文件保留）"
      ;;
    status)
      systemctl --user --no-pager status "${unit}" || echo "${unit} 未在运行"
      ;;
    *)
      echo "用法: $0 [install|uninstall|status]" >&2
      exit 2
      ;;
  esac
  exit 0
}
