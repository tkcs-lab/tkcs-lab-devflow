package Adapter {
    doc /* The Claude Code plugin content: hooks, commands and the playbooks agents follow. */
    part def ClaudeAdapter {
        doc /* Turns Claude Code hook events into guard actions and declares the plugin commands, skills, agents and board MCP server. */
    }
    part def Playbooks {
        doc /* Markdown procedures, role prompts, checklists and stack guides that agents follow and that call the tld command line. */
    }
    dependency from ClaudeAdapter to Core::Guard;
    dependency from Playbooks to Core::Cli;
}
