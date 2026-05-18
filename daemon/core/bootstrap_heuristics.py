"""Central bootstrap heuristics used before user or project profiles exist.

These catalogues are deliberately static startup defaults. They are not learned
preferences and should not be presented as a user-specific profile.
"""

from __future__ import annotations


BOOTSTRAP_AI_APPS = frozenset({
    "ChatGPT",
    "Claude",
    "Claude Desktop",
    "Codex",
    "Copilot",
    "Gemini",
    "Perplexity",
})

BOOTSTRAP_DEV_APPS = frozenset({
    "Code",
    "Cursor",
    "PyCharm",
    "Terminal",
    "Visual Studio Code",
    "VSCode",
    "Warp",
    "WebStorm",
    "Xcode",
    "iTerm2",
})

BOOTSTRAP_WORK_APPS = frozenset({
    "Code",
    "Cursor",
    "Terminal",
    "Visual Studio Code",
    "Xcode",
    "iTerm2",
})

BOOTSTRAP_BROWSER_APPS = frozenset({
    "Arc",
    "Chrome",
    "Firefox",
    "Google Chrome",
    "Safari",
})

BOOTSTRAP_WRITING_APPS = frozenset({
    "Bear",
    "Notes",
    "Notion",
    "Obsidian",
    "Pages",
})

BOOTSTRAP_TERMINAL_APPS = frozenset({
    "Terminal",
    "Warp",
    "iTerm2",
})

BOOTSTRAP_APP_BUNDLE_ROLES: dict[str, str] = {
    "com.apple.Safari": "browser",
    "com.apple.Terminal": "terminal",
    "com.apple.dt.Xcode": "dev_tool",
    "com.google.Chrome": "browser",
    "com.microsoft.VSCode": "dev_tool",
    "dev.pulse.test.UnknownAI": "ai_assistant",
    "dev.pulse.test.UnknownIDE": "dev_tool",
}

BOOTSTRAP_SELF_APPS = frozenset({
    "Pulse",
    "PulseApp",
})

BOOTSTRAP_NON_WORK_TITLE_HINTS = frozenset({
    "disney+",
    "netflix",
    "prime video",
    "spotify",
    "twitch",
    "youtube",
})
