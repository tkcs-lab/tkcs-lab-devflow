// A port def, ports typed by it, and a part def used twice.
package Ports {
    port def DataPort;
    port def ControlPort {
        doc /* Carries control messages. */
    }
    part def Sensor {
        doc /* Reads a value and publishes it. */
        port tx : DataPort;
        port ctl : ControlPort;
    }
    part def Station {
        doc /* Holds two sensors. */
        part left : Sensor;
        part right : Sensor;
    }
}
