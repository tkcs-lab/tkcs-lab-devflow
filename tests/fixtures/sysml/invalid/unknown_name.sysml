// expect: 5: unknown name 'Missing'
package U {
    part def A {
        doc /* A. */
        part x : Missing;
    }
}
