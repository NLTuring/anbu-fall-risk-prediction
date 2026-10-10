#!/usr/bin/env bash
# Read-only, non-root diagnostics. No camera capture, installs or permission changes.
set -u
printf '\n== OS / kernel / architecture ==\n'
if [[ -r /etc/os-release ]]; then while IFS= read -r line; do printf '%s\n' "$line"; done < /etc/os-release; fi
uname -a
id
printf '\n== Python ==\n'
command -v python3 && python3 --version
printf '\n== Camera nodes (metadata only) ==\n'
shopt -s nullglob
nodes=(/dev/video*)
if ((${#nodes[@]})); then ls -l "${nodes[@]}"; else printf 'No /dev/video nodes found\n'; fi
if command -v v4l2-ctl >/dev/null 2>&1; then
  v4l2-ctl --version
  v4l2-ctl --list-devices
else
  printf 'v4l2-ctl unavailable. Optional manual OS command: sudo apt install v4l-utils\n'
fi
printf '\n== NPU/runtime discovery (not used by this CPU diagnostic service) ==\n'
for path in /dev/rknpu /sys/class/devfreq/*npu* /usr/lib/librknnrt.so /usr/lib/aarch64-linux-gnu/librknnrt.so /usr/local/lib/librknnrt.so; do
  [[ ! -e "$path" ]] || ls -ld "$path"
done
if command -v ldconfig >/dev/null 2>&1; then
  ldconfig -p 2>/dev/null | while IFS= read -r line; do
    case "$line" in *rknn*|*rknpu*) printf '%s\n' "$line";; esac
  done
fi
printf '\nDiscovery is not proof of working NPU inference. No model or services were installed.\n'
