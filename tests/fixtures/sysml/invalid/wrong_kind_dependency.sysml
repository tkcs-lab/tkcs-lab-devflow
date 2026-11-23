// expect: 7: 'P' is a port def; a part def is needed
package W {
    port def P;
    part def A {
        doc /* A. */
    }
    dependency from A to P;
}
