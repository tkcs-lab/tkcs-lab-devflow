package Core {
    doc /* The tld library: the command line and the rules, plans and operations behind it. */
    port def CommandSurface {
        doc /* The tld command groups other components call. */
    }
    part def Cli {
        doc /* Dispatches each tld group and command to the module that runs it. */
        port commands : CommandSurface;
    }
    part def Profile {
        doc /* Validates, resolves and patches the project profile against its schema. */
    }
    part def Plan {
        doc /* Validates plan manifests and tracks phase status, scope drift and active runs. */
    }
    part def Roles {
        doc /* Decides which review roles a point requires and verifies their reports. */
    }
    part def Guard {
        doc /* Tool-agnostic guard rules and the definition-of-done gate; each rule maps an action to a decision. */
    }
    part def Ops {
        doc /* Repository operations behind the ops commands, such as docs index, release preparation, specs and the architecture model. */
    }
    part def SysmlLib {
        doc /* Parses, checks, lays out and draws the architecture model. */
    }
    dependency from Cli to Profile;
    dependency from Cli to Plan;
    dependency from Cli to Roles;
    dependency from Cli to Guard;
    dependency from Cli to Ops;
    dependency from Cli to Board::BoardClient;
    dependency from Guard to Board::BoardClient;
    dependency from Plan to Guard;
    dependency from Roles to Plan;
    dependency from Roles to Profile;
    dependency from Profile to Plan;
    dependency from Ops to Profile;
    dependency from Ops to SysmlLib;
}
