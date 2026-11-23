// Part usages: a part def made of other part defs.
package Composition {
    part def Wheel {
        doc /* A wheel. */
    }
    part def Axle {
        doc /* Joins two wheels. */
        part left : Wheel;
        part right : Wheel;
    }
    part def Car {
        doc /* A car with two axles. */
        part front : Axle;
        part rear : Axle;
    }
}
