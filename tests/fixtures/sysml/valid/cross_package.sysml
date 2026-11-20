// A dependency and a part type named across packages, and a nested package using its owner's names.
package CrossPackage {
    package Core {
        doc /* The core. */
        part def Engine {
            doc /* Does the work. */
        }
        package Inner {
            part def Helper {
                doc /* Helps the engine; sees Engine without a qualifier. */
                part owner : Engine;
            }
        }
    }
    package Shell {
        part def Cli {
            doc /* The command line. */
            part engine : Core::Engine;
        }
        dependency from Cli to Core::Engine;
        dependency from Core::Inner::Helper to Core::Engine;
    }
}
