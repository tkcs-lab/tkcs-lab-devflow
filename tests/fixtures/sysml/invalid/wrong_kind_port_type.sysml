// expect: 8: 'B' is a part def; a port def is needed
package W {
    part def B {
        doc /* B. */
    }
    part def A {
        doc /* A. */
        port x : B;
    }
}
