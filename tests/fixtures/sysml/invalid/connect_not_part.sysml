// expect: 11: connect: 'zz' is not a part of 'C::D'
package C {
    port def L;
    part def A {
        doc /* A. */
        port o : L;
    }
    part def D {
        doc /* D. */
        part a : A;
        connect zz.o to a.o;
    }
}
