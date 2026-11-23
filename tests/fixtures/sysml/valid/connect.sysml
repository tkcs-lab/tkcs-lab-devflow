// Two parts of one part def, connected through their ports.
package Connect {
    port def Link;
    part def Producer {
        doc /* Produces data. */
        port tx : Link;
    }
    part def Consumer {
        doc /* Consumes data. */
        port inp : Link;
    }
    part def Pipeline {
        doc /* Wires a producer to a consumer. */
        part src : Producer;
        part dst : Consumer;
        connect src.tx to dst.inp;
    }
}
