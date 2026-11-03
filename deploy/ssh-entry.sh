#!/bin/bash
# Installed root-owned; the dedicated SSH key cannot open an interactive shell.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
if [[ ${SSH_ORIGINAL_COMMAND:-} =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
    exec sudo -n -u petrmath /usr/local/libexec/petrmath-deploy "${BASH_REMATCH[1]}"
fi
printf '%s\n' 'Only deploy <40-character main commit SHA> is permitted.' >&2
exit 64
