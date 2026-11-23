package Board {
    doc /* The status board: a small service for status records and asks, and the client that talks to it. */
    port def BoardApi {
        doc /* The HTTP and MCP interface for records, asks and usage readings. */
    }
    part def BoardServer {
        doc /* Stores status records and asks and serves the owner's web page. */
        port api : BoardApi;
    }
    part def BoardClient {
        doc /* Reads and writes records and asks over the board interface and bridges it to MCP over standard input and output. */
    }
    dependency from BoardClient to BoardServer;
}
