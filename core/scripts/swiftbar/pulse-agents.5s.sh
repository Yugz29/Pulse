#!/bin/bash
# <swiftbar.title>Pulse — agents</swiftbar.title>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
#
# Pulse — sessions d'agent en attente, et le dernier lot Intelligence.
# Lecture seule de ~/.pulse_v2/run/agents/ et de
# ~/.pulse_intelligence/state.json ; aucun appel à Core, aucun réseau.
# Lié dans le dossier de plugins SwiftBar par install_agent_state_hooks.sh ;
# `pwd -P` suit le lien jusqu'au dépôt.
script_dir="$(cd "$(dirname "$(readlink "${BASH_SOURCE[0]}" || echo "${BASH_SOURCE[0]}")")" && pwd -P)"
exec /usr/bin/env python3 "$script_dir/../pulse_agents_menu.py"
