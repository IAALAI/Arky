#!/usr/bin/env bash
set -euo pipefail
case "${1:-status}" in
  status) systemctl --no-pager status arknights.service nginx ;;
  start|stop|restart) sudo systemctl "$1" arknights.service ;;
  logs) journalctl -u arknights.service -n 80 --no-pager ;;
  *) echo "usage: $0 [status|start|stop|restart|logs]" >&2; exit 2 ;;
esac
