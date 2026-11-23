// expect: 6: duplicate name 'D::Twice'
package D {
    part def Twice {
        doc /* One. */
    }
    part def Twice {
        doc /* Two. */
    }
}
